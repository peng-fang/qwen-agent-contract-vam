"""金额适用条件核验（确定性）。

原则：
1. 先校验条件与参数，再给金额；条件不足或存在多种可能时只给分档/公式。
2. 每个金额与条件都带 evidence_id，且条件必须能在原文中找到。
3. 不调用模型。

覆盖：
- 退款：手续费比例、已上课节数上限、申请期限、开课阶段、实付金额、每节原价；
- 违约金：比例、计算基数（剩余费用/实付）、与退款手续费是否叠加。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .schema import Clause, ClauseType, DocRole, Document, MatchResult

STATUS_LABELS = {
    'applicable': '条件满足，可测算',
    'conditional': '条件化测算',
    'insufficient': '条件或参数不足',
    'not_applicable': '条件不满足，不适用',
    'no_amount': '无金额条款',
}

_NUM = r'([0-9][0-9,]*(?:\.[0-9]+)?)'
_MONEY_SUFFIX = r'\s*(?:元|块|人民币)'

Quote = Tuple[str, str]  # (原文片段, evidence_id)


def _num(value: str) -> float:
    return float(value.replace(',', ''))


def _money(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 2)


def _find(pattern: str, quotes: Sequence[Quote], flags: int = 0):
    for quote, evidence_id in quotes:
        match = re.search(pattern, quote, flags)
        if match:
            return match, quote, evidence_id
    return None


def _condition(label: str, met: Optional[bool], evidence_id: str, quote: str, *,
               requires_fact: Optional[str] = None) -> Dict[str, Any]:
    result = {
        'condition': label,
        'met': met,
        'evidence_id': evidence_id,
        'quote': quote,
    }
    if evidence_id.startswith('user:'):
        result.update(source='user', fact_key=evidence_id[5:])
    if requires_fact is not None:
        result['requires_fact'] = requires_fact
    return result


def _contract_segments(documents: Sequence[Document]) -> List[Quote]:
    """把合同正文切成可定位的短句，并生成可反查的 evidence_id。"""
    segments: List[Quote] = []
    seen = set()
    for document in documents:
        if document.role != DocRole.CONTRACT:
            continue
        for page in document.pages:
            for part in re.split(r'[。；\n]+', page.text):
                text = part.strip(' ，,;；')
                if len(text) < 4:
                    continue
                start = page.text.find(text)
                if start < 0:
                    continue
                end = start + len(text)
                evidence_id = f'ev-{document.document_id}-p{page.page}-c{start}-{end}'
                if evidence_id in seen:
                    continue
                seen.add(evidence_id)
                segments.append((text, evidence_id))
    return segments


def _paid_amount(quotes: Sequence[Quote]):
    # 排除 "100 元/次" 这类单价，避免把单价当成合同总金额
    return _find(
        r'(?:学费|课程费|培训费|年卡|会员费|租金|实付|已付|总费用|合同总价|合同总金额|总金额)'
        r'[^0-9]{0,10}' + _NUM + r'\s*(?:元|块|人民币)'
        r'(?!\s*/\s*(?:次|月|年|节|期|人))',
        quotes,
    )


def _unit_price(quotes: Sequence[Quote]):
    return _find(
        r'(?:每节|每课时|原价每节|课时单价)[^0-9]{0,6}' + _NUM + _MONEY_SUFFIX,
        quotes,
    )


def _used_count(quotes: Sequence[Quote]) -> Optional[Tuple[int, str, str]]:
    for quote, evidence_id in quotes:
        match = re.search(r'已上(?:课)?[^0-9]{0,4}([0-9]+)\s*节', quote)
        if match:
            return int(match.group(1)), evidence_id, quote
    return None


def _scenario(label: str, condition: str, amount: Optional[float], formula: str,
              applicable: Optional[bool], missing: List[str],
              evidence_ids: List[str]) -> Dict[str, Any]:
    return {
        'label': label,
        'condition': condition,
        'amount': _money(amount),
        'formula': formula,
        'applicable': applicable,
        'missing': list(dict.fromkeys(missing)),
        'evidence_ids': list(dict.fromkeys(evidence_ids)),
    }


def _refund_check(match: MatchResult, clauses: Sequence[Clause],
                  documents: Sequence[Document], confirmed_facts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    refund = next(
        (c for c in clauses
         if c.evidence.role == DocRole.CONTRACT and c.clause_type == ClauseType.REFUND),
        None,
    )
    if refund is None:
        return {'status': 'no_amount', 'status_label': STATUS_LABELS['no_amount'],
                'basis': [], 'scenarios': [], 'missing': [], 'method': 'deterministic_rules'}

    quotes = _contract_segments(documents)
    rate = (refund.fields.get('rates') or [None])[0]
    paid = _paid_amount(quotes)
    unit = _unit_price(quotes)
    used = _used_count(quotes)
    if confirmed_facts is not None:
        def fact_number(key):
            value = confirmed_facts[key]
            return re.match(r'(.+)', str(value)), '用户确认：' + str(value), 'user:' + key
        if 'used_sessions' in confirmed_facts:
            used = (confirmed_facts['used_sessions'], 'user:used_sessions',
                    '用户确认已上课 ' + str(confirmed_facts['used_sessions']) + ' 节')
        if 'total_paid' in confirmed_facts:
            paid = fact_number('total_paid')
        if 'unit_price' in confirmed_facts:
            unit = fact_number('unit_price')
    max_hit = _find(r'超过\s*([0-9]+)\s*节', quotes)
    max_sessions = int(max_hit[0].group(1)) if max_hit else None
    if max_sessions is None:
        cap = _find(r'([0-9]+)\s*节(?:以上|及以上|为上限)', quotes)
        max_sessions = int(cap[0].group(1)) if cap else None
    window = _find(r'([0-9]+)\s*(?:日|天)内', quotes)
    phase = '开课前' if any('开课前' in q for q, _ in quotes) else (
        '开课后' if any('开课后' in q for q, _ in quotes) else None)

    basis: List[Dict[str, Any]] = []
    missing: List[str] = []
    evidence_ids = [refund.evidence.evidence_id]
    if confirmed_facts is not None and any('开课前' in q for q, _ in quotes) and any('开课后' in q for q, _ in quotes):
        return {'status': 'insufficient', 'status_label': STATUS_LABELS['insufficient'],
                'reason': '合同含多个申请阶段，需分别确认适用收费规则后测算',
                'basis': [], 'scenarios': [], 'missing': ['按申请阶段确认适用收费规则'],
                'method': 'deterministic_rules'}
    if confirmed_facts is not None:
        if unit is not None and used is None:
            missing.append('已上课节数')
        if used is not None and used[0] > 0 and unit is None:
            missing.append('每节原价')

    if max_sessions is not None and max_hit:
        met = None if used is None else used[0] <= max_sessions
        basis.append(_condition(
            f'已上课节数不超过 {max_sessions} 节', met, max_hit[2], max_hit[1],
            requires_fact='used_sessions',
        ))
        evidence_ids.append(max_hit[2])
        if used is None:
            missing.append('已上课节数')
    if window:
        day = (confirmed_facts or {}).get('request_day')
        basis.append(_condition(
            f'退款申请在 {window[0].group(1)} 日内提出', None if day is None else day <= int(window[0].group(1)),
            window[2], window[1], requires_fact='request_day',
        ))
        if day is None:
            missing.append('申请时间')
        else:
            basis.append(_condition(f'用户确认申请距约定起点 {day} 天', True, 'user:request_day', str(day)))
    if phase:
        phase_hit = next((item for item in quotes if phase in item[0]), None)
        if phase_hit:
            supplied_phase = (confirmed_facts or {}).get('request_phase')
            basis.append(_condition(
                f'{phase}提出退款', None if supplied_phase is None else supplied_phase == phase,
                phase_hit[1], phase_hit[0], requires_fact='request_phase',
            ))
            if supplied_phase is None:
                missing.append('申请阶段')
            else:
                basis.append(_condition('用户确认申请阶段：' + supplied_phase, True, 'user:request_phase', supplied_phase))
    if rate is None:
        missing.append('手续费比例')
    else:
        basis.append(_condition(
            f'手续费比例为 {rate:.0%}', True, refund.evidence.evidence_id,
            refund.evidence.quote,
        ))
    if paid is None:
        missing.append('实付金额')
    else:
        basis.append(_condition(
            f'实付金额为 {_num(paid[0].group(1)):.2f} 元', True, paid[2], paid[1],
        ))
        evidence_ids.append(paid[2])
    if used is not None:
        basis.append(_condition(
            f'已上课 {used[0]} 节', True, used[1], used[2],
        ))
        evidence_ids.append(used[1])
    if unit is not None:
        basis.append(_condition(
            f'每节原价 {_num(unit[0].group(1)):.2f} 元', True, unit[2], unit[1],
        ))
        evidence_ids.append(unit[2])

    if confirmed_facts is not None and any(item['met'] is False for item in basis):
        return {'status': 'not_applicable', 'status_label': STATUS_LABELS['not_applicable'],
                'reason': '用户补充事实未满足所列合同条件', 'basis': basis,
                'scenarios': [], 'missing': [], 'method': 'deterministic_rules'}

    # 明确超上限：不给金额
    if max_sessions is not None and used is not None and used[0] > max_sessions:
        return {
            'status': 'not_applicable',
            'status_label': STATUS_LABELS['not_applicable'],
            'reason': f'已上 {used[0]} 节，超过合同约定的 {max_sessions} 节上限，按原文不适用退费。',
            'basis': basis,
            'scenarios': [],
            'missing': [],
            'method': 'deterministic_rules',
        }

    paid_value = _num(paid[0].group(1)) if paid else None
    unit_value = _num(unit[0].group(1)) if unit else None
    used_value = used[0] if used else None
    fee = paid_value * rate if paid_value is not None and rate is not None else None
    used_cost = unit_value * used_value if unit_value is not None and used_value is not None else None
    soft_missing = {'申请时间', '申请阶段'}
    hard_missing = [item for item in missing if item not in soft_missing]
    amount = None
    if paid_value is not None and fee is not None and not hard_missing:
        amount = paid_value - (used_cost or 0.0) - fee
        amount = max(amount, 0.0)

    trigger = '满足上述全部条件'
    if '申请时间' in missing and '申请阶段' in missing:
        trigger = f'在约定期限内、{phase or "约定阶段"}提出申请'
    elif '申请时间' in missing:
        trigger = '在约定期限内提出申请'
    elif '申请阶段' in missing:
        trigger = f'{phase}提出申请'

    formula = '实付金额'
    if used_cost is not None:
        formula += ' - 已上课时×每节原价'
    if rate is not None:
        formula += ' - 实付金额×手续费比例'

    penalty = next(
        (c for c in clauses
         if c.evidence.role == DocRole.CONTRACT and c.clause_type == ClauseType.PENALTY),
        None,
    )
    penalty_rate = (penalty.fields.get('rates') or [None])[0] if penalty else None
    penalty_amount = None
    if penalty_rate is not None and paid_value is not None:
        remaining = paid_value - (used_cost or 0.0)
        penalty_base = remaining if (
            '剩余' in penalty.evidence.quote or '未履行' in penalty.evidence.quote
        ) else paid_value
        penalty_amount = max(penalty_base, 0.0) * penalty_rate

    stacking_hit = _find(r'叠加|同时适用|合并计算|一并|另需支付', quotes)
    scenarios: List[Dict[str, Any]] = []
    if penalty is not None and penalty_rate is not None:
        if stacking_hit:
            basis.append(_condition(
                '原文明确违约金与退款手续费叠加', True, stacking_hit[2], stacking_hit[1],
            ))
            evidence_ids.append(stacking_hit[2])
            total = None
            if amount is not None and penalty_amount is not None:
                total = max(amount - penalty_amount, 0.0)
            scenarios.append(_scenario(
                '手续费 + 违约金（原文明确叠加）',
                '同时触发退款与提前解约',
                total,
                formula + ' - 剩余费用×违约金比例',
                total is not None,
                missing,
                evidence_ids + [penalty.evidence.evidence_id],
            ))
            status = 'applicable' if total is not None and not missing else (
                'conditional' if total is not None and not hard_missing else 'insufficient'
            )
        else:
            basis.append(_condition(
                '原文未明确违约金是否与退款手续费叠加', None,
                penalty.evidence.evidence_id, penalty.evidence.quote,
            ))
            scenarios.append(_scenario(
                '仅扣退款手续费', '不触发违约金', amount, formula,
                amount is not None, missing, evidence_ids,
            ))
            scenarios.append(_scenario(
                '手续费 + 违约金', '同时触发提前解约',
                None if amount is None or penalty_amount is None
                else max(amount - penalty_amount, 0.0),
                formula + ' - 剩余费用×违约金比例',
                False if amount is None or penalty_amount is None else None,
                missing + ([] if penalty_amount is not None else ['违约金计算基数']),
                evidence_ids + [penalty.evidence.evidence_id],
            ))
            status = 'conditional'
    else:
        scenarios.append(_scenario(
            '退款金额', trigger, amount, formula,
            amount is not None, missing, evidence_ids,
        ))
        if max_sessions is not None and used is None:
            scenarios.append(_scenario(
                f'已上超过 {max_sessions} 节', f'已上课节数 > {max_sessions}',
                None, '按原文不适用退费', False, missing, evidence_ids,
            ))
            status = 'insufficient'
        elif amount is None:
            status = 'insufficient'
        elif missing:
            status = 'conditional'
        else:
            status = 'applicable'

    return {
        'status': status,
        'status_label': STATUS_LABELS[status],
        'basis': basis,
        'scenarios': scenarios,
        'missing': list(dict.fromkeys(missing)),
        'method': 'deterministic_rules',
        'note': '金额为按原文条件与参数的确定性测算，不构成法律意见；条件未满足时不提供单一金额。',
    }


def _penalty_check(match: MatchResult, clauses: Sequence[Clause],
                   documents: Sequence[Document]) -> Dict[str, Any]:
    penalty = next(
        (c for c in clauses
         if c.evidence.role == DocRole.CONTRACT and c.clause_type == ClauseType.PENALTY),
        None,
    )
    if penalty is None:
        return {'status': 'no_amount', 'status_label': STATUS_LABELS['no_amount'],
                'basis': [], 'scenarios': [], 'missing': [], 'method': 'deterministic_rules'}

    quotes = _contract_segments(documents)
    rate = (penalty.fields.get('rates') or [None])[0]
    paid = _paid_amount(quotes)
    used = _used_count(quotes)
    unit = _unit_price(quotes)
    basis: List[Dict[str, Any]] = []
    missing: List[str] = []
    evidence_ids = [penalty.evidence.evidence_id]

    if rate is None:
        missing.append('违约金比例')
    else:
        basis.append(_condition(
            f'违约金比例为 {rate:.0%}', True,
            penalty.evidence.evidence_id, penalty.evidence.quote,
        ))
    base = None
    if paid is not None:
        base = _num(paid[0].group(1))
        basis.append(_condition(
            f'实付金额为 {base:.2f} 元', True, paid[2], paid[1],
        ))
        evidence_ids.append(paid[2])
        if '剩余' in penalty.evidence.quote or '未履行' in penalty.evidence.quote:
            if used is not None and unit is not None:
                base -= used[0] * _num(unit[0].group(1))
                basis.append(_condition(
                    f'已上课 {used[0]} 节，每节 {_num(unit[0].group(1)):.2f} 元',
                    True, used[1], used[2],
                ))
                evidence_ids.extend([used[1], unit[2]])
            else:
                missing.append('剩余费用计算参数')
    else:
        missing.append('违约金计算基数')

    amount = base * rate if base is not None and rate is not None and not missing else None
    scenarios = [_scenario(
        '违约金', '触发提前解除/违约条件', amount,
        '剩余费用（或实付金额）×违约金比例',
        amount is not None, missing, evidence_ids,
    )]
    status = 'applicable' if amount is not None and not missing else 'insufficient'
    return {
        'status': status,
        'status_label': STATUS_LABELS[status],
        'basis': basis,
        'scenarios': scenarios,
        'missing': list(dict.fromkeys(missing)),
        'method': 'deterministic_rules',
        'note': '违约金需以触发条件与计算基数为前提，缺少参数时不给单一金额。',
    }


def build_amount_checks(
    matches: Sequence[MatchResult], clauses: Sequence[Clause],
    documents: Sequence[Document],
) -> Dict[str, Dict[str, Any]]:
    checks: Dict[str, Dict[str, Any]] = {}
    for match in matches:
        if match.clause_type == ClauseType.REFUND:
            checks[match.clause_type.value] = _refund_check(match, clauses, documents)
        elif match.clause_type == ClauseType.PENALTY:
            checks[match.clause_type.value] = _penalty_check(match, clauses, documents)
    return checks
