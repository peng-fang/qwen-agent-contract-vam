"""合同核验相关路由。"""

import uuid
from pathlib import Path
from typing import List

import aiofiles
from fastapi import APIRouter, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from app.schemas import ContractAnalyzeResponse
from app.services.contract_service import analyze_contract

router = APIRouter(prefix='/api/contract', tags=['contract'])

UPLOAD_DIR = Path(__file__).resolve().parents[2] / 'uploads'


@router.post('/analyze', response_model=ContractAnalyzeResponse)
async def analyze(
    question: str = Form(...),
    files: List[UploadFile] = File(...),
):
    """上传一份或多份材料 + 问题，返回合同核验回答。"""
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

    answer = await run_in_threadpool(analyze_contract, saved, question)
    return ContractAnalyzeResponse(
        question=question,
        answer=answer,
        files=[Path(p).name for p in saved],
    )
