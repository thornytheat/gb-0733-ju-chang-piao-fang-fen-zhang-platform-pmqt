import csv
from io import StringIO

import pytest

from app.config import SAMPLE_DIR, SEAT_COLUMNS


def seat_csv(source, rows):
    stream = StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(SEAT_COLUMNS[source])
    writer.writerows(rows)
    return stream.getvalue().encode()


def holds_bytes():
    return (SAMPLE_DIR / 'seat_holds.csv').read_bytes()


def reductions_bytes():
    return (SAMPLE_DIR / 'seat_reduction.csv').read_bytes()


def test_sample_preview_books_unpaid_first_then_package_split(client):
    report = client.get('/api/seats/sample').json()
    by_show = {row['show']: row for row in report['items']}
    assert report['balanced'] is True
    assert (by_show['A-LAKE']['unpaid_released'], by_show['A-LAKE']['package_split']) == (2, 0)
    assert (by_show['B-RAIN']['unpaid_released'], by_show['B-RAIN']['package_split'],
            by_show['B-RAIN']['due_cents']) == (2, 1, 3334)
    # 团体锁超时：拒绝留痕且座位版本未推进。
    assert by_show['E-MATINEE']['version'] == -1 and by_show['E-MATINEE']['active_count'] == 2
    attempts = client.get('/api/seats/sample', params={'view': 'attempts'}).json()['items']
    rejected = next(item for item in attempts if item['snapshot_id'] == 'SNAP-EM-LATE')
    assert rejected['status'] == 'rejected' and rejected['reason_code'] == 'GROUP_LOCK_DEADLINE_PASSED'


def test_snapshot_retry_does_not_add_occupancy_or_duplicate_eviction(client):
    run_id = client.post('/api/runs/sample').json()['run_id']
    client.post(f'/api/seats/{run_id}/holds',
                files={'files': ('seat_holds.csv', holds_bytes(), 'text/csv')})
    rows = reductions_bytes().splitlines()
    payload = b'\n'.join((rows[0], rows[1]))
    first = client.post(f'/api/seats/{run_id}/reductions',
                        files={'files': ('seat_reduction.csv', payload, 'text/csv')}).json()
    second = client.post(f'/api/seats/{run_id}/reductions',
                         files={'files': ('seat_reduction.csv', payload, 'text/csv')}).json()
    assert first['reused'] is False and second['reused'] is True
    evictions = client.get(f'/api/seats/{run_id}', params={'view': 'evictions'}).json()['items']
    assert len(evictions) == 2 and len({item['id'] for item in evictions}) == 2
    versions = [item for item in client.get(f'/api/seats/{run_id}').json()['items']
                if item['show'] == 'A-LAKE']
    assert versions[0]['version'] == 0


def test_failed_reduction_rolls_back_seats_but_keeps_attempt_record(client):
    run_id = client.post('/api/runs/sample').json()['run_id']
    extra = holds_bytes() + b'H-E2,E-MATINEE,E-02,00107,held,2026-11-05T14:05:00+08:00\n'
    client.post(f'/api/seats/{run_id}/holds',
                files={'files': ('seat_holds.csv', extra, 'text/csv')})
    first = seat_csv('seat_reduction.csv', [
        ('SNAP-E1', 'E-MATINEE', '2026-11-17T20:00:00+08:00', '1', '')])
    client.post(f'/api/seats/{run_id}/reductions',
                files={'files': ('seat_reduction.csv', first, 'text/csv')})
    impossible = seat_csv('seat_reduction.csv', [
        ('SNAP-E0', 'E-MATINEE', '2026-11-17T20:05:00+08:00', '0', '')])
    response = client.post(f'/api/seats/{run_id}/reductions',
                           files={'files': ('seat_reduction.csv', impossible, 'text/csv')})
    assert response.status_code == 409 and response.json()['code'] == 'SEAT_CAPACITY_EXCEEDED'
    show = next(item for item in client.get(f'/api/seats/{run_id}').json()['items']
                if item['show'] == 'E-MATINEE')
    assert (show['capacity'], show['active_count'], show['version']) == (1, 1, 0)
    hold = client.get(f'/api/seats/{run_id}/holds', params={'q': 'H-E2'}).json()['items'][0]
    assert hold['hold_status'] == 'held'
    attempts = client.get(f'/api/seats/{run_id}', params={'view': 'attempts'}).json()['items']
    assert [item['status'] for item in attempts] == ['applied', 'rejected']


