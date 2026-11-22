from app.modules.m8_seats.seat_plan import check_show_balance, plan_show


def hold(hold_id, seat, ticket='', held_at='2026-11-05T10:00:00+00:00', status='held'):
    return {'hold_id': hold_id, 'show': 'S1', 'seat_label': seat, 'ticket': ticket,
            'hold_status': status, 'held_at': held_at, 'line': 1, 'end_line': 1, 'raw': [hold_id]}


def test_unpaid_holds_are_released_before_paid_package_seats():
    holds = [hold('H1', 'A1', 'T1'), hold('H2', 'A2'), hold('H3', 'A3', 'T2')]
    plan = plan_show('S1', holds, 1, {('T1', 'S1'): 500, ('T2', 'S1'): 700})
    assert plan['feasible'] and plan['gap'] == 2
    assert [item['hold_id'] for item in plan['evictions']] == ['H2', 'H1']
    assert [item['eviction_type'] for item in plan['evictions']] == ['unpaid_release', 'package_split']
    assert plan['refund_dues'] == [
        {'ticket': 'T1', 'show': 'S1', 'due_cents': 500, 'allocated_cents': 500, 'hold_id': 'H1'}]
    assert plan['remaining_seats'] == ['A3']


def test_paid_seat_without_published_allocation_cannot_be_split():
    holds = [hold('H1', 'A1', 'T1')]
    plan = plan_show('S1', holds, 0, {})
    assert not plan['feasible'] and plan['gap'] == 1 and plan['evictions'] == []


def test_released_holds_are_not_counted_as_active_or_clearable():
    holds = [hold('H1', 'A1', status='released'), hold('H2', 'A2')]
    plan = plan_show('S1', holds, 1, {})
    assert plan['feasible'] and plan['gap'] == 0
    assert plan['remaining_seats'] == ['A2']


def test_growth_or_equal_capacity_needs_no_eviction():
    holds = [hold('H1', 'A1', 'T1')]
    assert plan_show('S1', holds, 5, {('T1', 'S1'): 100})['evictions'] == []


def test_show_balance_detects_capacity_and_due_mismatch():
    evictions = [{'eviction_type': 'package_split'}]
    assert check_show_balance('S1', 1, ['A1', 'A2'], evictions, [{'due_cents': 10}]) == 'SEAT_CAPACITY_EXCEEDED'
    assert check_show_balance('S1', 2, ['A1', 'A2'], evictions, []) == 'SEAT_RECONCILE_FAILED'
    assert check_show_balance('S1', 2, ['A1', 'A2'], evictions, [{'due_cents': 10}]) == ''
