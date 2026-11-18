"""基于规则的条款抽取。

模型不是必需的：默认全部用正则 + 句界切分完成；
模型抽取器只能"提议原文片段"，本模块负责把片段定位回页码与字符区间，
并从片段里确定性提取金额、比例、期限、条件等字段。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .schema import Clause, ClauseType, Document, EvidenceSpan, PageText

# ---------------------------------------------------------------------------
# 关键词与句界
# ---------------------------------------------------------------------------

CLAUSE_KEYWORDS: Dict[ClauseType, Tuple[str, ...]] = {
    ClauseType.REFUND: (
        '退费', '退款', '退还', '退卡', '退租', '退课', '返还',
        # 口语 / 方言
        '退钱', '返钱', '退回来', '把钱退', '给退', '能退', '退得了', '退返', '全退',
        # 英文
        'refund', 'refundable', 'reimburse', 'reimbursement', 'money back', 'money-back',
    ),
    ClauseType.PENALTY: (
        '违约金', '违约责任', '违约费用', '违约赔偿', '罚金', '赔偿金',
        '提前解除', '提前终止', '提前退租', '提前退课', '毁约',
        # 口语 / 方言
        '违约', '赔钱', '赔偿', '赔', '罚款', '罚钱',
        # 英文
        'penalty', 'penalties', 'liquidated damages', 'breach of contract',
        'early termination fee', 'termination fee', 'cancellation fee',
        'cancellation charge', 'forfeit', 'forfeiture',
    ),
    ClauseType.AUTO_RENEWAL: (
        '自动续费', '自动续租', '自动扣费', '自动扣款', '自动展期', '自动延期',
        '视为同意续费', '视为同意续租', '续费一年', '续租一年', '到期自动', '期满自动',
        '不会扣款', '无需续费', '不自动续费', '不自动续租',
        # 口语 / 方言
        '续订', '续约', '顺延', '自动续', '到期继续', '到期接着', '自动扣钱',
        # 英文
        'auto-renew', 'auto renew', 'auto-renewal', 'automatic renewal',
        'automatically renew', 'renew automatically', 'renews automatically',
        'recurring charge', 'recurring billing', 'auto-charge', 'auto-debit',
    ),
    ClauseType.SERVICE_TERM: (
        '服务期限', '合同期限', '租赁期限', '租期', '有效期', '服务期', '服务周期',
        '课程共', '课程时长', '课程为期', '学习期', '会员期',
        # 口语 / 方言
        '期限', '时长', '合同期', '包一年', '用一年', '学一年', '租一年',
        # 英文
        'service term', 'contract term', 'lease term', 'term of service',
        'service period', 'validity period', 'valid until', 'valid for', 'duration',
        'membership period', 'course duration', 'course lasts', 'for a period of',
    ),
    ClauseType.EXTRA_FEE: (
        '其他费用', '额外收费', '另行收费', '另行收取', '另收', '附加费', '杂费',
        '教材费', '服装费', '材料费', '资料费', '无需另付',
        '储物柜', '体测', '改约', '管理费', '物业费', '网费', '清洁费', '维修费', '印花税',
        # 口语 / 方言
        '加钱', '加收', '另算', '另外算', '多收钱', '乱收费', '额外的钱', '另外掏钱',
        # 英文
        'additional fee', 'extra fee', 'surcharge', 'service charge',
        'maintenance fee', 'cleaning fee', 'admin fee', 'administration fee',
        'registration fee', 'late fee', 'materials fee', 'processing fee',
        'hidden fee', 'no extra charge', 'no additional fees', 'all-inclusive',
    ),
}

_PENALTY_WORDS = (
    '违约金', '违约责任', '违约费用', '违约赔偿', '罚金', '赔偿金', '罚钱', '赔钱',
    'penalty', 'penalties', 'liquidated damages', 'termination fee',
    'cancellation fee', 'cancellation charge', 'forfeit',
)
_REFUND_WORDS = ('退费', '退款', '退还', '退钱', '返还', 'refund')

_SENTENCE_END = '。；;！？'
_CLAUSE_REF_RE = re.compile(r'第[一二三四五六七八九十百零]+条')
_DATE_CN_RE = re.compile(r'(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日')
_DATE_ISO_RE = re.compile(r'(20\d{2})-(\d{1,2})-(\d{1,2})')

_PERCENT_RES = (
    re.compile(r'(\d+(?:\.\d+)?)\s*%'),
    re.compile(r'(\d+(?:\.\d+)?)\s*(?:percent|per\s*cent|个?点)', re.I),
)
_CN_PERCENT_RE = re.compile(r'百分之\s*(\d+(?:\.\d+)?|[一二两三四五六七八九十百零]+)')
_CHENG_RE = re.compile(r'([一二两三四五六七八九十])\s*成')

_MONEY_RES = (
    re.compile(r'(?:RMB|CNY|HKD|HK\$|US\$|[$￥¥])\s*(\d[\d,]*(?:\.\d+)?)', re.I),
    re.compile(r'(\d[\d,]*(?:\.\d+)?)\s*(?:元|块|蚊|dollars?|yuan|RMB|CNY|HKD)', re.I),
    re.compile(r'([一二两三四五六七八九十百千零]{1,8})\s*(?:元|块|蚊)'),
)
_PER_UNIT_RES = (
    re.compile(
        r'(?:RMB|CNY|HKD|HK\$|US\$|[$￥¥])?\s*'
        r'(\d[\d,]*(?:\.\d+)?|[一二两三四五六七八九十百千零]{1,8})'
        r'\s*(?:元|块|蚊|HKD|RMB|CNY)?\s*(?:/|每)\s*'
        r'(年|月|次|节|课时|天|周|期|学期|学年|季度|人|'
        r'months?|years?|sessions?|lessons?|days?|weeks?|terms?|quarters?|persons?)',
        re.I,
    ),
    re.compile(
        r'每\s*(年|月|次|节|课时|天|周|期|学期|学年|季度|人)\s*'
        r'(\d[\d,]*(?:\.\d+)?|[一二两三四五六七八九十百千零]{1,8})\s*(?:元|块|蚊)',
    ),
    re.compile(
        r'(?:RMB|CNY|HKD|HK\$|US\$|[$￥¥])?\s*'
        r'(\d[\d,]*(?:\.\d+)?|[一二两三四五六七八九十百千零]{1,8})'
        r'\s*(?:元|块|蚊|HKD|RMB|CNY)?\s*(?:per|a|each|/)\s*'
        r'(months?|years?|sessions?|lessons?|days?|weeks?|terms?|quarters?|persons?)',
        re.I,
    ),
)
_UNIT_NORMALIZE = {
    'month': '月', 'months': '月', 'year': '年', 'years': '年',
    'session': '次', 'sessions': '次', 'lesson': '节', 'lessons': '节',
    'day': '天', 'days': '天', 'week': '周', 'weeks': '周',
    'term': '期', 'terms': '期', 'quarter': '季度', 'quarters': '季度',
    'person': '人', 'persons': '人',
}
_EN_NUMBER_WORDS = {
    'a': 1, 'an': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10, 'eleven': 11,
    'twelve': 12,
}
_DURATION_RES = (
    re.compile(r'(\d{1,3}|[一二两三四五六七八九十]{1,3})\s*(个月|年|月|周|星期|日|天)'),
    re.compile(
        r'(\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|an?)\s*'
        r'(months?|years?|weeks?|days?)',
        re.I,
    ),
)
_EN_DURATION_UNITS = {'month': '个月', 'months': '个月', 'year': '年', 'years': '年',
                      'week': '周', 'weeks': '周', 'day': '天', 'days': '天'}
_NOTICE_RES = (
    re.compile(r'(?:届满前|提前|于)\s*(\d{1,3})\s*(?:个)?(?:工作日|日|天)'),
    re.compile(r'提前\s*([一二两三四五六七八九十]{1,2})\s*(?:个)?月'),
    re.compile(r'(\d{1,3})\s*(?:days?[\'’]?|天)\s*(?:prior|before|in\s+advance|notice)', re.I),
    re.compile(r'notice\s*(?:period\s*)?of\s*(\d{1,3})\s*(?:days?|天)', re.I),
)
_CAP_RE = re.compile(
    r'(?:超过|more\s+than|over|after)\s*(\d{1,3}|[一二两三四五六七八九十]{1,3})\s*'
    r'(?:节|课时|次|lessons?|sessions?)'
    r'.{0,24}?(?:不支持|不予|不能|拒绝|无法|不退|不给退|退不了|'
    r'no\s+refund|non[- ]?refundable|not\s+refundable)',
    re.I,
)
# 英文常把否定放在前面：non-refundable after 12 lessons
_CAP_REV_RE = re.compile(
    r'(?:no\s+refund|non[- ]?refundable|not\s+refundable|不支持退|不予退|不退|不给退|退不了)'
    r'.{0,30}?(?:超过|more\s+than|over|after)?\s*'
    r'(\d{1,3}|[一二两三四五六七八九十]{1,3})\s*(?:节|课时|次|lessons?|sessions?)',
    re.I,
)

_CN_DIGITS = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
              '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
_CN_UNITS = {'十': 10, '百': 100, '千': 1000, '万': 10000}


def _has_keyword(text: str, keyword: str) -> bool:
    """英文关键词按大小写不敏感、忽略空格匹配；中文保持原样子串匹配。"""
    if keyword.isascii():
        return (keyword.lower().replace(' ', '')
                in text.lower().replace(' ', ''))
    return keyword in text


def _cn_number(text: str) -> Optional[float]:
    """解析「两百」「一百二十」「三千五」等中文数字。"""
    if not text:
        return None
    if text.isdigit():
        return float(text)
    total = 0.0
    section = 0.0
    number = 0.0
    for char in text:
        if char in _CN_DIGITS:
            number = float(_CN_DIGITS[char])
        elif char in _CN_UNITS:
            unit = _CN_UNITS[char]
            if unit == 10000:
                total += (section + number) * unit
                section = 0.0
            else:
                if number == 0:
                    number = 1.0
                section += number * unit
            number = 0.0
        else:
            return None
    return total + section + number


def _cn_to_int(text: str) -> Optional[int]:
    if text.isdigit():
        return int(text)
    if text == '十':
        return 10
    if '十' in text:
        left, _, right = text.partition('十')
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    if len(text) == 1:
        return _CN_DIGITS.get(text)
    return None


def _normalize_with_map(text: str) -> Tuple[str, List[int]]:
    """去掉空白用于匹配，同时记录每个字符回到原文的下标。"""
    chars: List[str] = []
    index_map: List[int] = []
    for index, char in enumerate(text):
        if char.isspace():
            continue
        chars.append(char)
        index_map.append(index)
    return ''.join(chars), index_map


def _sentence_spans(normalized: str) -> List[Tuple[int, int]]:
    spans: List[Tuple[int, int]] = []
    start = 0
    for index, char in enumerate(normalized):
        boundary = char in _SENTENCE_END
        if char == '.':
            previous = normalized[index - 1] if index else ''
            following = normalized[index + 1] if index + 1 < len(normalized) else ''
            # 只在句末/后接大写时切分，避免把 5.5、a.m. 等切开
            boundary = (
                not previous.isdigit()
                and not following.isdigit()
                and (not following or not following.islower())
            )
        if boundary:
            if index > start:
                spans.append((start, index))
            start = index + 1
    if start < len(normalized):
        spans.append((start, len(normalized)))
    return spans


# ---------------------------------------------------------------------------
# 字段抽取
# ---------------------------------------------------------------------------

def _mask_dates(text: str) -> Tuple[str, List[str]]:
    dates: List[str] = []

    def replace(match: re.Match) -> str:
        year, month, day = match.group(1), int(match.group(2)), int(match.group(3))
        dates.append(f'{year}-{month:02d}-{day:02d}')
        return ' ' * len(match.group(0))

    masked = _DATE_CN_RE.sub(replace, text)
    masked = _DATE_ISO_RE.sub(replace, masked)
    return masked, dates


def _as_float(raw: str) -> float:
    return float(raw.replace(',', ''))


def _amount_value(raw: str) -> Optional[float]:
    if re.fullmatch(r'[\d,]+(?:\.\d+)?', raw):
        return _as_float(raw)
    return _cn_number(raw)


def _percent_values(masked: str) -> List[float]:
    values = set()
    for pattern in _PERCENT_RES:
        for match in pattern.finditer(masked):
            values.add(round(float(match.group(1)) / 100, 4))
    for match in _CN_PERCENT_RE.finditer(masked):
        number = _cn_number(match.group(1))
        if number is not None:
            values.add(round(number / 100, 4))
    for match in _CHENG_RE.finditer(masked):
        digit = _CN_DIGITS.get(match.group(1))
        if digit:
            values.add(round(digit / 10, 4))
    return sorted(values)


def _per_unit_values(masked: str) -> Tuple[List[Dict[str, Any]], List[Tuple[int, int]]]:
    items: List[Dict[str, Any]] = []
    spans: List[Tuple[int, int]] = []
    for index, pattern in enumerate(_PER_UNIT_RES):
        for match in pattern.finditer(masked):
            spans.append((match.start(), match.end()))
            if index == 1:
                unit_raw, amount_raw = match.group(1), match.group(2)
            else:
                amount_raw, unit_raw = match.group(1), match.group(2)
            value = _amount_value(amount_raw)
            if value is None:
                continue
            unit = _UNIT_NORMALIZE.get(unit_raw.lower(), unit_raw)
            items.append({'amount': round(value, 2), 'unit': unit})
    unique: List[Dict[str, Any]] = []
    seen = set()
    for item in items:
        key = (item['amount'], item['unit'])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique, spans


def _duration_value(raw: str) -> Optional[int]:
    if raw.isdigit():
        return int(raw)
    lowered = raw.lower()
    if lowered in _EN_NUMBER_WORDS:
        return _EN_NUMBER_WORDS[lowered]
    return _cn_to_int(raw)


def extract_fields(text: str) -> Dict[str, Any]:
    """从一段原文里确定性提取可比对字段。"""
    masked, dates = _mask_dates(text)
    rates = _percent_values(masked)

    unique_per_unit, unit_spans = _per_unit_values(masked)

    amounts: List[float] = []
    for pattern in _MONEY_RES:
        for match in pattern.finditer(masked):
            if any(start < match.end() and match.start() < end for start, end in unit_spans):
                continue
            raw = match.group(1)
            if re.fullmatch(r'[\d,]+(?:\.\d+)?', raw):
                value: Optional[float] = _as_float(raw)
            else:
                value = _cn_number(raw)
            if value is None:
                continue
            amounts.append(round(value, 2))
    amounts = sorted(set(amounts))

    durations: List[Dict[str, Any]] = []
    for pattern in _DURATION_RES:
        for match in pattern.finditer(masked):
            value = _duration_value(match.group(1))
            unit_raw = match.group(2)
            unit = _EN_DURATION_UNITS.get(unit_raw.lower(), unit_raw)
            if value is None or value > 120:
                continue
            durations.append({'value': value, 'unit': unit})

    notice_days: Optional[int] = None
    for index, pattern in enumerate(_NOTICE_RES):
        notice_match = pattern.search(masked)
        if not notice_match:
            continue
        if index == 1:  # 「提前一个月」按 30 日计
            months = _cn_to_int(notice_match.group(1))
            notice_days = months * 30 if months else None
        else:
            notice_days = int(notice_match.group(1))
        if notice_days is not None:
            break

    conditions: List[str] = []
    cap_match = _CAP_RE.search(masked) or _CAP_REV_RE.search(masked)
    if cap_match:
        cap = _cn_to_int(cap_match.group(1))
        if cap:
            conditions.append(f'used_sessions>{cap}:no_refund')
    if '书面' in masked or re.search(r'written\s+notice', masked, re.I):
        conditions.append('written_notice')

    no_refund = bool(re.search(
        r'non[- ]?refundable|not\s+refundable|no\s+refunds?|cannot\s+be\s+refunded'
        r'|no\s+cancellation|不(?:给|予|支持|能|让|得)?退(?:钱|费|款|课)|退不了|没得退',
        masked, re.I,
    ))

    flags = {
        'full_refund': bool(re.search(
            r'(?<!不)(?<!能)全额退|无条件退|全额返还|无理由退|一分不扣|全额给回|全退'
            r'|full\s+refund|100%\s*refund|unconditional\s+refund'
            r'|money[- ]back\s+guarantee|no[- ]questions[- ]asked',
            masked, re.I,
        )) and not no_refund,
        'free_of_charge': bool(re.search(
            r'不(?:再|另行|另外|额外)?(?:收取|收|扣).{0,6}(?:手续费|费用|费)|无需另(?:付|收)|不必另付'
            r'|无任何额外收费|无额外收费|全部免费|绝不收取|零手续费|已包含在|含在.{0,4}内|一价全包'
            r'|不(?:会|用|需要|必)?(?:再)?(?:加钱|另收|多收|额外收|另算|多掏)|不加钱|不另收'
            r'|一分不扣|不扣一分'
            r'|包在(?:里|内)|含在(?:里|内)'
            r'|no\s+(?:extra|additional|hidden|other)\s+(?:fee|fees|charge|charges|cost|costs)'
            r'|free\s+of\s+charge|at\s+no\s+(?:extra\s+)?cost|all[- ]inclusive'
            r'|included\s+in\s+the\s+(?:price|fee)|zero\s+fee',
            masked, re.I,
        )),
        'auto_renewal': bool(re.search(
            r'自动续费|自动续租|自动续期|自动扣费|自动扣款|自动展期|自动延期|视为同意续费|视为同意续租'
            r'|续订|续约|顺延'
            r'|auto[- ]?renew(?:al|s|ed)?|automatically\s+renews?|automatic\s+renewal'
            r'|renews?\s+automatically|recurring\s+(?:charge|billing|payment)'
            r'|auto[- ]?(?:charge|debit)',
            masked, re.I,
        )) and not bool(re.search(
            r'不自动续费|不自动续租|无需自动续费|不会自动续|不会扣款|不扣款|不会扣钱|不再扣钱|不会再扣钱'
            r'|到期(?:就|自动)?(?:停|结束|终止)|到期不续|不再续|不用续'
            r'|不会\s*auto[- ]?renew|不\s*auto[- ]?renew'
            r'|will\s+not\s+(?:auto[- ]?renew|renew)|does\s+not\s+auto[- ]?renew'
            r'|no\s+auto[- ]?renewal|not\s+automatically\s+renewed',
            masked, re.I,
        )),
        'no_auto_renewal': bool(re.search(
            r'不自动续费|不自动续租|不设.{0,4}续租|不会扣款|不扣款|到期自动结束|无需续费'
            r'|不会扣钱|不再扣钱|不会再扣钱|不会自动续|到期(?:就|自动)?(?:停|结束|终止)|到期不续|不再续|不用续'
            r'|不会\s*auto[- ]?renew|不\s*auto[- ]?renew'
            r'|will\s+not\s+(?:auto[- ]?renew|renew)|does\s+not\s+auto[- ]?renew'
            r'|no\s+auto[- ]?renewal|not\s+automatically\s+renewed'
            r'|ends?\s+automatically|expires?\s+automatically',
            masked, re.I,
        )),
        'no_penalty': bool(re.search(
            r'(?:不|无需|免)(?:收取|支付|承担|须|需)?[^，。；]{0,6}(?:违约金|违约费用|违约赔偿|罚金|赔偿金)'
            r'|无(?:额外|任何)?(?:违约金|违约费用|罚金|赔偿金)'
            r'|不(?:用|需|要)?赔(?:钱)?|不罚钱|不罚款|不扣违约金|免(?:收)?违约金'
            r'|no\s+(?:early\s+termination|cancellation|breach)\s+(?:fee|fees|penalty|penalties|charge|charges)'
            r'|without\s+(?:any\s+)?penalty|free\s+to\s+cancel|no\s+penalty',
            masked, re.I,
        )),
        'refundable': bool(re.search(
            r'可.{0,6}退(?:费|款|课)|支持退(?:费|款|课)|随时退|无理由退|能退|可以退|给退|退得了'
            r'|refundable|eligible\s+for\s+a\s+refund|can\s+be\s+refunded'
            r'|entitled\s+to\s+a\s+refund',
            masked, re.I,
        )) and not no_refund,
        'no_refund': no_refund,
    }
    flags = {key: value for key, value in flags.items() if value}

    clause_ref_match = _CLAUSE_REF_RE.search(text)

    return {
        'amounts': amounts,
        'rates': rates,
        'per_unit_amounts': unique_per_unit,
        'durations': durations,
        'dates': dates,
        'notice_days': notice_days,
        'conditions': conditions,
        'flags': flags,
        'clause_ref': clause_ref_match.group(0) if clause_ref_match else '',
    }


def _confidence(fields: Dict[str, Any]) -> float:
    if fields['rates'] or fields['per_unit_amounts'] or fields['dates'] or fields['amounts']:
        return 0.9
    if fields['flags'] or fields['conditions']:
        return 0.75
    return 0.6


# ---------------------------------------------------------------------------
# 文档级抽取
# ---------------------------------------------------------------------------

def _iter_page_sentences(page: PageText):
    normalized, index_map = _normalize_with_map(page.text)
    for start, end in _sentence_spans(normalized):
        sentence = normalized[start:end]
        yield start, end, sentence, normalized, index_map


def build_clause(
    document: Document,
    page: PageText,
    clause_type: ClauseType,
    start: int,
    end: int,
    index_map: List[int],
    extractor: str = 'rules',
) -> Clause:
    """用归一化区间构造条款，并映射回原文页码/字符偏移。"""
    if not index_map or start >= len(index_map):
        raise ValueError('无效的字符区间')
    end = min(end, len(index_map))
    char_start = index_map[start]
    char_end = index_map[end - 1] + 1
    quote = page.text[char_start:char_end]
    fields = extract_fields(quote)
    return Clause(
        clause_type=clause_type,
        evidence=EvidenceSpan(
            document_id=document.document_id,
            filename=document.filename,
            role=document.role,
            page=page.page,
            chunk_id=f'{document.document_id}#p{page.page}',
            char_start=char_start,
            char_end=char_end,
            quote=quote,
        ),
        fields=fields,
        confidence=_confidence(fields),
        extractor=extractor,
    )


_SERVICE_TERM_DEFINITION_RE = re.compile(
    r'(?:服务期限|合同期限|租赁期限|租期|有效期|期限|时长|合同期)\s*(?:为|是|自|至|：|:|共)'
    r'|(?:service\s*term|contract\s*term|lease\s*term|term\s*of\s*service'
    r'|service\s*period|validity\s*period|membership\s*period|course\s*duration'
    r'|course\s*lasts|valid\s*until|valid\s*for|duration|for\s*a\s*period\s*of)'
    r'\s*(?:is|of|from|for|:|：)?'
    r'|20\d{2}'
    r'|(?:包|用|学|租)\s*(?:\d{1,3}|[一二两三四五六七八九十]{1,3})\s*(?:个月|年|月|周|天)',
    re.I,
)


def extract_document(document: Document) -> List[Clause]:
    """对一份材料做全量规则抽取，按类型/页码/位置排序。"""
    clauses: List[Clause] = []
    for page in document.pages:
        for start, end, sentence, _, index_map in _iter_page_sentences(page):
            for clause_type, keywords in CLAUSE_KEYWORDS.items():
                if not any(_has_keyword(sentence, keyword) for keyword in keywords):
                    continue
                # "服务期限届满前"是时间状语，不是服务期限条款本身
                if clause_type == ClauseType.SERVICE_TERM and not _SERVICE_TERM_DEFINITION_RE.search(sentence):
                    continue
                # "提前退课需支付违约金"是违约责任，不是退款条款
                if (clause_type == ClauseType.REFUND
                        and any(_has_keyword(sentence, word) for word in _PENALTY_WORDS)
                        and not any(_has_keyword(sentence, word) for word in _REFUND_WORDS)):
                    continue
                clauses.append(build_clause(
                    document, page, clause_type, start, end, index_map,
                ))
    clauses.sort(key=lambda c: (c.clause_type.value, c.evidence.page, c.evidence.char_start))
    return clauses


def locate_quote(document: Document, quote: str) -> Optional[Tuple[PageText, int, int]]:
    """在文档中定位一段原文，返回 (页, 归一化起点, 归一化终点)。

    模型给出的页码不直接采信；定位失败即丢弃该候选。
    """
    target, _ = _normalize_with_map(quote)
    if len(target) < 4:
        return None
    for page in document.pages:
        normalized, _ = _normalize_with_map(page.text)
        position = normalized.find(target)
        if position >= 0:
            return page, position, position + len(target)
    return None


def clauses_by_type(clauses: List[Clause]) -> Dict[ClauseType, List[Clause]]:
    table: Dict[ClauseType, List[Clause]] = {clause_type: [] for clause_type in ClauseType}
    for clause in clauses:
        table[clause.clause_type].append(clause)
    return table
