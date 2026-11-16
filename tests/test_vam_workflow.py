"""Regressions for scenario correctness, calculations, and the public VAM workflow."""

from pathlib import Path

import pytest

from vam_sandbox import pipeline
from vam_sandbox.comparison import calculate


REPURCHASE = {
    'principal': 10_000_000, 'annual_rate': 8, 'years': 3, 'interest': 'simple',
    'extra_fee': 0, 'offset': 0, 'cap_mode': 'none', 'payment_days': 30,
}
LEASE = {
    'deposit': 5_000, 'penalty': 10_000, 'extra_fee': 0,
    'cap_mode': 'none', 'early_exit_applies': True,
}
VALID = {'risk_score': 8, 'feasibility_score': 4, 'loss_score': 3, 'confidence': 0.8}


def test_local_qwen_is_available_scorer(monkeypatch):
    monkeypatch.setenv('VAM_SCORER_PROVIDER', 'local')

    def generate(cfg, system, user, **kwargs):
        assert '本地 Qwen 校准' in system
        return {'risk_score': 7, 'feasibility_score': 5, 'loss_score': 6, 'confidence': 0.7, 'evidence': '测试'}, ''

    monkeypatch.setattr(pipeline, '_generate_json', generate)
    raw, _ = pipeline._score_leaf({'model': 'qwen2.5:7b'}, '合同原文', '情景')
    assert raw['scorer_model'] == 'qwen2.5:7b'
    assert raw['feasibility_score'] == 5


def test_vam_cascade_falls_back_to_qwen_on_low_confidence(monkeypatch):
    monkeypatch.delenv('VAM_SCORER_PROVIDER', raising=False)
    monkeypatch.setenv('VAM_INTERN_CONFIDENCE', '0.6')
    calls = []

    def intern(contract_text, scenario_text):
        calls.append('intern')
        return {**VALID, 'confidence': 0.3, 'model': 'Intern-Decision-2B'}, ''

    def local(cfg, contract_text, scenario_text, temperature, max_tokens):
        calls.append('local')
        return {**VALID, 'confidence': 0.7, 'scorer_model': 'qwen2.5:7b'}, ''

    monkeypatch.setattr(pipeline, '_intern_score', intern)
    monkeypatch.setattr(pipeline, '_local_score', local)
    raw, _ = pipeline._score_leaf({}, '合同原文', '情景')
    assert calls == ['intern', 'local']
    assert raw['scorer_model'] == 'qwen2.5:7b'


def test_intern_scorer_option_and_model_name_survives(monkeypatch):
    from vam_sandbox.render import render_markdown_report

    monkeypatch.delenv('VAM_SCORER_PROVIDER', raising=False)
    monkeypatch.setenv('VAM_SCORER_PROVIDER', 'intern')
    inputs = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {**VALID, 'model': 'Intern-Decision-2B', 'evidence': '输入依据：示例输入'}

    def post(url, *, json, timeout):
        inputs.append(json)
        return Response()

    monkeypatch.setattr(pipeline.requests, 'post', post)
    raw, _ = pipeline._score_leaf({}, '合同原文', '该情景的完整路径')
    tree = pipeline.normalize_tree({'branches': [node('事件')]})
    scores, _ = pipeline.compute_scores(tree, {'B1': pipeline.normalize_scorer_result(raw)})
    assert inputs == [{'contract_text': '合同原文', 'scenario_text': '该情景的完整路径'}]
    assert scores[0]['scorer_model'] == 'Intern-Decision-2B'
    markdown = render_markdown_report({'tree': tree})
    assert 'Intern\\-Decision\\-2B' in markdown and '示例输入' not in markdown


def node(name, trigger='unknown', children=None):
    return {
        'id': 'duplicate', 'branch': name, 'premise': name, 'trigger': trigger,
        'evidence_ids': ['E1', 'fabricated'], 'children': children or [],
    }


@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), '-Infinity', -1, 100, 'unusable'])
def test_invalid_scores_are_never_salvaged(value):
    score = pipeline.normalize_scorer_result({**VALID, 'risk_score': value})
    assert score['status'] == 'invalid'
    assert score['invalid_fields'] == ['risk_score']
    assert pipeline._total_from_scores(score) is None


def test_missing_score_stays_unscored_and_never_recommends_an_event():
    tree = pipeline.normalize_tree({'branches': [node('业绩未达标'), node('业绩达标')]})
    ranked, best = pipeline.compute_scores(tree, {'B2': VALID})
    assert [r['total_score'] for r in ranked] == [None, 39.5]
    assert tree['branches'][0]['_risk'] is None
    assert best == {}


