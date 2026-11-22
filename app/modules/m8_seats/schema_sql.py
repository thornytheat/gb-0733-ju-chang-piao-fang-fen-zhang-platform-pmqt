from pathlib import Path

SEAT_SCHEMA = Path(__file__).with_name('schema.sql').read_text(encoding='utf-8')
