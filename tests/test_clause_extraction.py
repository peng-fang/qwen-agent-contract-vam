"""角色 B：条款结构化抽取与跨文档匹配的回归测试。

固定使用 demo_data 里的合成宣传页与合同；
另用临时文本覆盖"一致 / 单边缺失 / 双方缺失"等 PDF 之外的组合。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from clause_extraction import ClauseType, DocRole, Verdict, analyze_files, load_document
from clause_extraction import llm_extractor

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / 'demo_data'


def _require_pdf() -> None:
    pytest.importorskip('pdfplumber', reason='未安装 pdfplumber，跳过 PDF 用例')


@pytest.fixture(scope='module')
def gym_bundle():
    _require_pdf()
    return analyze_files([
        (str(DEMO / 'promo_gym.pdf'), None),
        (str(DEMO / 'contract_gym.pdf'), None),
    ])


def _match(bundle, clause_type: ClauseType):
    return next(item for item in bundle.matches if item.clause_type == clause_type)


def _clauses(bundle, clause_type: ClauseType):
    return [item for item in bundle.clauses if item.clause_type == clause_type]


def test_roles_inferred_from_filenames(gym_bundle):
    roles = {document.filename: document.role for document in gym_bundle.documents}
    assert roles['promo_gym.pdf'] == DocRole.PROMO
    assert roles['contract_gym.pdf'] == DocRole.CONTRACT


def test_extracts_all_five_clause_types(gym_bundle):
    found = {clause.clause_type for clause in gym_bundle.clauses}
    assert found == set(ClauseType)


def test_evidence_offsets_point_to_original_text(gym_bundle):
    for clause in gym_bundle.clauses:
        document = next(d for d in gym_bundle.documents if d.document_id == clause.evidence.document_id)
        page = next(p for p in document.pages if p.page == clause.evidence.page)
        assert page.text[clause.evidence.char_start:clause.evidence.char_end] == clause.evidence.quote
        assert clause.evidence.quote.strip()


def test_contract_refund_fields_are_deterministic(gym_bundle):
    refunds = [c for c in _clauses(gym_bundle, ClauseType.REFUND)
               if c.evidence.role == DocRole.CONTRACT]
    rates = {rate for clause in refunds for rate in clause.fields['rates']}
    per_unit = {(item['amount'], item['unit']) for clause in refunds
                for item in clause.fields['per_unit_amounts']}
    conditions = {condition for clause in refunds for condition in clause.fields['conditions']}

    assert 0.2 in rates
    assert (300.0, '节') in per_unit
    assert 'used_sessions>12:no_refund' in conditions


def test_refund_is_conflict_between_promo_and_contract(gym_bundle):
    result = _match(gym_bundle, ClauseType.REFUND)
    text = '；'.join(result.reasons)
    assert result.verdict == Verdict.CONFLICT
    assert '全额退款' in text
    assert '20%' in text
    assert result.promo and result.contract
    assert result.promo['evidences'][0]['filename'] == 'promo_gym.pdf'
    assert result.contract['evidences'][0]['filename'] == 'contract_gym.pdf'


def test_extra_fee_is_conflict(gym_bundle):
    result = _match(gym_bundle, ClauseType.EXTRA_FEE)
    assert result.verdict == Verdict.CONFLICT
    fees = {(item['amount'], item['unit']) for item in result.contract['fields']['per_unit_amounts']}
    assert fees == {(200.0, '年'), (100.0, '次'), (50.0, '次')}
    assert result.reasons


def test_auto_renewal_missing_in_promo(gym_bundle):
    result = _match(gym_bundle, ClauseType.AUTO_RENEWAL)
    assert result.verdict == Verdict.MISSING_IN_PROMO
    assert result.promo is None
    assert result.contract['fields']['notice_days'] == 7
    assert result.contract['fields']['flags']['auto_renewal'] is True
    assert result.contract['evidences'][0]['page'] == 2


def test_penalty_missing_in_promo(gym_bundle):
    result = _match(gym_bundle, ClauseType.PENALTY)
    assert result.verdict == Verdict.MISSING_IN_PROMO
    assert 0.3 in result.contract['fields']['rates']


def test_service_term_missing_in_promo(gym_bundle):
    result = _match(gym_bundle, ClauseType.SERVICE_TERM)
    assert result.verdict == Verdict.MISSING_IN_PROMO
    assert result.contract['fields']['dates'] == ['2026-01-01', '2026-12-31']


def test_consistent_service_term_with_synthetic_text(tmp_path):
    promo = tmp_path / 'promo_a.txt'
    contract = tmp_path / 'contract_a.txt'
    promo.write_text('服务期限为2026年1月1日至2026年12月31日。', encoding='utf-8')
    contract.write_text('服务期限为2026年1月1日至2026年12月31日。', encoding='utf-8')

    bundle = analyze_files([(str(promo), None), (str(contract), None)])
    result = _match(bundle, ClauseType.SERVICE_TERM)
    assert result.verdict == Verdict.CONSISTENT


def test_both_sides_missing(tmp_path):
    promo = tmp_path / 'promo_b.txt'
    contract = tmp_path / 'contract_b.txt'
    promo.write_text('本材料仅用于活动说明。', encoding='utf-8')
    contract.write_text('本协议仅约定课程安排。', encoding='utf-8')

    bundle = analyze_files([(str(promo), None), (str(contract), None)])
    assert {result.verdict for result in bundle.matches} == {Verdict.MISSING_BOTH}


def test_missing_in_contract_for_promo_only_promise(tmp_path):
    promo = tmp_path / 'promo_c.txt'
    contract = tmp_path / 'contract_c.txt'
    promo.write_text('会员可随时申请退费，未上课全额退款。', encoding='utf-8')
    contract.write_text('本协议仅约定课程安排。', encoding='utf-8')

    bundle = analyze_files([(str(promo), None), (str(contract), None)])
    result = _match(bundle, ClauseType.REFUND)
    assert result.verdict == Verdict.MISSING_IN_CONTRACT


def test_rules_are_default_without_model(gym_bundle):
    assert gym_bundle.extractor == 'rules'
    assert gym_bundle.warnings == []


def test_llm_candidates_must_be_grounded(monkeypatch, gym_bundle):
    """模型只提议片段：无法在原文定位的候选必须被丢弃。"""
    _require_pdf()
    document = load_document(str(DEMO / 'contract_gym.pdf'), DocRole.CONTRACT, 'doc9')
    fake_payload = (
        '[{"clause_type":"service_term","quote":"本合同服务期限为2026年1月1日至2026年12月31日"},'
        '{"clause_type":"refund","quote":"本合同承诺无条件全额退款且不收取任何手续费"}]'
    )
    monkeypatch.setattr(llm_extractor, '_chat', lambda config, doc: fake_payload)

    clauses, warnings = llm_extractor.extract_with_llm(document, {'model': 'stub'})
    assert len(clauses) == 1
    assert clauses[0].clause_type == ClauseType.SERVICE_TERM
    assert clauses[0].evidence.page == 1
    assert '服务期限' in clauses[0].evidence.quote
    assert len(warnings) == 1
    assert '无法在原文定位' in warnings[0]
