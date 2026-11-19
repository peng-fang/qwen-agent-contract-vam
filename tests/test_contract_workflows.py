"""Offline integration checks for state, provenance, corrections and calculations."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from fastapi.testclient import TestClient
from app.main import app
from app.services import workflow_store as store, report_dialogue, semantic_review, payment_plans


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'ROOT', tmp_path / 'records')
    monkeypatch.setenv('AUTO_START_OLLAMA', '0')
    monkeypatch.setenv('MODEL_PRELOAD', '0')
    monkeypatch.setenv('LEGAL_WEB_SEARCH_ENABLED', '0')
    monkeypatch.setenv('EVIDENCE_REGISTRY_DIR', str(tmp_path / 'evidence'))
    return TestClient(app)


def upload(client, promo='开课前申请可全额退款。', contract='开课前申请可全额退款。开课后申请退款，扣除10%手续费。'):
    response = client.post('/api/contract/clauses', data={'roles': 'promo,contract'}, files=[
        ('files', ('promo.txt', promo.encode(), 'text/plain')),
        ('files', ('contract.txt', contract.encode(), 'text/plain')),
    ])
    assert response.status_code == 200, response.text
    return response.json()


def test_supplement_resume_provenance_and_conflict(client):
    result = upload(client, contract='学费4800元，每节300元；超过12节不予退费，退费扣除20%手续费。')
    task = result['task_id']
    initial = client.get(f'/api/workflows/verifications/{task}').json()
    response = client.post(f'/api/workflows/verifications/{task}/facts', json={
        'revision': initial['task_revision'], 'facts': {'used_sessions': 8}})
    assert response.status_code == 200, response.text
    updated = response.json()
    refund = next(m['amount'] for m in updated['matches'] if m['clause_type'] == 'refund')
    assert refund['status'] == 'applicable'
    assert refund['scenarios'][0]['amount'] == 1440
    assert any(b.get('source') == 'user' and b['fact_key'] == 'used_sessions' for b in refund['basis'])
    assert all('用户确认' not in p['text'] for d in updated['documents'] for p in d['pages'])
    assert client.post(f'/api/workflows/verifications/{task}/facts', json={
        'revision': 1, 'facts': {'used_sessions': 3}}).status_code == 409
    assert client.post(f'/api/workflows/verifications/{task}/facts', json={
        'revision': updated['task_revision'], 'facts': {'used_sessions': 13}}).json()['matches'][0]['amount']['status'] == 'not_applicable'


@pytest.mark.parametrize('facts', [{'used_sessions': -1}, {'used_sessions': 1.5}, {'used_sessions': True},
                                   {'made_up_field': 1}, {'request_phase': 'unknown'}])
def test_invalid_facts_rejected(client, facts):
    result = upload(client)
    assert client.post(f"/api/workflows/verifications/{result['task_id']}/facts",
                       json={'revision': 1, 'facts': facts}).status_code == 422


def test_window_and_phase_are_still_checked(client):
    data = upload(client, contract='学费4800元，每节300元；开课前7天内申请退款，手续费20%。')
    response = client.post(f"/api/workflows/verifications/{data['task_id']}/facts", json={
        'revision': 1, 'facts': {'used_sessions': 0, 'request_day': 9, 'request_phase': '开课前'}}).json()
    assert response['matches'][0]['amount']['status'] == 'not_applicable'


def review_output(payload, verdict='consistent'):
    return {'items': [{'clause_type': kind, 'verdict': verdict, 'reason': '分别比较开课前后条件。',
        'citations': [e['evidence_id'] for m in payload['matches'] if m['clause_type'] == kind
                      for side in ('promo', 'contract') for e in m[side]['evidences']]}
                     for kind in payload['requested_types']]}, {'model': 'test', 'provider': 'fake'}


def test_semantic_review_keeps_baseline_and_invalidates_on_facts(client, monkeypatch):
    data = upload(client)
    monkeypatch.setattr(semantic_review, 'generate_json', lambda system, payload, *args: review_output(payload))
    response = client.post(f"/api/workflows/verifications/{data['task_id']}/review", json={'revision': 1})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['matches'][0]['verdict'] == 'conflict'
    assert result['semantic_review']['matches'][0]['verdict'] == 'consistent'
    assert result['semantic_review']['matches'][0]['amount'] is None
    updated = client.post(f"/api/workflows/verifications/{data['task_id']}/facts", json={
        'revision': result['task_revision'], 'facts': {'used_sessions': 0}}).json()
    assert updated['semantic_review'] is None


def test_bad_semantic_citation_does_not_mutate_record(client, monkeypatch):
    data = upload(client)
    monkeypatch.setattr(semantic_review, 'generate_json', lambda *args: ({'items': [{
        'clause_type': 'refund', 'verdict': 'consistent', 'reason': 'test', 'citations': ['invented']}]}, {}))
    assert client.post(f"/api/workflows/verifications/{data['task_id']}/review", json={'revision': 1}).status_code == 502
    assert store.get('verifications', data['task_id'])['revision'] == 1


def test_report_snapshot_survives_file_cleanup_and_history(client, tmp_path, monkeypatch):
    path = tmp_path / 'lease.txt'
    path.write_text('第一条 押金5000元。第二条 提前退租违约金10000元。', encoding='utf-8')
    report = {'region': 'mainland', 'risks': [
        {'risk_id': 'R1', 'quote': '押金5000元', 'legal_basis': []},
        {'risk_id': 'R2', 'quote': '提前退租违约金10000元', 'legal_basis': []}]}
    snapshot = report_dialogue.persist_report(report, str(path))
    path.unlink()
    chat = client.post('/api/workflows/conversations', json={'report_id': snapshot['report_id']}).json()
    calls = []
    def model(system, payload, *args):
        calls.append(payload)
        return {'answer': '建议明确抵扣关系。[R2]', 'citations': ['R2']}, {'model': 'test'}
    monkeypatch.setattr(report_dialogue, 'generate_json', model)
    for question in ['第二条怎么改？', '再委婉一点']:
        response = client.post(f"/api/workflows/conversations/{chat['id']}/messages", json={
            'question': question, 'risk_ids': ['R2'], 'revision': chat['revision']})
        assert response.status_code == 200, response.text
        chat = response.json()
    assert len(calls[1]['history']) == 2
    assert calls[1]['report']['region'] == 'mainland'
    assert calls[1]['evidence']['C1']['text']
    assert len(client.get(f"/api/workflows/conversations/{chat['id']}").json()['messages']) == 4
    assert client.post(f"/api/workflows/conversations/{chat['id']}/messages", json={
        'question': 'test', 'risk_ids': ['nonexistent'], 'revision': chat['revision']}).status_code == 422


def test_invented_chat_citation_is_rejected(client, tmp_path, monkeypatch):
    p = tmp_path / 'source.txt'; p.write_text('押金金额为5000元。', encoding='utf-8')
    report = report_dialogue.persist_report({'risks': []}, str(p))
    chat = report_dialogue.conversation(report['report_id'])
    monkeypatch.setattr(report_dialogue, 'generate_json', lambda *args: ({'answer': '[Fake]', 'citations': ['Fake']}, {}))
    assert client.post(f"/api/workflows/conversations/{chat['id']}/messages", json={
        'question': '修改建议', 'risk_ids': [], 'revision': 1}).status_code == 502
    assert store.get('conversations', chat['id'])['messages'] == []


def plans():
    return [{'title': '全款', 'currency': 'CNY', 'payer': '承租人', 'confirmed': True,
             'installments': [{'due_date': '2027-01-01', 'amount': '12000', 'label': '全款'}]},
            {'title': '分期', 'currency': 'CNY', 'payer': '承租人', 'confirmed': True,
             'installments': [{'due_date': f'2027-{m:02}-01', 'amount': '4000', 'label': '分期'} for m in range(1, 4)]}]


def test_payment_dates_decimal_and_revision(client):
    response = client.post('/api/workflows/payments', json={'plans': plans()})
    assert response.status_code == 200, response.text
    data = response.json()
    assert [p['total'] for p in data['comparison']['plans']] == ['12000.00', '12000.00']
    assert data['comparison']['plans'][1]['points'][0]['cumulative'] == '4000.00'
    modified = plans(); modified[1]['installments'][0]['amount'] = '.10'
    update = client.post('/api/workflows/payments', json={'plans': modified, 'id': data['id'], 'revision': 1}).json()
    assert update['comparison']['plans'][1]['total'] == '8000.10'
    assert len(update['history']) == 1
    assert client.post('/api/workflows/payments', json={'plans': modified, 'id': data['id'], 'revision': 1}).status_code == 409
    assert client.get(f"/api/workflows/payments/{data['id']}").json()['revision'] == 2


@pytest.mark.parametrize('mutation', ['currency', 'payer', 'unconfirmed', 'negative', 'precision', 'date'])
def test_invalid_payment_plan(client, mutation):
    items = plans()
    if mutation == 'currency': items[1]['currency'] = 'USD'
    if mutation == 'payer': items[1]['payer'] = '其他人'
    if mutation == 'unconfirmed': items[1]['confirmed'] = False
    if mutation == 'negative': items[1]['installments'][0]['amount'] = '-1'
    if mutation == 'precision': items[1]['installments'][0]['amount'] = '0.001'
    if mutation == 'date': items[1]['installments'][0]['due_date'] = '2027-02-30'
    assert client.post('/api/workflows/payments', json={'plans': items}).status_code == 422


def test_payment_draft_sources_are_restored_from_original(client, monkeypatch):
    monkeypatch.setattr(payment_plans, 'generate_json', lambda *args: ({'title': '草稿', 'currency': 'CNY',
        'payer': '乙方', 'missing': ['签约日'], 'installments': [{'due_date': None, 'amount': 4000,
        'label': '首期', 'source_ids': ['C1']}]}, {'model': 'test'}))
    result = client.post('/api/workflows/payment-draft', files={'file': (
        'contract.txt', '签约日支付首期4000元。'.encode(), 'text/plain')})
    assert result.status_code == 200, result.text
    assert result.json()['confirmed'] is False
    assert result.json()['installments'][0]['due_date'] is None
    assert result.json()['sources'][0]['quote'] == '签约日支付首期4000元。'


def test_path_traversal_and_unknown_records(client):
    assert client.get('/api/workflows/payments/not-a-record').status_code == 422
    assert client.get('/api/workflows/payments/' + 'f' * 32).status_code == 404
    with pytest.raises(ValueError): store.get('reports', '../secret')


def test_custom_endpoint_does_not_load_or_forward_shared_key(monkeypatch):
    from app.services import workflow_llm as llm
    monkeypatch.setenv('WORKFLOW_MODEL_PROVIDER', 'openai')
    monkeypatch.setenv('WORKFLOW_API_BASE', 'https://custom.invalid/v1')
    monkeypatch.delenv('WORKFLOW_API_KEY', raising=False)
    def forbidden():
        raise AssertionError('Shared credential loader must not run for a custom endpoint')
    monkeypatch.setattr(llm, '_key', forbidden)
    with pytest.raises(llm.ModelUnavailable, match='WORKFLOW_API_KEY'):
        llm.generate_json('test', {}, {}, 'test')


def test_multiphase_amounts_need_separate_conditions(client):
    task = upload(client)
    result = client.post(f"/api/workflows/verifications/{task['task_id']}/facts", json={
        'revision': 1, 'facts': {'request_phase': '开课后', 'used_sessions': 8}}).json()
    assert result['matches'][0]['amount']['status'] == 'insufficient'
    assert result['matches'][0]['amount']['scenarios'] == []


def test_chat_repairs_missing_citation_before_saving(client, tmp_path, monkeypatch):
    p = tmp_path / 'source.txt'; p.write_text('押金为5000元。', encoding='utf-8')
    report = report_dialogue.persist_report({'risks': []}, str(p))
    chat = report_dialogue.conversation(report['report_id'])
    seen = []
    def generate(system, payload, schema, name):
        seen.append(bool(payload.get('validation_feedback')))
        if len(seen) == 1:
            return {'answer': '建议明确押金退还时间。', 'citations': []}, {}
        return {'answer': '建议明确押金退还时间。[C1]', 'citations': ['C1']}, {}
    monkeypatch.setattr(report_dialogue, 'generate_json', generate)
    result = client.post(f"/api/workflows/conversations/{chat['id']}/messages", json={
        'question': '给个建议', 'risk_ids': [], 'revision': 1})
    assert result.status_code == 200
    assert seen == [False, True]
    assert len(result.json()['messages']) == 2
    assert result.json()['messages'][-1]['citations'][0]['quote'] == '押金为5000元。'


def test_same_risk_ids_in_different_reports_stay_isolated(client, tmp_path, monkeypatch):
    seen = []
    def generate(system, payload, *args):
        seen.append((payload['report']['region'], payload['evidence']['R1']['quote'], len(payload['history'])))
        return {'answer': '需确认。[R1]', 'citations': ['R1']}, {}
    monkeypatch.setattr(report_dialogue, 'generate_json', generate)
    for region, quote in [('mainland', '押金5000元。'), ('hongkong', '按金2000港元。')]:
        p = tmp_path / (region + '.txt'); p.write_text(quote, encoding='utf-8')
        report = report_dialogue.persist_report({'region': region, 'risks': [
            {'risk_id': 'R1', 'quote': quote, 'legal_basis': []}]}, str(p))
        chat = report_dialogue.conversation(report['report_id'])
        assert client.post(f"/api/workflows/conversations/{chat['id']}/messages", json={
            'question': '解释第一条', 'risk_ids': ['R1'], 'revision': 1}).status_code == 200
    assert seen == [('mainland', '押金5000元。', 0), ('hongkong', '按金2000港元。', 0)]
