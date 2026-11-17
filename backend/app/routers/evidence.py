"""Evidence search and indexing routes."""

import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.schemas import EvidenceSearchRequest, EvidenceSearchResponse
from app.services import evidence_service
from app.routers.contract import UPLOAD_DIR

router = APIRouter(prefix='/api/evidence', tags=['evidence'])
MAX_UPLOAD = 10 * 1024 * 1024


@router.post('/index')
async def index(file: UploadFile = File(...)):
    """Persist a PDF once and return the id used by evidence search/checklist."""
    if not file.filename or Path(file.filename).suffix.lower() != '.pdf':
        raise HTTPException(400, '证据定位只支持 PDF 文件。')
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, '合同文件最多 10 MB。')
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f'{uuid.uuid4().hex}.pdf'
    (UPLOAD_DIR / name).write_bytes(data)
    return {'file_id': name, 'filename': Path(file.filename).name}


@router.post('/search', response_model=EvidenceSearchResponse)
async def search(req: EvidenceSearchRequest):
    matches = await run_in_threadpool(evidence_service.search, req.filename, req.query)
    return EvidenceSearchResponse(matches=matches)
