"""Real API acceptance on fictional contracts; no keys or private materials in output.

Run with --live to explicitly enable model calls. The default only prints usage.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if not args.live:
        parser.print_help(); return
    os.environ.update(AUTO_START_OLLAMA='0', MODEL_PRELOAD='0', LEGAL_WEB_SEARCH_ENABLED='0', WORKFLOW_MODEL_PROVIDER='openai')
    from fastapi.testclient import TestClient
    from app.main import app
    from app.services import workflow_store as store, report_dialogue, rental_review_service
    out = ROOT / '.venv' / 'review_artifacts' / 'live_acceptance'
    out.mkdir(parents=True, exist_ok=True)
    store.ROOT = out / 'records'
    rental_review_service.CACHE_DIR = out / 'review-cache'
    os.environ['REVIEW_MODEL_PROVIDER'] = 'openai'
    os.environ['REVIEW_CACHE_ENABLED'] = '0'
    os.environ['EVIDENCE_REGISTRY_DIR'] = str(out / 'evidence')
    client = TestClient(app)
    results = {}
    def checked(response):
        if response.status_code != 200:
            raise RuntimeError(f'Acceptance endpoint returned {response.status_code}: {response.text[:300]}')
        return response.json()
    for name, contract, expected in [
        ('different_phases', '开课前申请可全额退款。开课后申请退款，扣除10%手续费。', 'consistent'),
        ('true_conflict', '开课前申请退款扣除10%手续费。', 'conflict'),
    ]:
        task = checked(client.post('/api/contract/clauses', data={'roles': 'promo,contract'}, files=[
            ('files', ('promo.txt', '开课前申请可全额退款。'.encode(), 'text/plain')),
            ('files', ('contract.txt', contract.encode(), 'text/plain'))]))
        result = checked(client.post(f"/api/workflows/verifications/{task['task_id']}/review", json={'revision': 1}))
        refund = next(i for i in result['semantic_review']['items'] if i['clause_type'] == 'refund')
        assert refund['verdict'] == expected, (name, refund)
        results[name] = result['semantic_review']
        print('PASS', name, flush=True)
    contract = out / 'lease.txt'
    contract.write_text('第一条 租金每月3000元。第二条 押金5000元。第三条 提前退租押金不退，另付10000元违约金。', encoding='utf-8')
    generated_report = checked(client.post('/api/contract/rental-review',
        data={'use_llm': 'true', 'contract_type': 'rental', 'region': 'mainland'},
        files={'file': ('lease.txt', contract.read_bytes(), 'text/plain')}))
    assert generated_report['report_id']
    assert any(t['agent'] == '条款理解 Agent' and t['status'] == 'done' for t in generated_report['agent_trace'])
    results['generated_report'] = generated_report
    print('PASS remote_initial_report', flush=True)
    report = {'region': 'mainland', 'contract_type': 'rental', 'risks': [
        {'risk_id': f'R{i}', 'quote': q, 'title': title, 'legal_basis': []}
        for i, q, title in [(1, '租金每月3000元', '租金'), (2, '押金5000元', '押金'),
                             (3, '提前退租押金不退，另付10000元违约金', '押金与违约金抵扣关系')]]}
    report = report_dialogue.persist_report(report, str(contract))
    chat = checked(client.post('/api/workflows/conversations', json={'report_id': report['report_id']}))
    for question in ['第三条风险怎么修改？请给出可协商的条款草案。', '保留上一版关于押金抵扣的意思，再委婉一点。']:
        chat = checked(client.post(f"/api/workflows/conversations/{chat['id']}/messages", json={
            'question': question, 'risk_ids': ['R3'], 'revision': chat['revision']}))
        assert '押金' in chat['messages'][-1]['content']
    assert len(chat['messages']) == 4
    results['report_dialogue'] = chat
    print('PASS report_dialogue', flush=True)
    text = '乙方向甲方以人民币付款：2027年1月1日支付4000元，2027年2月1日支付4000元，2027年3月1日支付4000元。'
    draft = checked(client.post('/api/workflows/payment-draft', files={'file': ('payments.txt', text.encode(), 'text/plain')}))
    assert len(draft['installments']) == 3
    assert sum(i['amount'] for i in draft['installments']) == 12000
    assert [i['due_date'] for i in draft['installments']] == ['2027-01-01', '2027-02-01', '2027-03-01']
    results['payment_draft'] = draft
    print('PASS payment_draft', flush=True)
    (out / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Live acceptance completed; results saved under .venv/review_artifacts/live_acceptance', flush=True)


if __name__ == '__main__':
    main()
