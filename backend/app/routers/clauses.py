"""条款结构化抽取、证据反查与合同版本对比接口。"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import List, Tuple

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app.schemas import (
    ClauseExtractionResponse,
    EvidenceResolveResponse,
    VersionCompareResponse,
)
from app.services import clause_service
from clause_extraction import EvidenceNotFound

router = APIRouter(prefix='/api/contract', tags=['clauses'])

UPLOAD_DIR = Path(__file__).resolve().parents[2] / 'uploads'


async def _save_upload(upload: UploadFile, index: int) -> Tuple[str, str]:
    original_name = Path(upload.filename or f'upload_{index}').name
    suffix = Path(original_name).suffix
    target = UPLOAD_DIR / f'{uuid.uuid4().hex}{suffix}'
    target.write_bytes(await upload.read())
    return str(target), original_name


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
        path, original_name = await _save_upload(upload, index)
        role = role_tokens[index] if index < len(role_tokens) else ''
        specs.append((path, original_name, role))

    try:
        result = await run_in_threadpool(
            clause_service.extract_clauses, specs, use_llm,
        )
    except clause_service.DocumentReadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ClauseExtractionResponse(**result)


@router.get('/evidence/{evidence_id}', response_model=EvidenceResolveResponse)
async def resolve_evidence(evidence_id: str) -> EvidenceResolveResponse:
    """按 evidence_id 反查原文；ID 不合法、文档未注册或区间越界都返回 404。"""
    try:
        data = await run_in_threadpool(clause_service.resolve_evidence, evidence_id)
    except EvidenceNotFound as exc:
        detail = exc.args[0] if exc.args else str(exc)
        raise HTTPException(status_code=404, detail=detail) from exc
    return EvidenceResolveResponse(**data)


@router.post('/versions', response_model=VersionCompareResponse)
async def compare_versions(
    old_file: UploadFile = File(...),
    new_file: UploadFile = File(...),
) -> VersionCompareResponse:
    """对比两份合同版本，返回每类条款的新增/删除/变更/未变。"""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    old_spec = await _save_upload(old_file, 0)
    new_spec = await _save_upload(new_file, 1)

    try:
        result = await run_in_threadpool(
            clause_service.compare_versions, old_spec, new_spec,
        )
    except clause_service.DocumentReadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return VersionCompareResponse(**result)
