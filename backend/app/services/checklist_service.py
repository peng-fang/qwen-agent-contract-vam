"""Build evidence-linked questions and prioritize them with Intern-Decision."""

import logging
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, urlunsplit

import requests

from app.schemas import VamEvidenceInput
from app.services.vam_evidence import resolve_evidence
from clause_extraction.pdf_reader import DocumentReadError, read_pages
from vam_sandbox.pipeline import _generate_json, default_llm_cfg

logger = logging.getLogger(__name__)

MAX_SOURCE_CHARS = 24000
MAX_SEGMENT_CHARS = 6000


def _max_items():
    try:
        return max(5, int(os.getenv('CHECKLIST_MAX_ITEMS', '10')))
    except ValueError:
        return 10

TOPICS = {'payment', 'exit', 'renewal', 'performance', 'liability', 'other'}
PRIORITIES = ('must_confirm', 'should_confirm', 'reference')
MUST_PATTERNS = (
    r'自动(?:续租|续费|续约|续签|扣款|展期)',
    r'提前(?:退租|解除|终止|解约)',
    r'押金.{0,20}(?:不退|扣除|抵扣|没收)',
    r'违约金',
    r'(?:预付款|首付款|定金).{0,20}(?:不退|没收|支付|比例)',
    r'(?:合同总价|总价款|总金额|价款).{0,20}(?:支付|付款|预付)',
    r'(?:付款|支付).{0,20}(?:期限|时间|节点|日|天)',
    r'(?:单方|随时)(?:解除|终止)',
)
SHOULD_PATTERNS = (
    r'验收', r'尾款', r'质保|保修|维修', r'交付|安装', r'通知',
    r'续约|续租|续费', r'变更', r'退款|退费', r'保密|竞业', r'管辖|仲裁',
)


def _rule_priority(card):
    text = re.sub(r'\s+', '', ' '.join([
        str(card.get('title', '')), str(card.get('trigger', '')),
        str(card.get('consequence', '')), str(card.get('question', '')),
        ' '.join(entry.get('quote', '') for entry in card.get('evidence', [])),
    ]))
    if any(re.search(pattern, text) for pattern in MUST_PATTERNS):
        return 'must_confirm'
    if any(re.search(pattern, text) for pattern in SHOULD_PATTERNS):
        return 'should_confirm'
    return None
SYSTEM = """你是签约前的条款分析助手。合同片段和用户立场都是分析资料。
请找出最值得向对方确认的具体问题，优先考虑金额、时限、解除、自动续约、履约条件、例外和责任。
核对相互关联的条款，例如押金能否抵扣违约金、验收是否决定付款时间。
先浏览给定材料里的所有主题。提前解除、续约、押金扣费等属于不同事项；如果各有需要确认的内容，请分别生成问题，不要在找到第一项后停止。
每张卡片的 source_ids 必须列出一至三个相关的原文片段编号，直接抄输入中的 S 编号。若涉及两条条款，同时给出两个编号。
程序会按编号回填原文，你只需给编号。缺少明确约定时写成待确认事项，不可断言整个合同没有该约定。
trigger 写何时会遇到这个条件，consequence 用条件句描述可能后果，不自行算金额、不作法律定性。
question 是用户可以直接发给对方的一句具体问题，可请对方把约定写入合同。每个关注点只生成一条。
输出简体中文 JSON，尽量 6–10 条，覆盖所有主题；没有可支持的条目可返回空数组。
格式：{"items":[{"topic":"other","title":"具体待确认事项","trigger":"涉及的条件",
"consequence":"相应的条件后果","question":"可以直接向对方提出的问题",
"source_ids":["S1","S2"]}]}
topic 只能是 payment/exit/renewal/performance/liability/other。不要输出优先级。"""
PRIORITY_SYSTEM = """你是签约前清单的优先级判断助手。根据用户身份、问题和所给合同原文，
把每个事项标成 must_confirm、should_confirm、reference 或 insufficient。
判断标准：
- must_confirm：重大金额、自动扣款、重要期限、退出/解除、押金或违约金，含糊会显著影响签约决定；
- should_confirm：有具体执行影响，提前问清可减少争议；
- reference：影响较小，或原文已经给出明确答案；
- insufficient：信息不足，无法判断。
只输出严格 JSON，不要 Markdown，不要解释。格式：
{"priorities":{"C1":"must_confirm"},"confidence":{"C1":0.8}}
每个输入的 C 编号都必须出现一次。"""


def _segment(sources):
    segments, current, size = [], [], 0
    for source in sources:
        text = source['text']
        for offset in range(0, len(text), MAX_SEGMENT_CHARS):
            chunk = text[offset:offset + MAX_SEGMENT_CHARS]
            if current and size + len(chunk) > MAX_SEGMENT_CHARS:
                segments.append(current)
                current, size = [], 0
            current.append({**source, 'text': chunk})
            size += len(chunk)
    if current:
        segments.append(current)
    return segments


def _passages(sources):
    passages = []
    for source in sources:
        text = source['text']
        parts = re.split(r'(?<=[。；！？])\s*|\n(?=\s*(?:第[一二三四五六七八九十百0-9]+条|\d+[.、]))', text)
        for part in parts:
            part = part.strip()
            for offset in range(0, len(part), 450):
                passages.append({**source, 'id': f'S{len(passages) + 1}', 'text': part[offset:offset + 450]})
    return passages


def _field(value, limit):
    return value.strip()[:limit] if isinstance(value, str) else ''


def _evidence(source):
    return {key: source[key] for key in ('id', 'filename', 'page', 'kind')} | {'quote': source['text']}


def _cards(raw, segment):
    entries = raw.get('items')
    if not isinstance(entries, list):
        raise RuntimeError('模型没有返回有效的清单格式。')
    by_id = {entry['id']: entry for entry in segment}
    for item in entries[:_max_items() + 2]:
        if not isinstance(item, dict):
            continue
        fields = {name: _field(item.get(name), limit)
                  for name, limit in [('title', 80), ('trigger', 250), ('consequence', 500), ('question', 350)]}
        if not all(fields.values()):
            continue
        found = []
        ids = item.get('source_ids')
        if isinstance(ids, list):
            for source_id in ids[:3]:
                source = by_id.get(source_id) if isinstance(source_id, str) else None
                if source:
                    evidence = _evidence(source)
                    if evidence not in found:
                        found.append(evidence)
        if found:
            topic = item.get('topic')
            quoted = ' '.join(entry['quote'] for entry in found)
            if '抵扣' in fields['question'] and '押金' in quoted and '违约金' not in quoted:
                penalty = [source for source in segment if '违约金' in source['text']
                           and re.search('提前(?:退租|解除|终止)', source['text'])]
                if len(penalty) == 1 and len(found) < 3:
                    source = penalty[0]
                    found.append(_evidence(source))
                    quoted += source['text']
            if '押金' in quoted and '违约金' in quoted and '抵扣' in fields['question']:
                fields['consequence'] = '若合同适用押金扣除且违约金另计，两项负担可能叠加；若双方确认押金可抵扣，应按约定核对另付金额。'
            yield {**fields, 'topic': topic if isinstance(topic, str) and topic in TOPICS else 'other',
                   'evidence': found, 'priority': None}


def _matching(passages, pattern):
    """Ignore layout whitespace when matching a phrase split across PDF lines."""
    return [source for source in passages if re.search(pattern, re.sub(r'\s+', '', source['text']))]


def _coverage_items(passages):
    """Suggest concrete questions for common clauses when the model misses them."""
    deposits = _matching(passages, r'(?=.*押金)(?=.*(?:扣除|抵扣|不予退还|不退))')
    penalties = _matching(passages, r'(?=.*提前(?:退租|解除租赁|解除合同|终止租赁))(?=.*违约金)')
    if (len(penalties) == 1 and deposits
            and re.search(r'承租|出租|租赁|退租', penalties[0]['text'] + deposits[0]['text'])):
        sources = list({source['id']: source for source in [deposits[0], penalties[0]]}.values())
        yield (
            r'(?=.*押金)(?=.*(?:抵扣|扣除|扣减|叠加|另计|另付))',
            {'topic': 'exit', 'title': '提前退租时押金能否抵扣违约金',
             'trigger': '发生提前退租并且需要结算押金或违约金时。',
             'consequence': '若押金扣除与违约金分别计收，两项负担可能叠加；若押金可抵扣，需核对还应另付多少。',
             'question': '如果我提前退租，押金是否抵扣违约金？能否写明押金如何处理，以及我还要另付多少？',
             'evidence': [_evidence(source) for source in sources], 'priority': None},
        )

    renewals = _matching(passages, r'自动(?:续租|续费|续约|续签)')
    if renewals:
        details = _matching(passages, r'续租租金|续约价格|续期(?:租金|费用)|续费金额')
        detail = next((source for source in details if source['id'] != renewals[0]['id']), None)
        index = passages.index(renewals[0])
        previous = passages[index - 1] if index else None
        sources = [renewals[0]]
        if previous and re.search(r'(?:续租|续约|续费|续签).*通知', re.sub(r'\s+', '', previous['text'])):
            sources.append(previous)
        if detail and detail not in sources:
            sources.append(detail)
        yield (
            r'续租|续约|续费|续签',
            {'topic': 'renewal', 'title': '自动续约的通知期限和续期费用',
             'trigger': '合同即将到期，需要决定是否续约时。',
             'consequence': '符合所引条款的自动续约条件时，可能继续承担下一期的费用和义务。',
             'question': '如果我不续约，最迟要在哪天用什么方式通知？若触发续约，续期多久、费用怎么定？',
             'evidence': [_evidence(source) for source in sources], 'priority': None},
        )

    deductions = _matching(passages, r'(?=.*押金)(?=.*扣)(?=.*(?:维修|清洁|恢复原状))')
    if deductions:
        yield (
            r'维修|清洁|恢复原状|磨损',
            {'topic': 'liability', 'title': '押金扣除维修和清洁费用的标准',
             'trigger': '结算押金时。',
             'consequence': '若相关费用按合同从押金扣除，实际退回金额会减少，需核对适用范围和计价。',
             'question': '哪些维修、清洁或恢复费用可以从押金扣除？正常磨损如何处理，能否提供计价标准和扣款凭证？',
             'evidence': [_evidence(deductions[0])], 'priority': None},
        )

    payments = _matching(passages, r'(?=.*(?:预付款|首付款|合同总价|价款|尾款))(?=.*(?:支付|付款|退还|不退))')
    if payments:
        yield (
            r'预付款|首付款|尾款|付款|价款',
            {'topic': 'payment', 'generic': True, 'title': '预付款、尾款和退款条件',
             'trigger': '签约后付款或合同解除需要结算时。',
             'consequence': '预付款或尾款可能已经支付，但退款、抵扣和结算顺序没有写清。',
             'question': '预付款和尾款分别在什么条件下支付、什么情况下退还？合同解除时已付款项如何结算？',
             'evidence': [_evidence(payments[0])], 'priority': None},
        )

    terminations = _matching(passages, r'(?=.*(?:解除|终止|退出|退租))(?=.*(?:通知|补偿|退款|结算|不退|扣))')
    if terminations:
        yield (
            r'解除|终止|退出|退租',
            {'topic': 'exit', 'generic': True, 'title': '提前解除或退出的通知与结算',
             'trigger': '一方需要提前解除或退出合同时。',
             'consequence': '解除条件、通知期、已付款项和未履行部分如何结算不明确，可能产生额外扣费。',
             'question': '提前解除或退出需要提前多久通知？已付款项、未使用服务和违约金分别如何结算？',
             'evidence': [_evidence(terminations[0])], 'priority': None},
        )

    acceptance = _matching(passages, r'(?=.*(?:验收|交付|安装))(?=.*(?:标准|期限|视为|合格|日内|工作日))')
    if acceptance:
        yield (
            r'验收|交付|安装',
            {'topic': 'performance', 'generic': True, 'title': '验收标准与逾期未验收的后果',
             'trigger': '设备或服务交付、安装完成时。',
             'consequence': '验收标准、验收期限和逾期未验收的后果不清，可能影响尾款和索赔。',
             'question': '验收的具体标准是什么？多少天内验收？逾期未验收是否视为合格？',
             'evidence': [_evidence(acceptance[0])], 'priority': None},
        )

    warranty = _matching(passages, r'(?=.*(?:质保|保修|维修))(?=.*(?:期限|范围|费用|不承担|排除|易耗))')
    if warranty:
        yield (
            r'质保|保修|维修',
            {'topic': 'performance', 'generic': True, 'title': '质保范围、期限和维修费用',
             'trigger': '设备或服务出现故障、需要维修时。',
             'consequence': '质保范围、期限和维修费用承担不清，可能把维修成本转给用户。',
             'question': '质保期多长、覆盖哪些部件和故障？维修响应时间和费用由谁承担？',
             'evidence': [_evidence(warranty[0])], 'priority': None},
        )

    changes = _matching(passages, r'(?=.*(?:变更|调整|替代))(?=.*(?:单方|有权|通知|价格|型号))')
    if changes:
        yield (
            r'变更|调整|替代',
            {'topic': 'performance', 'generic': True, 'title': '单方变更价格、型号或服务内容',
             'trigger': '供应商调整价格、设备型号或服务范围时。',
             'consequence': '一方可能单方面改变合同内容，用户缺少协商、拒绝或退出机制。',
             'question': '价格、型号或服务内容变更需要谁同意？用户能否拒绝变更或解除合同？',
             'evidence': [_evidence(changes[0])], 'priority': None},
        )

    disputes = _matching(passages, r'(?=.*(?:仲裁|管辖|诉讼|争议))(?=.*(?:法院|仲裁|香港|内地))')
    if disputes:
        yield (
            r'仲裁|管辖|诉讼|争议',
            {'topic': 'other', 'generic': True, 'title': '争议解决方式和管辖地',
             'trigger': '双方发生争议时。',
             'consequence': '仲裁与诉讼、管辖地和维权成本不清，可能增加解决争议的难度。',
             'question': '争议由仲裁还是法院处理？具体机构和地点在哪里？律师费由谁承担？',
             'evidence': [_evidence(disputes[0])], 'priority': None},
        )


def _ensure_coverage(candidates, passages):
    covered = []
    for pattern, fallback in _coverage_items(passages):
        if fallback.get('generic'):
            candidate = next((item for item in candidates if item not in covered
                              and item['topic'] == fallback['topic']), None)
        else:
            anchor = fallback['evidence'][0]['id']
            candidate = next((item for item in candidates if item not in covered
                              and re.search(pattern, item['title'] + item['question'])
                              and (any(source['id'] == anchor for source in item['evidence'])
                                   or (fallback['topic'] == 'exit'
                                       and any('押金' in source['quote'] for source in item['evidence'])))
                              and (fallback['topic'] != 'exit' or any(
                                  '违约金' in source['quote'] for source in item['evidence']))), None)
        if candidate is None:
            candidate = fallback
            candidates.append(candidate)
        elif fallback['topic'] in ('exit', 'renewal'):
            # One precise question with the relevant conditions is preferable
            # to an overlapping card asking only whether a clause exists.
            candidate.update(fallback)
        covered.append(candidate)
    return covered


def _apply_rule_priorities(cards):
    for card in cards:
        priority = _rule_priority(card)
        card['priority'] = priority
        card['priority_source'] = 'rule' if priority else None
        card['priority_confidence'] = 0.85 if priority else None


def _call_intern_priority(cards, role):
    base = os.getenv('VAM_INTERN_URL', 'http://127.0.0.1:8010/score')
    parts = urlsplit(base)
    url = urlunsplit(parts._replace(path=parts.path.rstrip('/').removesuffix('/score') + '/priority'))
    payload = {'role': role, 'items': [
        {'id': card['id'], 'title': card['title'], 'trigger': card['trigger'],
         'consequence': card['consequence'], 'question': card['question'],
         'quotes': [entry['quote'] for entry in card['evidence']]}
        for card in cards
    ]}
    decisions = {}
    confidences = {}
    model = None
    for offset in range(0, len(cards), 5):
        response = requests.post(url, json={**payload, 'items': payload['items'][offset:offset + 5]}, timeout=25)
        response.raise_for_status()
        data = response.json()
        choices = data.get('priorities')
        if not isinstance(choices, dict) or not isinstance(data.get('model'), str):
            raise ValueError('Invalid priority response')
        decisions.update(choices)
        if isinstance(data.get('confidence'), dict):
            confidences.update(data['confidence'])
        model = data['model']
    for card in cards:
        choice = decisions.get(card['id'])
        card['priority'] = choice if choice in PRIORITIES else None
        card['priority_source'] = 'intern' if card['priority'] else None
        confidence = confidences.get(card['id'])
        card['priority_confidence'] = float(confidence) if isinstance(confidence, (int, float)) else None
    return model


