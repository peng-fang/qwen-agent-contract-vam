"""合同情景推演与决策评分相关路由。"""

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.schemas import (
    VamDeepenRequest,
    VamCompareRequest,
    VamExportRequest,
    VamExportResponse,
    VamResult,
    VamRunRequest,
)
from app.services import vam_service

router = APIRouter(prefix='/api/vam', tags=['vam'])


async def _execute(operation, *args):
    try:
        return await run_in_threadpool(operation, *args)
    except vam_service.RunUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_input=False, include_context=False)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail='模型暂时未能生成可用情景，请检查模型服务后重试。') from exc


@router.post('/run', response_model=VamResult)
async def run(req: VamRunRequest):
    return await _execute(vam_service.run, req)


@router.post('/deepen', response_model=VamResult)
async def deepen(req: VamDeepenRequest):
    return await _execute(vam_service.deepen, req.result, req.leaf_id)


@router.post('/compare', response_model=VamResult)
async def compare(req: VamCompareRequest):
    return await _execute(vam_service.compare, req)


@router.post('/export', response_model=VamExportResponse)
async def export(req: VamExportRequest):
    markdown = await _execute(vam_service.export_markdown, req.result)
    return VamExportResponse(markdown=markdown)
