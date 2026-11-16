"""合同核验相关路由。"""

import asyncio
import json
import queue
import re
import threading
import uuid
from pathlib import Path
from typing import List

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.schemas import ContractAnalyzeResponse, RentalReviewResponse
from app.services.contract_service import analyze_contract
from app.services.clause_service import inspect_amounts
from app.services import rental_review_service

router = APIRouter(prefix='/api/contract', tags=['contract'])

UPLOAD_DIR = Path(__file__).resolve().parents[2] / 'uploads'

_MONEY_IN_ANSWER = re.compile(r'[0-9]+\s*(?:元|块)|退款|退费|违约金|手续费')


def _amount_notice(answer: str, checks: List[dict]) -> str:
    """模型回答含金额时，先说明确定性条件核验是否通过。"""
    if not checks or not _MONEY_IN_ANSWER.search(answer or ''):
        return ''
    blocked = [
        item for item in checks
        if item.get('status') in {'not_applicable', 'insufficient', 'conditional'}
    ]
    if not blocked:
        return ''
    details = '；'.join(
        f"{item.get('clause_label', item.get('clause_type'))}：{item.get('status_label', '')}"
        for item in blocked
    )
    return (
        '【金额适用条件未全部满足】' + details
        + '。以下回答中的金额不能直接作为结算依据，请先补齐条件或参数。'
    )


@router.post('/analyze', response_model=ContractAnalyzeResponse)
async def analyze(
    question: str = Form(...),
    files: List[UploadFile] = File(...),
):
    """上传一份或多份材料 + 问题，返回合同核验回答。"""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    saved: List[str] = []
    specs: List[tuple] = []
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
        specs.append((str(dest), Path(f.filename).name))

    answer = await run_in_threadpool(analyze_contract, saved, question)
    try:
        checks = await run_in_threadpool(inspect_amounts, specs)
    except Exception:  # noqa: BLE001 - 条件核验失败不能阻断问答
        checks = []
    return ContractAnalyzeResponse(
        question=question,
        answer=answer,
        files=[Path(p).name for p in saved],
        amount_checks=checks,
        amount_notice=_amount_notice(answer, checks),
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

    def progress(stage: str, status: str, detail: str = '') -> None:
        events.put({'type': 'progress', 'stage': stage, 'status': status, 'detail': detail})

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
