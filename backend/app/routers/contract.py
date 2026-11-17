"""合同核验相关路由。"""

import asyncio
import copy
import json
import queue
import threading
import uuid
from pathlib import Path
from typing import List

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from qwen_agent.llm.base import ModelServiceError
from starlette.concurrency import run_in_threadpool

from app.schemas import ContractAnalyzeResponse, RentalReviewResponse
from app.services.contract_service import analyze_contract, analyze_contract_stream
from app.services import rental_review_service

router = APIRouter(prefix='/api/contract', tags=['contract'])

UPLOAD_DIR = Path(__file__).resolve().parents[2] / 'uploads'


async def _save_uploads(files: List[UploadFile]) -> List[str]:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved: List[str] = []
    for f in files:
        if not f.filename:
            continue
        suffix = Path(f.filename).suffix or ''
        name = f'{uuid.uuid4().hex}{suffix}'
        dest = UPLOAD_DIR / name
        data = await f.read()
        async with aiofiles.open(dest, 'wb') as out:
            await out.write(data)
        saved.append(str(dest))
    return saved


@router.post('/analyze', response_model=ContractAnalyzeResponse)
async def analyze(
    question: str = Form(...),
    files: List[UploadFile] = File(...),
):
    """上传一份或多份材料 + 问题，返回合同核验回答。"""
    saved = await _save_uploads(files)

    try:
        answer = await run_in_threadpool(analyze_contract, saved, question)
    except ModelServiceError as exc:
        raise HTTPException(
            status_code=503,
            detail='本地模型服务不可用。请确认 Ollama 已启动，且 qwen2.5:7b 已下载。',
        ) from exc
    return ContractAnalyzeResponse(
        question=question,
        answer=answer,
        files=[Path(p).name for p in saved],
    )


@router.post('/analyze/stream')
async def analyze_stream(
    question: str = Form(...),
    files: List[UploadFile] = File(...),
):
    """流式返回合同核验回答；事件类型为 chunk / done / error。"""
    saved = await _save_uploads(files)

    def event_generator():
        try:
            for text in analyze_contract_stream(saved, question):
                yield f"data: {json.dumps({'type': 'chunk', 'text': text}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'files': [Path(p).name for p in saved]}, ensure_ascii=False)}\n\n"
        except ModelServiceError as exc:
            detail = '本地模型服务不可用。请确认 Ollama 已启动，且 qwen2.5:7b 已下载。'
            yield f"data: {json.dumps({'type': 'error', 'detail': detail}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@router.post('/rental-review', response_model=RentalReviewResponse)
async def rental_review(
    file: UploadFile = File(...),
    use_llm: bool = Form(True),
    region: str = Form('mainland'),
    contract_type: str = Form('rental'),
):
    """上传一份合同，返回多 Agent 风险审查报告。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail='请上传一份合同')

    region = (region or 'mainland').strip().lower()
    if region not in {'mainland', 'hongkong'}:
        raise HTTPException(status_code=400, detail='region 只支持 mainland 或 hongkong')

    contract_type = (contract_type or 'rental').strip().lower()
    if contract_type not in {'rental', 'consumer', 'procurement', 'labor', 'loan', 'ecommerce', 'franchise', 'dispute', 'other', 'auto'}:
        raise HTTPException(status_code=400, detail='不支持的 contract_type')

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {'.pdf', '.docx', '.txt', '.md'}:
        raise HTTPException(status_code=400, detail='只支持 PDF、DOCX、TXT、MD 格式')

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / f'{uuid.uuid4().hex}{suffix}'
    data = await file.read()
    async with aiofiles.open(target, 'wb') as out:
        await out.write(data)

    try:
        result = await run_in_threadpool(
            rental_review_service.run,
            str(target),
            Path(file.filename).name,
            use_llm,
            region,
            contract_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    result['file_id'] = target.name
    return RentalReviewResponse(**result)


@router.post('/rental-review/stream')
async def rental_review_stream(
    file: UploadFile = File(...),
    use_llm: bool = Form(True),
    region: str = Form('mainland'),
    contract_type: str = Form('rental'),
):
    """SSE 版本：推送解析、分类、规则、模型、法律检索和 Judge 阶段。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail='请上传一份合同')

    region = (region or 'mainland').strip().lower()
    if region not in {'mainland', 'hongkong'}:
        raise HTTPException(status_code=400, detail='region 只支持 mainland 或 hongkong')

    contract_type = (contract_type or 'rental').strip().lower()
    if contract_type not in {'rental', 'consumer', 'procurement', 'labor', 'loan', 'ecommerce', 'franchise', 'dispute', 'other', 'auto'}:
        raise HTTPException(status_code=400, detail='不支持的 contract_type')

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {'.pdf', '.docx', '.txt', '.md'}:
        raise HTTPException(status_code=400, detail='只支持 PDF、DOCX、TXT、MD 格式')

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target = UPLOAD_DIR / f'{uuid.uuid4().hex}{suffix}'
    data = await file.read()
    async with aiofiles.open(target, 'wb') as out:
        await out.write(data)

    events: queue.Queue = queue.Queue()

    def progress(stage: str, status: str, detail: str = '', payload=None) -> None:
        events.put({'type': 'progress', 'stage': stage, 'status': status, 'detail': detail})
        if isinstance(payload, dict) and isinstance(payload.get('risks'), list):
            events.put({
                'type': 'partial',
                'phase': payload.get('phase', ''),
                'risks': copy.deepcopy(payload['risks']),
            })

    def worker() -> None:
        try:
            result = rental_review_service.run(
                str(target),
                Path(file.filename).name,
                use_llm,
                region,
                contract_type,
                progress=progress,
            )
            result['file_id'] = target.name
            events.put({'type': 'result', 'result': result})
        except Exception as exc:  # noqa: BLE001
            events.put({'type': 'error', 'detail': str(exc)})
        finally:
            events.put(None)

    threading.Thread(target=worker, name='rental-review-stream', daemon=True).start()

    async def event_generator():
        try:
            while True:
                item = await asyncio.to_thread(events.get)
                if item is None:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass

    return StreamingResponse(
        event_generator(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )
