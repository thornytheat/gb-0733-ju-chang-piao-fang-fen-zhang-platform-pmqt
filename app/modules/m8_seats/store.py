import json
import sqlite3
from contextlib import closing
from pathlib import Path

from app.errors import Problem
from app.manifest import canonical, checksum, utc_now
from app.modules.m8_seats.schema_sql import SEAT_SCHEMA
from app.modules.m8_seats.seat_plan import check_show_balance, plan_show


class SeatStore:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        return db

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute('PRAGMA journal_mode = WAL')
            db.executescript(SEAT_SCHEMA)

    # ------------------------------------------------------------------ 账册
    def book(self, book):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM seat_books WHERE book = ?', (book,)).fetchone()
        if not row:
            raise Problem(404, 'SEAT_BOOK_NOT_FOUND', {'book': book})
        return dict(row)

    def book_exists(self, book):
        with closing(self.connect()) as db:
            return db.execute('SELECT 1 FROM seat_books WHERE book = ?', (book,)).fetchone() is not None

    def replace_holds(self, book, run_id, payload, holds):
        """占位导入：整组替换账册占位（缩座前基线可重发），已应用缩座后拒绝重写。"""
        now = utc_now()
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            bound = db.execute('SELECT run_id FROM seat_books WHERE book = ?', (book,)).fetchone()
            if bound and bound['run_id'] != run_id:
                raise Problem(409, 'SEAT_BOOK_CONFLICT', {'book': book, 'bound_run': bound['run_id']})
            if db.execute("SELECT 1 FROM seat_snapshot_attempts WHERE book = ? AND status = 'applied'",
                          (book,)).fetchone():
                raise Problem(409, 'SEAT_BASELINE_LOCKED', {'book': book})
            if bound:
                db.execute('UPDATE seat_books SET payload = ?, updated_at = ? WHERE book = ?',
                           (canonical(payload), now, book))
            else:
                db.execute('INSERT INTO seat_books VALUES (?, ?, ?, ?, ?)',
                           (book, run_id, canonical(payload), now, now))
            db.execute('DELETE FROM seat_holds WHERE book = ?', (book,))
            db.executemany(
                'INSERT INTO seat_holds (id, book, show, seat_label, ticket, hold_status, held_at,'
                ' source_line, end_line, raw) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                [(item['hold_id'], book, item['show'], item['seat_label'], item['ticket'], item['hold_status'],
                  item['held_at'], item['line'], item['end_line'],
                  json.dumps(item['raw'], ensure_ascii=False)) for item in holds])
            return {'book': book, 'holds': len(holds), 'replaced': bool(bound)}

    def holds(self, book, show=''):
        sql = 'SELECT * FROM seat_holds WHERE book = ?'
        args = [book]
        if show:
            sql += ' AND show = ?'
            args.append(show)
        sql += ' ORDER BY show, seat_label, id'
        with closing(self.connect()) as db:
            rows = db.execute(sql, args).fetchall()
        return [self._hold(row) for row in rows]

    def hold(self, book, hold_id):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM seat_holds WHERE book = ? AND id = ?', (book, hold_id)).fetchone()
        if not row:
            raise Problem(404, 'HOLD_NOT_FOUND', {'hold_id': hold_id})
        return self._hold(row)

    @staticmethod
    def _hold(row):
        return {'hold_id': row['id'], 'show': row['show'], 'seat_label': row['seat_label'],
                'ticket': row['ticket'], 'hold_status': row['hold_status'], 'held_at': row['held_at'],
                'line': row['source_line'], 'end_line': row['end_line'], 'raw': json.loads(row['raw'])}

    # ------------------------------------------------------------------ 缩座
    def attempt(self, book, snapshot_id):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM seat_snapshot_attempts WHERE book = ? AND snapshot_id = ?',
                             (book, snapshot_id)).fetchone()
        return self._attempt(row) if row else None

    def apply_reduction(self, book, snapshot_payload, records, shows, allocations):
        """应用缩座快照；业务失败时座位改动全部回滚，但失败尝试单独留痕且不丢失。"""
        snapshot_id = records[0]['snapshot_id']
        payload_hash = checksum(snapshot_payload)
        now = utc_now()
        lines = json.dumps(sorted({item['line'] for item in records}))
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM seat_snapshot_attempts WHERE book = ? AND snapshot_id = ?',
                                  (book, snapshot_id)).fetchone()
            if existing:
                # 重试：直接返回既有结果，不新增任何占用或版本。
                db.commit()
                return {'snapshot_id': snapshot_id, 'reused': True, 'status': existing['status'],
                        'reason_code': existing['reason_code']}
            reason, detail = self._validate_attempt(records, shows)
            if reason:
                self._record_attempt(db, book, snapshot_id, payload_hash, lines, 'rejected', reason, detail, now)
                db.commit()
                raise Problem(409, reason, detail)
            by_show = {}
            for row in db.execute('SELECT * FROM seat_holds WHERE book = ?', (book,)).fetchall():
                by_show.setdefault(row['show'], []).append(self._hold(row))
            plans = []
            for record in records:
                plan = plan_show(record['show'], by_show.get(record['show'], []),
                                 record['new_capacity'], allocations)
                if not plan['feasible']:
                    detail = {'snapshot_id': snapshot_id, 'show': record['show'], 'gap': plan['gap'],
                              'clearable': len(plan['evictions']), 'new_capacity': record['new_capacity']}
                    self._record_attempt(db, book, snapshot_id, payload_hash, lines, 'rejected',
                                         'SEAT_CAPACITY_EXCEEDED', detail, now)
                    db.commit()
                    raise Problem(409, 'SEAT_CAPACITY_EXCEEDED', detail)
                plans.append((record, plan))
            self._persist(db, book, snapshot_id, plans, now)
            self._record_attempt(db, book, snapshot_id, payload_hash, lines, 'applied', '', {}, now)
            db.commit()
            return {'snapshot_id': snapshot_id, 'reused': False, 'status': 'applied',
                    'shows': [record['show'] for record, _ in plans]}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _validate_attempt(records, shows):
        for record in records:
            deadline = record['group_lock_deadline']
            if deadline and record['reported_at'] > deadline:
                return 'GROUP_LOCK_DEADLINE_PASSED', {
                    'snapshot_id': record['snapshot_id'], 'show': record['show'],
                    'deadline': deadline, 'reported_at': record['reported_at']}
        return '', {}

    def _persist(self, db, book, snapshot_id, plans, now):
        for record, plan in plans:
            current = db.execute('SELECT COALESCE(MAX(version), -1) AS v FROM seat_versions WHERE book = ? AND show = ?',
                                 (book, record['show'])).fetchone()['v']
            active_seats = plan['remaining_seats']
            failure = check_show_balance(record['show'], record['new_capacity'], active_seats,
                                         plan['evictions'], plan['refund_dues'])
            if failure:
                raise Problem(409, failure, {'show': record['show']})
            db.execute('INSERT INTO seat_versions (book, show, version, snapshot_id, capacity, active_seats, created_at)'
                       ' VALUES (?, ?, ?, ?, ?, ?, ?)',
                       (book, record['show'], current + 1, snapshot_id, record['new_capacity'],
                        json.dumps(active_seats, ensure_ascii=False), now))
            for item in plan['evictions']:
                cursor = db.execute(
                    'INSERT INTO seat_evictions (book, snapshot_id, show, seat_label, hold_id, ticket,'
                    ' eviction_type, reason_code, source_line, evicted_at, recorded_at)'
                    ' VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (book, snapshot_id, item['show'], item['seat_label'], item['hold_id'], item['ticket'],
                     item['eviction_type'], item['reason_code'], item['line'], item['held_at'], now))
                db.execute('UPDATE seat_holds SET hold_status = ? WHERE book = ? AND id = ?',
                           ('released', book, item['hold_id']))
                if item['eviction_type'] == 'package_split' and item['due_cents']:
                    db.execute('INSERT INTO seat_refund_dues (book, eviction_id, snapshot_id, ticket, show,'
                               ' due_cents, allocated_cents, state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                               (book, cursor.lastrowid, snapshot_id, item['ticket'], item['show'],
                                item['due_cents'], item['due_cents'], 'due', now))

    @staticmethod
    def _record_attempt(db, book, snapshot_id, payload_hash, lines, status, reason, detail, now):
        db.execute('INSERT INTO seat_snapshot_attempts (book, snapshot_id, payload_hash, source_lines, status,'
                   ' reason_code, detail, received_at, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                   (book, snapshot_id, payload_hash, lines, status, reason,
                    json.dumps(detail, ensure_ascii=False), now, now))

    # ------------------------------------------------------------------ 核对
    def report(self, book, shows):
        with closing(self.connect()) as db:
            hold_rows = db.execute('SELECT * FROM seat_holds WHERE book = ? ORDER BY show, seat_label, id',
                                   (book,)).fetchall()
            version_rows = db.execute('SELECT * FROM seat_versions WHERE book = ? ORDER BY show, version',
                                      (book,)).fetchall()
            eviction_rows = db.execute('SELECT * FROM seat_evictions WHERE book = ? ORDER BY show, id',
                                       (book,)).fetchall()
            due_rows = db.execute('SELECT * FROM seat_refund_dues WHERE book = ? ORDER BY show, id',
                                  (book,)).fetchall()
            attempts = db.execute('SELECT * FROM seat_snapshot_attempts WHERE book = ? ORDER BY id',
                                  (book,)).fetchall()
        evictions_by_show, dues_by_show = {}, {}
        for row in eviction_rows:
            evictions_by_show.setdefault(row['show'], []).append(dict(row))
        for row in due_rows:
            dues_by_show.setdefault(row['show'], []).append(dict(row))
        latest_version = {}
        for row in version_rows:
            latest_version[row['show']] = row
        show_rows = []
        balanced = True
        for show_id in sorted(shows):
            active = [self._hold(row) for row in hold_rows
                     if row['show'] == show_id and row['hold_status'] != 'released']
            version = latest_version.get(show_id)
            active_seats = sorted(item['seat_label'] for item in active)
            capacity = version['capacity'] if version else len(active_seats)
            evictions = evictions_by_show.get(show_id, [])
            dues = dues_by_show.get(show_id, [])
            unpaid = sum(1 for item in evictions if item['eviction_type'] == 'unpaid_release')
            split = sum(1 for item in evictions if item['eviction_type'] == 'package_split')
            reason = check_show_balance(show_id, capacity, active_seats, evictions, dues)
            version_seats = json.loads(version['active_seats']) if version else active_seats
            if version and sorted(version_seats) != active_seats:
                reason = reason or 'SEAT_RECONCILE_FAILED'
            if reason:
                balanced = False
            show_rows.append({
                'show': show_id, 'title': shows[show_id]['title'], 'venue': shows[show_id]['venue'],
                'capacity': capacity, 'active_count': len(active_seats), 'released_count': len(evictions),
                'unpaid_released': unpaid, 'package_split': split,
                'due_cents': sum(item['due_cents'] for item in dues),
                'version': version['version'] if version else -1,
                'snapshot_id': version['snapshot_id'] if version else '',
                'balanced': not reason, 'reason_code': reason,
            })
        return {'book': book, 'balanced': balanced, 'shows': show_rows,
                'attempts': [self._attempt(row) for row in attempts],
                'evictions': [dict(row) for row in eviction_rows],
                'refund_dues': [dict(row) for row in due_rows]}

    @staticmethod
    def _attempt(row):
        return {'snapshot_id': row['snapshot_id'], 'status': row['status'], 'reason_code': row['reason_code'],
                'detail': json.loads(row['detail']) if row['detail'] else {}, 'recorded_at': row['recorded_at']}
