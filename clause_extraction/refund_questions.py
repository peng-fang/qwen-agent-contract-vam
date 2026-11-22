"""Choose a single factual question from the existing refund check."""

from __future__ import annotations

QUESTIONS = {
    'used_sessions': ('已上课节数', '你已经上了几节课？'),
    'request_day': ('申请时间', '你在合同约定的起算日之后第几天申请退款？'),
    'request_phase': ('申请阶段', '你是在开课前还是开课后申请退款？'),
    'total_paid': ('实付金额', '你实际支付了多少元？'),
    'unit_price': ('每节原价', '每节课的原价是多少元？'),
}


def missing_user_facts(check: dict) -> list[str]:
    if check.get('status') not in {'conditional', 'insufficient'}:
        return []
    missing = set(check.get('missing', []))
    return [field for field, (label, _) in QUESTIONS.items() if label in missing]


def next_refund_question(check: dict) -> dict | None:
    missing = missing_user_facts(check)
    if not missing:
        return None
    for condition in check.get('basis', []):
        field = condition.get('requires_fact')
        if field in missing and condition['met'] is None:
            return {'field': field, 'question': QUESTIONS[field][1],
                    'condition': condition['condition'], 'evidence_id': condition['evidence_id']}

    # An undefined fee rule cannot be settled by collecting payment details.
    # Eligibility questions can still rule out this refund, so they come first.
    if set(check.get('missing', [])) - {label for label, _ in QUESTIONS.values()}:
        return None
    field = missing[0]
    return {'field': field, 'question': QUESTIONS[field][1], 'condition': None, 'evidence_id': None}
