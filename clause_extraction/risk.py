"""合同风险评分与红线规则（确定性，不调用模型）。

评分只作为"签约前需要重点确认的程度"，不是法律结论：
- 矛盾：宣传承诺与合同约定直接冲突；
- 宣传有、合同无：承诺未写进合同，事后难以主张；
- 合同自动续费但未约定提前通知期：默认扣款风险；
- 退费设置"已上课超过 N 节不退"等上限：消费者可退金额受限。
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from .schema import CLAUSE_LABELS, Clause, ClauseType, MatchResult, Verdict

_CONFLICT_WEIGHTS = {
    ClauseType.REFUND: 25,
    ClauseType.PENALTY: 15,
    ClauseType.AUTO_RENEWAL: 25,
    ClauseType.SERVICE_TERM: 10,
    ClauseType.EXTRA_FEE: 15,
}

_MISSING_IN_CONTRACT_WEIGHTS = {
    ClauseType.REFUND: 12,
    ClauseType.PENALTY: 6,
    ClauseType.AUTO_RENEWAL: 10,
    ClauseType.SERVICE_TERM: 5,
    ClauseType.EXTRA_FEE: 8,
}


def _evidence_ids(side: Any) -> List[str]:
    if not isinstance(side, dict):
        return []
    return [item.get('evidence_id', '') for item in side.get('evidences') or [] if item.get('evidence_id')]


def _level(score: int) -> tuple:
    if score >= 60:
        return 'high', '高风险'
    if score >= 30:
        return 'medium', '中风险'
    return 'low', '低风险'


def assess_risk(matches: Sequence[MatchResult], clauses: Sequence[Clause]) -> Dict[str, Any]:
    score = 0
    redlines: List[Dict[str, Any]] = []
    factors: List[str] = []

    for match in matches:
        label = CLAUSE_LABELS[match.clause_type]
        clause_type = match.clause_type
        if match.verdict == Verdict.CONFLICT:
            weight = _CONFLICT_WEIGHTS.get(clause_type, 10)
            score += weight
            factors.append(f'{label}：宣传与合同矛盾（+{weight}）')
            redlines.append({
                'clause_type': clause_type.value,
                'clause_label': label,
                'severity': 'high' if weight >= 20 else 'medium',
                'reason': '；'.join(match.reasons) or '宣传承诺与合同约定冲突',
                'evidence_ids': _evidence_ids(match.promo) + _evidence_ids(match.contract),
            })
        elif match.verdict == Verdict.MISSING_IN_CONTRACT:
            weight = _MISSING_IN_CONTRACT_WEIGHTS.get(clause_type, 5)
            score += weight
            factors.append(f'{label}：宣传有承诺、合同未约定（+{weight}）')
            redlines.append({
                'clause_type': clause_type.value,
                'clause_label': label,
                'severity': 'medium',
                'reason': '；'.join(match.reasons) or '宣传承诺未写入合同',
                'evidence_ids': _evidence_ids(match.promo),
            })
        elif match.verdict == Verdict.MISSING_IN_PROMO and clause_type in {
            ClauseType.AUTO_RENEWAL, ClauseType.EXTRA_FEE,
        }:
            score += 6
            factors.append(f'{label}：合同有约定、宣传未提及（+6）')
            redlines.append({
                'clause_type': clause_type.value,
                'clause_label': label,
                'severity': 'medium',
                'reason': '；'.join(match.reasons) or '合同有相关约定，宣传材料未提示',
                'evidence_ids': _evidence_ids(match.contract),
            })

    for clause in clauses:
        if clause.evidence.role.value != 'contract':
            continue
        if clause.clause_type == ClauseType.AUTO_RENEWAL:
            if clause.fields.get('flags', {}).get('auto_renewal'):
                notice_days = clause.fields.get('notice_days')
                if notice_days is None:
                    score += 8
                    factors.append('自动续费：合同未约定提前通知期（+8）')
                    redlines.append({
                        'clause_type': clause.clause_type.value,
                        'clause_label': '自动续费/续租',
                        'severity': 'high',
                        'reason': '合同约定自动续费，但未写提前多少天通知',
                        'evidence_ids': [clause.evidence.evidence_id],
                    })
                elif int(notice_days) > 15:
                    score += 4
                    factors.append(f'自动续费：提前通知 {notice_days} 日偏长（+4）')
        caps = [item for item in clause.fields.get('conditions') or [] if item.endswith(':no_refund')]
        if caps:
            score += 5
            factors.append(f'退款上限：{caps[0]}（+5）')
            redlines.append({
                'clause_type': ClauseType.REFUND.value,
                'clause_label': '退款',
                'severity': 'medium',
                'reason': f'合同设置退费上限（{caps[0]}）',
                'evidence_ids': [clause.evidence.evidence_id],
            })

    score = min(100, score)
    level, level_label = _level(score)
    return {
        'score': score,
        'level': level,
        'level_label': level_label,
        'redlines': redlines,
        'factors': factors,
        'method': 'deterministic_rules',
        'note': '评分只表示签约前需要重点确认的程度，不构成法律意见。',
    }
