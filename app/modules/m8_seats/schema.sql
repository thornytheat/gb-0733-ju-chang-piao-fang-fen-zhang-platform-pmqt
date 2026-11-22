-- 场馆缩座（M8）独立账册：座位版本化、清退依据只追加。
CREATE TABLE IF NOT EXISTS seat_books (
    book TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS seat_holds (
    id TEXT NOT NULL,
    book TEXT NOT NULL REFERENCES seat_books(book),
    show TEXT NOT NULL,
    seat_label TEXT NOT NULL,
    ticket TEXT NOT NULL DEFAULT '',
    hold_status TEXT NOT NULL,
    held_at TEXT NOT NULL,
    source_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    raw TEXT NOT NULL,
    PRIMARY KEY (book, id)
);
CREATE INDEX IF NOT EXISTS seat_holds_book_show ON seat_holds(book, show);
CREATE TABLE IF NOT EXISTS seat_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book TEXT NOT NULL REFERENCES seat_books(book),
    show TEXT NOT NULL,
    version INTEGER NOT NULL,
    snapshot_id TEXT NOT NULL,
    capacity INTEGER NOT NULL,
    active_seats TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (book, show, version)
);
CREATE TABLE IF NOT EXISTS seat_snapshot_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book TEXT NOT NULL REFERENCES seat_books(book),
    snapshot_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    source_lines TEXT NOT NULL,
    status TEXT NOT NULL,
    reason_code TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    received_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE (book, snapshot_id)
);
CREATE TABLE IF NOT EXISTS seat_evictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book TEXT NOT NULL REFERENCES seat_books(book),
    snapshot_id TEXT NOT NULL,
    show TEXT NOT NULL,
    seat_label TEXT NOT NULL,
    hold_id TEXT NOT NULL,
    ticket TEXT NOT NULL DEFAULT '',
    eviction_type TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    source_line INTEGER NOT NULL,
    evicted_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS seat_evictions_book_show ON seat_evictions(book, show);
CREATE TABLE IF NOT EXISTS seat_refund_dues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book TEXT NOT NULL REFERENCES seat_books(book),
    eviction_id INTEGER NOT NULL REFERENCES seat_evictions(id),
    snapshot_id TEXT NOT NULL,
    ticket TEXT NOT NULL,
    show TEXT NOT NULL,
    due_cents INTEGER NOT NULL,
    allocated_cents INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'due',
    created_at TEXT NOT NULL,
    UNIQUE (book, eviction_id)
);
CREATE INDEX IF NOT EXISTS seat_dues_book_show ON seat_refund_dues(book, show);