def test_initial_bounds_and_conflicting_children():
    invalid = node('相反状态', 'not_met')
    deep = node('第三层')
    raws = [node(f'情景 {i}', 'met', [invalid, node('仍然触发', children=[deep]), node('多余')]) for i in range(4)]
    tree = pipeline.normalize_tree({'branches': raws}, {'E1'})
    leaves = pipeline.iter_leaves_with_path(tree)
    assert len(leaves) == 3
    assert all(len(path) == 2 and leaf['trigger'] == 'met' for path, leaf in leaves)
    assert all(leaf['evidence_ids'] == ['E1'] for _, leaf in leaves)
    assert any('冲突' in item for item in tree['warnings'])
    assert any('上限' in item or '超过' in item for item in tree['warnings'])

    full = pipeline.normalize_tree({'branches': [node(str(i), children=[node('X'), node('Y')]) for i in range(3)]})
    assert len(pipeline.iter_leaves_with_path(full)) == 6


def test_calculations_only_use_confirmed_parameters():
    assert calculate('repurchase', REPURCHASE, 'met')['amount'] == 12_400_000
    assert calculate('repurchase', {**REPURCHASE, 'interest': 'compound'}, 'met')['amount'] == 12_597_120
    assert calculate('repurchase', {**REPURCHASE, 'cap_mode': 'fixed', 'cap': 11_000_000}, 'met')['amount'] == 11_000_000
    assert calculate('repurchase', {}, 'not_met')['amount'] == 0
    assert calculate('repurchase', REPURCHASE, 'unknown')['amount'] is None
    assert '计息方式' in calculate('repurchase', {**REPURCHASE, 'interest': ''}, 'met')['missing']
    assert calculate('repurchase', {**REPURCHASE, 'years': '2.5'}, 'met')['amount'] is None
    for rule, amount in [('add', 15_000), ('offset', 10_000), ('refund', 10_000)]:
        assert calculate('lease_exit', {**LEASE, 'deposit_rule': rule}, 'met')['amount'] == amount
    assert calculate('lease_exit', {**LEASE, 'deposit_rule': 'add', 'early_exit_applies': False}, 'met')['amount'] is None


def test_deepen_preserves_context_ids_and_unaffected_scores(monkeypatch):
    prompts = []
    calls = []
    raw_tree = {'scenario': '合同测试', 'assumptions': ['全局假设'], 'uncertainties': ['待核实'],
                'branches': [node('祖先约束', 'met', [node('当前路径')]), node('未变化情景', 'not_met')]}

    def generate(cfg, system, user, **kwargs):
        prompts.append(user)
        if system == pipeline.DIVERGE_SYSTEM:
            return raw_tree, ''
        return {'branches': [node('甲'), node('乙')]}, ''

    def score(cfg, source, scenario):
        calls.append((source, scenario))
        if '甲' in scenario:
            raise TimeoutError
        return VALID, 'test-score'

    monkeypatch.setattr(pipeline, '_generate_json', generate)
    monkeypatch.setattr(pipeline, '_score_leaf', score)
    original = pipeline.run_sandbox('原始背景', {'model': 'fake'}, {
        'role': 'company', 'objective': 'cash', 'experimental_scoring': True,
        'evidence': [{'id': 'E1', 'filename': 'contract.pdf', 'page': 1, 'quote': '可核验证据'}],
    })
    assert all(text in calls[0][1] for text in ['祖先约束', '当前路径', '全局假设', '待核实'])
    assert all(text in calls[0][0] for text in ['原始背景', '可核验证据', '融资方'])
    result = pipeline.deepen_leaf(original, ['B1', 'B1.1'], {'model': 'fake'})
    assert all(text in prompts[-1] for text in ['原始背景', '可核验证据', '祖先约束', '全局假设'])
    assert [r['leaf_id'] for r in result['ranked']] == ['B1.1.1', 'B1.1.2', 'B2']
    assert [r['status'] for r in result['ranked']] == ['error', 'valid', 'valid']
    assert sum('未变化情景' in scenario for _, scenario in calls) == 1
    assert not original['tree']['branches'][0]['children'][0]['children']
    with pytest.raises(ValueError, match='3 层'):
        pipeline.deepen_leaf(result, ['B1', 'B1.1', 'B1.1.1'], {'model': 'fake'})


