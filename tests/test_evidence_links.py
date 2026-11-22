from pathlib import Path

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
    doc, anchor = _document('退款条件见第八条。', '\n第八条 仅适用于A班。',
                            PageText(2, '第八条 仅适用于B班。'))
    assert select_related_evidence(doc, anchor)['related'] == []


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
        ('files', ('contract.txt', '七天内可退款。\n本条仅适用于开课前。'.encode(), 'text/plain')),
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
    (related,) = response.json()['related_evidence']['related']
    assert related['quote'] == '本条仅适用于开课前。'
    assert client.get(f"/api/contract/evidence/ev-{anchor['document_id']}-p1-c0-9999",
                      params={'include_related': 'true'}).status_code == 404
