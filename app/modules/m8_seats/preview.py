from app.config import SAMPLE_DIR
from app.errors import Problem
from app.modules.m8_seats.records import parse_holds, parse_reductions
from app.modules.m8_seats.service import allocation_index, snapshot_indexes
from app.records import Isolations

# 预览使用独立账册命名空间，避免与真实发布的同名账册座位数据互相污染。
PREVIEW_BOOK = 'preview-sample'


def seed_preview(seat_store, snapshot):
    """把内置样例座位与缩座快照灌入独立座位库，供 /api/seats/sample 预览。"""
    if seat_store.book_exists(PREVIEW_BOOK):
        return
    tickets, shows = snapshot_indexes(snapshot)
    holds_data = (SAMPLE_DIR / 'seat_holds.csv').read_bytes()
    holds, _ = parse_holds(holds_data, tickets, shows, Isolations())
    seat_store.replace_holds(PREVIEW_BOOK, snapshot['manifest']['run_id'], {'preview': True}, holds)
    reductions_data = (SAMPLE_DIR / 'seat_reduction.csv').read_bytes()
    records, _ = parse_reductions(reductions_data, shows, Isolations())
    grouped = {}
    for record in records:
        grouped.setdefault(record['snapshot_id'], []).append(record)
    allocations = allocation_index(snapshot)
    for snapshot_id in sorted(grouped):
        try:
            seat_store.apply_reduction(PREVIEW_BOOK, reductions_data, grouped[snapshot_id], shows, allocations)
        except Problem:
            # 拒绝的快照也已在 attempts 中留痕，预览继续应用后续快照。
            continue
