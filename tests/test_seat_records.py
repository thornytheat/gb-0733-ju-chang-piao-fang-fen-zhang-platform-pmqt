import csv
from io import StringIO

import pytest

from app.config import SEAT_COLUMNS
from app.modules.m8_seats.records import parse_holds, parse_reductions
from app.records import Isolations


def write(source, rows):
    stream = StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(SEAT_COLUMNS[source])
    writer.writerows(rows)
    return stream.getvalue().encode()


@pytest.fixture
def catalogue(sample):
    tickets = {row['ticket']: row for row in sample['tickets']}
    shows = {row['show']: row for row in sample['shows']}
    return tickets, shows


def test_holds_require_known_show_ticket_and_valid_status(catalogue):
    tickets, shows = catalogue
    data = write('seat_holds.csv', [
        ('H-OK', 'A-LAKE', 'A-1', '00107', 'held', '2026-11-05T10:00:00+08:00'),
        ('H-SHOW', 'NOPE', 'A-2', '', 'reserved', '2026-11-05T10:00:00+08:00'),
        ('H-TIX', 'A-LAKE', 'A-3', '999999', 'held', '2026-11-05T10:00:00+08:00'),
        ('H-STATUS', 'A-LAKE', 'A-4', '', 'blocked', '2026-11-05T10:00:00+08:00'),
        ('H-FREE', 'A-LAKE', 'A-5', '', 'reserved', '2026-11-05T10:00:00+08:00'),
    ])
    isolates = Isolations()
    holds, _ = parse_holds(data, tickets, shows, isolates)
    codes = {row['key']: row['code'] for row in isolates.rows}
    assert codes == {'H-SHOW': 'HOLD_SHOW_UNKNOWN', 'H-TIX': 'HOLD_TICKET_UNKNOWN',
                     'H-STATUS': 'HOLD_STATUS_INVALID'}
    assert [item['hold_id'] for item in holds] == ['H-OK', 'H-FREE']


def test_duplicate_seat_label_in_one_show_is_isolated(catalogue):
    tickets, shows = catalogue
    data = write('seat_holds.csv', [
        ('H-1', 'A-LAKE', 'DUP', '', 'reserved', '2026-11-05T10:00:00+08:00'),
        ('H-2', 'A-LAKE', 'DUP', '', 'reserved', '2026-11-05T10:01:00+08:00'),
        ('H-3', 'B-RAIN', 'DUP', '', 'reserved', '2026-11-05T10:02:00+08:00'),
    ])
    isolates = Isolations()
    holds, _ = parse_holds(data, tickets, shows, isolates)
    assert [row['code'] for row in isolates.rows] == ['SEAT_LABEL_DUPLICATE']
    assert {item['hold_id'] for item in holds} == {'H-1', 'H-3'}


def test_reduction_rows_require_known_show_and_non_negative_capacity(catalogue):
    _, shows = catalogue
    data = write('seat_reduction.csv', [
        ('SNAP-1', 'A-LAKE', '2026-11-17T20:00:00+08:00', '4', ''),
        ('SNAP-2', 'GHOST', '2026-11-17T20:00:00+08:00', '4', ''),
        ('SNAP-3', 'B-RAIN', '2026-11-17T20:00:00+08:00', '-1', ''),
    ])
    isolates = Isolations()
    records, _ = parse_reductions(data, shows, isolates)
    codes = {row['key']: row['code'] for row in isolates.rows}
    assert codes == {'SNAP-2': 'REDUCTION_SHOW_UNKNOWN', 'SNAP-3': 'REDUCTION_CAP_INVALID'}
    assert [item['snapshot_id'] for item in records] == ['SNAP-1']
