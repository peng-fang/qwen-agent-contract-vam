from pathlib import Path

import requests
from fastapi.testclient import TestClient


def test_checklist_sources_priorities_and_conditional_amounts(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / 'backend'))
    from app.main import app
    from app.services import checklist_service

    client = TestClient(app)
    first = '承租人违约时，出租人可以扣除押金5000元。'
    second = '提前解除合同，应支付10000元违约金。'
    text = f'{first}\n{second}'

    def card(title, source_id):
        return {'title': title, 'trigger': '提前解除时', 'consequence': '可能扣款',
                'question': title, 'source_ids': [source_id]}

    def generate(cfg, system, prompt, **kwargs):
        assert '承租人' in prompt
        return {'items': [card('赔付期限何时起算？', 'S2'), card('押金能否抵扣？', 'S1'),
                          card('有伪造引用的问题？', 'S99')]}, ''

    class PriorityReply:
        def raise_for_status(self):
            pass

        def json(self):
            return {'model': 'Intern-Decision-2B',
                    'priorities': {'C1': 'should_confirm', 'C2': 'must_confirm'}}

    def post(url, json, timeout):
        assert url.endswith('/priority')
        assert json['items'][1]['quotes'] == [first, second]
        return PriorityReply()

    monkeypatch.setattr(checklist_service, '_generate_json', generate)
    monkeypatch.setenv('CHECKLIST_PRIORITY_PROVIDER', 'intern')
    with monkeypatch.context() as patch:
        patch.setattr(checklist_service.requests, 'post', post)
        response = client.post('/api/checklist/run', data={'role': '承租人'},
                               files={'file': ('example.txt', text.encode(), 'text/plain')})
    assert response.status_code == 200, response.text
    result = response.json()
    assert [item['title'] for item in result['items']] == ['提前退租时押金能否抵扣违约金', '赔付期限何时起算？']
    assert [entry['quote'] for entry in result['items'][0]['evidence']] == [first, second]
    assert result['priority_model'] == 'Intern-Decision-2B'

    def unavailable(*args, **kwargs):
        raise requests.Timeout
    with monkeypatch.context() as patch:
        patch.setattr(checklist_service.requests, 'post', unavailable)
        result = client.post('/api/checklist/run', data={'text': text, 'role': '承租人'}).json()
    assert result['warning']
    assert len(result['items']) == 2
    assert result['items'][0]['priority'] is None

    estimate = client.post('/api/checklist/consequence', json={'template': 'lease_exit', 'parameters': {
        'deposit': 5000, 'penalty': 10000, 'extra_fee': 0, 'cap_mode': 'none', 'early_exit_applies': True,
    }})
    assert [row['amount'] for row in estimate.json()] == [15000, 10000, 10000]


def test_checklist_recovers_topics_missed_by_generator(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / 'backend'))
    from app.services import checklist_service as service

    pages = [
        {'filename': 'lease.pdf', 'kind': 'pdf', 'page': 1,
         'text': '甲方可以扣除押金。提前退租，应支付违约金。'},
        {'filename': 'lease.pdf', 'kind': 'pdf', 'page': 2,
         'text': '未提前20日通知，合同自动续\n租6个月。续租租金由双方另议。'
                 '甲方可从押金扣除维修及清洁费用。'},
    ]
    card = {'title': '押金是否抵扣违约金', 'question': '押金能否抵扣违约金？',
            'trigger': '提前退租时', 'consequence': '可能需要额外支付', 'source_ids': ['S1', 'S2']}
    monkeypatch.setattr(service, '_document_sources', lambda *args: pages)
    monkeypatch.setattr(service, '_generate_json', lambda *args, **kwargs: (
        {'items': [card] + [{**card, 'question': f'提前退租费用问题 {i}？'} for i in range(4)]}, ''))

    def prioritize(cards, role):
        for item in cards:
            item['priority'] = 'should_confirm' if item['evidence'][0]['page'] == 2 else 'must_confirm'
            item['priority_source'] = 'rule'
        return '规则优先级', None

    monkeypatch.setattr(service, '_prioritize', prioritize)
    result = service.generate_checklist('承租人', filename='lease.pdf', content=b'placeholder')
    assert len(result['items']) == 5
    exit_question = next(item for item in result['items'] if item['topic'] == 'exit')
    assert '抵扣违约金' in exit_question['question']
    assert [entry['id'] for entry in exit_question['evidence']] == ['S1', 'S2']
    renewal = next(item for item in result['items'] if item['topic'] == 'renewal')
    deductions = next(item for item in result['items'] if item['topic'] == 'liability')
    assert [entry['page'] for entry in renewal['evidence']] == [2, 2]
    assert '自动续\n租' in renewal['evidence'][0]['quote']
    assert '维修及清洁费用' in deductions['evidence'][0]['quote']

    # A selected excerpt cannot introduce questions about unseen clauses.
    monkeypatch.setattr(service, '_generate_json', lambda *args, **kwargs: ({'items': [card]}, ''))
    excerpt = service.generate_checklist('承租人', text=pages[0]['text'])
    assert len(excerpt['items']) == 1