def _call_qwen_priority(cards, role):
    cfg = default_llm_cfg()
    if cfg.get('model_server'):
        cfg['generate_cfg'] = {**cfg.get('generate_cfg', {}), 'response_format': {'type': 'json_object'}}
    lines = []
    for card in cards:
        quotes = ' / '.join(entry.get('quote', '') for entry in card.get('evidence', []))
        lines.append(
            f'[{card["id"]}] {card["title"]}\n'
            f'原文：{quotes}\n条件：{card["trigger"]}\n'
            f'可能后果：{card["consequence"]}\n问题：{card["question"]}'
        )
    user = f'用户身份：{role}\n待判断事项：\n' + '\n\n'.join(lines)
    raw, _ = _generate_json(cfg, PRIORITY_SYSTEM, user, temperature=0.0, max_tokens=1200)
    choices = raw.get('priorities')
    if not isinstance(choices, dict):
        raise ValueError('Invalid priority response')
    confidences = raw.get('confidence') if isinstance(raw.get('confidence'), dict) else {}
    for card in cards:
        choice = choices.get(card['id'])
        card['priority'] = choice if choice in PRIORITIES else None
        card['priority_source'] = 'qwen' if card['priority'] else None
        confidence = confidences.get(card['id'])
        card['priority_confidence'] = float(confidence) if isinstance(confidence, (int, float)) else None
    return cfg.get('model') or 'qwen'


def _prioritize(cards, role):
    provider = os.getenv('CHECKLIST_PRIORITY_PROVIDER', 'cascade').strip().lower()
    if provider not in {'rules', 'hybrid', 'intern', 'qwen', 'cascade'}:
        provider = 'cascade'

    if provider == 'intern':
        for card in cards:
            card['priority'] = None
            card['priority_source'] = None
            card['priority_confidence'] = None
        pending = cards
    else:
        _apply_rule_priorities(cards)
        pending = [card for card in cards if card['priority'] is None]

    if provider == 'rules' or not pending:
        warning = None if all(card['priority'] for card in cards) else '部分事项暂未定级，按生成顺序展示。'
        return '规则优先级', warning

    if provider == 'cascade':
        try:
            intern_model = _call_intern_priority(pending, role)
        except (requests.RequestException, TypeError, ValueError, AttributeError) as exc:
            logger.warning('Intern priority unavailable, falling back to Qwen: %s', type(exc).__name__)
            intern_model = None

        try:
            confidence_floor = float(os.getenv('CHECKLIST_INTERN_CONFIDENCE', '0.6'))
        except ValueError:
            confidence_floor = 0.6
        needs_qwen = [
            card for card in pending
            if card.get('priority') is None
            or card.get('priority_confidence') is None
            or float(card['priority_confidence']) < confidence_floor
        ]
        qwen_model = None
        if needs_qwen:
            try:
                qwen_model = _call_qwen_priority(needs_qwen, role)
            except (requests.RequestException, TypeError, ValueError, AttributeError) as exc:
                logger.warning('Qwen priority fallback unavailable: %s', type(exc).__name__)

        models = [name for name in (intern_model, qwen_model) if name]
        warning = None if all(card['priority'] for card in cards) else '部分事项暂未定级，按生成顺序展示。'
        return ' + '.join(models) if models else '规则优先级', warning

    try:
        if provider == 'qwen':
            model = _call_qwen_priority(pending, role)
        else:
            model = _call_intern_priority(pending, role)
        warning = None if all(card['priority'] for card in cards) else '部分事项暂未定级，按生成顺序展示。'
        return model, warning
    except (requests.RequestException, TypeError, ValueError, AttributeError) as exc:
        logger.warning('Checklist priority unavailable: %s', type(exc).__name__)
        return '规则优先级', '优先级服务暂不可用，已按规则和生成顺序展示。'



