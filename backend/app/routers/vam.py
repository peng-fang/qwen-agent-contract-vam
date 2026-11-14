"""合同情景推演与决策评分相关路由。"""

from fastapi import APIRouter, HTTPException
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

MODEL_UNAVAILABLE = (
    '推演服务不可用：未检测到可用的模型或评分服务。'
    '请启动 Ollama / 配置 DashScope，或启动 Intern sidecar（8010）。'
    '条款对照、风险评分与规则评测不依赖模型，仍可正常使用。'
)


@router.post('/run', response_model=VamResult)
async def run(req: VamRunRequest):
    try:
        return await run_in_threadpool(vam_service.run, req.query)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f'{MODEL_UNAVAILABLE}（{exc}）') from exc


@router.post('/deepen', response_model=VamResult)
async def deepen(req: VamDeepenRequest):
    try:
        return await run_in_threadpool(vam_service.deepen, req.result, req.leaf_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f'{MODEL_UNAVAILABLE}（{exc}）') from exc


@router.post('/export', response_model=VamExportResponse)
async def export(req: VamExportRequest):
    markdown = await run_in_threadpool(vam_service.export_markdown, req.result)
    return VamExportResponse(markdown=markdown)
