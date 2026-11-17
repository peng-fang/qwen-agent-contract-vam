"""Pre-signing checklist endpoint."""

import asyncio
import copy
import json
import queue
import threading
from pathlib import Path
from typing import Annotated, List, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.services.checklist_pdf import build_checklist_pdf
from app.services.checklist_service import MAX_SOURCE_CHARS, generate_checklist
from vam_sandbox.comparison import calculate

router = APIRouter(prefix='/api/checklist', tags=['checklist'])
MAX_UPLOAD = 10 * 1024 * 1024
MAX_EVIDENCE = 30


class ConsequenceRequest(BaseModel):
    template: Literal['repurchase', 'lease_exit']
    parameters: dict = Field(max_length=12)


class ChecklistExportRequest(BaseModel):
    items: list[dict] = Field(min_length=1, max_length=20)
    role: str = Field(default='', max_length=80)
    scope: str = Field(default='', max_length=200)


@router.post('/export')
def export_pdf(req: ChecklistExportRequest):
    try:
        content = build_checklist_pdf(req.items, req.role, req.scope)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f'生成 PDF 失败：{type(exc).__name__}') from exc
    return Response(
        content=content,
        media_type='application/pdf',
        headers={'Content-Disposition': 'attachment; filename="checklist.pdf"'},
    )


async def _read_uploads(file: UploadFile | None, files: List[UploadFile]) -> List[tuple[str, bytes]]:
    uploads = ([file] if file else []) + list(files or [])
    if len(uploads) > 6:
        raise HTTPException(413, '一次最多使用 6 份合同材料。')
    result: List[tuple[str, bytes]] = []
    for upload in uploads:
        if not upload.filename:
            continue
        data = await upload.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, '合同文件最多 10 MB。')
        result.append((Path(upload.filename).name, data))
    return result


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
    files: List[UploadFile] = File(default=[]),
):
    try:
        selected = json.loads(evidence)
        if not isinstance(selected, list) or len(selected) > MAX_EVIDENCE or any(not isinstance(item, dict) for item in selected):
            raise ValueError(f'最多可带入 {MAX_EVIDENCE} 段已定位的原文。')
        contents = await _read_uploads(file, files)
        return await run_in_threadpool(
            generate_checklist, role, text, '', None, selected, contents=contents,
        )
    except json.JSONDecodeError as exc:
        raise HTTPException(400, '原文数据无效。') from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, '模型暂时未能生成清单。请稍后重试或缩短输入。') from exc


@router.post('/run/stream')
async def run_stream(
    role: Annotated[str, Form(max_length=80)] = '',
    text: Annotated[str, Form(max_length=MAX_SOURCE_CHARS)] = '',
    evidence: Annotated[str, Form(max_length=20000)] = '[]',
    file: Annotated[UploadFile | None, File()] = None,
    files: List[UploadFile] = File(default=[]),
):
    """SSE 版本：推送读取、生成、优先级和最终清单。"""
    try:
        selected = json.loads(evidence)
        if not isinstance(selected, list) or len(selected) > MAX_EVIDENCE or any(not isinstance(item, dict) for item in selected):
            raise ValueError(f'最多可带入 {MAX_EVIDENCE} 段已定位的原文。')
        contents = await _read_uploads(file, files)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, '原文数据无效。') from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    events: queue.Queue = queue.Queue()

    def progress(stage: str, status: str, detail: str = '', payload=None) -> None:
        events.put({'type': 'progress', 'stage': stage, 'status': status, 'detail': detail})
        if isinstance(payload, dict) and isinstance(payload.get('items'), list):
            events.put({'type': 'partial', 'items': copy.deepcopy(payload['items'])})

    def worker() -> None:
        try:
            result = generate_checklist(
                role, text, '', None, selected, progress=progress, contents=contents,
            )
            events.put({'type': 'result', 'result': result})
        except Exception as exc:  # noqa: BLE001
            events.put({'type': 'error', 'detail': str(exc)})
        finally:
            events.put(None)

    threading.Thread(target=worker, name='checklist-stream', daemon=True).start()

    async def event_generator():
        while True:
            item = await asyncio.to_thread(events.get)
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )
