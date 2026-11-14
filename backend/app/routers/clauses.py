"""条款结构化抽取接口。"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.schemas import ClauseExtractionResponse
from app.services import clause_service

router = APIRouter(prefix='/api/contract', tags=['clauses'])

UPLOAD_DIR = Path(__file__).resolve().parents[2] / 'uploads'


@router.post('/clauses', response_model=ClauseExtractionResponse)
async def extract_clauses(
    files: List[UploadFile] = File(...),
    roles: str = Form(''),
    use_llm: bool = Form(False),
) -> ClauseExtractionResponse:
    """上传宣传材料与合同，返回结构化条款和逐类比对结论。

    roles 用逗号分隔，按文件顺序对应：promo / contract / auto。
    留空时按原始文件名自动判断（含 promo/宣传 视为宣传材料）。
    """
    if not files:
        raise HTTPException(status_code=400, detail='至少上传一份材料')

    role_tokens = [token.strip() for token in roles.split(',')] if roles.strip() else []
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    specs = []
    for index, upload in enumerate(files):
        original_name = Path(upload.filename or f'upload_{index}').name
        suffix = Path(original_name).suffix
        target = UPLOAD_DIR / f'{uuid.uuid4().hex}{suffix}'
        target.write_bytes(await upload.read())
        role = role_tokens[index] if index < len(role_tokens) else ''
        specs.append((str(target), original_name, role))

    try:
        result = await run_in_threadpool(
            clause_service.extract_clauses, specs, use_llm,
        )
    except clause_service.DocumentReadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ClauseExtractionResponse(**result)
