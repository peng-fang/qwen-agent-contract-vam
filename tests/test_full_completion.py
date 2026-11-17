"""条款侧新增能力的回归测试。

覆盖：evidence_id 反查、三/六标签、确定性证据复核、风险评分、合同版本对比。
VAM 推演由 main 的 `test_vam_tree.py` / `test_vam_workflow.py` 覆盖。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clause_extraction import (
    ClauseType,
    DocRole,
    EvidenceNotFound,
    Verdict,
    VerdictGroup,
    analyze_documents,
    assess_risk,
    diff_documents,
    document_id_for,
    load_document,
    register_document,
    resolve_evidence,
    review_bundle,
)

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / 'demo_data'


def _demo_bundle():
    pytest.importorskip('pdfplumber', reason='未安装 pdfplumber，跳过 PDF 用例')
    documents = [
        load_document(str(DEMO / 'promo_gym.pdf'), DocRole.PROMO, 'doc-promo'),
        load_document(str(DEMO / 'contract_gym.pdf'), DocRole.CONTRACT, 'doc-contract'),
    ]
    return analyze_documents(documents)


def test_evidence_id_roundtrip_and_404(tmp_path):
    path = tmp_path / 'contract.txt'
    path.write_text('退费时扣除 20% 手续费。', encoding='utf-8')
    document = load_document(str(path), DocRole.CONTRACT, 'doc-test', 'contract.txt')
    document.document_id = document_id_for('contract', 'contract.txt', document.pages)
    register_document(document, str(tmp_path / 'registry'))

    bundle = analyze_documents([document])
    refund = next(clause for clause in bundle.clauses if clause.clause_type == ClauseType.REFUND)
    evidence_id = refund.evidence.evidence_id

    resolved = resolve_evidence(evidence_id, str(tmp_path / 'registry'))
    assert resolved['quote'] == refund.evidence.quote
    assert resolved['page'] == refund.evidence.page
    assert resolved['verified'] is True

    with pytest.raises(EvidenceNotFound):
        resolve_evidence('ev-doc-missing-p1-c0-4', str(tmp_path / 'registry'))
    with pytest.raises(EvidenceNotFound):
        resolve_evidence('not-an-evidence-id', str(tmp_path / 'registry'))


def test_verdict_groups_are_three_way():
    from clause_extraction.schema import VERDICT_GROUPS

    assert VERDICT_GROUPS[Verdict.CONFLICT] == VerdictGroup.CONFLICT
    assert VERDICT_GROUPS[Verdict.CONSISTENT] == VerdictGroup.CONSISTENT
    for verdict in (
        Verdict.MISSING_IN_CONTRACT,
        Verdict.MISSING_IN_PROMO,
        Verdict.MISSING_BOTH,
        Verdict.UNCLEAR,
    ):
        assert VERDICT_GROUPS[verdict] == VerdictGroup.INSUFFICIENT


def test_deterministic_review_passes_and_catches_tampering():
    pytest.importorskip('pdfplumber', reason='未安装 pdfplumber，跳过 PDF 用例')
    bundle = _demo_bundle()
    assert bundle.evidence_review['checked'] == len(bundle.clauses)
    assert bundle.evidence_review['failed'] == 0

    target = bundle.clauses[0]
    target.evidence.quote = target.evidence.quote + '（被篡改）'
    review = review_bundle(bundle.documents, bundle.clauses)
    assert review['failed'] >= 1
    assert any('原文切片与 quote 不一致' in problem
               for failure in review['failures'] for problem in failure['problems'])


def test_risk_assessment_is_deterministic():
    bundle = _demo_bundle()
    risk = assess_risk(bundle.matches, bundle.clauses)
    assert risk['method'] == 'deterministic_rules'
    assert 0 <= risk['score'] <= 100
    assert risk['level'] in {'low', 'medium', 'high'}
    assert any(item['clause_type'] == 'refund' for item in risk['redlines'])
    assert all(item['evidence_ids'] for item in risk['redlines'])


def test_version_diff_detects_field_changes(tmp_path):
    old_path = tmp_path / 'contract_old.txt'
    new_path = tmp_path / 'contract_new.txt'
    old_path.write_text('退费时扣除 20% 手续费。服务期限为2026年1月1日至2026年12月31日。',
                        encoding='utf-8')
    new_path.write_text('退费时扣除 10% 手续费。服务期限为2026年1月1日至2026年12月31日。',
                        encoding='utf-8')

    old_doc = load_document(str(old_path), DocRole.CONTRACT, 'doc-old', 'contract_old.txt')
    new_doc = load_document(str(new_path), DocRole.CONTRACT, 'doc-new', 'contract_new.txt')
    result = diff_documents(old_doc, new_doc)

    refund = next(row for row in result['rows'] if row['clause_type'] == 'refund')
    term = next(row for row in result['rows'] if row['clause_type'] == 'service_term')
    assert refund['status'] == 'changed'
    assert any(change['field'] == 'rates' for change in refund['changes'])
    assert term['status'] == 'unchanged'
    assert result['summary']['changed'] == 1

