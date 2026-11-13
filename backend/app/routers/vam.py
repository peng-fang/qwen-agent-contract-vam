"""对赌协议推演相关路由。"""

from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from app.schemas import (
    VamDeepenRequest,
    VamExportRequest,
    VamExportResponse,
    VamResult,
    VamRunRequest,
)
from app.services import vam_service

router = APIRouter(prefix='/api/vam', tags=['vam'])


@router.post('/run', response_model=VamResult)
async def run(req: VamRunRequest):
    return await run_in_threadpool(vam_service.run, req.query)


@router.post('/deepen', response_model=VamResult)
async def deepen(req: VamDeepenRequest):
    return await run_in_threadpool(vam_service.deepen, req.result, req.leaf_id)


@router.post('/export', response_model=VamExportResponse)
async def export(req: VamExportRequest):
    markdown = await run_in_threadpool(vam_service.export_markdown, req.result)
    return VamExportResponse(markdown=markdown)
