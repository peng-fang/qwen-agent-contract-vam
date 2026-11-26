from pathlib import Path

import pytest

from clause_extraction.evidence_links import select_related_evidence
from clause_extraction.registry import register_document, resolve_evidence
from clause_extraction.schema import DocRole, Document, EvidenceSpan, PageText
from scripts.eval_linked_evidence import evaluate


def _document(head, continuation, *pages):
    document = Document('fixture', 'contract.txt', DocRole.CONTRACT,
                        [PageText(1, head + continuation), *pages])
    anchor = EvidenceSpan('fixture', 'contract.txt', DocRole.CONTRACT, 1, 'p1', 0, len(head), head)
    return document, anchor


def test_adjacent_exception_keeps_exact_offsets_and_does_not_cross_heading():
    head = '报名后七天内可退款'
    exception = '本条仅适用于开课前。'
    doc, anchor = _document(head, f'。\r\n  {exception}\n第三条 会员身份。\n但需提交本人证件。')
    result = select_related_evidence(doc, anchor, budget=len(exception))
    (related,) = result['related']
    assert related['relation'] == 'qualifier'
    assert doc.pages[0].text[related['char_start']:related['char_end']] == exception
    assert result['extra_quote_chars'] == len(exception)
    tight = select_related_evidence(doc, anchor, budget=len(exception) - 1)
    assert tight['related'] == []
    assert tight['omitted'] == 1


def test_cross_page_reference_round_trips_through_registry(tmp_path):
    doc, anchor = _document('取消要求见第八条。', '\n会员须保留凭证。',
                            PageText(2, '第八条\n取消须提前三十日通知。'))
    register_document(doc, str(tmp_path))
    resolved = resolve_evidence(anchor.evidence_id, str(tmp_path), include_related=True)
    (related,) = resolved['related_evidence']['related']
    assert (related['relation'], related['page']) == ('reference', 2)
    assert related['quote'] == '第八条\n取消须提前三十日通知。'
    checked = resolve_evidence(related['evidence_id'], str(tmp_path))
    assert checked['quote'] == related['quote']
    assert 'related_evidence' not in checked


def test_ambiguous_number_is_not_linked():
    doc, anchor = _document('退款条件见第八条。', '\n第8条 仅适用于A班。',
                            PageText(2, '第８條 仅适用于B班。'))
    result = select_related_evidence(doc, anchor)
    assert result['related'] == []
    assert result['unresolved_references'] == [
        {'reference': '第八条', 'from_evidence_id': anchor.evidence_id, 'reason': 'ambiguous'},
    ]


@pytest.mark.parametrize(('reference', 'expected_reason'), [
    ('第八条', 'missing'), ('第八条第二款', 'subpart'),
    ('第八条（２）', 'subpart'), ('第八条之一', 'subpart'),
])
def test_unresolved_reference_reports_exact_target(reference, expected_reason):
    # A suffixed heading must not be mistaken for the plain Article 8.
    doc, anchor = _document(f'退款条件依照{reference}。', '\n第八条之一 退款例外另行约定。')
    result = select_related_evidence(doc, anchor)
    assert not result['related']
    assert result['unresolved_reference_count'] == 1
    assert result['unresolved_references'][0] == {
        'reference': reference, 'from_evidence_id': anchor.evidence_id, 'reason': expected_reason,
    }


def test_mixed_number_forms_preserve_source_text_and_path():
    doc, anchor = _document('退款条件參見第８條。', '',
                            PageText(2, '第八条 适用范围按第１２条办理。'),
                            PageText(3, '第十二條 开课前可退。'))
    result = select_related_evidence(doc, anchor)
    bridge, terminal = result['related']
    assert [step['article'] for step in terminal['reference_path']] == ['第８條', '第１２条']
    assert terminal['quote'] == '第十二條 开课前可退。'
    assert bridge['evidence_id'] == terminal['reference_path'][-1]['from_evidence_id']
    assert result['unresolved_reference_count'] == 0


def test_unresolved_references_are_counted_but_display_is_bounded():
    doc, anchor = _document('退款条件见第8条、见第八条、见第九条、见第十条、见第十一条。', '')
    result = select_related_evidence(doc, anchor)
    assert result['unresolved_reference_count'] == 4
    assert [item['reference'] for item in result['unresolved_references']] == ['第8条', '第九条', '第十条']


def test_two_hop_path_recalls_intermediate_article_and_terminal_condition(tmp_path):
    doc, anchor = _document('退款条件见第八条。', '\n会员须保留凭证。',
                            PageText(2, '第八条 退款申请期限依照第十二条的规则办理。'),
                            PageText(3, '第十二条 仅开课前适用。'))
    register_document(doc, str(tmp_path))
    result = resolve_evidence(anchor.evidence_id, str(tmp_path), include_related=True)
    intermediate, terminal = result['related_evidence']['related']
    assert [intermediate['page'], terminal['page']] == [2, 3]
    assert terminal['reference_path'] == [
        {'article': '第八条', 'from_evidence_id': anchor.evidence_id, 'to_evidence_id': intermediate['evidence_id']},
        {'article': '第十二条', 'from_evidence_id': intermediate['evidence_id'], 'to_evidence_id': terminal['evidence_id']},
    ]
    assert resolve_evidence(terminal['evidence_id'], str(tmp_path))['quote'] == terminal['quote']
    assert len(select_related_evidence(doc, anchor, max_hops=1)['related']) == 1
    # The terminal could fit alone. It must not appear without the longer bridge.
    assert select_related_evidence(doc, anchor, budget=len(terminal['quote']))['related'] == []


def test_reference_cycle_does_not_duplicate_evidence():
    doc, anchor = _document('第四条 退款条件见第八条。', '\n会员须保留凭证。',
                            PageText(2, '第八条 退款事项以第四条为准。'))
    (related,) = select_related_evidence(doc, anchor)['related']
    assert [step['article'] for step in related['reference_path']] == ['第八条']


def test_development_comparison_has_identical_anchor_and_budget():
    rows = evaluate(48)
    linked = [row for row in rows if row['method'] == 'linked']
    nearby = {row['case']: row for row in rows if row['method'] == 'nearby'}
    for row in linked:
        baseline = nearby[row['case']]
        assert row['contract'].split('\n')[0] == baseline['contract'].split('\n')[0]
        assert all(sum(len(item['quote']) for item in arm['related']) <= 48 for arm in (row, baseline))
    assert all(row['qualifier_present'] for row in linked)


def test_evidence_api_adds_related_only_when_requested(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'backend'))
    monkeypatch.setenv('EVIDENCE_REGISTRY_DIR', str(tmp_path / 'registry'))
    from app.main import app
    from app.routers import clauses

    monkeypatch.setattr(clauses, 'UPLOAD_DIR', tmp_path / 'uploads')
    client = TestClient(app)
    uploaded = client.post('/api/contract/clauses', files=[
        ('files', ('promo.txt', '无论开课与否都可退款。'.encode(), 'text/plain')),
        ('files', ('contract.txt', ('七天内可退款，适用范围见第8条。\n'
                                    '第八条 适用阶段见第十二条。\n'
                                    '第１２条 仅适用于开课前，但例外详见第十五条。').encode(), 'text/plain')),
    ], data={'roles': 'promo,contract'})
    assert uploaded.status_code == 200, uploaded.text
    anchor = next(row['evidence'] for row in uploaded.json()['clauses']
                  if row['evidence']['role'] == 'contract' and row['clause_type'] == 'refund')
    url = f"/api/contract/evidence/{anchor['evidence_id']}"
    response = client.get(url)
    assert response.status_code == 200
    assert 'related_evidence' not in response.json()
    response = client.get(url, params={'include_related': 'true'})
    assert response.status_code == 200
    intermediate, terminal = response.json()['related_evidence']['related']
    assert terminal['quote'] == '第１２条 仅适用于开课前，但例外详见第十五条。'
    assert terminal['reference_path'][0]['from_evidence_id'] == anchor['evidence_id']
    assert terminal['reference_path'][1]['from_evidence_id'] == intermediate['evidence_id']
    assert response.json()['related_evidence']['unresolved_references'] == [
        {'reference': '第十五条', 'from_evidence_id': terminal['evidence_id'], 'reason': 'depth_limit'},
    ]
    assert client.get(f"/api/contract/evidence/ev-{anchor['document_id']}-p1-c0-9999",
                      params={'include_related': 'true'}).status_code == 404