def _document_sources(filename, content):
    label = Path(filename).name[:240]
    suffix = Path(label).suffix.lower()
    if suffix not in ('.pdf', '.txt'):
        raise ValueError('请选择 PDF 或 UTF-8 TXT 合同。')
    if suffix == '.txt':
        try:
            return [{'filename': label, 'page': None, 'kind': 'text',
                     'text': content.decode('utf-8-sig')}]
        except UnicodeDecodeError as exc:
            raise ValueError('TXT 请使用 UTF-8 编码。') from exc
    try:
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'contract.pdf'
            path.write_bytes(content)
            pages = read_pages(str(path))
    except DocumentReadError as exc:
        raise ValueError('无法读取 PDF，请检查文件是否完整或已解锁。') from exc
    return [{'filename': label, 'page': page.page, 'kind': 'pdf', 'text': page.text} for page in pages]


def _dedupe_cards(cards):
    """Remove exact and near-duplicate questions, keeping the first wording."""
    kept = []
    for card in cards:
        question = re.sub(r'[\W_]+', '', str(card.get('question', ''))).casefold()
        title = re.sub(r'[\W_]+', '', str(card.get('title', ''))).casefold()
        if not question:
            continue
        duplicate = False
        for existing in kept:
            other_question = re.sub(r'[\W_]+', '', str(existing.get('question', ''))).casefold()
            other_title = re.sub(r'[\W_]+', '', str(existing.get('title', ''))).casefold()
            same_topic = card.get('topic') == existing.get('topic')
            question_ratio = SequenceMatcher(None, question, other_question).ratio()
            title_ratio = SequenceMatcher(None, title, other_title).ratio()
            if question_ratio >= 0.86 or (same_topic and title_ratio >= 0.8):
                duplicate = True
                break
        if not duplicate:
            kept.append(card)
    return kept


def _emit_progress(progress, stage, status, detail='', payload=None):
    if not progress:
        return
    try:
        if payload is not None:
            try:
                progress(stage, status, detail, payload)
                return
            except TypeError:
                pass
        progress(stage, status, detail)
    except Exception:
        pass


