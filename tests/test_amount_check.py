"""金额适用条件核验的回归测试（确定性，不调用模型）。

覆盖：条件满足、条件不满足、条件不足需分档、叠加规则、超上限。
"""

from __future__ import annotations

from typing import Any, Dict

from clause_extraction import (
    ClauseType,
    DocRole,
    Document,
    PageText,
    analyze_documents,
    document_id_for,
    register_document,
    resolve_evidence,
)


def _bundle(text: str, tmp_path) -> Dict[str, Any]:
    promo = Document(
        document_id='',
        filename='promo.txt',
        role=DocRole.PROMO,
        pages=[PageText(page=1, text='课程介绍。')],
    )
    contract = Document(
        document_id='',
        filename='contract.txt',
        role=DocRole.CONTRACT,
        pages=[PageText(page=1, text=text)],
    )
    for document in (promo, contract):
        document.document_id = document_id_for(
            document.role.value, document.filename, document.pages,
        )
        register_document(document, str(tmp_path / 'registry'))
    bundle = analyze_documents([promo, contract])
    return {
        'bundle': bundle,
        'registry': str(tmp_path / 'registry'),
        'matches': {match.clause_type: match for match in bundle.matches},
    }


def _ids(check: Dict[str, Any]) -> list[str]:
    ids = [item['evidence_id'] for item in check['basis']]
    for scenario in check['scenarios']:
        ids.extend(scenario['evidence_ids'])
    return list(dict.fromkeys(ids))


def test_conditions_satisfied_computes_amount(tmp_path):
    data = _bundle(
        '学费 4800 元，每节 300 元；已上 8 节课，退费时扣除 20% 手续费。',
        tmp_path,
    )
    check = data['matches'][ClauseType.REFUND].amount

    assert check['status'] == 'applicable'
    assert check['scenarios'][0]['amount'] == 1440.0
    assert check['missing'] == []
    assert all(item['met'] is not False for item in check['basis'])
    for evidence_id in _ids(check):
        assert resolve_evidence(evidence_id, data['registry'])['verified'] is True


def test_condition_not_satisfied_returns_no_amount(tmp_path):
    data = _bundle(
        '学费 4800 元，每节 300 元；已上 13 节课，超过 12 节不予退费，退费时扣除 20% 手续费。',
        tmp_path,
    )
    check = data['matches'][ClauseType.REFUND].amount

    assert check['status'] == 'not_applicable'
    assert check['scenarios'] == []
    assert '12 节上限' in check['reason']
    cap = next(item for item in check['basis'] if '12 节' in item['condition'])
    assert cap['met'] is False
    assert resolve_evidence(cap['evidence_id'], data['registry'])['verified'] is True


def test_insufficient_parameters_yield_tiers_not_single_value(tmp_path):
    data = _bundle(
        '学费 4800 元，每节 300 元；超过 12 节不予退费，退费时扣除 20% 手续费。',
        tmp_path,
    )
    check = data['matches'][ClauseType.REFUND].amount

    assert check['status'] == 'insufficient'
    assert '已上课节数' in check['missing']
    assert len(check['scenarios']) == 2
    assert all(item['amount'] is None for item in check['scenarios'])
    assert any(item['applicable'] is False for item in check['scenarios'])
    assert all(item['formula'] for item in check['scenarios'])


def test_stacking_rule_produces_combined_amount(tmp_path):
    data = _bundle(
        '学费 4800 元，每节 300 元；已上 8 节课，退费时扣除 20% 手续费。'
        '提前解约需按剩余费用支付违约金 30%，与手续费叠加。',
        tmp_path,
    )
    refund = data['matches'][ClauseType.REFUND].amount
    penalty = data['matches'][ClauseType.PENALTY].amount

    assert refund['status'] == 'applicable'
    assert '叠加' in refund['scenarios'][0]['label']
    assert refund['scenarios'][0]['amount'] == 720.0
    assert penalty['status'] == 'applicable'
    assert penalty['scenarios'][0]['amount'] == 720.0
    for evidence_id in _ids(refund) + _ids(penalty):
        assert resolve_evidence(evidence_id, data['registry'])['verified'] is True


def test_over_session_cap_is_not_applicable(tmp_path):
    data = _bundle(
        '学费 4800 元，每节 300 元；已上 20 节课，超过 12 节不予退费，退费时扣除 20% 手续费。',
        tmp_path,
    )
    check = data['matches'][ClauseType.REFUND].amount

    assert check['status'] == 'not_applicable'
    assert check['scenarios'] == []
    assert '已上 20 节' in check['reason']
    assert '12' in check['reason']
