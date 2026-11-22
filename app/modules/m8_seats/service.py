from app.errors import Problem
from app.records import Isolations
from app.modules.m8_seats.records import parse_holds, parse_reductions


def snapshot_indexes(snapshot):
    """从已发布运行快照构建票码、场次索引，不改 m1–m7 快照契约。"""
    tickets = {row['ticket']: row for row in snapshot['tickets']}
    shows = {row['show']: row for row in snapshot['shows']}
    return tickets, shows


def allocation_index(snapshot):
    """已发布分账中票场份额，作为拆票待退款的金额依据。"""
    return {(row['ticket'], row['show']): row['allocated_cents'] for row in snapshot['publication']['allocations']}


def import_holds(seat_store, book, run_id, data, snapshot):
    isolates = Isolations()
    tickets, shows = snapshot_indexes(snapshot)
    holds, stats = parse_holds(data, tickets, shows, isolates)
    if isolates.rows:
        return {'accepted': 0, 'isolated': len(isolates.rows), 'quarantine': isolates.rows, 'replaced': False}
    result = seat_store.replace_holds(book, run_id, {'run_id': run_id, 'holds': holds}, holds)
    return {'accepted': len(holds), 'isolated': 0, 'quarantine': [], 'replaced': result['replaced'], 'stats': stats}


def apply_reduction(seat_store, book, data, snapshot):
    isolates = Isolations()
    _, shows = snapshot_indexes(snapshot)
    records, stats = parse_reductions(data, shows, isolates)
    if isolates.rows:
        return {'snapshot_id': '', 'reused': False, 'status': 'rejected', 'quarantine': isolates.rows, 'stats': stats}
    if not records:
        raise Problem(422, 'REDUCTION_EMPTY')
    result = seat_store.apply_reduction(book, data, records, shows, allocation_index(snapshot))
    return {**result, 'quarantine': [], 'stats': stats}