def test_checklist_rules_first(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / 'backend'))
    from app.services import checklist_service as service

    monkeypatch.delenv('CHECKLIST_PRIORITY_PROVIDER', raising=False)
    monkeypatch.setenv('CHECKLIST_PRIORITY_PROVIDER', 'rules')
    cards = [
        {'id': 'C1', 'title': '自动续费能否关闭', 'trigger': '到期前', 'consequence': '可能自动扣款',
         'question': '如何关闭自动续费？', 'evidence': [{'quote': '到期自动续费12个月'}]},
        {'id': 'C2', 'title': '验收标准是什么', 'trigger': '交付时', 'consequence': '可能影响尾款',
         'question': '验收标准是什么？', 'evidence': [{'quote': '设备交付后验收'}]},
        {'id': 'C3', 'title': '一般沟通方式', 'trigger': '日常沟通', 'consequence': '影响日常联系',
         'question': '如何联系？', 'evidence': [{'quote': '双方应保持沟通'}]},
    ]
    model, warning = service._prioritize(cards, '采购方')
    assert model == '规则优先级'
    assert cards[0]['priority'] == 'must_confirm'
    assert cards[1]['priority'] == 'should_confirm'
    assert cards[2]['priority'] is None
    assert warning


def test_checklist_hybrid_only_asks_model_for_ambiguous(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / 'backend'))
    from app.services import checklist_service as service

    monkeypatch.setenv('CHECKLIST_PRIORITY_PROVIDER', 'hybrid')
    cards = [
        {'id': 'C1', 'title': '自动续费能否关闭', 'trigger': '到期前', 'consequence': '可能自动扣款',
         'question': '如何关闭自动续费？', 'evidence': [{'quote': '到期自动续费12个月'}]},
        {'id': 'C2', 'title': '一般沟通方式', 'trigger': '日常沟通', 'consequence': '影响日常联系',
         'question': '如何联系？', 'evidence': [{'quote': '双方应保持沟通'}]},
    ]
    calls = []

    def fake(cards, role):
        calls.append([card['id'] for card in cards])
        cards[0]['priority'] = 'should_confirm'
        cards[0]['priority_source'] = 'intern'
        return 'Intern-Decision-2B'

    monkeypatch.setattr(service, '_call_intern_priority', fake)
    model, warning = service._prioritize(cards, '承租人')
    assert model == 'Intern-Decision-2B'
    assert calls == [['C2']]
    assert cards[0]['priority'] == 'must_confirm'
    assert cards[1]['priority'] == 'should_confirm'
    assert warning is None


def test_checklist_qwen_only_asks_model_for_ambiguous(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / 'backend'))
    from app.services import checklist_service as service

    monkeypatch.setenv('CHECKLIST_PRIORITY_PROVIDER', 'qwen')
    cards = [
        {'id': 'C1', 'title': '自动续费能否关闭', 'trigger': '到期前', 'consequence': '可能自动扣款',
         'question': '如何关闭自动续费？', 'evidence': [{'quote': '到期自动续费12个月'}]},
        {'id': 'C2', 'title': '一般沟通方式', 'trigger': '日常沟通', 'consequence': '影响日常联系',
         'question': '如何联系？', 'evidence': [{'quote': '双方应保持沟通'}]},
    ]
    calls = []

    def fake(cards, role):
        calls.append([card['id'] for card in cards])
        cards[0]['priority'] = 'reference'
        cards[0]['priority_source'] = 'qwen'
        return 'qwen2.5:7b'

    monkeypatch.setattr(service, '_call_qwen_priority', fake)
    model, warning = service._prioritize(cards, '承租人')
    assert model == 'qwen2.5:7b'
    assert calls == [['C2']]
    assert cards[0]['priority'] == 'must_confirm'
    assert cards[1]['priority'] == 'reference'
    assert warning is None
