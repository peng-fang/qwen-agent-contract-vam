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

from clause_extraction import DocRole, analyze_documents, infer_role  # noqa: E402
from clause_extraction.pdf_reader import DocumentReadError, load_document  # noqa: E402

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


def extract_clauses(
    specs: Sequence[Tuple[str, str, str]],
    use_llm: bool = False,
) -> Dict[str, Any]:
    """specs: [(落盘路径, 原始文件名, 角色字符串)]。"""
    documents = []
    for index, (path, original_name, role) in enumerate(specs, start=1):
        documents.append(load_document(
            path=path,
            role=_resolve_role(original_name, role),
            document_id=f'doc{index}',
            filename=original_name,
        ))
    bundle = analyze_documents(documents, use_llm=use_llm)
    return bundle.to_dict()


__all__ = ['extract_clauses', 'DocumentReadError']
