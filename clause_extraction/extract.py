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
    ClauseType.REFUND: ('退费', '退款', '退还', '退卡', '退租', '退课'),
    ClauseType.PENALTY: ('违约金', '违约责任', '提前解除', '提前终止', '提前退租', '毁约'),
    ClauseType.AUTO_RENEWAL: (
        '自动续费', '自动续租', '视为同意续费', '视为同意续租', '续费一年', '续租一年',
    ),
    ClauseType.SERVICE_TERM: ('服务期限', '合同期限', '租赁期限', '租期', '有效期', '服务期'),
    ClauseType.EXTRA_FEE: (
        '其他费用', '额外收费', '另行收费', '储物柜', '体测', '改约',
        '管理费', '物业费', '网费', '清洁费', '维修费', '印花税',
    ),
}

_SENTENCE_END = '。；;！？'
_CLAUSE_REF_RE = re.compile(r'第[一二三四五六七八九十百零]+条')
_DATE_CN_RE = re.compile(r'(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日')
_DATE_ISO_RE = re.compile(r'(20\d{2})-(\d{1,2})-(\d{1,2})')
_PERCENT_RE = re.compile(r'(\d+(?:\.\d+)?)\s*%')
_MONEY_RE = re.compile(r'(?:人民币|港币|HK\$|￥|¥)?\s*(\d[\d,]*(?:\.\d+)?)\s*元')
_PER_UNIT_RE = re.compile(r'(\d[\d,]*(?:\.\d+)?)\s*元\s*/\s*(年|月|次|节|课时|天)')
_PER_SESSION_RE = re.compile(r'每\s*(?:节|课时|次)\s*(\d[\d,]*(?:\.\d+)?)\s*元')
_DURATION_RE = re.compile(r'([0-9]{1,3}|[一二两三四五六七八九十]{1,3})\s*(个月|年|月|日|天)')
_NOTICE_RE = re.compile(r'(?:届满前|提前|于)\s*(\d{1,3})\s*(?:个)?(?:工作日|日|天)')
_CAP_RE = re.compile(r'超过\s*(\d{1,3})\s*(?:节|课时|次).{0,8}?(?:不支持|不予|不能|拒绝).{0,4}?退')

_CN_DIGITS = {'一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
              '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


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
        if char in _SENTENCE_END:
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


def extract_fields(text: str) -> Dict[str, Any]:
    """从一段原文里确定性提取可比对字段。"""
    masked, dates = _mask_dates(text)
    rates = sorted({round(_as_float(m.group(1)) / 100, 4) for m in _PERCENT_RE.finditer(masked)})

    per_unit: List[Dict[str, Any]] = []
    for match in _PER_UNIT_RE.finditer(masked):
        per_unit.append({'amount': round(_as_float(match.group(1)), 2), 'unit': match.group(2)})
    for match in _PER_SESSION_RE.finditer(masked):
        per_unit.append({'amount': round(_as_float(match.group(1)), 2), 'unit': '节'})
    seen_units = set()
    unique_per_unit = []
    for item in per_unit:
        key = (item['amount'], item['unit'])
        if key not in seen_units:
            seen_units.add(key)
            unique_per_unit.append(item)

    unit_spans = [(m.start(), m.end()) for m in _PER_UNIT_RE.finditer(masked)]
    unit_spans += [(m.start(), m.end()) for m in _PER_SESSION_RE.finditer(masked)]

    amounts: List[float] = []
    for match in _MONEY_RE.finditer(masked):
        if any(start < match.end() and match.start() < end for start, end in unit_spans):
            continue
        amounts.append(round(_as_float(match.group(1)), 2))
    amounts = sorted(set(amounts))

    durations: List[Dict[str, Any]] = []
    for match in _DURATION_RE.finditer(masked):
        value = _cn_to_int(match.group(1))
        if value is None or value > 120:
            continue
        durations.append({'value': value, 'unit': match.group(2)})

    notice_match = _NOTICE_RE.search(masked)
    notice_days = int(notice_match.group(1)) if notice_match else None

    conditions: List[str] = []
    cap_match = _CAP_RE.search(masked)
    if cap_match:
        conditions.append(f'used_sessions>{int(cap_match.group(1))}:no_refund')
    if '书面' in masked:
        conditions.append('written_notice')

    flags = {
        'full_refund': bool(re.search(r'全额退|无条件退', masked)),
        'free_of_charge': bool(re.search(
            r'不(?:再)?(?:收取|收).{0,6}手续费|无任何额外收费|全部免费|绝不收取|零手续费', masked)),
        'auto_renewal': bool(re.search(r'自动续费|自动续租|视为同意续费|视为同意续租', masked))
        and not bool(re.search(r'不自动续费|不自动续租|无需自动续费', masked)),
        'no_auto_renewal': bool(re.search(r'不自动续费|不自动续租|不设.{0,4}续租', masked)),
        'refundable': bool(re.search(r'可.{0,4}退费|支持退费|随时退', masked))
        and not bool(re.search(r'不支持退费|不予退费', masked)),
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
    r'(?:服务期限|合同期限|租赁期限|租期|有效期)\s*(?:为|自|至|：|:)|20\d{2}'
)


def extract_document(document: Document) -> List[Clause]:
    """对一份材料做全量规则抽取，按类型/页码/位置排序。"""
    clauses: List[Clause] = []
    for page in document.pages:
        for start, end, sentence, _, index_map in _iter_page_sentences(page):
            for clause_type, keywords in CLAUSE_KEYWORDS.items():
                if not any(keyword in sentence for keyword in keywords):
                    continue
                # "服务期限届满前"是时间状语，不是服务期限条款本身
                if clause_type == ClauseType.SERVICE_TERM and not _SERVICE_TERM_DEFINITION_RE.search(sentence):
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
