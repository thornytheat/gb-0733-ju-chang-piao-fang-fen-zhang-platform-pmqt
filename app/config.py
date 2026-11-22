from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / 'sample_data'
SAMPLE_BOOK = 'tour-demo'
PREVIEW = 'sample'
RULE_VERSION = 'theatre-1.0.0'
REPORT_ZONE = 'Asia/Shanghai'
MAX_SOURCE_BYTES = 512 * 1024
MAX_SOURCE_ROWS = 12_000
MAX_CENTS = 9_999_999_999

SOURCE_COLUMNS = {
    'tickets.csv': ('ticket', 'paid_at', 'amount', 'unit', 'status', 'note'),
    'shows.csv': ('show', 'title', 'venue', 'publication_status', 'opens', 'closes', 'cancelled_at'),
    'rights.csv': ('ticket', 'show', 'weight'),
    'scans.csv': ('scan_id', 'ticket', 'show', 'scanned_at', 'gate'),
    'refunds.csv': ('refund_id', 'ticket', 'show', 'refunded_at', 'amount', 'unit'),
}

# M8 场馆缩座的两份专用 CSV，独立于五份分账源，不进入 SOURCE_COLUMNS 契约。
SEAT_COLUMNS = {
    'seat_holds.csv': ('hold_id', 'show', 'seat_label', 'ticket', 'reservation_status', 'held_at'),
    'seat_reduction.csv': ('snapshot_id', 'show', 'reported_at', 'new_capacity', 'group_lock_deadline'),
}
SEAT_DB_NAME = 'seats.sqlite3'
