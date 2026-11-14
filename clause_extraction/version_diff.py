"""合同版本对比（确定性）。

输入两份都按"合同"角色读取的材料，输出每类条款的 新增 / 删除 / 变更 / 未变：
- 只比较结构化字段（金额、比例、期限、通知期、条件、标记、条号）；
- 每个变化都带旧/新两边的可回查证据 ID。
"""

from __future__ import annotations

from typing import Any, Dict, List

from .extract import extract_document
from .match import _merge_fields
from .schema import CLAUSE_LABELS, Clause, ClauseType, Document

_COMPARED_FIELDS = [
    'amounts',
    'rates',
    'per_unit_amounts',
    'durations',
    'dates',
    'notice_days',
    'conditions',
    'flags',
    'clause_ref',
]


def _by_type(clauses: List[Clause]) -> Dict[ClauseType, List[Clause]]:
    table = {clause_type: [] for clause_type in ClauseType}
    for clause in clauses:
        table[clause.clause_type].append(clause)
    return table


def _evidences(clauses: List[Clause]) -> List[Dict[str, Any]]:
    return [clause.evidence.to_dict() for clause in clauses]


def diff_documents(old: Document, new: Document) -> Dict[str, Any]:
    old_table = _by_type(extract_document(old))
    new_table = _by_type(extract_document(new))

    rows: List[Dict[str, Any]] = []
    for clause_type in ClauseType:
        old_clauses = old_table[clause_type]
        new_clauses = new_table[clause_type]
        changes: List[Dict[str, Any]] = []

        if not old_clauses and not new_clauses:
            status = 'unchanged'
        elif not old_clauses:
            status = 'added'
            changes = [{'field': 'clause', 'old': None, 'new': '新增条款'}]
        elif not new_clauses:
            status = 'removed'
            changes = [{'field': 'clause', 'old': '删除条款', 'new': None}]
        else:
            old_fields = _merge_fields(old_clauses)
            new_fields = _merge_fields(new_clauses)
            for field in _COMPARED_FIELDS:
                if old_fields.get(field) != new_fields.get(field):
                    changes.append({
                        'field': field,
                        'old': old_fields.get(field),
                        'new': new_fields.get(field),
                    })
            status = 'changed' if changes else 'unchanged'

        rows.append({
            'clause_type': clause_type.value,
            'clause_label': CLAUSE_LABELS[clause_type],
            'status': status,
            'changes': changes,
            'old': {
                'clause_count': len(old_clauses),
                'evidences': _evidences(old_clauses),
            },
            'new': {
                'clause_count': len(new_clauses),
                'evidences': _evidences(new_clauses),
            },
        })

    summary = {
        'added': sum(1 for row in rows if row['status'] == 'added'),
        'removed': sum(1 for row in rows if row['status'] == 'removed'),
        'changed': sum(1 for row in rows if row['status'] == 'changed'),
        'unchanged': sum(1 for row in rows if row['status'] == 'unchanged'),
    }
    return {
        'old_document': {
            'document_id': old.document_id,
            'filename': old.filename,
        },
        'new_document': {
            'document_id': new.document_id,
            'filename': new.filename,
        },
        'summary': summary,
        'rows': rows,
        'method': 'deterministic_field_diff',
    }