def generate_checklist(role='', text='', filename='', content=None, evidence=None, progress=None, contents=None):
    role = role.strip()[:80] or '身份未指定，优先提示对双方都需要明确的事项'
    if not text.strip() and content is None and not contents and not evidence:
        raise ValueError('请至少提供一种材料：上传文件、粘贴条款或带入原文。')
    _emit_progress(progress, 'parse', 'running', '正在读取合同材料。')
    sources = []
    if contents:
        for name, data in contents:
            sources.extend(_document_sources(name, data))
    elif content is not None:
        sources.extend(_document_sources(filename, content))
    if text.strip():
        sources.append({'filename': '粘贴的条款', 'page': None, 'kind': 'text', 'text': text})
    if evidence:
        for item in evidence:
            try:
                selected = VamEvidenceInput.model_validate(item)
                resolved = resolve_evidence([selected])
                sources.extend({'filename': entry['filename'], 'page': entry['page'],
                                'kind': 'pdf', 'text': entry['quote']} for entry in resolved)
            except (ValueError, TypeError):
                # Evidence can outlive an upload session or reference a PDF that
                # is no longer available. The quote itself is still valid input.
                if isinstance(item, dict) and str(item.get('quote', '')).strip():
                    sources.append({
                        'filename': str(item.get('filename') or '所选原文'),
                        'page': item.get('page'),
                        'kind': 'text',
                        'text': str(item['quote']),
                    })
    sources = [source for source in sources if source['text'].strip()]
    if not sources:
        raise ValueError('没有读到可分析的文本。扫描图片请先转换为可复制文本。')
    if sum(len(source['text']) for source in sources) > MAX_SOURCE_CHARS:
        raise ValueError('材料超过 24000 字，请粘贴要核对的章节或从合同核验带入原文。')
    passages = _passages(sources)
    _emit_progress(progress, 'parse', 'done', f'读取 {len(sources)} 段材料，切分 {len(passages)} 个片段。')
    _emit_progress(progress, 'generate', 'running', '正在生成待确认问题。')

    cfg = default_llm_cfg()
    if cfg.get('model_server'):
        cfg['generate_cfg']['response_format'] = {'type': 'json_object'}
    candidates = []
    seen = set()
    for segment in _segment(passages):
        prompt = f'用户身份：{role}\n\n' + '\n\n'.join(
            f'[{source["id"]}] {source["text"]}' for source in segment
        )
        raw, _ = _generate_json(cfg, SYSTEM, prompt, temperature=0.1, max_tokens=3600)
        for card in _cards(raw, segment):
            key = re.sub(r'[\W_]+', '', card['question']).casefold()
            if key and key not in seen:
                seen.add(key)
                candidates.append(card)
    coverage = _ensure_coverage(candidates, passages)
    candidates = _dedupe_cards(candidates)
    coverage = [card for card in coverage if card in candidates]
    for index, card in enumerate(candidates, 1):
        card['id'] = f'C{index}'
    _emit_progress(progress, 'generate', 'done', f'已生成 {len(candidates)} 条候选问题。')
    _emit_progress(
        progress,
        'priority',
        'running',
        '正在判断哪些问题必须优先确认。',
        payload={'items': [dict(card) for card in candidates]},
    )
    model, warning = None, None
    if candidates:
        try:
            model, warning = _prioritize(candidates, role)
        except (requests.RequestException, TypeError, ValueError, AttributeError) as exc:
            logger.warning('Checklist priority unavailable: %s', type(exc).__name__)
            warning = '优先级服务暂不可用，清单按生成顺序展示。'
    _emit_progress(progress, 'priority', 'done', '优先级判断完成。')
    priority_order = {name: index for index, name in enumerate(PRIORITIES)}
    candidates.sort(key=lambda item: priority_order.get(item['priority'], len(PRIORITIES)))
    # 所有 must/should 都保留；reference 只用于补足数量，最多 CHECKLIST_MAX_ITEMS 条。
    max_items = _max_items()
    chosen = []
    chosen_ids = set()

    def add_card(card):
        if card['id'] not in chosen_ids:
            chosen_ids.add(card['id'])
            chosen.append(card)

    for card in coverage:
        add_card(card)
    for card in candidates:
        if card['priority'] in {'must_confirm', 'should_confirm'}:
            add_card(card)
    for card in candidates:
        if len(chosen) >= max_items:
            break
        if card['priority'] not in {'must_confirm', 'should_confirm'}:
            add_card(card)
    included = chosen_ids
    scope = '所选原文' if evidence else '所上传文件的可读取文本' if content is not None else '粘贴的条款'
    result_items = [card for card in candidates if card['id'] in included]
    _emit_progress(progress, 'done', 'done', f'生成完成，共 {len(result_items)} 条待确认事项。')
    return {'items': result_items,
            'priority_model': model, 'warning': warning, 'scope': scope,
            'source_count': len(sources)}
