"""租房合同风险审查多 Agent 流水线。

流程：
1. 合同解析：PDF/DOCX/TXT → 按页文本 → 条款片段
2. 条款理解 Agent：抽取当事人、租金、押金、期限、续租、解除、违约金、维修等事实
3. 风险审查 Agent：提出风险候选（必须带原文 quote）
4. 法律检索 Agent：在本地《民法典》条文要旨库中做确定性检索
5. 交叉验证 Agent：检查押金/违约金/解除权/维修等条款组合
6. Judge Agent：逐条质疑证据与法律依据，标记 supported / needs_review / rejected

约束：
- 模型只提出候选，不直接决定法条；
- 每条风险必须能回查到合同 quote；
- 没有法条依据时标记“需要人工复核”，不硬下结论；
- 只适用于中国内地租房合同，输出为风险提示，不是法律意见。
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import json5
from qwen_agent.llm import get_chat_model

from .legal_corpus import retrieve_legal_basis
from .legal_web import search_official
from .parser import Clause, ParsedContract, normalize_text, parse_contract

DISCLAIMER = '本结果仅用于签约前风险提示，不构成法律意见；具体权利义务请结合完整合同并咨询执业律师。'
REGIONS = {
    'mainland': '中国内地',
    'hongkong': '中国香港',
}
DEFAULT_REGION = 'mainland'
CONTRACT_TYPES = {
    'rental': '住宅租赁',
    'consumer': '健身/培训服务',
    'procurement': '采购/买卖',
    'labor': '劳动合同',
    'loan': '借款/担保',
    'ecommerce': '消费/电商',
    'franchise': '加盟/特许经营',
    'dispute': '争议解决',
}
DEFAULT_CONTRACT_TYPE = 'rental'

ANALYZE_SYSTEM = """你是「签之前」的合同条款分析 Agent，服务对象是准备签约的普通消费者或中小企业。
本次审查合同类型：{contract_type}；法域：{region}。只适用该法域法律，不要混用其他地区规则。你会收到按页、按条切分的合同文本，每条有 [C1] 这样的编号。

请完成两件事：
A. 抽取合同事实 facts：当事人、价款/费用、押金/定金、期限、续约、解除、违约金、验收/交付、维修/质保、其他费用。
B. 提出风险候选 risks：找出对用户不利、含糊、矛盾或可能无效的条款。
   如果合同条款足够，请提出 **5–8 条不同风险**，覆盖不同条款和高/中/低等级；不要只输出 1–2 条。
   如果材料确实不足，可以少于 5 条，并在 facts.missing 中说明缺少什么。

严格要求：
1. 每条风险必须给出 clause_ids（来自输入的 C 编号）和 quote（从对应条款逐字复制的短句，20-120 字）。
2. 不要引用具体法条，不要下“违法/无效”的法律结论；法律依据由后端按法域和合同类型检索。
3. 不要编造合同没有的内容；信息不足写进 missing。
4. 区分“风险”与“需要确认的信息”。
5. 输出严格 JSON，不要 Markdown、不要解释文字。
6. 保持简洁：每条 explanation 和 suggestion 各不超过 80 字，最多 8 条风险。

JSON schema：
{
  "facts": {
    "party_a": "", "party_b": "", "price": "", "deposit": "",
    "term": "", "renewal": "", "termination": "", "penalty": "",
    "delivery": "", "repair": "", "refund": "", "other_fees": "", "missing": []
  },
  "risks": [
    {
      "clause_ids": ["C1"],
      "title": "一句话风险标题",
      "risk_type": "deposit|penalty|termination|renewal|repair|rent|format_clause|other",
      "quote": "逐字原文",
      "explanation": "为什么对用户有风险",
      "suggestion": "签约前怎么问/怎么改",
      "severity": "high|medium|low",
      "legal_keywords": ["押金", "违约金"],
      "confidence": 0.0
    }
  ],
  "cross_clause_observations": [
    {"clause_ids": ["C1", "C2"], "title": "条款组合风险", "explanation": "组合后可能产生的额外负担"}
  ]
}
"""

JUDGE_SYSTEM = """你是「签之前」的合同审查 Judge Agent，任务是质疑风险 Agent 的结论，而不是替它补充新风险。
你会收到：合同条款、风险候选、后端检索到的法律依据。

逐条判断：
1. quote 是否真的来自对应条款？
2. 风险解释是否超出原文？是否把“需要确认”说成“确定违法”？
3. 法律依据是否与风险类型相关？没有依据时是否应转人工复核？
4. 是否存在过度推断、重复、把正常商业条款误报为风险？

输出严格 JSON：
{
  "judgments": [
    {
      "risk_id": "R1",
      "status": "supported|needs_review|rejected",
      "reason": "一句话说明",
      "confidence": 0.0
    }
  ]
}
只能评价已有 risk_id，不能新增风险。没有足够证据时必须用 needs_review。
"""

CLASSIFY_SYSTEM = """你是「签之前」的合同分类 Agent。请根据合同标题、条款和关键词判断合同类型与法律领域。
只输出严格 JSON，不要 Markdown。

可选合同类型：
- rental：住宅租赁
- consumer：健身/培训/消费服务
- procurement：采购/买卖/工程
- labor：劳动合同
- loan：借款/担保
- ecommerce：消费/电商
- franchise：加盟/特许经营
- dispute：争议解决条款（如果合同主要是争议解决条款）