def test_eviction_and_refund_due_are_append_only_with_full_basis(client):
    run_id = client.post('/api/runs/sample').json()['run_id']
    client.post(f'/api/seats/{run_id}/holds',
                files={'files': ('seat_holds.csv', holds_bytes(), 'text/csv')})
    payload = b'\n'.join(reductions_bytes().splitlines()[:3])
    client.post(f'/api/seats/{run_id}/reductions',
                files={'files': ('seat_reduction.csv', payload, 'text/csv')})
    dues = client.get(f'/api/seats/{run_id}', params={'view': 'dues'}).json()['items']
    due = next(item for item in dues if item['ticket'] == '00107')
    assert (due['show'], due['due_cents'], due['allocated_cents'], due['state']) == ('B-RAIN', 3334, 3334, 'due')
    evictions = client.get(f'/api/seats/{run_id}', params={'view': 'evictions'}).json()['items']
    split = next(item for item in evictions if item['eviction_type'] == 'package_split')
    assert split['hold_id'] == 'H-B1' and split['source_line'] == 8 and split['ticket'] == '00107'


def test_hold_voucher_is_deterministic_and_carries_fingerprint(client):
    run_id = client.post('/api/runs/sample').json()['run_id']
    client.post(f'/api/seats/{run_id}/holds',
                files={'files': ('seat_holds.csv', holds_bytes(), 'text/csv')})
    first = client.get(f'/api/seats/{run_id}/holds/H-B1/voucher')
    second = client.get(f'/api/seats/{run_id}/holds/H-B1/voucher')
    assert first.status_code == 200 and first.content == second.content
    assert first.headers['X-Content-SHA256'] in first.content.decode()
    assert 'H-B1' in first.content.decode() and 'text/csv' in first.headers['content-type']
    missing = client.get(f'/api/seats/{run_id}/holds/NOPE/voucher')
    assert missing.status_code == 404 and missing.json()['code'] == 'HOLD_NOT_FOUND'


def test_holds_cannot_be_rewritten_after_a_reduction_is_applied(client):
    run_id = client.post('/api/runs/sample').json()['run_id']
    files = {'files': ('seat_holds.csv', holds_bytes(), 'text/csv')}
    assert client.post(f'/api/seats/{run_id}/holds', files=files).json()['accepted'] == 15
    payload = b'\n'.join(reductions_bytes().splitlines()[:2])
    client.post(f'/api/seats/{run_id}/reductions',
                files={'files': ('seat_reduction.csv', payload, 'text/csv')})
    response = client.post(f'/api/seats/{run_id}/holds', files=files)
    assert response.status_code == 409 and response.json()['code'] == 'SEAT_BASELINE_LOCKED'


def test_quarantined_hold_rows_never_create_occupancy(client):
    run_id = client.post('/api/runs/sample').json()['run_id']
    bad = holds_bytes() + b'H-BAD,A-LAKE,A-99,999999,held,2026-11-05T10:00:00+08:00\n'
    outcome = client.post(f'/api/seats/{run_id}/holds',
                          files={'files': ('seat_holds.csv', bad, 'text/csv')}).json()
    assert outcome['accepted'] == 0 and outcome['isolated'] == 1
    assert client.get(f'/api/seats/{run_id}/holds', params={'q': 'H-BAD'}).json()['total'] == 0


