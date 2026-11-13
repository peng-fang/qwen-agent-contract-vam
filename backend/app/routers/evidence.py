"""证据定位相关路由。"""

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from app.schemas import EvidenceSearchRequest, EvidenceSearchResponse
from app.services import evidence_service

router = APIRouter(prefix='/api/evidence', tags=['evidence'])


@router.post('/search', response_model=EvidenceSearchResponse)
async def search(req: EvidenceSearchRequest):
    matches = await run_in_threadpool(evidence_service.search, req.filename, req.query)
    return EvidenceSearchResponse(matches=matches)
