"""跨文档匹配与冲突判定。

判定只使用结构化字段，不调用模型；
每条结论都带可回查的原文片段（文件/页码/字符区间）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .extract import clauses_by_type
from .schema import Clause, ClauseType, Document, DocRole, MatchResult, Verdict

_UNIT_ORDER = {'年': 0, '个月': 1, '月': 2, '次': 3, '节': 4, '课时': 5, '天': 6}


def _unit_key(item: Dict[str, Any]) -> tuple:
    return _UNIT_ORDER.get(str(item.get('unit')), 9), float(item.get('value') or item.get('amount') or 0)


def _merge_fields(clauses: List[Clause]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {
        'amounts': set(),
        'rates': set(),
        'per_unit_amounts': set(),
        'durations': set(),
        'dates': set(),
        'notice_days': None,
        'conditions': set(),
        'flags': {},
        'clause_ref': '',
    }
    for clause in clauses:
        fields = clause.fields
        merged['amounts'].update(fields.get('amounts') or [])
        merged['rates'].update(fields.get('rates') or [])
        for item in fields.get('per_unit_amounts') or []:
            merged['per_unit_amounts'].add((item['amount'], item['unit']))
        for item in fields.get('durations') or []:
            merged['durations'].add((item['value'], item['unit']))
        merged['dates'].update(fields.get('dates') or [])
        if fields.get('notice_days') is not None:
            merged['notice_days'] = fields['notice_days']
        merged['conditions'].update(fields.get('conditions') or [])
        for key, value in (fields.get('flags') or {}).items():
            merged['flags'][key] = merged['flags'].get(key, False) or bool(value)
        if fields.get('clause_ref') and not merged['clause_ref']:
            merged['clause_ref'] = fields['clause_ref']

    return {
        'amounts': sorted(merged['amounts']),
        'rates': sorted(merged['rates']),
        'per_unit_amounts': sorted(
            [{'amount': amount, 'unit': unit} for amount, unit in merged['per_unit_amounts']],
            key=_unit_key,
        ),
        'durations': sorted(
            [{'value': value, 'unit': unit} for value, unit in merged['durations']],
            key=_unit_key,
        ),
        'dates': sorted(merged['dates']),
        'notice_days': merged['notice_days'],
        'conditions': sorted(merged['conditions']),
        'flags': merged['flags'],
        'clause_ref': merged['clause_ref'],
    }


def merge_fields(clauses: List[Clause]) -> Dict[str, Any]:
    """把同类条款的字段合并成可比较的一侧（供匹配与版本对比复用）。"""
    return _merge_fields(clauses)


def _side_payload(clauses: List[Clause]) -> Optional[Dict[str, Any]]:
    if not clauses:
        return None
    refs = sorted({c.evidence.role.value + ':' + (c.fields.get('clause_ref') or '未标条号')
                   for c in clauses})
    return {
        'clause_refs': refs,
        'fields': _merge_fields(clauses),
        'evidences': [c.evidence.to_dict() for c in clauses],
    }


def _format_rates(rates: List[float]) -> str:
    return '、'.join(f'{rate * 100:g}%' for rate in rates)


def _format_per_unit(items: List[Dict[str, Any]]) -> str:
    return '、'.join(f"{item['amount']:g} 元/{item['unit']}" for item in items)


def _value_key(item: Any) -> Any:
    """把 dict/list 字段转成可哈希键，避免 set(dict) 报错。"""
    if isinstance(item, dict):
        return tuple(sorted((str(key), _value_key(value)) for key, value in item.items()))
    if isinstance(item, (list, tuple)):
        return tuple(_value_key(value) for value in item)
    return item


def _values_conflict(left: List[Any], right: List[Any]) -> bool:
    return bool(left) and bool(right) and {_value_key(x) for x in left} != {_value_key(x) for x in right}


def _match_refund(
    promo: Optional[Dict[str, Any]], contract: Optional[Dict[str, Any]],
) -> Tuple[Verdict, List[str], Dict[str, Any]]:
    reasons: List[str] = []
    if promo is None and contract is None:
        return Verdict.MISSING_BOTH, ['双方材料均未提及退款条款'], {}
    if promo is None:
        return Verdict.MISSING_IN_PROMO, ['合同约定了退款规则，宣传材料未提及'], {}
    if contract is None:
        return Verdict.MISSING_IN_CONTRACT, ['宣传材料承诺退款，合同未约定'], {}

    promo_fields, contract_fields = promo['fields'], contract['fields']
    promo_rates = promo_fields['rates']
    contract_rates = contract_fields['rates']
    promo_flags = promo_fields['flags']
    contract_caps = [c for c in contract_fields['conditions'] if c.endswith(':no_refund')]

    if promo_flags.get('full_refund') and contract_rates:
        reasons.append(
            f'宣传承诺全额退款，合同约定扣除 {_format_rates(contract_rates)} 手续费'
        )
    if promo_flags.get('free_of_charge') and contract_rates:
        reasons.append(
            f'宣传承诺不收取手续费，合同约定手续费 {_format_rates(contract_rates)}'
        )
    if _values_conflict(promo_rates, contract_rates):
        reasons.append(
            f'退款手续费比例不一致：宣传 {_format_rates(promo_rates)}，合同 {_format_rates(contract_rates)}'
        )
    if promo_flags.get('full_refund') and contract_caps:
        reasons.append(
            f'宣传承诺全额退款，合同另设退费限制（{contract_caps[0]}）'
        )
    if reasons:
        return Verdict.CONFLICT, reasons, {
            'promo_rates': promo_rates, 'contract_rates': contract_rates,
        }

    if promo_rates and contract_rates:
        return Verdict.CONSISTENT, ['双方手续费比例一致'], {'rates': contract_rates}
    if promo_flags.get('refundable') and contract_flags_refundable(contract_fields):
        return Verdict.CONSISTENT, ['双方均确认可退费，未发现数值冲突'], {}
    return Verdict.UNCLEAR, ['双方均有退款表述，但缺少可比较的手续费/条件字段'], {}


def contract_flags_refundable(fields: Dict[str, Any]) -> bool:
    return bool(fields['flags'].get('refundable')) and not fields['conditions']


def _match_penalty(
    promo: Optional[Dict[str, Any]], contract: Optional[Dict[str, Any]],
) -> Tuple[Verdict, List[str], Dict[str, Any]]:
    if promo is None and contract is None:
        return Verdict.MISSING_BOTH, ['双方材料均未提及违约金'], {}
    if promo is None:
        return Verdict.MISSING_IN_PROMO, ['合同约定了违约责任，宣传材料未提及'], {}
    if contract is None:
        return Verdict.MISSING_IN_CONTRACT, ['宣传材料提及违约责任，合同未约定'], {}

    promo_fields, contract_fields = promo['fields'], contract['fields']
    if _values_conflict(promo_fields['rates'], contract_fields['rates']):
        return Verdict.CONFLICT, [
            f"违约金比例不一致：宣传 {_format_rates(promo_fields['rates'])}，"
            f"合同 {_format_rates(contract_fields['rates'])}"
        ], {'promo_rates': promo_fields['rates'], 'contract_rates': contract_fields['rates']}
    if contract_fields['rates'] and not promo_fields['rates']:
        return Verdict.UNCLEAR, ['合同有明确违约金比例，宣传未给出比例，无法直接比较'], {}
    return Verdict.CONSISTENT, ['未发现违约金比例冲突'], {}


def _match_auto_renewal(
    promo: Optional[Dict[str, Any]], contract: Optional[Dict[str, Any]],
) -> Tuple[Verdict, List[str], Dict[str, Any]]:
    if promo is None and contract is None:
        return Verdict.MISSING_BOTH, ['双方材料均未提及自动续费/续租'], {}
    if contract is None:
        return Verdict.MISSING_IN_CONTRACT, ['宣传材料提及续费，合同未约定'], {}
    if promo is None:
        return Verdict.MISSING_IN_PROMO, ['合同约定了自动续费/续租，宣传材料未提及'], {}

    promo_fields, contract_fields = promo['fields'], contract['fields']
    contract_auto = bool(contract_fields['flags'].get('auto_renewal'))
    promo_no_auto = bool(promo_fields['flags'].get('no_auto_renewal'))
    promo_auto = bool(promo_fields['flags'].get('auto_renewal'))

    if contract_auto and promo_no_auto:
        return Verdict.CONFLICT, ['宣传承诺不自动续费，合同约定可自动续费'], {}
    if contract_auto and not promo_auto:
        return Verdict.MISSING_IN_PROMO, [
            '合同约定自动续费/续租，宣传材料未提及，用户可能在不知情下被扣款'
        ], {}
    if contract_auto and promo_auto:
        promo_notice = promo_fields['notice_days']
        contract_notice = contract_fields['notice_days']
        if promo_notice is not None and contract_notice is not None and promo_notice != contract_notice:
            return Verdict.CONFLICT, [
                f'续费通知期不一致：宣传提前 {promo_notice} 日，合同提前 {contract_notice} 日'
            ], {'promo_notice_days': promo_notice, 'contract_notice_days': contract_notice}
        return Verdict.CONSISTENT, ['双方均约定自动续费，未发现通知期冲突'], {}
    if not contract_auto and promo_no_auto:
        return Verdict.CONSISTENT, ['双方均不自动续费'], {}
    return Verdict.UNCLEAR, ['双方均有续费表述，但缺少可比较的自动续费标记'], {}


def _match_service_term(
    promo: Optional[Dict[str, Any]], contract: Optional[Dict[str, Any]],
) -> Tuple[Verdict, List[str], Dict[str, Any]]:
    if promo is None and contract is None:
        return Verdict.MISSING_BOTH, ['双方材料均未提及服务期限'], {}
    if promo is None:
        return Verdict.MISSING_IN_PROMO, ['合同约定了服务期限，宣传材料未提及'], {}
    if contract is None:
        return Verdict.MISSING_IN_CONTRACT, ['宣传材料提及服务期限，合同未约定'], {}

    promo_fields, contract_fields = promo['fields'], contract['fields']
    if _values_conflict(promo_fields['dates'], contract_fields['dates']):
        return Verdict.CONFLICT, [
            f"服务期限不一致：宣传 {promo_fields['dates']}，合同 {contract_fields['dates']}"
        ], {'promo_dates': promo_fields['dates'], 'contract_dates': contract_fields['dates']}
    if _values_conflict(promo_fields['durations'], contract_fields['durations']):
        return Verdict.CONFLICT, [
            f"服务时长不一致：宣传 {promo_fields['durations']}，合同 {contract_fields['durations']}"
        ], {}
    if promo_fields['dates'] and contract_fields['dates']:
        return Verdict.CONSISTENT, ['双方服务期限一致'], {'dates': contract_fields['dates']}
    return Verdict.UNCLEAR, ['双方均有期限表述，但缺少可比较的起止日期'], {}


def _match_extra_fee(
    promo: Optional[Dict[str, Any]], contract: Optional[Dict[str, Any]],
) -> Tuple[Verdict, List[str], Dict[str, Any]]:
    if promo is None and contract is None:
        return Verdict.MISSING_BOTH, ['双方材料均未提及额外收费'], {}
    if promo is None:
        return Verdict.MISSING_IN_PROMO, ['合同列出了额外收费，宣传材料未提及'], {}
    if contract is None:
        return Verdict.MISSING_IN_CONTRACT, ['宣传材料提及收费，合同未约定'], {}

    promo_fields, contract_fields = promo['fields'], contract['fields']
    promo_free = bool(promo_fields['flags'].get('free_of_charge'))
    contract_fees = contract_fields['per_unit_amounts']

    if promo_free and contract_fees:
        return Verdict.CONFLICT, [
            '宣传承诺无任何额外收费，合同仍列出：' + _format_per_unit(contract_fees)
        ], {'promo_free_of_charge': True, 'contract_fees': contract_fees}
    if _values_conflict(promo_fields['per_unit_amounts'], contract_fees):
        return Verdict.CONFLICT, [
            f"额外收费不一致：宣传 {_format_per_unit(promo_fields['per_unit_amounts'])}，"
            f"合同 {_format_per_unit(contract_fees)}"
        ], {'promo_fees': promo_fields['per_unit_amounts'], 'contract_fees': contract_fees}
    if promo_fields['per_unit_amounts'] and promo_fields['per_unit_amounts'] == contract_fees:
        return Verdict.CONSISTENT, ['双方列出的额外收费项目与单价一致'], {
            'fees': contract_fees,
        }
    if promo_free and not contract_fees:
        return Verdict.CONSISTENT, ['宣传与合同均未列出额外收费'], {}
    if contract_fees:
        return Verdict.UNCLEAR, ['合同列出了额外收费，宣传未明确表态'], {}
    return Verdict.UNCLEAR, ['双方均有收费表述，但缺少可比较的单价'], {}


_MATCHERS = {
    ClauseType.REFUND: _match_refund,
    ClauseType.PENALTY: _match_penalty,
    ClauseType.AUTO_RENEWAL: _match_auto_renewal,
    ClauseType.SERVICE_TERM: _match_service_term,
    ClauseType.EXTRA_FEE: _match_extra_fee,
}


def match_documents(documents: List[Document], clauses: List[Clause]) -> List[MatchResult]:
    """按条款类型做宣传材料 vs 合同的确定性比对。"""
    promo_ids = {d.document_id for d in documents if d.role == DocRole.PROMO}
    promo_clauses = [c for c in clauses if c.evidence.document_id in promo_ids]
    contract_clauses = [c for c in clauses if c.evidence.document_id not in promo_ids]

    promo_table = clauses_by_type(promo_clauses)
    contract_table = clauses_by_type(contract_clauses)

    results: List[MatchResult] = []
    for clause_type, matcher in _MATCHERS.items():
        promo_side = _side_payload(promo_table[clause_type])
        contract_side = _side_payload(contract_table[clause_type])
        verdict, reasons, compared = matcher(promo_side, contract_side)
        results.append(MatchResult(
            clause_type=clause_type,
            verdict=verdict,
            reasons=reasons,
            promo=promo_side,
            contract=contract_side,
            compared=compared,
        ))
    return results
