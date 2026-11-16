"""租房合同审查的确定性回归测试（不调用模型）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from rental_review import parse_contract, review_parsed
from rental_review.legal_corpus import retrieve_legal_basis


@pytest.fixture(autouse=True)
def _disable_web_search(monkeypatch):
    monkeypatch.setenv('LEGAL_WEB_SEARCH_ENABLED', '0')

SAMPLE = """住宅租赁合同
出租人（甲方）：张三
承租人（乙方）：李四
第一条 租赁期限：2026年1月1日至2027年1月1日。
第二条 租金：每月5000元，押金5000元，押金在退租时扣除清洁费后退还。
第三条 乙方提前退租的，押金不予退还，并另行支付违约金10000元。
第四条 甲方有权随时收回房屋，无需提前通知。
第五条 租赁期满自动续租六个月，续租租金由甲方决定。
第六条 房屋维修由乙方自行承担，正常损耗也从押金中扣除。
"""


def _parsed(tmp_path: Path, text: str = SAMPLE, name: str = 'lease.txt'):
    path = tmp_path / name
    path.write_text(text, encoding='utf-8')
    return parse_contract(str(path), name)


def test_parser_splits_clauses(tmp_path):
    parsed = _parsed(tmp_path)
    assert parsed.file_type == 'text'
    assert len(parsed.clauses) >= 5
    assert parsed.clauses[0].page == 1
    assert any('押金' in clause.text for clause in parsed.clauses)


def test_rule_review_has_evidence_and_legal_basis(tmp_path):
    result = review_parsed(_parsed(tmp_path), use_llm=False)
    assert result['summary']['risk_level'] in {'high', 'medium', 'low'}
    assert result['risks']
    assert all(risk['quote'].strip() for risk in result['risks'])
    assert all(risk['status'] in {'supported', 'needs_review'} for risk in result['risks'])
    assert any(risk['legal_basis'] for risk in result['risks'])
    assert result['disclaimer']


def test_cross_clause_deposit_penalty(tmp_path):
    result = review_parsed(_parsed(tmp_path), use_llm=False)
    assert any(risk['source'] == 'cross_rule' for risk in result['risks'])
    assert any('押金' in risk['title'] and '违约金' in risk['title'] for risk in result['risks'])


def test_legal_retrieval_is_deterministic():
    hit = retrieve_legal_basis('押金不退 违约金过高 维修费用')
    assert hit
    assert hit[0]['article'].startswith('第')
    assert retrieve_legal_basis('完全无关的天气预报') == []


def test_hong_kong_and_mainland_corpora_do_not_mix():
    mainland = retrieve_legal_basis('押金 违约金 维修 租金调整')
    hongkong = retrieve_legal_basis('租约 按金 不合理 加租', jurisdiction='hongkong')
    assert mainland
    assert hongkong
    assert all(item['jurisdiction'] == 'mainland' for item in mainland)
    assert all(item['jurisdiction'] == 'hongkong' for item in hongkong)
    assert hongkong[0]['source'].startswith('香港法例')


def test_review_result_carries_region(tmp_path):
    result = review_parsed(_parsed(tmp_path), use_llm=False, region='hongkong')
    assert result['region'] == 'hongkong'
    assert result['region_label'] == '中国香港'
    assert '中国香港' in result['disclaimer']
    assert all(
        law['jurisdiction'] == 'hongkong'
        for risk in result['risks']
        for law in risk['legal_basis']
    )


def test_hong_kong_loan_dispute_ecommerce_franchise_law():
    loan = retrieve_legal_basis('利息 贷款 服务费 放债', jurisdiction='hongkong', contract_type='loan')
    dispute = retrieve_legal_basis('仲裁 法院 管辖 争议解决', jurisdiction='hongkong', contract_type='dispute')
    ecommerce = retrieve_legal_basis('虚假宣传 商品说明 电商', jurisdiction='hongkong', contract_type='ecommerce')
    franchise = retrieve_legal_basis('加盟费 特许经营 信息披露', jurisdiction='hongkong', contract_type='franchise')
    assert any(item['article'] == '香港法例第163章第24条' for item in loan)
    assert any('第609章' in item['article'] for item in dispute)
    assert any('第362章' in item['article'] for item in ecommerce)
    assert any('加盟' in item['title'] for item in franchise)


def test_tavily_provider_filters_official_domains(monkeypatch):
    from rental_review import legal_web
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                'results': [
                    {'url': 'https://www.elegislation.gov.hk/hk/cap609'},
                    {'url': 'https://example.com/fake-law'},
                ]
            }

    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse()

    monkeypatch.setenv('LEGAL_WEB_PROVIDER', 'tavily')
    monkeypatch.setenv('TAVILY_API_KEY', 'tvly-test')
    monkeypatch.setattr(legal_web.requests, 'post', fake_post)
    links = legal_web._search_links('仲裁 管辖', 'hongkong', limit=2)
    assert links == ['https://www.elegislation.gov.hk/hk/cap609']
    assert len(calls) == 1


def test_html_decoding_handles_gbk():
    from rental_review.legal_web import _decode_html

    raw = '<html><meta charset="gb2312">广州市租赁合同</html>'.encode('gb18030')
    text = _decode_html(raw, 'utf-8')
    assert '广州市租赁合同' in text
    assert '锟' not in text


def test_judge_retries_with_compact_payload(monkeypatch):
    from rental_review import pipeline

    calls = []

    def fake_safe_json(system, user, max_tokens=2800, model=None):
        calls.append((system, user, max_tokens))
        if len(calls) == 1:
            return None, 'invalid json'
        return {'judgments': [{'risk_id': 'R1', 'status': 'needs_review', 'reason': 'test'}]}, 'ok'

    monkeypatch.setattr(pipeline, '_safe_json', fake_safe_json)
    result = pipeline._judge_with_llm([{
        'risk_id': 'R1',
        'title': '测试风险',
        'quote': '测试条款',
        'explanation': '测试解释',
        'legal_basis': [{'article': '第一条', 'title': '测试', 'summary': '摘要', 'verified': False}],
        'evidence_verified': True,
    }])
    assert result is not None
    assert len(calls) == 2
    assert '重试' in calls[1][0]
    assert '"risk_id": "R1"' in calls[1][1]


def test_consumer_procurement_labor_rules(tmp_path):
    consumer = '''健身培训服务合同
第一条 会员卡有效期一年，过期作废。
第二条 退课需扣除30%手续费，已上课时按原价计算。
第三条 课程自动续费，无需另行通知。
第四条 门店关闭时经营者有权调整为其他门店，消费者不得异议。
'''
    procurement = '''设备采购合同
第一条 设备交付后由采购方在3日内验收。
第二条 验收合格后支付尾款。
第三条 逾期交付按合同总额的0.01%支付违约金。
第四条 质保期为一年，质保范围另行通知。
'''
    labor = '''劳动合同
第一条 合同期限三年，试用期六个月。
第二条 月工资已包含加班费，不再另行支付。
第三条 员工自愿放弃社会保险。
第四条 离职后两年内受竞业限制。
'''
    consumer_result = review_parsed(_parsed(tmp_path, consumer, 'consumer.txt'), use_llm=False, contract_type='consumer')
    procurement_result = review_parsed(_parsed(tmp_path, procurement, 'procurement.txt'), use_llm=False, contract_type='procurement')
    labor_result = review_parsed(_parsed(tmp_path, labor, 'labor.txt'), use_llm=False, contract_type='labor')

    assert consumer_result['contract_type_label'] == '健身/培训服务'
    assert any('退款' in risk['title'] or '续费' in risk['title'] for risk in consumer_result['risks'])
    assert any('验收' in risk['title'] for risk in procurement_result['risks'])
    assert any('试用期' in risk['title'] for risk in labor_result['risks'])
    assert any('竞业' in risk['title'] for risk in labor_result['risks'])


def test_risks_sorted_high_first(tmp_path):
    result = review_parsed(_parsed(tmp_path), use_llm=False)
    order = {'high': 0, 'medium': 1, 'low': 2}
    severities = [order[risk['severity']] for risk in result['risks']]
    assert severities == sorted(severities)
    assert result['summary']['total_risks'] == len(result['risks'])


def test_auto_contract_classification(tmp_path):
    loan = '''借款合同
第一条 借款本金100万元，服务费5万元。
第二条 逾期按日万分之五计收罚息。
第三条 保证人承担连带保证责任。
'''
    result = review_parsed(_parsed(tmp_path, loan, 'auto_loan.txt'), use_llm=False, contract_type='auto')
    assert result['contract_type_requested'] == 'auto'
    assert result['contract_type'] == 'loan'
    assert result['classification']['source'] == 'rules'
    assert result['classification']['confidence'] > 0
    assert result['classification']['known_type'] is True


def test_unknown_contract_type_marked_unknown(tmp_path):
    text = '''神秘服务协议
第一条 双方就未来合作事项作出安排。
第二条 具体内容另行协商。
'''
    result = review_parsed(_parsed(tmp_path, text, 'unknown.txt'), use_llm=False, contract_type='auto')
    assert result['contract_type'] == 'other'
    assert result['classification']['known_type'] is False
    assert result['classification']['confidence'] < 0.6


def test_other_contract_uses_generic_rules(tmp_path):
    text = '''其他服务协议
第一条 甲方有权单方变更服务内容，无需提前通知。
第二条 乙方应支付预付款，合同解除时不予退还。
第三条 交付后三日内验收。
第四条 违约金按合同总额的 30% 计算。
'''
    result = review_parsed(
        _parsed(tmp_path, text, 'other.txt'),
        use_llm=False,
        contract_type='other',
    )
    assert result['contract_type'] == 'other'
    assert result['contract_type_label'] == '其他/未识别'
    assert result['classification']['known_type'] is False
    risk_types = {risk['risk_type'] for risk in result['risks']}
    assert 'unilateral_change' in risk_types
    assert 'payment' in risk_types or 'penalty' in risk_types


def test_progress_callback_reports_stages(tmp_path):
    events = []
    result = review_parsed(
        _parsed(tmp_path),
        use_llm=False,
        progress=lambda stage, status, detail: events.append((stage, status)),
    )
    stages = {stage for stage, _ in events}
    assert {'classify', 'rules', 'cross', 'legal', 'judge', 'done'} <= stages
    assert result['summary']['total_risks'] > 0


def test_review_result_cache(tmp_path, monkeypatch):
    from backend.app.services import rental_review_service as service
    monkeypatch.setattr(service, 'CACHE_DIR', tmp_path / 'review-cache')
    monkeypatch.setenv('REVIEW_CACHE_ENABLED', '1')
    source = tmp_path / 'contract.txt'
    source.write_text('测试合同', encoding='utf-8')
    calls = []

    def fake_review(path, filename, use_llm=True, region='mainland', contract_type='rental', progress=None):
        calls.append(filename)
        return {'filename': filename, 'contract_type': contract_type, 'risks': []}

    monkeypatch.setattr(service, 'review_contract', fake_review)
    first = service.run(str(source), 'a.txt', use_llm=False, region='hongkong', contract_type='labor')
    second = service.run(str(source), 'b.txt', use_llm=False, region='hongkong', contract_type='labor')
    assert first['cache_hit'] is False
    assert second['cache_hit'] is True
    assert second['filename'] == 'b.txt'
    assert len(calls) == 1


def test_low_risk_skips_web_search():
    from rental_review.pipeline import _select_web_indexes
    candidates = [
        {'severity': 'high'},
        {'severity': 'low'},
        {'severity': 'medium'},
        {'severity': 'low'},
    ]
    web_queries = {1: 'high query', 2: 'low query', 3: 'medium query', 4: 'low query'}
    assert _select_web_indexes(candidates, web_queries, skip_low=True) == [1, 3]
    assert _select_web_indexes(candidates, web_queries, skip_low=False) == [1, 3, 2, 4]
    assert _select_web_indexes(candidates, web_queries, skip_low=False, low_max=1) == [1, 3, 2]


def test_loan_ecommerce_franchise_dispute_rules(tmp_path):
    loan = '''借款合同
第一条 借款本金100万元，服务费5万元，利息预先从本金中扣除。
第二条 逾期按日万分之五计收罚息。
第三条 任一笔其他合同违约即构成交叉违约。
第四条 出借人有权宣布借款加速到期。
第五条 保证人承担连带保证责任。
第六条 提前还款需支付违约金。
'''
    ecommerce = '''电商服务合同
第一条 七天无理由退货，但已拆封商品不适用。
第二条 退货运费由消费者承担。
第三条 争议由平台所在地法院管辖。
第四条 会员自动续费，扣费前不另行通知。
第五条 商品图片仅供参考，以实物为准。
'''
    franchise = '''加盟合同
第一条 加盟费10万元，保证金5万元，均不予退还。
第二条 品牌方有权调整加盟区域。
第三条 续约需重新支付加盟费。
第四条 加盟商退出时按品牌方规定结算。
第五条 品牌方有权调整供货价。
第六条 加盟前不提供信息披露文件。
'''
    dispute = '''合同争议条款
第一条 争议提交仲裁委员会仲裁。
第二条 同时约定由合同签订地法院诉讼。
第三条 通知寄出即视为送达。
第四条 败诉方承担律师费和保全费。
'''
    loan_result = review_parsed(_parsed(tmp_path, loan, 'loan.txt'), use_llm=False, contract_type='loan')
    ecommerce_result = review_parsed(_parsed(tmp_path, ecommerce, 'ecommerce.txt'), use_llm=False, contract_type='ecommerce')
    franchise_result = review_parsed(_parsed(tmp_path, franchise, 'franchise.txt'), use_llm=False, contract_type='franchise')
    dispute_result = review_parsed(_parsed(tmp_path, dispute, 'dispute.txt'), use_llm=False, contract_type='dispute')

    assert loan_result['contract_type_label'] == '借款/担保'
    assert any('砍头息' in risk['title'] or '费用' in risk['title'] for risk in loan_result['risks'])
    assert any('交叉违约' in risk['title'] for risk in loan_result['risks'])
    assert ecommerce_result['contract_type_label'] == '消费/电商'
    assert any('退货' in risk['title'] for risk in ecommerce_result['risks'])
    assert any('管辖' in risk['title'] for risk in ecommerce_result['risks'])
    assert franchise_result['contract_type_label'] == '加盟/特许经营'
    assert any('加盟费' in risk['title'] for risk in franchise_result['risks'])
    assert any('区域' in risk['title'] for risk in franchise_result['risks'])
    assert dispute_result['contract_type_label'] == '争议解决'
    assert any('仲裁' in risk['title'] or '冲突' in risk['title'] for risk in dispute_result['risks'])
    assert any('管辖' in risk['title'] for risk in dispute_result['risks'])


def test_judge_only_high_and_medium_by_default():
    from rental_review.pipeline import _judgeable_risks

    risks = [
        {'risk_id': 'R1', 'severity': 'high'},
        {'risk_id': 'R2', 'severity': 'medium'},
        {'risk_id': 'R3', 'severity': 'low'},
    ]
    assert [risk['risk_id'] for risk in _judgeable_risks(risks)] == ['R1', 'R2']


def test_extract_json_repairs_duplicate_object_braces():
    from rental_review.pipeline import _extract_json

    malformed = '''{
      "facts": {"party_a": "甲"},
      "risks": [
        {
          {
            "clause_ids": ["C1"],
            "title": "测试风险",
            "quote": "测试条款",
            "explanation": "测试解释",
            "suggestion": "测试建议",
            "severity": "high"
          }
        }
      ]
    }'''
    data = _extract_json(malformed)
    assert len(data['risks']) == 1
    assert data['risks'][0]['title'] == '测试风险'


def test_hong_kong_employment_local_law():
    from rental_review.legal_corpus import retrieve_legal_basis

    notice = retrieve_legal_basis('通知期 解雇 终止', jurisdiction='hongkong', contract_type='labor')
    deduction = retrieve_legal_basis('扣工资 罚款 押金', jurisdiction='hongkong', contract_type='labor')
    dismissal = retrieve_legal_basis('即时解雇 无通知', jurisdiction='hongkong', contract_type='labor')
    assert any('第57章第6条' in item['article'] for item in notice)
    assert any('第57章第32条' in item['article'] for item in deduction)
    assert any('第57章第9条' in item['article'] for item in dismissal)
