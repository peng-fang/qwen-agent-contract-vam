"""证据注册表：把材料的按页文本按文档 ID 落盘，支持 evidence_id 反查。

设计约束：
- evidence_id 只由"文档 ID + 页码 + 字符区间"决定，模型无法伪造；
- 反查时从注册表重新切出原文，不采信前端或模型回传的 quote；
- 未注册的文档/越界区间一律 404，不做猜测。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .evidence_links import select_related_evidence
from .schema import DocRole, Document, EvidenceSpan, PageText

_EVIDENCE_ID_RE = re.compile(
    r'^ev-(?P<doc>[\w-]+)-p(?P<page>\d+)-c(?P<start>\d+)-(?P<end>\d+)$'
)


class EvidenceNotFound(KeyError):
    """evidence_id 不存在、所属文档未注册，或字符区间越界。"""


def default_registry_dir() -> Path:
    override = os.getenv('EVIDENCE_REGISTRY_DIR', '').strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / 'backend' / 'uploads' / '_evidence'


def document_id_for(role: str, filename: str, pages: Sequence[PageText]) -> str:
    """内容指纹：同内容同文件名同角色得到同一个 ID，重复上传不会漂移。"""
    digest = hashlib.sha256()
    digest.update(f'{role}|{filename}|'.encode('utf-8'))
    for page in pages:
        digest.update(page.text.encode('utf-8'))
        digest.update(b'\x00')
    return f'doc-{digest.hexdigest()[:12]}'


def register_document(document: Document, registry_dir: Optional[str] = None) -> str:
    directory = Path(registry_dir) if registry_dir else default_registry_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        'document_id': document.document_id,
        'filename': document.filename,
        'role': document.role.value,
        'pages': [page.to_dict() for page in document.pages],
    }
    path = directory / f'{document.document_id}.json'
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return document.document_id


def _load_registered(document_id: str, registry_dir: Optional[str] = None) -> Dict[str, Any]:
    directory = Path(registry_dir) if registry_dir else default_registry_dir()
    path = directory / f'{document_id}.json'
    if not path.is_file():
        raise EvidenceNotFound(f'未找到证据所属文档：{document_id}')
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceNotFound(f'证据注册表损坏：{document_id}') from exc


def resolve_evidence(evidence_id: str, registry_dir: Optional[str] = None, *,
                     include_related: bool = False) -> Dict[str, Any]:
    """按 evidence_id 反查原文，返回页码、字符区间、quote 与上下文。"""
    match = _EVIDENCE_ID_RE.match((evidence_id or '').strip())
    if not match:
        raise EvidenceNotFound(f'evidence_id 格式不合法：{evidence_id!r}')

    document_id = match.group('doc')
    page_number = int(match.group('page'))
    char_start = int(match.group('start'))
    char_end = int(match.group('end'))

    record = _load_registered(document_id, registry_dir)
    pages: List[Dict[str, Any]] = record.get('pages') or []
    page_text = next((item.get('text', '') for item in pages if item.get('page') == page_number), None)
    if page_text is None:
        raise EvidenceNotFound(f'第 {page_number} 页不存在：{document_id}')
    if not (0 <= char_start < char_end <= len(page_text)):
        raise EvidenceNotFound(
            f'字符区间越界：{char_start}-{char_end}，该页长度 {len(page_text)}'
        )

    quote = page_text[char_start:char_end]
    if not quote.strip():
        raise EvidenceNotFound('字符区间对应空文本')

    context_start = max(0, char_start - 60)
    context_end = min(len(page_text), char_end + 60)
    result = {
        'evidence_id': evidence_id,
        'document_id': document_id,
        'filename': record.get('filename', ''),
        'role': record.get('role', ''),
        'page': page_number,
        'char_start': char_start,
        'char_end': char_end,
        'quote': quote,
        'context': page_text[context_start:context_end],
        'verified': True,
    }
    if include_related:
        role = DocRole(record.get('role', 'unknown'))
        document = Document(document_id, result['filename'], role,
                            [PageText(page=p['page'], text=p['text']) for p in pages])
        anchor = EvidenceSpan(document_id, document.filename, role, page_number,
                              f'p{page_number}', char_start, char_end, quote)
        result['related_evidence'] = select_related_evidence(document, anchor)
    return result