def test_api_handoff_compare_and_export(monkeypatch, tmp_path):
    import sys
    from fastapi.testclient import TestClient

    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / 'backend'))
    from app.main import app
    from app.services import vam_evidence

    file_id = 'a' * 32 + '.pdf'
    # Reuse the bundled contract to exercise real PDF quote verification.
    source = root / 'demo_data' / 'contract_gym.pdf'
    (tmp_path / file_id).write_bytes(source.read_bytes())
    monkeypatch.setattr(vam_evidence, 'UPLOAD_DIR', tmp_path)
    import pdfplumber
    with pdfplumber.open(source) as pdf:
        page_no, quote = next((i, line) for i, page in enumerate(pdf.pages, 1)
                              for line in (page.extract_text() or '').splitlines() if line.strip())

    prompts = []

    def generate(cfg, system, user, **kwargs):
        prompts.append(user)
        generated = node('已触发', 'met')
        generated['events'] = ['模型猜测需支付 800 万元']
        generated['action_effects'] = {'A1': '模型猜测需支付 800 万元'}
        return {'scenario': '测试', 'trigger_quote': quote, 'branches': [generated, node('待确认')]}, 'raw trace'

    monkeypatch.setattr(pipeline, '_generate_json', generate)
    client = TestClient(app)
    evidence = {'file_id': file_id, 'filename': 'contract_gym.pdf', 'page': page_no, 'quote': quote}
    actions = [
        {'label': '原条款', 'parameters': REPURCHASE},
        {'label': '提议上限', 'terms': '假设修订已接受',
         'parameters': {**REPURCHASE, 'cap_mode': 'fixed', 'cap': 11_000_000}},
    ]
    request = {'query': '条件计算测试', 'evidence': [evidence], 'role': 'company', 'objective': 'cash',
               'template': 'repurchase', 'actions': actions}
    response = client.post('/api/vam/run', json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['study']['evidence'][0]['quote'] == quote
    assert all(text in prompts[0] for text in [quote, '融资方'])
    assert '提议上限' not in prompts[0]
    assert result['tree']['branches'][0]['evidence_ids'] == ['E1']
    assert result['tree']['trigger_excerpt'] == {'quote': quote, 'evidence_id': 'E1'}
    scenarios = result['comparison']['scenarios']
    assert scenarios[0]['preferred_action_ids'] == ['A2']
    assert scenarios[0]['branch'] == '回购义务已触发'
    assert scenarios[0]['cells'][0]['effect'] == ''
    assert scenarios[1]['trigger'] == 'not_met'
    assert scenarios[1]['preferred_action_ids'] == []
    assert result['best'] == {}
    assert result['comparison']['max_amounts'] == {'A1': 12_400_000, 'A2': 11_000_000}

    run_id = result['run_id']
    changed = client.post('/api/vam/compare', json={
        'run_id': run_id, 'actions': [actions[0], {**actions[1], 'parameters': {
            **actions[1]['parameters'], 'cap': 10_500_000,
        }}], 'triggers': {'B2': 'not_met'},
    })
    assert changed.status_code == 200, changed.text
    next_result = changed.json()
    assert len(prompts) == 1
    assert next_result['comparison']['max_amounts'] == {'A1': 12_400_000, 'A2': 10_500_000}
    assert next_result['tree']['branches'][1]['trigger'] == 'not_met'
    report = client.post('/api/vam/export', json={'result': {'run_id': next_result['run_id']}}).json()['markdown']
    assert '10,500,000.00' in report and '所选合同原文' in report and '推荐路径' not in report
    assert '800 万元' not in report
    original_report = client.post('/api/vam/export', json={'result': {'run_id': run_id}}).json()['markdown']
    assert '11,000,000.00' in original_report
    assert client.post('/api/vam/compare', json={'run_id': run_id, 'actions': actions,
                                                'triggers': {'B1': 'not_met'}}).status_code == 400
    forged = {**request, 'evidence': [{**evidence, 'quote': '伪造引用，不存在于原文件。'}]}
    assert client.post('/api/vam/run', json=forged).status_code == 400
    assert client.post('/api/vam/export', json={'result': {}}).status_code == 404


def test_qualitative_effects_keep_actions_separate(monkeypatch):
    generated = node('对方拒绝修订')
    generated['action_effects'] = {'A1': '按原条款等待履行'}
    monkeypatch.setattr(pipeline, '_generate_json', lambda *args, **kwargs: ({
        'branches': [node('提出延期'), generated],
    }, ''))
    study = {'actions': [{'id': 'A1', 'label': '提出延期', 'terms': '以对方同意为条件', 'parameters': {}}]}
    result = pipeline.run_sandbox('延期条款', {'model': 'fake'}, study)
    assert [branch['branch'] for branch in result['tree']['branches']] == ['对方拒绝修订']
    assert result['comparison']['scenarios'][0]['cells'][0]['effect'] == '按原条款等待履行'
    assert result['comparison']['scenarios'][0]['preferred_action_ids'] == []