输出：
{
  "contract_type": "rental|consumer|procurement|labor|loan|ecommerce|franchise|dispute",
  "confidence": 0.0,
  "legal_domains": ["例如：租赁合同", "押金", "违约责任"],
  "jurisdiction_hint": "mainland|hongkong|unknown",
  "reason": "一句话说明判断依据"
}
如果无法判断，contract_type 填 rental 之外的值会失败，所以请选择最接近的类型并降低 confidence。
"""


def _llm_cfg(model: Optional[str] = None) -> Dict[str, Any]:
    return {
        'model': model or os.getenv('OLLAMA_MODEL', 'qwen2.5:7b'),
        'model_server': os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434/v1'),
        'api_key': os.getenv('OLLAMA_API_KEY', 'ollama'),
        'generate_cfg': {'max_tokens': 2800, 'temperature': 0.1, 'max_input_tokens': 12000},
    }


def _chat(system: str, user: str, max_tokens: int = 2800, model: Optional[str] = None, json_mode: bool = False) -> str:
    cfg = _llm_cfg(model)
    cfg['generate_cfg'] = {**cfg['generate_cfg'], 'max_tokens': max_tokens}
    if json_mode and os.getenv('OLLAMA_JSON_MODE', '1').strip().lower() not in {'0', 'false', 'no'}:
        cfg['generate_cfg']['response_format'] = {'type': 'json_object'}
    llm = get_chat_model(cfg)
    output = llm.chat(messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': user}], stream=False)
    return output[-1]['content']


def _repair_json_text(text: str) -> str:
    """修复模型常见的 JSON 小毛病：重复 `{`、错位的 `]}`、尾逗号。"""
    text = re.sub(r'(\[\s*)\{\s*\{', r'\1{', text)
    text = re.sub(r'(,\s*)\{\s*\{', r'\1{', text)
    text = re.sub(r'\}\s*\]\s*\}\s*(\],)', r'}\1', text)
    text = re.sub(r'\}\s*\}\s*\]', '}]', text)
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    return text


def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or '').strip()
    fences = re.findall(r'```(?:json)?\s*(.*?)```', text, re.S)
    if fences:
        text = fences[0].strip()
    start, end = text.find('{'), text.rfind('}')
    if start == -1 or end <= start:
        raise ValueError('模型输出中没有 JSON 对象')
    payload = _repair_json_text(text[start:end + 1])
    return json5.loads(payload)


def _safe_json(system: str, user: str, max_tokens: int = 2800, model: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], str]:
    try:
        raw = _chat(system, user, max_tokens, model, json_mode=True)
        return _extract_json(raw), raw
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def _contract_prompt(parsed: ParsedContract, contract_type_label: str = '') -> str:
    lines = [
        f'文件：{parsed.filename}',
        f'合同类型：{contract_type_label or "未指定"}',
        f'总页数：{len(parsed.pages)}',
        '条款：',
    ]
    for clause in parsed.clauses:
        lines.append(f'[{clause.clause_id}] 第{clause.page}页\n{clause.text[:1200]}')
    return '\n\n'.join(lines)


def _sentence_for(text: str, keyword: str) -> str:
    for sentence in re.split(r'(?<=[。；;！？!?])', text):
        if keyword in sentence and sentence.strip():
            return sentence.strip()[:180]
    return text.strip()[:180]


def _find_clause(parsed: ParsedContract, clause_id: str) -> Optional[Clause]:
    return next((c for c in parsed.clauses if c.clause_id == clause_id), None)


def _verify_quote(parsed: ParsedContract, clause_ids: List[str], quote: str) -> Tuple[Optional[Clause], str, bool]:
    q = normalize_text(quote)
    candidates = [c for c in parsed.clauses if c.clause_id in clause_ids] or parsed.clauses
    for clause in candidates:
        if q and q in normalize_text(clause.text):
            return clause, quote.strip(), True
    for clause in parsed.clauses:
        if q and q in normalize_text(clause.text):
            return clause, quote.strip(), True
    # quote 不可逐字回查时，退回该条款的原文片段，但明确标记未通过核验
    clause = candidates[0] if candidates else parsed.clauses[0]
    return clause, _sentence_for(clause.text, quote[:6] or clause.text[:6]), False


def _fallback_facts(parsed: ParsedContract) -> Dict[str, Any]:
    text = parsed.text
    def grab(pattern: str) -> str:
        m = re.search(pattern, text)
        return m.group(0) if m else ''
    return {
        'party_a': grab(r'(?:出租人|業主|甲方|用人单位|用人單位|僱主|雇主|借款人|采购方|採購方|特许人|特許人|经营者|經營者)[：:]\s*[^\n，,；;]{1,30}'),
        'party_b': grab(r'(?:承租人|租客|乙方|劳动者|勞動者|僱員|雇员|出借人|供应方|供應方|被特许人|被特許人|消费者|消費者)[：:]\s*[^\n，,；;]{1,30}'),
        'price': grab(r'(?:租金|月租|价款|價款|工资|工資|本金|服务费|服務費|加盟费|加盟費|课程费|課程費|课时费|課時費|会员费|會員費)[^\n。；;]{0,60}'),
        'deposit': grab(r'(?:押金|按金|保证金|保證金|定金)[^\n。；;]{0,60}'),
        'term': grab(r'(?:租赁期限|租期|合同期限|合約期限|服务期限|服務期限|课程有效期|課程有效期|会员卡有效期|會員卡有效期|借款期限)[^\n。；;]{0,60}'),
        'renewal': grab(r'(?:续租|續租|续约|續約|自动续|自動續)[^\n。；;]{0,60}'),
        'termination': grab(r'(?:解除|收回房屋|提前终止|提前終止|退课|退課|解僱)[^\n。；;]{0,60}'),
        'penalty': grab(r'(?:违约金|違約金|违约赔偿|違約賠償|罚息|罰息|罰款)[^\n。；;]{0,60}'),
        'delivery': grab(r'(?:交付|验收|驗收|送货|送貨)[^\n。；;]{0,60}'),
        'repair': grab(r'(?:维修|維修|修理|质保|質保|保修)[^\n。；;]{0,60}'),
        'refund': grab(r'(?:退款|退费|退費|退货|退貨|退课|退課)[^\n。；;]{0,60}'),
        'other_fees': grab(r'(?:物业费|物業費|管理费|管理費|水电费|水電費|清洁费|清潔費|维修费|維修費|手续费|手續費)[^\n。；;]{0,60}'),
        'missing': [],
    }


def _normalize_facts(facts: Dict[str, Any]) -> Dict[str, Any]:
    """兼容旧版模型返回的 landlord/tenant/rent 等字段。"""
    mapping = {
        'landlord': 'party_a',
        'tenant': 'party_b',
        'rent': 'price',
        'payment': 'price',
    }
    normalized = dict(facts)
    for old, new in mapping.items():
        if old in normalized and not normalized.get(new):
            normalized[new] = normalized.pop(old)
    return normalized


def _rule_risk_candidates(parsed: ParsedContract, contract_type: str = 'rental') -> List[Dict[str, Any]]:
    text = parsed.text

    def has(pattern: str) -> bool:
        return bool(re.search(pattern, text))

    rules: List[tuple] = []

    if contract_type == 'rental':
        if '押金' in text and any(k in text for k in ('不予退还', '不退还', '扣除全部', '没收', '押金不退')):
            rules.append(('押金退还条件不明确', 'deposit', '押金', 'high',
                          '押金能否退、何时退、扣多少没有写清，退租时容易产生争议。',
                          '要求写明押金退还时间、可扣除项目和凭证。'))
        if '押金' in text and not has(r'(押金|保证金)[^\n。；;]{0,60}(日内|工作日|期限内|退还时间)'):
            rules.append(('押金退还期限未约定', 'deposit', '押金', 'medium',
                          '合同没有写清退租后多少日内退还押金，容易拖延。',
                          '要求写明退还期限、逾期利息和扣款凭证。'))
        if '押金' in text and any(k in text for k in ('扣除', '扣款')) and not any(k in text for k in ('凭证', '明细', '标准')):
            rules.append(('押金扣除项目/标准不明确', 'deposit', '扣除', 'high',
                          '押金可以扣除，但没有列出可扣项目、计算标准或凭证要求。',
                          '要求列明可扣除项目、金额标准和凭证。'))
        if '违约金' in text and has(r'违约金[^\n。；;]{0,30}\d'):
            rules.append(('违约金可能过高', 'penalty', '违约金', 'high',
                          '违约金金额或计算基数不明确，可能与实际损失不匹配。',
                          '要求写明违约金计算基数、上限和实际损失抵扣方式。'))
        if '提前退租' in text and '违约金' in text:
            rules.append(('提前退租违约责任较重', 'penalty', '提前退租', 'high',
                          '提前退租同时涉及押金和违约金，实际退出成本可能高于预期。',
                          '要求写明提前通知期、违约金上限和押金抵扣顺序。'))
        if '转租' in text and not any(k in text for k in ('同意', '书面同意')):
            rules.append(('转租条件不明确', 'sublease', '转租', 'medium',
                          '合同提到转租，但没有写明是否需房东书面同意及条件。',
                          '要求写明转租同意方式、条件和费用。'))
        if '解除' in text and not has(r'(提前|通知).{0,16}(解除|终止)'):
            rules.append(('解除程序/通知期不明确', 'termination', '解除', 'high',
                          '合同允许解除，但没有约定通知期、通知方式和结算流程。',
                          '要求写明解除通知期、送达方式和押金/费用结算。'))
        renewal_has_notice = has(r'(提前|通知).{0,16}(续租|续约|不续|不租)')
        if ('自动续租' in text or '自动续约' in text or ('续租' in text and not renewal_has_notice)):
            rules.append(('自动续租/续约条件不明确', 'renewal', '续租', 'medium',
                          '未明确通知期、续租租金或取消方式，可能被动续租。',
                          '要求补充提前通知期、续租租金上限和取消方式。'))
        if any(k in text for k in ('单方解除', '随时收回', '无条件收回', '有权收回')):
            rules.append(('出租人单方解除权过大', 'termination', '单方解除', 'high',
                          '房东可在缺少通知、补偿或合理理由的情况下收回房屋。',
                          '要求限定解除情形，并约定提前通知和搬迁补偿。'))
        repair_shifted = has(r'(乙方|承租人)[^。；;\n]{0,40}(承担|负责)[^。；;\n]{0,12}(维修|修理|维修费)') or \
            has(r'(维修|修理)[^。；;\n]{0,20}(由乙方|由承租人|乙方承担|承租人承担)') or \
            ('自行维修' in text and '甲方' not in text)
        if '维修' in text and repair_shifted and not has(r'(甲方|出租人)[^。；;\n]{0,20}(负责|承担)[^。；;\n]{0,12}(维修|修理)'):
            rules.append(('维修责任可能转嫁给租客', 'repair', '维修', 'medium',
                          '维修义务和费用承担不清，正常损耗可能被从押金中扣除。',
                          '要求列明维修责任、响应时限和费用承担。'))
        if any(k in text for k in ('涨租', '租金调整', '租金上调', '上调租金')):
            rules.append(('租金调整/额外费用不明确', 'rent', '涨租', 'medium',
                          '租金或附加费用的调整条件、上限和计算方式不明确。',
                          '要求写明调整周期、上限和提前通知期。'))

    elif contract_type == 'consumer':
        if any(k in text for k in ('不退', '手续费', '扣除', '违约金')) and any(k in text for k in ('退款', '退费', '退课')):
            rules.append(('退款/退费扣费条件不明确', 'refund', '退款', 'high',
                          '退款条件、手续费比例和计算基数不清，退课时可能被高额扣费。',
                          '要求写明退款计算公式、已上课时如何计价、手续费上限。'))
        if ('自动续费' in text or '自动续课' in text) and not has(r'(提前|通知).{0,16}(取消|关闭|续费|续课)'):
            rules.append(('自动续费/续课缺少取消机制', 'renewal', '自动续费', 'high',
                          '未明确取消方式、通知期和扣费时间，可能被动续费。',
                          '要求写明取消入口、提前通知期和扣费前提醒。'))
        if any(k in text for k in ('有效期', '过期作废', '逾期作废')):
            rules.append(('课程/会员有效期与过期处理不明确', 'term', '有效期', 'medium',
                          '课时或会员权益可能过期作废，但合同没有写清延期、退费或补偿规则。',
                          '要求写明有效期、延期条件和未使用课时的处理。'))
        for marker in ('门店关闭', '有权调整', '转店', '服务变更', '更换教练'):
            if marker in text:
                rules.append(('经营者可单方变更服务', 'service_change', marker, 'high',
                              '门店、课程或教练变更可能影响履约，但消费者缺少退出或补偿选择。',
                              '要求约定变更通知、替代方案和消费者解除/退款权。'))
        if any(k in text for k in ('不得转让', '不得退卡', '不得转课')):
            rules.append(('会员/课程转让退卡受限', 'transfer', '不得转让' if '不得转让' in text else '不得退卡', 'medium',
                          '会员卡或课程可能不得转让、不得退卡，消费者退出成本较高。',
                          '要求写明转让/退卡条件、手续费和余额处理。'))
        if any(k in text for k in ('概不负责', '人身伤害', '免责', '风险自负')):
            rules.append(('免责条款可能过宽', 'liability', '免责', 'high',
                          '经营者可能通过免责条款排除人身伤害或服务质量责任。',
                          '要求保留经营者因过错造成损害的责任，并明确保险安排。'))
        if '定金' in text and any(k in text for k in ('不退', '不予退还', '没收')):
            rules.append(('定金不退条件不明确', 'deposit', '定金', 'high',
                          '定金与订金、预付款未区分，取消时可能全部没收。',
                          '要求区分定金/订金/预付款，并写明退还条件。'))
        if any(k in text for k in ('培训贷', '分期贷款', '贷款', '金融')):
            rules.append(('预付课程绑定贷款', 'loan', '贷款', 'high',
                          '课程退款与贷款还款可能脱钩，停止上课后仍可能背负贷款。',
                          '要求写明退款时贷款如何处理、由谁结清。'))

    elif contract_type == 'procurement':
        if '验收' in text and not has(r'验收[^\n。；;]{0,30}(标准|期限|日内|工作日)'):
            rules.append(('验收标准/期限不明确', 'acceptance', '验收', 'high',
                          '验收标准、验收期限和逾期未验收的后果不清，尾款和索赔容易争议。',
                          '要求写明验收指标、期限、异议方式和视为验收规则。'))
        if '尾款' in text and '验收' in text:
            rules.append(('尾款支付与验收绑定不清', 'payment', '尾款', 'medium',
                          '尾款支付节点与验收结果的关系不清，可能出现已验收仍不付款或未验收先付款。',
                          '要求写明验收合格后多少日付款、发票和质保金安排。'))
        if any(k in text for k in ('逾期', '迟延', '延期')) and '违约金' in text:
            rules.append(('逾期交付/付款责任不足', 'delay', '逾期', 'medium',
                          '逾期违约责任、计算基数和上限不清，实际损失可能无法覆盖。',
                          '要求写明逾期日费率、起算点和解除权。'))
        if any(k in text for k in ('质保', '保修')) and not has(r'(质保|保修)[^\n。；;]{0,30}(年|月|日)'):
            rules.append(('质保期/保修范围不明确', 'warranty', '质保', 'medium',
                          '质保期限、范围和响应时间不清，设备故障时难以主张。',
                          '要求写明质保期、保修范围、响应时限和备件供应。'))
        if any(k in text for k in ('价格调整', '涨价', '最低采购', '采购量')):
            rules.append(('价格调整或最低采购承诺风险', 'price', '价格调整', 'high',
                          '价格调整机制、最低采购量和未达标责任可能造成额外成本。',
                          '要求写明调价公式、触发条件、最低采购量和退出机制。'))
        if any(k in text for k in ('单方解除', '随时解除', '无条件解除')):
            rules.append(('单方解除权缺少限制', 'termination', '单方解除', 'high',
                          '一方可随时解除，但未约定通知期、已履行部分结算和损失补偿。',
                          '要求限定解除情形，并约定通知期和结算方式。'))
        for marker in ('预付款', '首付款', '定金'):
            if marker in text:
                rules.append(('预付款/首付款退款条件不明确', 'payment', marker, 'high',
                              '合同可能要求先付款，但未写清未交付、验收不合格或解除时如何退款。',
                              '要求写明预付款比例、退款条件和担保方式。'))
                break
        if '知识产权' in text and not re.search(r'知识产权[^\n。；;]{0,40}(归属|许可|使用)', text):
            rules.append(('知识产权归属/许可不清', 'ip', '知识产权', 'medium',
                          '采购或定制成果的知识产权归属、许可范围不清，后续使用可能受限。',
                          '要求写明成果归属、许可范围和第三方素材责任。'))

    elif contract_type == 'labor':
        def kw(*options: str) -> str:
            return next((item for item in options if item in text), options[-1])

        probation = kw('试用期', '試用期')
        if probation in text and re.search(r'(?:试用期|試用期)[^\n。；;]{0,20}(?:六个月|六個月|6个月|6個月|一年|超过|超過)', text):
            rules.append(('试用期长度或次数可能超限', 'probation', probation, 'high',
                          '试用期长度、工资或约定次数可能不符合法定上限。',
                          '核对劳动合同期限与试用期上限，避免重复试用。'))
        if '加班' in text and any(k in text for k in ('包含', '已包含', '不另计', '不支付', '不另行支付')):
            rules.append(('加班费被打包或排除', 'overtime', '加班', 'high',
                          '工资可能被写成已包含加班费，实际加班无法获得额外报酬。',
                          '要求写明工时制度、加班审批和加班费计算。'))
        social = kw('社保', '社会保险', '社會保險', '強積金', '强积金')
        if social in text and any(k in text for k in ('不缴', '不繳', '自行', '补贴', '補貼', '放弃', '放棄', '不為', '不供款')):
            rules.append(('社保/强积金缴纳义务被排除', 'social_insurance', social, 'high',
                          '用人单位可能要求劳动者自行缴纳或放弃社保/强积金，影响医疗、工伤和养老权益。',
                          '要求依法缴纳社保/强积金，并明确缴费基数和地点。'))
        noncompete = kw('竞业限制', '競業限制', '竞业', '競業')
        has_compensation = any(k in text for k in ('补偿', '補償', '经济补偿', '經濟補償'))
        no_compensation = any(k in text for k in ('無須', '无须', '不支付', '不予補償', '不予补偿', '沒有補償', '没有补偿'))
        if noncompete in text and (not has_compensation or no_compensation):
            rules.append(('竞业限制缺少经济补偿', 'non_compete', noncompete, 'high',
                          '限制劳动者离职后就业，却没有约定补偿标准或支付方式。',
                          '要求写明竞业范围、期限和按月补偿标准。'))
        penalty = kw('罚款', '罰款', '押金', '按金', '扣工资', '扣工資', '扣款')
        if penalty in text:
            rules.append(('罚款/押金/扣工资条款', 'penalty', penalty, 'high',
                          '用人单位可能以罚款、押金或扣工资方式转嫁经营风险。',
                          '要求删除罚款/押金条款，明确工资扣减的法定情形。'))
        termination = kw('单方解除', '單方解除', '随时解除', '隨時解除', '无条件解除', '無條件解除', '即时解雇', '即時解僱')
        if termination in text:
            rules.append(('单方解除权缺少限制', 'termination', termination, 'high',
                          '用人单位可单方解除，但未约定通知、补偿和解除情形。',
                          '要求限定解除情形，并写明通知期和经济补偿。'))
        working = kw('996', '单休', '單休', '每周六天', '每週六天', '每周工作六天', '每週工作六天', '大小周')
        if working in text:
            rules.append(('工作时间安排可能超限', 'working_time', working, 'medium',
                          '工作时间、休息休假和加班安排可能违反法定工时制度。',
                          '要求写明工时制度、休息日和加班安排。'))

    elif contract_type == 'loan':
        fee_keyword = next((k for k in ('服务费', '手续费', '管理费', '砍头息', '预先扣除') if k in text), None)
        if fee_keyword:
            rules.append(('利息外费用/砍头息不明确', 'fee', fee_keyword, 'high',
                          '借款可能通过服务费、手续费或预先扣息抬高实际成本。',
                          '要求列明综合年化成本、所有费用和实际到账金额。'))
        if any(k in text for k in ('利息', '利率')) and not any(k in text for k in ('年化', '年利率', '实际利率')):
            rules.append(('利率口径不明确', 'interest', '利息' if '利息' in text else '利率', 'medium',
                          '合同只写利息，没有写清年化/实际利率和计息方式。',
                          '要求写明年化利率、计息周期和总还款额。'))
        if any(k in text for k in ('逾期', '罚息')) and any(k in text for k in ('利息', '罚息')):
            rules.append(('逾期利息/罚息可能过高', 'overdue', '罚息' if '罚息' in text else '逾期', 'high',
                          '逾期利息、罚息和违约金的叠加可能超过法定保护范围。',
                          '要求写明逾期利率上限和计算方式。'))
        if '交叉违约' in text:
            rules.append(('交叉违约条款可能扩大风险', 'cross_default', '交叉违约', 'high',
                          '一处违约可能触发其他合同全部到期，风险会跨合同扩散。',
                          '要求限定交叉违约的金额门槛、通知和补救期。'))
        if any(k in text for k in ('加速到期', '提前到期', '立即到期')):
            keyword = next(k for k in ('加速到期', '提前到期', '立即到期') if k in text)
            rules.append(('加速到期条款缺少限制', 'acceleration', keyword, 'high',
                          '债权人可在特定事件后宣布全部借款立即到期，借款人现金流可能断裂。',
                          '要求限定触发事件、通知程序和补救期。'))
        if any(k in text for k in ('保证', '担保')) and not any(k in text for k in ('保证范围', '担保范围', '保证期间')):
            keyword = '保证' if '保证' in text else '担保'
            rules.append(('担保范围/保证期间不明确', 'guarantee', keyword, 'high',
                          '担保范围、保证期间和保证方式不清，担保人可能承担超出预期的责任。',
                          '要求写明担保范围、保证期间和一般/连带保证。'))
        if '提前还款' in text and '违约金' in text:
            rules.append(('提前还款违约金', 'prepayment', '提前还款', 'medium',
                          '提前还款可能被收取违约金或手续费，实际节省的利息减少。',
                          '要求写明提前还款条件、违约金上限和利息结算方式。'))

    elif contract_type == 'ecommerce':
        if '无理由' in text and any(k in text for k in ('不适用', '除外', '不退', '不支持')):
            rules.append(('七天无理由退货可能被限制', 'return', '无理由', 'high',
                          '合同或规则可能排除法定无理由退货，消费者收到商品后难以退回。',
                          '要求写明无理由退货期限、例外商品和退款时限。'))
        if '退货' in text and '运费' in text:
            rules.append(('退货运费承担不明确', 'return_fee', '退货', 'medium',
                          '退货运费由谁承担、是否保价和何时退还货款不清。',
                          '要求写明退货运费承担、退货地址和验货规则。'))
        if any(k in text for k in ('管辖', '平台所在地', '商家所在地')):
            rules.append(('争议管辖地可能对消费者不利', 'jurisdiction', '管辖', 'high',
                          '管辖法院或仲裁地可能约定在平台/商家所在地，消费者维权成本高。',
                          '要求保留消费者住所地或收货地法院管辖。'))
        if '自动续费' in text:
            rules.append(('自动续费条款', 'renewal', '自动续费', 'high',
                          '自动续费可能缺少显著提示、取消入口和扣费前通知。',
                          '要求写明取消方式、扣费前提醒和退款规则。'))
        if any(k in text for k in ('免责', '概不负责', '风险自负')):
            rules.append(('电商免责条款可能过宽', 'liability', '免责', 'high',
                          '平台或商家可能通过免责条款排除商品质量、虚假宣传责任。',
                          '要求保留商品质量、描述不符和人身损害责任。'))
        if any(k in text for k in ('以实物为准', '图片仅供参考', '宣传不一致')):
            rules.append(('商品描述与宣传可能不一致', 'description', '以实物为准', 'high',
                          '商品页面、宣传图和实物描述可能不一致，消费者难以主张违约。',
                          '要求保存商品页面、明确规格和验收标准。'))

    elif contract_type == 'franchise':
        if any(k in text for k in ('加盟费', '保证金')) and any(k in text for k in ('不退', '不予退还', '没收')):
            rules.append(('加盟费/保证金退还条件不明确', 'fee', '加盟费', 'high',
                          '加盟费、保证金可能不退，但合同没有写清退出、违约和结算规则。',
                          '要求写明费用构成、退还条件和退出结算。'))
        if any(k in text for k in ('区域', '商圈', '选址')) and any(k in text for k in ('调整', '保留', '变更')):
            rules.append(('区域保护可能被单方调整', 'territory', '区域', 'high',
                          '加盟区域、商圈保护可能被品牌方单方调整，影响经营预期。',
                          '要求写明区域范围、保护半径和调整补偿。'))
        if '续约' in text and '加盟费' in text:
            rules.append(('续约条件/费用不明确', 'renewal', '续约', 'medium',
                          '续约是否重新收取加盟费、装修费和保证金不清。',
                          '要求写明续约条件、费用和品牌方拒绝续约的补偿。'))
        if any(k in text for k in ('退出', '解除')) and not any(k in text for k in ('结算', '退还', '回购')):
            rules.append(('退出结算机制缺失', 'exit', '退出', 'high',
                          '加盟商退出时库存、设备、押金和未履行期间费用如何结算不清。',
                          '要求写明退出通知期、库存回购和费用结算。'))
        if any(k in text for k in ('供货价', '价格调整', '涨价')):
            rules.append(('供货价格调整风险', 'supply_price', '供货价', 'high',
                          '品牌方可能单方调整供货价或最低采购量，加盟商利润被压缩。',
                          '要求写明调价公式、提前通知和最低采购量。'))
        if any(k in text for k in ('信息披露', '冷静期', '加盟商有权解除')):
            rules.append(('信息披露/冷静期条款', 'disclosure', '信息披露', 'medium',
                          '加盟前信息披露和冷静期解除权可能被忽略或缩短。',
                          '要求核对信息披露文件、冷静期和解除条件。'))

    elif contract_type == 'dispute':
        if '仲裁' in text and '法院' in text:
            rules.append(('仲裁与法院管辖可能冲突', 'forum_conflict', '仲裁', 'high',
                          '合同同时约定仲裁和法院诉讼，争议解决方式可能不明确。',
                          '要求只保留一种争议解决方式，并写明机构/法院。'))
        if '管辖' in text and any(k in text for k in ('平台所在地', '商家所在地', '甲方所在地', '乙方所在地')):
            rules.append(('管辖地可能对一方不利', 'jurisdiction', '管辖', 'high',
                          '管辖地约定在对方所在地，会增加差旅、律师和时间成本。',
                          '要求改为消费者住所地/合同履行地，或选择中立仲裁地。'))
        if '通知' in text and any(k in text for k in ('视为送达', '邮寄', '电子邮件')):
            rules.append(('通知送达条款可能过宽', 'notice', '视为送达', 'medium',
                          '通知方式、送达地址和视为送达条件不清，可能错过异议期限。',
                          '要求写明送达地址、变更通知和合理送达期限。'))
        if any(k in text for k in ('律师费', '保全费', '公证费')):
            rules.append(('维权费用承担不明确', 'cost', '律师费', 'medium',
                          '律师费、保全费、公证费等维权成本由谁承担不清。',
                          '要求写明费用承担规则和合理上限。'))

    # 通用格式条款风险：所有合同类型都适用
    for marker in ('概不负责', '一切责任', '最终解释权', '不得异议'):
        if marker in text:
            rules.append(('格式条款可能加重相对方责任', 'format_clause', marker, 'high',
                          '单方免责、最终解释权等表述可能构成不公平的格式条款。',
                          '要求删除绝对化免责/解释权表述，明确责任边界。'))

    candidates: List[Dict[str, Any]] = []
    for title, risk_type, keyword, severity, explanation, suggestion in rules:
        if keyword not in text:
            continue
        clause = next((c for c in parsed.clauses if keyword in c.text), parsed.clauses[0])
        quote = _sentence_for(clause.text, keyword)
        candidates.append({
            'clause_ids': [clause.clause_id],
            'title': title,
            'risk_type': risk_type,
            'quote': quote,
            'explanation': explanation,
            'suggestion': suggestion,
            'severity': severity,
            'legal_keywords': [keyword],
            'confidence': 0.62,
            'source': 'rule',
        })
    return candidates


def _cross_clause_candidates(parsed: ParsedContract, contract_type: str = 'rental') -> List[Dict[str, Any]]:
    text = parsed.text
    results: List[Dict[str, Any]] = []

    deposit_clauses = [c for c in parsed.clauses if '押金' in c.text]
    penalty_clauses = [c for c in parsed.clauses if '违约金' in c.text]
    if contract_type in {'rental', 'consumer'} and deposit_clauses and penalty_clauses:
        d = deposit_clauses[0]
        p = penalty_clauses[0]
        results.append({
            'clause_ids': [d.clause_id, p.clause_id],
            'title': '押金与违约金可能叠加',
            'risk_type': 'cross_clause',
            'quote': _sentence_for(p.text, '违约金'),
            'explanation': '合同同时约定押金和违约金，但没有说明押金能否抵扣违约金；退租时可能被要求“押金不退 + 另付违约金”。',
            'suggestion': '要求写明：押金是否抵扣违约金、抵扣顺序、以及租客最多承担多少。',
            'severity': 'high',
            'legal_keywords': ['押金', '违约金', '抵扣'],
            'confidence': 0.78,
            'source': 'cross_rule',
        })

    renew_clauses = [c for c in parsed.clauses if any(k in c.text for k in ('续租', '续约', '自动续'))]
    if contract_type == 'rental' and renew_clauses and not re.search(r'(提前|通知|书面).{0,12}(续租|续约|不续)', text):
        c = renew_clauses[0]
        results.append({
            'clause_ids': [c.clause_id],
            'title': '续租缺少通知期',
            'risk_type': 'cross_clause',
            'quote': _sentence_for(c.text, '续租'),
            'explanation': '合同提到续租，但没有明确提前多久通知、续租租金如何确定，租客可能被动接受新条件。',
            'suggestion': '要求补充：提前多少天通知、续租租金上限、未通知时如何处理。',
            'severity': 'medium',
            'legal_keywords': ['续租', '通知', '租赁期限'],
            'confidence': 0.7,
            'source': 'cross_rule',
        })

    unilateral = [c for c in parsed.clauses if any(k in c.text for k in ('单方解除', '随时收回', '无条件收回'))]
    if contract_type == 'rental' and unilateral and not re.search(r'(提前|通知|补偿|赔偿).{0,12}(解除|收回)', text):
        c = unilateral[0]
        results.append({
            'clause_ids': [c.clause_id],
            'title': '单方解除缺少通知与补偿',
            'risk_type': 'cross_clause',
            'quote': _sentence_for(c.text, '解除' if '解除' in c.text else '收回'),
            'explanation': '房东拥有单方解除/收回权，但合同没有约定提前通知期或补偿，租客可能突然失去住所。',
            'suggestion': '要求约定提前通知期、仅限特定违约情形、以及搬迁/装修损失补偿。',
            'severity': 'high',
            'legal_keywords': ['解除', '通知', '违约'],
            'confidence': 0.76,
            'source': 'cross_rule',
        })

    if contract_type == 'consumer':
        refund_clauses = [c for c in parsed.clauses if any(k in c.text for k in ('退款', '退费', '退课'))]
        fee_clauses = [c for c in parsed.clauses if any(k in c.text for k in ('手续费', '违约金', '扣除'))]
        if refund_clauses and fee_clauses:
            results.append({
                'clause_ids': [refund_clauses[0].clause_id, fee_clauses[0].clause_id],
                'title': '退款与手续费/违约金可能双重扣减',
                'risk_type': 'cross_clause',
                'quote': _sentence_for(fee_clauses[0].text, '手续费' if '手续费' in fee_clauses[0].text else '违约金'),
                'explanation': '合同同时约定退款限制和手续费/违约金，但没有说明计算顺序和上限；退课时可能被重复扣费。',
                'suggestion': '要求写明退款计算顺序、手续费上限、已上课时计价方式。',
                'severity': 'high',
                'legal_keywords': ['退款', '手续费', '违约金'],
                'confidence': 0.76,
                'source': 'cross_rule',
            })

    if contract_type == 'procurement':
        acceptance_clauses = [c for c in parsed.clauses if '验收' in c.text]
        payment_clauses = [c for c in parsed.clauses if any(k in c.text for k in ('尾款', '付款', '价款'))]
        if acceptance_clauses and payment_clauses:
            results.append({
                'clause_ids': [acceptance_clauses[0].clause_id, payment_clauses[0].clause_id],
                'title': '验收与尾款支付节点可能脱节',
                'risk_type': 'cross_clause',
                'quote': _sentence_for(payment_clauses[0].text, '尾款' if '尾款' in payment_clauses[0].text else '付款'),
                'explanation': '验收和尾款分别约定，但没有写清验收不合格时尾款如何处理、逾期未验收是否视为合格。',
                'suggestion': '要求写明验收期限、视为验收规则、尾款支付条件和质保金。',
                'severity': 'high',
                'legal_keywords': ['验收', '尾款', '付款'],
                'confidence': 0.78,
                'source': 'cross_rule',
            })

    if contract_type == 'labor':
        probation_clauses = [c for c in parsed.clauses if '试用期' in c.text]
        term_clauses = [c for c in parsed.clauses if '合同期限' in c.text or '劳动合同期限' in c.text]
        if probation_clauses and term_clauses:
            results.append({
                'clause_ids': [probation_clauses[0].clause_id, term_clauses[0].clause_id],
                'title': '试用期与合同期限需要联合核对',
                'risk_type': 'cross_clause',
                'quote': _sentence_for(probation_clauses[0].text, '试用期'),
                'explanation': '试用期上限取决于劳动合同期限；两条分别看可能看不出试用期是否超限。',
                'suggestion': '按合同期限核对试用期上限，并确认是否重复约定试用期。',
                'severity': 'high',
                'legal_keywords': ['试用期', '劳动合同期限'],
                'confidence': 0.8,
                'source': 'cross_rule',
            })
        noncompete = [c for c in parsed.clauses if '竞业限制' in c.text]
        if noncompete and not re.search(r'竞业限制[^。；;\n]{0,80}(补偿|经济补偿)', text):
            results.append({
                'clause_ids': [noncompete[0].clause_id],
                'title': '竞业限制与经济补偿未对应',
                'risk_type': 'cross_clause',
                'quote': _sentence_for(noncompete[0].text, '竞业限制'),
                'explanation': '合同限制离职后就业，但没有约定补偿标准或支付方式。',
                'suggestion': '要求写明竞业范围、期限和按月补偿标准。',
                'severity': 'high',
                'legal_keywords': ['竞业限制', '补偿'],
                'confidence': 0.8,
                'source': 'cross_rule',
            })

    if contract_type == 'loan':
        guarantee = [c for c in parsed.clauses if '担保' in c.text or '保证' in c.text]
        cross = [c for c in parsed.clauses if '交叉违约' in c.text]
        if guarantee and cross:
            results.append({
                'clause_ids': [guarantee[0].clause_id, cross[0].clause_id],
                'title': '担保责任与交叉违约可能叠加',
                'risk_type': 'cross_clause',
                'quote': _sentence_for(cross[0].text, '交叉违约'),
                'explanation': '担保范围可能覆盖其他合同的交叉违约，导致担保责任超出预期。',
                'suggestion': '要求写明担保范围、交叉违约门槛和最高责任上限。',
                'severity': 'high',
                'legal_keywords': ['担保', '交叉违约'],
                'confidence': 0.8,
                'source': 'cross_rule',
            })

    if contract_type == 'ecommerce':
        returns = [c for c in parsed.clauses if '退货' in c.text or '无理由' in c.text]
        freight = [c for c in parsed.clauses if '运费' in c.text]
        if returns and freight:
            results.append({
                'clause_ids': [returns[0].clause_id, freight[0].clause_id],
                'title': '退货权利与运费承担可能脱节',
                'risk_type': 'cross_clause',
                'quote': _sentence_for(returns[0].text, '退货' if '退货' in returns[0].text else '无理由'),
                'explanation': '合同可能允许退货，但运费、保价和退款时点另算，实际退货成本不明确。',
                'suggestion': '要求写明清退货运费承担、退货地址和退款到账期限。',
                'severity': 'medium',
                'legal_keywords': ['退货', '运费'],
                'confidence': 0.74,
                'source': 'cross_rule',
            })

    if contract_type == 'franchise':
        fees = [c for c in parsed.clauses if '加盟费' in c.text or '保证金' in c.text]
        exits = [c for c in parsed.clauses if '退出' in c.text or '解除' in c.text]
        if fees and exits:
            results.append({
                'clause_ids': [fees[0].clause_id, exits[0].clause_id],
                'title': '加盟费/保证金与退出结算未对应',
                'risk_type': 'cross_clause',
                'quote': _sentence_for(fees[0].text, '加盟费' if '加盟费' in fees[0].text else '保证金'),
                'explanation': '合同约定加盟费/保证金，但退出时是否退还、如何结算未与退出条款对应。',
                'suggestion': '要求写明退出时费用退还比例、库存回购和未履行期间结算。',
                'severity': 'high',
                'legal_keywords': ['加盟费', '保证金', '退出'],
                'confidence': 0.78,
                'source': 'cross_rule',
            })

    if contract_type == 'dispute':
        arbitration = [c for c in parsed.clauses if '仲裁' in c.text]
        court = [c for c in parsed.clauses if '法院' in c.text or '诉讼' in c.text]
        if arbitration and court:
            results.append({
                'clause_ids': [arbitration[0].clause_id, court[0].clause_id],
                'title': '仲裁与诉讼条款可能冲突',
                'risk_type': 'cross_clause',
                'quote': _sentence_for(arbitration[0].text, '仲裁'),
                'explanation': '不同条款分别约定仲裁和法院诉讼，可能导致争议解决方式不明确。',
                'suggestion': '要求只保留一种方式，并写明仲裁机构或管辖法院。',
                'severity': 'high',
                'legal_keywords': ['仲裁', '法院', '管辖'],
                'confidence': 0.82,
                'source': 'cross_rule',
            })

    return results


def _normalize_risks(raw: Optional[Dict[str, Any]], parsed: ParsedContract) -> List[Dict[str, Any]]:
    risks: List[Dict[str, Any]] = []
    rows = raw.get('risks') if isinstance(raw, dict) else None
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            clause_ids = [str(x) for x in row.get('clause_ids') or [] if str(x) in {c.clause_id for c in parsed.clauses}]
            if not clause_ids:
                clause_ids = [parsed.clauses[0].clause_id]
            risks.append({
                'clause_ids': clause_ids,
                'title': str(row.get('title') or '合同风险').strip(),
                'risk_type': str(row.get('risk_type') or 'other').strip(),
                'quote': str(row.get('quote') or '').strip(),
                'explanation': str(row.get('explanation') or '').strip(),
                'suggestion': str(row.get('suggestion') or '').strip(),
                'severity': str(row.get('severity') or 'medium').lower(),
                'legal_keywords': [str(x) for x in row.get('legal_keywords') or []],
                'confidence': float(row.get('confidence') or 0.6),
                'source': 'llm',
            })
    return risks


def _dedupe(risks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for risk in risks:
        key = (normalize_text(risk.get('title', ''))[:30], normalize_text(risk.get('quote', ''))[:40])
        if key in seen:
            continue
        seen.add(key)
        out.append(risk)
    return out


def _judge_deterministic(risks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for risk in risks:
        verified_laws = [law for law in risk.get('legal_basis', []) if law.get('verified', True)]
        if not risk.get('evidence_verified'):
            risk['status'] = 'needs_review'
            risk['judge_reason'] = '引文未能逐字回查到对应条款，需人工核对。'
            risk['confidence'] = min(float(risk.get('confidence') or 0.5), 0.45)
        elif not verified_laws:
            risk['status'] = 'needs_review'
            risk['judge_reason'] = '未检索到可核验的法律依据，保留为待人工复核的风险提示。'
        elif risk.get('severity') == 'high' and float(risk.get('confidence') or 0) < 0.5:
            risk['status'] = 'needs_review'
            risk['judge_reason'] = '风险等级高但置信度不足，需人工确认。'
        else:
            risk['status'] = 'supported'
            risk['judge_reason'] = '引文可回查，且存在可核验的法律依据。'
    return risks


def _judge_payload(risks: List[Dict[str, Any]], compact: bool = False) -> Dict[str, Any]:
    rows = []
    for risk in risks:
        laws = []
        for law in risk.get('legal_basis', []):
            laws.append({
                'article': str(law.get('article', ''))[:80],
                'title': str(law.get('title', ''))[:100],
                'summary': str(law.get('summary', ''))[:160 if compact else 500],
                'verified': bool(law.get('verified', False)),
            })
        rows.append({
            'risk_id': risk['risk_id'],
            'title': str(risk.get('title', ''))[:120],
            'quote': str(risk.get('quote', ''))[:240 if compact else 800],
            'explanation': str(risk.get('explanation', ''))[:240 if compact else 700],
            'legal_basis': laws,
            'evidence_verified': risk.get('evidence_verified'),
        })
    return {'risks': rows}


def _valid_judgments(raw: Any) -> bool:
    return isinstance(raw, dict) and isinstance(raw.get('judgments'), list) and bool(raw['judgments'])


def _judgeable_risks(risks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    raw = os.getenv('JUDGE_SEVERITIES', 'high,medium')
    allowed = {item.strip() for item in raw.split(',') if item.strip()}
    return [risk for risk in risks if risk.get('severity') in allowed]


def _judge_with_llm(risks: List[Dict[str, Any]], model: Optional[str] = None) -> Optional[Dict[str, Any]]:
    judge_model = model or os.getenv('JUDGE_MODEL', '').strip() or None
    compact = os.getenv('JUDGE_COMPACT', '1').strip().lower() not in {'0', 'false', 'no'}
    # 默认使用压缩证据，减少 Judge 输入/输出长度
    payload = json.dumps(_judge_payload(risks, compact=compact), ensure_ascii=False)
    judged, _ = _safe_json(JUDGE_SYSTEM, payload, max_tokens=2400 if compact else 3000, model=judge_model)
    if _valid_judgments(judged):
        return judged

    # 第二次：强制压缩，要求只输出 JSON
    retry_system = JUDGE_SYSTEM + '\n这是重试。请严格只输出一个 JSON 对象，不要 Markdown、不要解释。'
    compact_payload = json.dumps(_judge_payload(risks, compact=True), ensure_ascii=False)
    judged, _ = _safe_json(retry_system, compact_payload, max_tokens=2200, model=judge_model)
    return judged if _valid_judgments(judged) else None


_CLASSIFY_HINTS = {
    'rental': ('租赁', '租約', '租金', '押金', '按金', '房東', '業主', '承租人', '租客', '租期', '退租', '續租'),
    'consumer': ('健身', '培训', '培訓', '课程', '課程', '会员', '會員', '私教', '课时', '課時', '退课', '退課', '门店', '門店', '教练', '教練'),
    'procurement': ('采购', '採購', '供货', '供貨', '验收', '驗收', '设备', '設備', '买方', '買方', '卖方', '賣方', '质保', '質保', '尾款', '交付'),
    'labor': ('劳动', '勞動', '僱傭', '雇佣', '僱員', '雇员', '員工', '员工', '僱主', '雇主', '工资', '工資', '试用期', '試用期', '社保', '強積金', '竞业', '競業', '加班', '解僱', '用人单位'),
    'loan': ('借款', '贷款', '貸款', '利息', '担保', '擔保', '保证人', '保證人', '还款', '還款', '本金', '放债', '放債', '罚息', '罰息'),
    'ecommerce': ('电商', '電商', '平台', '商品', '退货', '退貨', '七天无理由', '七天無理由', '店铺', '店鋪', '订单', '訂單', '快递', '快遞'),
    'franchise': ('加盟', '特许经营', '特許經營', '加盟费', '加盟費', '区域保护', '區域保護', '品牌方', '被特许人', '被特許人', '保证金', '保證金'),
    'dispute': ('仲裁', '管辖', '管轄', '诉讼', '訴訟', '争议解决', '爭議解決', '送达', '送達', '法院', '律师费', '律師費'),
}


def _rule_classify(parsed: ParsedContract) -> Dict[str, Any]:
    text = parsed.text
    scores = {}
    domains = []
    for contract_type, keywords in _CLASSIFY_HINTS.items():
        hits = [kw for kw in keywords if kw in text]
        scores[contract_type] = len(hits)
        if hits:
            domains.extend(hits[:4])
    best_type, best_score = max(scores.items(), key=lambda item: item[1])
    total = sum(scores.values())
    confidence = round(min(0.9, 0.3 + best_score / max(1, total)), 2) if best_score else 0.25
    return {
        'contract_type': best_type if best_score else 'rental',
        'confidence': confidence,
        'legal_domains': list(dict.fromkeys(domains))[:6],
        'jurisdiction_hint': 'unknown',
        'reason': '规则关键词分类（模型不可用或未启用）',
        'source': 'rules',
    }


def _classify_contract(parsed: ParsedContract, use_llm: bool = True) -> Dict[str, Any]:
    fallback = _rule_classify(parsed)
    if not use_llm:
        return fallback
    raw, _ = _safe_json(CLASSIFY_SYSTEM, _contract_prompt(parsed), max_tokens=600)
    if not isinstance(raw, dict):
        return fallback
    contract_type = str(raw.get('contract_type') or '').strip().lower()
    if contract_type not in CONTRACT_TYPES:
        return fallback
    try:
        confidence = float(raw.get('confidence') or 0.5)
    except (TypeError, ValueError):
        confidence = 0.5
    return {
        'contract_type': contract_type,
        'confidence': round(max(0.0, min(1.0, confidence)), 2),
        'legal_domains': [str(x) for x in raw.get('legal_domains') or []][:6],
        'jurisdiction_hint': str(raw.get('jurisdiction_hint') or 'unknown'),
        'reason': str(raw.get('reason') or ''),
        'source': 'llm',
    }


def _select_web_indexes(
    candidates: List[Dict[str, Any]],
    web_queries: Dict[int, str],
    skip_low: bool = True,
    low_max: Optional[int] = None,
) -> List[int]:
    severity_order = {'high': 0, 'medium': 1, 'low': 2}
    high_medium = [
        index for index in web_queries
        if candidates[index - 1].get('severity') in {'high', 'medium'}
    ]
    low = [
        index for index in web_queries
        if candidates[index - 1].get('severity') == 'low'
    ]
    if skip_low:
        low = []
    elif low_max is not None:
        low = low[:max(0, low_max)]
    return sorted(high_medium + low, key=lambda i: severity_order.get(candidates[i - 1].get('severity', 'medium'), 9))


def _emit(progress: Optional[Callable[[str, str, str], None]], stage: str, status: str, detail: str = '') -> None:
    if progress:
        try:
            progress(stage, status, detail)
        except Exception:
            pass


def review_parsed(
    parsed: ParsedContract,
    use_llm: bool = True,
    region: str = DEFAULT_REGION,
    contract_type: str = 'rental',
    progress: Optional[Callable[[str, str, str], None]] = None,
) -> Dict[str, Any]:
    region = (region or DEFAULT_REGION).strip().lower()
    if region not in REGIONS:
        raise ValueError(f'不支持的法域：{region}')
    requested_type = (contract_type or DEFAULT_CONTRACT_TYPE).strip().lower()
    if requested_type not in {*CONTRACT_TYPES, 'auto'}:
        raise ValueError(f'不支持的合同类型：{requested_type}')
    classification: Dict[str, Any] = {}
    _emit(progress, 'classify', 'running', '正在识别合同类型。')
    if requested_type == 'auto':
        rule_classification = _rule_classify(parsed)
        try:
            classify_threshold = float(os.getenv('AUTO_CLASSIFY_LLM_THRESHOLD', '0.6'))
        except ValueError:
            classify_threshold = 0.6
        if use_llm and float(rule_classification.get('confidence') or 0) < classify_threshold:
            classification = _classify_contract(parsed, use_llm)
        else:
            classification = rule_classification
            classification['reason'] = '规则分类（高置信度，跳过模型分类）'
        resolved_type = classification.get('contract_type', 'rental')
        if resolved_type not in CONTRACT_TYPES:
            resolved_type = 'rental'
        contract_type = resolved_type
    else:
        contract_type = requested_type
        classification = {
            'contract_type': contract_type,
            'confidence': 1.0,
            'legal_domains': [],
            'jurisdiction_hint': region,
            'reason': '用户手动选择',
            'source': 'user',
        }
    region_label = REGIONS[region]
    contract_type_label = CONTRACT_TYPES[contract_type]
    try:
        known_threshold = float(os.getenv('LEGAL_WEB_KNOWN_CONFIDENCE', '0.6'))
    except ValueError:
        known_threshold = 0.6
    known_type = requested_type != 'auto' or float(classification.get('confidence') or 0) >= known_threshold
    classification['known_type'] = known_type
    trace = [
        {'agent': '合同解析', 'status': 'done', 'detail': f'读取 {len(parsed.pages)} 页，切分 {len(parsed.clauses)} 条条款。'},
    ]
    _emit(progress, 'classify', 'done', f'识别为{contract_type_label}，置信度 {classification.get("confidence", 0):.0%}。')
    warnings: List[str] = []
    if requested_type == 'auto':
        trace.append({
            'agent': '合同分类 Agent',
            'status': 'done',
            'detail': f"识别为{contract_type_label}，置信度 {classification.get('confidence', 0):.0%}。",
        })
        if float(classification.get('confidence') or 0) < 0.6:
            warnings.append('合同类型自动识别置信度较低，建议在页面上手动确认合同类型。')
    facts = _fallback_facts(parsed)
    candidates = _rule_risk_candidates(parsed, contract_type)
    trace.append({'agent': '规则基线', 'status': 'done', 'detail': f'{contract_type_label}规则提出 {len(candidates)} 条候选。'})
    _emit(progress, 'rules', 'done', f'规则基线提出 {len(candidates)} 条候选。')

    if use_llm:
        _emit(progress, 'analyze', 'running', '条款理解与风险审查模型运行中。')
        analyze_model = os.getenv('ANALYZE_MODEL', '').strip() or None
        try:
            analyze_max_tokens = max(1200, int(os.getenv('ANALYZE_MAX_TOKENS', '4000')))
        except ValueError:
            analyze_max_tokens = 4000
        raw, error = _safe_json(
            ANALYZE_SYSTEM.replace('{region}', region_label).replace('{contract_type}', contract_type_label),
            _contract_prompt(parsed, contract_type_label),
            max_tokens=analyze_max_tokens,
            model=analyze_model,
        )
        if not raw and use_llm and os.getenv('ANALYZE_RETRY', '1').strip().lower() not in {'0', 'false', 'no'}:
            _emit(progress, 'analyze', 'running', '模型返回格式异常，正在重试一次。')
            raw, error = _safe_json(
                ANALYZE_SYSTEM.replace('{region}', region_label).replace('{contract_type}', contract_type_label),
                _contract_prompt(parsed, contract_type_label),
                max_tokens=analyze_max_tokens + 800,
                model=analyze_model,
            )
        if raw:
            llm_facts = raw.get('facts')
            if isinstance(llm_facts, dict):
                facts = {**facts, **{k: v for k, v in llm_facts.items() if v}}
                facts = _normalize_facts(facts)
            llm_risks = _normalize_risks(raw, parsed)
            candidates = _dedupe(llm_risks + candidates)
            trace.append({'agent': '条款理解 Agent', 'status': 'done', 'detail': '已抽取价款、期限、解除、违约、验收/维修等事实。'})
            trace.append({'agent': '风险审查 Agent', 'status': 'done', 'detail': f'模型提出 {len(llm_risks)} 条，与规则基线合并后 {len(candidates)} 条。'})
        else:
            warnings.append(f'模型分析失败，已使用规则基线：{error[:160]}')
            trace.append({'agent': '条款理解 Agent', 'status': 'warning', 'detail': '模型调用失败，使用规则抽取。'})
            _emit(progress, 'analyze', 'warning', f'模型分析失败，已使用规则基线：{error[:100]}')
    if use_llm and not any(item.get('agent') == '条款理解 Agent' and item.get('status') == 'warning' for item in trace):
        _emit(progress, 'analyze', 'done', '条款理解与风险审查完成。')

    # 交叉条款规则
    cross = _cross_clause_candidates(parsed, contract_type)
    candidates = _dedupe(candidates + cross)
    trace.append({'agent': '交叉验证 Agent', 'status': 'done', 'detail': f'发现 {len(cross)} 条跨条款组合风险。'})
    _emit(progress, 'cross', 'done', f'发现 {len(cross)} 条跨条款组合风险。')

    risks: List[Dict[str, Any]] = []
    web_count = 0
    _emit(progress, 'legal', 'running', '本地法律检索与官方网页兜底运行中。')

    def legal_query(candidate: Dict[str, Any]) -> str:
        return ' '.join([
            candidate.get('title', ''), candidate.get('explanation', ''),
            candidate.get('quote', ''), ' '.join(candidate.get('legal_keywords') or []),
        ]).strip()

    # 本地检索很快，先全部做完；只对缺依据的风险并发做官方网页兜底。
    legal_by_index: Dict[int, List[Dict[str, Any]]] = {}
    web_queries: Dict[int, str] = {}
    for index, candidate in enumerate(candidates, start=1):
        query = legal_query(candidate)
        legal = retrieve_legal_basis(query, limit=2, jurisdiction=region, contract_type=contract_type)
        for item in legal:
            item['source_type'] = 'local'
            item['verified'] = True
            item['retrieved_at'] = None
        legal_by_index[index] = legal
        if not legal:
            web_queries[index] = ' '.join([
                candidate.get('title', ''),
                ' '.join(candidate.get('legal_keywords') or []),
            ]).strip() or query

    skip_low = known_type
    try:
        unknown_low_max = max(0, int(os.getenv('LEGAL_WEB_UNKNOWN_LOW_MAX', '2')))
    except ValueError:
        unknown_low_max = 2
    selected_web = _select_web_indexes(
        candidates,
        web_queries,
        skip_low=skip_low,
        low_max=None if known_type else unknown_low_max,
    )
    web_results: Dict[int, List[Dict[str, Any]]] = {}
    if selected_web:
        workers = max(1, int(os.getenv('LEGAL_WEB_WORKERS', '3')))
        with ThreadPoolExecutor(max_workers=min(workers, len(selected_web))) as pool:
            futures = {
                index: pool.submit(
                    search_official,
                    web_queries[index],
                    region,
                    limit=1,
                    contract_type=contract_type,
                )
                for index in selected_web
            }
            for index, future in futures.items():
                try:
                    web_results[index] = future.result()
                except Exception:
                    web_results[index] = []
        web_count = sum(len(items) for items in web_results.values())
    _emit(progress, 'legal', 'done', f'本地法律库与官方网页检索完成，官方网页补充 {web_count} 条。')

    for index, candidate in enumerate(candidates, start=1):
        clause, quote, verified = _verify_quote(parsed, candidate.get('clause_ids', []), candidate.get('quote', ''))
        legal = legal_by_index.get(index) or web_results.get(index, [])
        risk = {
            'risk_id': f'R{index}',
            'title': candidate.get('title', '合同风险'),
            'risk_type': candidate.get('risk_type', 'other'),
            'severity': candidate.get('severity') if candidate.get('severity') in {'high', 'medium', 'low'} else 'medium',
            'clause_ids': [clause.clause_id] if clause else candidate.get('clause_ids', []),
            'page': clause.page if clause else None,
            'quote': quote,
            'explanation': candidate.get('explanation', ''),
            'suggestion': candidate.get('suggestion', ''),
            'legal_basis': legal,
            'confidence': round(max(0.0, min(1.0, float(candidate.get('confidence') or 0.6))), 3),
            'evidence_verified': verified,
            'status': 'needs_review',
            'judge_reason': '',
            'source': candidate.get('source', 'rule'),
        }
        risks.append(risk)

    trace.append({
        'agent': '法律检索 Agent',
        'status': 'done',
        'detail': (
            f'本地库优先，{len(selected_web)} 条缺少依据的风险并发检索官方网页；'
            f'本次补充 {web_count} 条。'
            + ('已知类型低风险不联网。' if known_type else f'未知类型低风险最多补 {unknown_low_max} 条。')
        ),
    })

    _emit(progress, 'judge', 'running', 'Judge 正在复核引文与法律依据。')
    judgeable = _judgeable_risks(risks)
    judgments = []
    if use_llm and judgeable:
        fast_judge_model = os.getenv('JUDGE_FAST_MODEL', '').strip() or None
        if fast_judge_model:
            verified_group = [
                risk for risk in judgeable
                if any(law.get('verified', True) for law in risk.get('legal_basis', []))
            ]
            unverified_group = [risk for risk in judgeable if risk not in verified_group]
        else:
            verified_group = judgeable
            unverified_group = []

        if verified_group:
            accurate = _judge_with_llm(verified_group)
            if accurate and isinstance(accurate.get('judgments'), list):
                judgments.extend(accurate['judgments'])
        if unverified_group:
            fast = _judge_with_llm(unverified_group, model=fast_judge_model)
            if fast and isinstance(fast.get('judgments'), list):
                judgments.extend(fast['judgments'])

    if judgments:
        by_id = {str(row.get('risk_id')): row for row in judgments if isinstance(row, dict)}
        for risk in risks:
            row = by_id.get(risk['risk_id'])
            if not row:
                continue
            status = str(row.get('status') or '')
            if status in {'supported', 'needs_review', 'rejected'}:
                risk['status'] = status
                risk['judge_reason'] = str(row.get('reason') or '')
                if row.get('confidence') is not None:
                    risk['confidence'] = round(max(0.0, min(1.0, float(row['confidence']))), 3)
        remaining = [risk for risk in risks if risk['risk_id'] not in by_id]
        if remaining:
            _judge_deterministic(remaining)
        trace.append({
            'agent': 'Judge Agent',
            'status': 'done',
            'detail': (
                f'LLM 复核 {len(judgeable)} 条高风险/中风险'
                + (f'（{len(unverified_group)} 条无核验依据走快速模型）' if fast_judge_model else '')
                + f'，其余 {len(remaining)} 条使用确定性复核。'
            ),
        })
    else:
        risks = _judge_deterministic(risks)
        if use_llm:
            warnings.append('Judge Agent 未返回可用结果，已使用确定性复核。')
        trace.append({'agent': 'Judge Agent', 'status': 'done', 'detail': '使用确定性规则复核引文与法律依据。'})

    _emit(progress, 'judge', 'done', 'Judge 复核完成。')

    # 没有可核验法律依据时，即使 Judge 说 supported 也降为待复核
    for risk in risks:
        verified_laws = [law for law in risk.get('legal_basis', []) if law.get('verified', True)]
        if risk['status'] == 'supported' and not verified_laws:
            risk['status'] = 'needs_review'
            risk['judge_reason'] = '法律依据未能核验，转人工复核。'

    # rejected 不进入最终报告；仅保留 high → medium → low
    final_risks = [r for r in risks if r['status'] != 'rejected']
    severity_order = {'high': 0, 'medium': 1, 'low': 2}
    status_order = {'needs_review': 0, 'supported': 1}
    final_risks.sort(
        key=lambda r: (
            severity_order.get(r['severity'], 9),
            status_order.get(r['status'], 9),
            -float(r.get('confidence') or 0),
        )
    )
    high = sum(1 for r in final_risks if r['severity'] == 'high' and r['status'] != 'rejected')
    medium = sum(1 for r in final_risks if r['severity'] == 'medium' and r['status'] != 'rejected')
    score = min(100, high * 25 + medium * 12 + max(0, len(final_risks) - high - medium) * 5)
    level = 'high' if score >= 60 else 'medium' if score >= 30 else 'low'
    _emit(progress, 'done', 'done', f'审查完成，共 {len(final_risks)} 条风险。')
    return {
        'filename': parsed.filename,
        'file_type': parsed.file_type,
        'region': region,
        'region_label': region_label,
        'contract_type': contract_type,
        'contract_type_label': contract_type_label,
        'contract_type_requested': requested_type,
        'classification': classification,
        'page_count': len(parsed.pages),
        'clause_count': len(parsed.clauses),
        'facts': facts,
        'risks': final_risks,
        'summary': {
            'risk_score': score,
            'risk_level': level,
            'risk_level_label': {'high': '高风险', 'medium': '中风险', 'low': '低风险'}[level],
            'total_risks': len(final_risks),
            'high_count': high,
            'medium_count': medium,
            'needs_review_count': sum(1 for r in final_risks if r['status'] == 'needs_review'),
        },
        'agent_trace': trace,
        'warnings': warnings,
        'disclaimer': f'{DISCLAIMER} 本次仅适用{region_label}法律。',
    }


def review_contract(
    path: str,
    filename: Optional[str] = None,
    use_llm: bool = True,
    region: str = DEFAULT_REGION,
    contract_type: str = 'rental',
    progress: Optional[Callable[[str, str, str], None]] = None,
) -> Dict[str, Any]:
    _emit(progress, 'parse', 'running', '正在解析合同文件。')
    parsed = parse_contract(path, filename=filename)
    _emit(progress, 'parse', 'done', f'读取 {len(parsed.pages)} 页，切分 {len(parsed.clauses)} 条条款。')
    return review_parsed(parsed, use_llm=use_llm, region=region, contract_type=contract_type, progress=progress)


__all__ = ['review_contract', 'review_parsed', 'DISCLAIMER', 'REGIONS', 'CONTRACT_TYPES', 'DEFAULT_REGION', 'DEFAULT_CONTRACT_TYPE']
