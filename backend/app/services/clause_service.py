"""条款抽取与匹配的业务封装。

保持 router -> service -> clause_extraction 的分层；
模型是可选项，未配置时 clause_extraction 自动使用规则抽取。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clause_extraction import (  # noqa: E402
    DocRole,
    analyze_documents,
    document_id_for,
    infer_role,
    register_document,
    resolve_evidence as _resolve_evidence,
)
from clause_extraction.pdf_reader import DocumentReadError, load_document  # noqa: E402
from clause_extraction.schema import Document  # noqa: E402
from clause_extraction.version_diff import diff_documents  # noqa: E402

_ROLE_MAP = {
    'promo': DocRole.PROMO,
    'contract': DocRole.CONTRACT,
    'unknown': DocRole.UNKNOWN,
    '': DocRole.UNKNOWN,
    'auto': DocRole.UNKNOWN,
}


def _resolve_role(original_name: str, role: str) -> DocRole:
    token = (role or '').strip().lower()
    if token not in _ROLE_MAP:
        raise ValueError(f'未知的角色：{role!r}，只支持 promo / contract / auto')
    resolved = _ROLE_MAP[token]
    if resolved == DocRole.UNKNOWN and token in {'', 'auto'}:
        return infer_role(original_name)
    return resolved


def _load_registered(
    path: str, original_name: str, role: DocRole,
) -> Document:
    document = load_document(path=path, role=role, document_id='', filename=original_name)
    document.document_id = document_id_for(role.value, original_name, document.pages)
    register_document(document)
    return document


def extract_clauses(
    specs: Sequence[Tuple[str, str, str]],
    use_llm: bool = False,
) -> Dict[str, Any]:
    """specs: [(落盘路径, 原始文件名, 角色字符串)]。"""
    documents = []
    for path, original_name, role in specs:
        documents.append(_load_registered(
            path, original_name, _resolve_role(original_name, role),
        ))
    bundle = analyze_documents(documents, use_llm=use_llm)
    return bundle.to_dict()


def compare_versions(
    old_spec: Tuple[str, str],
    new_spec: Tuple[str, str],
) -> Dict[str, Any]:
    """old_spec / new_spec: (落盘路径, 原始文件名)，两份都按合同角色读取。"""
    old_document = _load_registered(old_spec[0], old_spec[1], DocRole.CONTRACT)
    new_document = _load_registered(new_spec[0], new_spec[1], DocRole.CONTRACT)
    return diff_documents(old_document, new_document)


def resolve_evidence(evidence_id: str) -> Dict[str, Any]:
    return _resolve_evidence(evidence_id)


__all__ = [
    'extract_clauses',
    'compare_versions',
    'resolve_evidence',
    'DocumentReadError',
]