def test_header_only_reduction_is_rejected_with_422(client):
    run_id = client.post('/api/runs/sample').json()['run_id']
    client.post(f'/api/seats/{run_id}/holds',
                files={'files': ('seat_holds.csv', holds_bytes(), 'text/csv')})
    header_only = b'snapshot_id,show,reported_at,new_capacity,group_lock_deadline\n'
    response = client.post(f'/api/seats/{run_id}/reductions',
                           files={'files': ('seat_reduction.csv', header_only, 'text/csv')})
    assert response.status_code == 422 and response.json()['code'] == 'REDUCTION_EMPTY'


def test_multi_show_snapshot_rolls_back_when_any_show_is_infeasible(client):
    run_id = client.post('/api/runs/sample').json()['run_id']
    extra = holds_bytes() + b'H-D1,D-HOLD,D-01,00109,held,2026-11-05T14:05:00+08:00\n'
    client.post(f'/api/seats/{run_id}/holds',
                files={'files': ('seat_holds.csv', extra, 'text/csv')})
    payload = seat_csv('seat_reduction.csv', [
        ('SNAP-MULTI', 'A-LAKE', '2026-11-17T20:05:00+08:00', '3', ''),
        ('SNAP-MULTI', 'D-HOLD', '2026-11-17T20:05:00+08:00', '0', '')])
    response = client.post(f'/api/seats/{run_id}/reductions',
                           files={'files': ('seat_reduction.csv', payload, 'text/csv')})
    assert response.status_code == 409 and response.json()['code'] == 'SEAT_CAPACITY_EXCEEDED'
    rows = {item['show']: item for item in client.get(f'/api/seats/{run_id}').json()['items']}
    # 整单回退：A-LAKE 的可行改动也不得落库。
    assert rows['A-LAKE']['version'] == -1 and rows['A-LAKE']['active_count'] == 6
    assert rows['D-HOLD']['active_count'] == 1 and rows['D-HOLD']['version'] == -1
    attempts = client.get(f'/api/seats/{run_id}', params={'view': 'attempts'}).json()['items']
    assert attempts[-1]['status'] == 'rejected'


def test_group_lock_deadline_rejection_leaves_seats_untouched(client):
    run_id = client.post('/api/runs/sample').json()['run_id']
    client.post(f'/api/seats/{run_id}/holds',
                files={'files': ('seat_holds.csv', holds_bytes(), 'text/csv')})
    payload = seat_csv('seat_reduction.csv', [
        ('SNAP-LATE', 'E-MATINEE', '2026-11-18T18:30:00+08:00', '1', '2026-11-18T18:00:00+08:00')])
    response = client.post(f'/api/seats/{run_id}/reductions',
                           files={'files': ('seat_reduction.csv', payload, 'text/csv')})
    assert response.status_code == 409 and response.json()['code'] == 'GROUP_LOCK_DEADLINE_PASSED'
    show = next(item for item in client.get(f'/api/seats/{run_id}').json()['items']
                if item['show'] == 'E-MATINEE')
    assert show['version'] == -1 and show['active_count'] == 2
    # 同一快照 ID 重发只返回原裁决，不重复处理。
    replay = client.post(f'/api/seats/{run_id}/reductions',
                         files={'files': ('seat_reduction.csv', payload, 'text/csv')}).json()
    assert replay['reused'] is True and replay['status'] == 'rejected'
    # 场馆改发新快照（新 ID、合规时刻）后才能成功。
    fixed = seat_csv('seat_reduction.csv', [
        ('SNAP-ON-TIME', 'E-MATINEE', '2026-11-18T17:30:00+08:00', '1', '2026-11-18T18:00:00+08:00')])
    ok = client.post(f'/api/seats/{run_id}/reductions',
                     files={'files': ('seat_reduction.csv', fixed, 'text/csv')})
    assert ok.status_code == 200 and ok.json()['status'] == 'applied'
