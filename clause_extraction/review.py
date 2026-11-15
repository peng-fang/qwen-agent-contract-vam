"""确定性证据复核。

只做可机器验证的检查，不冒充"第二个 Agent"，也不做法律判断：
1. 文档、页码、字符区间是否存在；
2. 原文切片是否与 evidence.quote 逐字一致；
3. 从 quote 重新抽取的字段是否与返回给前端的字段一致；
4. evidence_id 是否带 `ev-` 前缀；ID 的完整解析与反查由 registry 负责。
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from .extract import extract_fields
from .schema import Clause, Document


def _clause_label(clause: Clause) -> str:
    from .schema import CLAUSE_LABELS

    return CLAUSE_LABELS[clause.clause_type]


def review_bundle(documents: Sequence[Document], clauses: Sequence[Clause]) -> Dict[str, Any]:
    docs = {document.document_id: document for document in documents}
    checks: List[Dict[str, Any]] = []

    for clause in clauses:
        evidence = clause.evidence
        problems: List[str] = []

        document = docs.get(evidence.document_id)
        if document is None:
            problems.append(f'文档未在本次结果中：{evidence.document_id}')
        else:
            page = next((item for item in document.pages if item.page == evidence.page), None)
            if page is None:
                problems.append(f'页码不在文档范围内：第 {evidence.page} 页')
            else:
                if not (0 <= evidence.char_start < evidence.char_end <= len(page.text)):
                    problems.append(
                        f'字符区间越界：{evidence.char_start}-{evidence.char_end}，'
                        f'该页长度 {len(page.text)}'
                    )
                else:
                    sliced = page.text[evidence.char_start:evidence.char_end]
                    if sliced != evidence.quote:
                        problems.append('原文切片与 quote 不一致')
                    if extract_fields(evidence.quote) != clause.fields:
                        problems.append('字段与 quote 重新抽取的结果不一致')

        expected_id = evidence.evidence_id
        if not expected_id.startswith('ev-'):
            problems.append('evidence_id 前缀不合法')

        checks.append({
            'evidence_id': expected_id,
            'clause_type': clause.clause_type.value,
            'clause_label': _clause_label(clause),
            'page': evidence.page,
            'filename': evidence.filename,
            'ok': not problems,
            'problems': problems,
        })

    failed = [item for item in checks if not item['ok']]
    return {
        'method': 'deterministic_offsets_and_field_rederivation',
        'checked': len(checks),
        'passed': len(checks) - len(failed),
        'failed': len(failed),
        'failures': failed[:20],
        'note': '只校验证据可回查性与字段自洽，不判断条款是否合法。',
    }
