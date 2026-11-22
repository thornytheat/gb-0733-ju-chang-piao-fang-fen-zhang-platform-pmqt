from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response

from app.browse import Browse, snapshot_for
from app.config import MAX_SOURCE_BYTES, PREVIEW
from app.errors import Problem
from app.modules.m8_seats.preview import PREVIEW_BOOK
from app.modules.m8_seats.service import apply_reduction, import_holds, snapshot_indexes
from app.modules.m8_seats.voucher import hold_voucher
from app.reasons import REASONS

router = APIRouter(prefix='/api/seats')


def seat_store(request):
    return request.app.state.seats


def book_for(run_id, snapshot):
    """预览运行落在独立座位账册，真实运行按分账账册隔离。"""
    return PREVIEW_BOOK if run_id == PREVIEW else snapshot['manifest']['book']


def require_one(filename, files):
    names = [item.filename for item in files]
    if names != [filename]:
        raise Problem(422, 'SEAT_SOURCE_SET', {'expected': [filename]})
    raw = files[0].file.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise Problem(413, 'FILE_LIMIT', {'source': filename})
    return raw


@router.post('/{run_id}/holds')
def upload_holds(request: Request, run_id: str, files: Annotated[list[UploadFile], File()]):
    snapshot = snapshot_for(request, run_id)
    data = require_one('seat_holds.csv', files)
    book = book_for(run_id, snapshot)
    outcome = import_holds(seat_store(request), book, snapshot['manifest']['run_id'], data, snapshot)
    quarantine = [{**row, 'reason': REASONS[row['code']]} for row in outcome['quarantine']]
    return {'book': book, 'accepted': outcome['accepted'], 'isolated': outcome['isolated'],
            'replaced': outcome['replaced'], 'quarantine': quarantine}


@router.post('/{run_id}/reductions')
def upload_reduction(request: Request, run_id: str, files: Annotated[list[UploadFile], File()]):
    snapshot = snapshot_for(request, run_id)
    data = require_one('seat_reduction.csv', files)
    book = book_for(run_id, snapshot)
    outcome = apply_reduction(seat_store(request), book, data, snapshot)
    quarantine = [{**row, 'reason': REASONS[row['code']]} for row in outcome['quarantine']]
    return {**{key: outcome.get(key) for key in ('snapshot_id', 'reused', 'status', 'shows')},
            'book': book, 'isolated': len(quarantine), 'quarantine': quarantine}


@router.get('/{run_id}')
def seat_report(request: Request, run_id: str, browse: Browse = Depends()):
    snapshot = snapshot_for(request, run_id)
    _, shows = snapshot_indexes(snapshot)
    report = seat_store(request).report(book_for(run_id, snapshot), shows)
    if browse.view == 'accepted':
        browse.view = 'shows'
    rows = browse.choose({
        'shows': report['shows'],
        'evictions': [{**row, 'reason': REASONS.get(row['reason_code'], row['reason_code'])}
                      for row in report['evictions']],
        'dues': report['refund_dues'],
        'attempts': [{**row, 'reason': REASONS.get(row['reason_code'], '') if row['reason_code'] else ''}
                     for row in report['attempts']],
    })
    return browse.page(rows, book=report['book'], balanced=report['balanced'])


@router.get('/{run_id}/holds/{hold_id}/voucher')
def hold_proof(request: Request, run_id: str, hold_id: str):
    snapshot = snapshot_for(request, run_id)
    book = book_for(run_id, snapshot)
    hold = seat_store(request).hold(book, hold_id)
    body, digest = hold_voucher(hold, book, snapshot['manifest']['run_id'])
    return Response(body, media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="hold-{hold_id}.csv"',
                             'X-Content-SHA256': digest})


@router.get('/{run_id}/holds')
def list_holds(request: Request, run_id: str, browse: Browse = Depends()):
    snapshot = snapshot_for(request, run_id)
    rows = seat_store(request).holds(book_for(run_id, snapshot))
    return browse.page(rows)
