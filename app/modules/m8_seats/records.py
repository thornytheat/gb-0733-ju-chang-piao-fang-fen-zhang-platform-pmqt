from app.config import SEAT_COLUMNS
from app.contracts import key, text, timestamp
from app.deduplicate import unique_records
from app.errors import RowError
from app.modules.m1_intake.reader import read_source

VALID_HOLD_STATUS = {'reserved', 'held', 'released'}


def _integer(value):
    value = text(value)
    if not value.isdigit():
        raise RowError('REDUCTION_CAP_INVALID')
    number = int(value)
    if number < 0 or number > 1_000_000:
        raise RowError('REDUCTION_CAP_INVALID')
    return number


def _optional_time(value):
    value = value.strip()
    return timestamp(value) if value else None


def _optional_key(value):
    value = value.strip()
    return key(value) if value else ''


def hold_records(rows, tickets, shows, isolates):
    for row in rows:
        values = row.values
        try:
            hold_id, show = key(values['hold_id']), key(values['show'])
            record = {
                'hold_id': hold_id, 'show': show, 'seat_label': text(values['seat_label']),
                'ticket': _optional_key(values['ticket']),
                'hold_status': text(values['reservation_status']), 'held_at': timestamp(values['held_at']),
            }
            if record['hold_status'] not in VALID_HOLD_STATUS:
                raise RowError('HOLD_STATUS_INVALID')
            if show not in shows:
                raise RowError('HOLD_SHOW_UNKNOWN')
            if record['ticket']:
                if record['ticket'] not in tickets:
                    raise RowError('HOLD_TICKET_UNKNOWN')
                if tickets[record['ticket']]['status'] != 'paid':
                    raise RowError('HOLD_TICKET_UNPAID')
        except RowError as exc:
            isolates.add(row, exc.code, values['hold_id'])
            continue
        yield record, row


def reduction_records(rows, shows, isolates):
    for row in rows:
        values = row.values
        try:
            snapshot_id, show = key(values['snapshot_id']), key(values['show'])
            record = {
                'snapshot_id': snapshot_id, 'show': show, 'reported_at': timestamp(values['reported_at']),
                'new_capacity': _integer(values['new_capacity']),
                'group_lock_deadline': _optional_time(values['group_lock_deadline']),
            }
            if show not in shows:
                raise RowError('REDUCTION_SHOW_UNKNOWN')
        except RowError as exc:
            isolates.add(row, exc.code, values['snapshot_id'])
            continue
        yield record, row


def parse_holds(data, tickets, shows, isolates):
    stats = {}
    rows = list(read_source(data, 'seat_holds.csv', stats, isolates, SEAT_COLUMNS['seat_holds.csv']))
    records = list(unique_records(hold_records(rows, tickets, shows, isolates), lambda item: item['hold_id'],
                                  'HOLD_ID_DUPLICATE', 'HOLD_ID_CONFLICT', isolates))
    seen, clean = set(), []
    for record in records:
        marker = (record['show'], record['seat_label'])
        if marker in seen:
            isolates.add_record(record, 'SEAT_LABEL_DUPLICATE', record['hold_id'],
                                show=record['show'], seat_label=record['seat_label'])
            continue
        seen.add(marker)
        clean.append(record)
    clean.sort(key=lambda item: (item['show'], item['seat_label'], item['hold_id']))
    return clean, stats


def parse_reductions(data, shows, isolates):
    stats = {}
    rows = list(read_source(data, 'seat_reduction.csv', stats, isolates, SEAT_COLUMNS['seat_reduction.csv']))
    records = list(unique_records(reduction_records(rows, shows, isolates),
                                  lambda item: (item['snapshot_id'], item['show']),
                                  'REDUCTION_DUPLICATE', 'REDUCTION_CONFLICT', isolates))
    records.sort(key=lambda item: (item['snapshot_id'], item['show']))
    return records, stats
