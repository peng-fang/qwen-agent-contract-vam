"""Pre-signing checklist endpoint."""

import json
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.services.checklist_service import MAX_SOURCE_CHARS, generate_checklist
from vam_sandbox.comparison import calculate

router = APIRouter(prefix='/api/checklist', tags=['checklist'])
MAX_UPLOAD = 10 * 1024 * 1024


class ConsequenceRequest(BaseModel):
    template: Literal['repurchase', 'lease_exit']
    parameters: dict = Field(max_length=12)


@router.post('/consequence')
def consequence(req: ConsequenceRequest):
    if req.template == 'lease_exit':
        return [
            {'label': label, **calculate(req.template, {**req.parameters, 'deposit_rule': rule}, 'met')}
            for rule, label in [('add', '押金没收，违约金另计'), ('offset', '没收的押金抵扣违约金'), ('refund', '押金退还')]
        ]
    return [
        {'label': label, **calculate(req.template, {**req.parameters, 'interest': interest}, 'met')}
        for interest, label in [('simple', '按单利'), ('compound', '按年复利')]
    ]


@router.post('/run')
async def run(
    role: Annotated[str, Form(max_length=80)] = '',
    text: Annotated[str, Form(max_length=MAX_SOURCE_CHARS)] = '',
    evidence: Annotated[str, Form(max_length=20000)] = '[]',
    file: Annotated[UploadFile | None, File()] = None,
):
    try:
        selected = json.loads(evidence)
        if not isinstance(selected, list) or len(selected) > 6 or any(not isinstance(item, dict) for item in selected):
            raise ValueError('最多可带入六段已定位的原文。')
        data = await file.read(MAX_UPLOAD + 1) if file else None
        if data is not None and len(data) > MAX_UPLOAD:
            raise HTTPException(413, '合同文件最多 10 MB。')
        filename = (file.filename or '') if file else ''
        return await run_in_threadpool(generate_checklist, role, text, filename, data, selected)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, '原文数据无效。') from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, '模型暂时未能生成清单。请稍后重试或缩短输入。') from exc
