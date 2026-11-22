import io

from app.manifest import checksum
from app.modules.m7_evidence.csv_out import make_csv

HOLD_FIELDS = ('hold_id', 'show', 'seat_label', 'ticket', 'hold_status', 'held_at', 'line', 'end_line', 'raw')


def hold_voucher(hold, book, run_id):
    """单个占位凭证：人读 CSV + 内容指纹，作为清退依据的可下载副本。"""
    rows = [{**hold, 'raw': '|'.join(hold['raw'])}]
    body = make_csv(rows, HOLD_FIELDS)
    digest = checksum(body)
    header = io.StringIO(newline='')
    header.write(f'# 场馆缩座占位凭证\n# 账册: {book}\n# 关联运行: {run_id}\n# 占位编号: {hold["hold_id"]}\n')
    header.write(f'# 内容指纹 sha256: {digest}\n')
    return header.getvalue().encode('utf-8') + body, digest
