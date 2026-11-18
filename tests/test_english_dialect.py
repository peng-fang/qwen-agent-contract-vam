"""英文 / 中英混写 / 口语方言条款的回归测试。"""

from __future__ import annotations

from typing import Dict, List

from clause_extraction import ClauseType, DocRole, Verdict, analyze_documents
from clause_extraction.schema import Document, PageText


def _doc(text: str, role: DocRole, name: str = 'doc.txt') -> Document:
    return Document(
        document_id=f'doc-{role.value}-{abs(hash(text)) % 100000}',
        filename=name,
        role=role,
        pages=[PageText(1, text)],
    )


def _bundle(promo: str, contract: str):
    return analyze_documents([
        _doc(promo, DocRole.PROMO, 'promo.txt'),
        _doc(contract, DocRole.CONTRACT, 'contract.txt'),
    ])


def _fields(bundle, clause_type: ClauseType, role: DocRole) -> List[Dict]:
    return [c.fields for c in bundle.clauses
            if c.clause_type == clause_type and c.evidence.role == role]


def _verdict(bundle, clause_type: ClauseType) -> Verdict:
    return next(m.verdict for m in bundle.matches if m.clause_type == clause_type)


def test_english_refund_keywords_and_full_refund():
    bundle = _bundle('Full refund within 7 days.', 'Non-refundable after 12 lessons.')
    promo = _fields(bundle, ClauseType.REFUND, DocRole.PROMO)
    assert promo and promo[0]['flags'].get('full_refund')
    contract = _fields(bundle, ClauseType.REFUND, DocRole.CONTRACT)
    assert contract and contract[0]['flags'].get('no_refund')
    assert 'used_sessions>12:no_refund' in contract[0]['conditions']


def test_english_penalty_and_percent():
    bundle = _bundle('No cancellation fee.', 'Cancellation fee is 20 percent.')
    contract = _fields(bundle, ClauseType.PENALTY, DocRole.CONTRACT)
    assert contract and contract[0]['rates'] == [0.2]
    assert _fields(bundle, ClauseType.PENALTY, DocRole.PROMO)[0]['flags'].get('no_penalty')


def test_english_auto_renewal_conflict_with_notice_days():
    bundle = _bundle(
        'No auto-renewal. The plan ends automatically.',
        'The plan renews automatically unless you cancel 30 days prior to expiry.',
    )
    contract = _fields(bundle, ClauseType.AUTO_RENEWAL, DocRole.CONTRACT)
    assert contract and contract[0]['flags'].get('auto_renewal')
    assert contract[0]['notice_days'] == 30
    assert _verdict(bundle, ClauseType.AUTO_RENEWAL) == Verdict.CONFLICT


def test_english_service_term_duration_and_units():
    bundle = _bundle(
        'The course lasts two years.',
        'The service term is 12 months. A service charge is 100 HKD per month.',
    )
    durations = [d for f in _fields(bundle, ClauseType.SERVICE_TERM, DocRole.CONTRACT)
                 for d in f['durations']]
    assert {'value': 12, 'unit': '个月'} in durations
    per_unit = [p for clause in bundle.clauses for p in clause.fields['per_unit_amounts']]
    assert {'amount': 100.0, 'unit': '月'} in per_unit


def test_english_extra_fee_conflict():
    bundle = _bundle(
        'No additional fees apply.',
        'A service charge of 100 HKD per month applies.',
    )
    assert _verdict(bundle, ClauseType.EXTRA_FEE) == Verdict.CONFLICT


def test_dialect_refund_full_refund_and_no_fee():
    bundle = _bundle(
        '不想学了随时退钱，一分不扣。',
        '开课后不退钱。',
    )
    promo = _fields(bundle, ClauseType.REFUND, DocRole.PROMO)
    assert promo and promo[0]['flags'].get('full_refund')
    assert promo[0]['flags'].get('free_of_charge')
    assert _verdict(bundle, ClauseType.REFUND) == Verdict.CONFLICT


def test_dialect_penalty_amount_and_auto_renewal():
    bundle = _bundle(
        '提前走人要赔两千块。',
        '到期顺延一年，自动扣钱。',
    )
    penalty = _fields(bundle, ClauseType.PENALTY, DocRole.PROMO)
    assert penalty and penalty[0]['amounts'] == [2000.0]
    auto = _fields(bundle, ClauseType.AUTO_RENEWAL, DocRole.CONTRACT)
    assert auto and auto[0]['flags'].get('auto_renewal')
    assert {'value': 1, 'unit': '年'} in auto[0]['durations']


def test_dialect_no_extra_charge():
    bundle = _bundle(
        '不会再加钱，包在里头。',
        '材料费另算，每月 100 元。',
    )
    promo = _fields(bundle, ClauseType.EXTRA_FEE, DocRole.PROMO)
    assert promo and promo[0]['flags'].get('free_of_charge')
    contract = _fields(bundle, ClauseType.EXTRA_FEE, DocRole.CONTRACT)
    assert contract and {'amount': 100.0, 'unit': '月'} in contract[0]['per_unit_amounts']
    assert _verdict(bundle, ClauseType.EXTRA_FEE) == Verdict.CONFLICT


def test_percentage_variants():
    bundle = _bundle('退款扣百分之五。', '退款扣两成，自动续费扣三成。')
    contract_rates = {rate for f in _fields(bundle, ClauseType.REFUND, DocRole.CONTRACT)
                      for rate in f['rates']}
    assert 0.2 in contract_rates
    assert 0.05 in {rate for f in _fields(bundle, ClauseType.REFUND, DocRole.PROMO)
                    for rate in f['rates']}
    assert 0.3 in {rate for f in _fields(bundle, ClauseType.AUTO_RENEWAL, DocRole.CONTRACT)
                   for rate in f['rates']}


def test_decimal_percent_is_not_split_into_two_sentences():
    bundle = _bundle('退款手续费 5.5%。', '退款手续费 5.5%。')
    promo = _fields(bundle, ClauseType.REFUND, DocRole.PROMO)
    assert promo and promo[0]['rates'] == [0.055]
    assert _verdict(bundle, ClauseType.REFUND) == Verdict.CONSISTENT


def test_english_evidence_offsets_point_to_original_text():
    bundle = _bundle('Full refund within 7 days.', 'Non-refundable after 12 lessons.')
    for clause in bundle.clauses:
        document = next(d for d in bundle.documents if d.document_id == clause.evidence.document_id)
        page = document.pages[clause.evidence.page - 1]
        assert page.text[clause.evidence.char_start:clause.evidence.char_end] == clause.evidence.quote
