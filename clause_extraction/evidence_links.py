"""Find reviewable related excerpts using source positions, without model calls."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import replace
from itertools import islice
from unicodedata import normalize

from .schema import Document, EvidenceSpan, PageText

_NUMBER = r'(?:[0-9０-９]{1,6}|[一二三四五六七八九十百零〇两]{1,8})'
_ARTICLE = rf'第\s*(?P<number>{_NUMBER})\s*[条條]'
_SUFFIX = rf'\s*(?:之\s*{_NUMBER}|第\s*{_NUMBER}\s*[款项項目]|[（(]\s*{_NUMBER}\s*[）)])'
_HEADING = re.compile(rf'^{_ARTICLE}(?!{_SUFFIX})')
_REFERENCE = re.compile(rf'(?:见|見|按照|按|依据|依照|参照|參照|以|受|适用|適用)\s*'
                        rf'(?P<article>{_ARTICLE})(?P<subpart>(?:{_SUFFIX})*)')
_DIGIT = '一二三四五六七八九'
_CN_ARTICLE = re.compile(rf'(?:[{_DIGIT}两]百(?:[{_DIGIT}]十[{_DIGIT}]?|[零〇][{_DIGIT}])?'
                         rf'|[{_DIGIT}]?十[{_DIGIT}]?|[{_DIGIT}两])')
_QUALIFIER = re.compile(
    r'^(?:但(?:是|书)?|然而|不过|除非|除.+?外\s*[,，]?|'
    r'(?:本条(?:款)?|上述(?:规定|条款|退费|退款|费用|期限)?|前述(?:规定|条款|退费|退款|费用|期限)?)'
    r'\s*(?:仅|不|适用|在|须|需|限于|以|如|依|见|另)|'
    r'(?:however|except|unless|subject to)\b)',
    re.IGNORECASE,
)
_BREAK = re.compile(r'[。！？；;!?]+|\r?\n|\.(?=\s|$)|\Z')


def _units(document: Document, page: PageText, start: int = 0):
    for separator in _BREAK.finditer(page.text, start):
        raw = page.text[start:separator.end()]
        quote = raw.strip()
        if quote and quote.strip('。！？；;!?.,，、:：'):
            offset = start + len(raw) - len(raw.lstrip())
            yield EvidenceSpan(document.document_id, document.filename, document.role, page.page,
                               f'p{page.page}', offset, offset + len(quote), quote)
        start = separator.end()


def _number_key(raw: str) -> str:
    number = normalize('NFKC', raw)
    if number.isdecimal():
        return str(int(number))
    if _CN_ARTICLE.fullmatch(number):
        number = number.replace('〇', '零').replace('两', '二')
        digits = '零' + _DIGIT
        total = 0
        for unit, value in (('百', 100), ('十', 10)):
            if unit in number:
                digit, number = number.split(unit)
                total += (digits.index(digit) if digit else 1) * value
                number = number.lstrip('零')
        return str(total + (digits.index(number) if number else 0))
    return number


def _numbered_references(quote: str) -> dict[tuple[str, str], str]:
    references = {}
    for match in _REFERENCE.finditer(quote):
        subpart = ''.join(normalize('NFKC', match['subpart']).split())
        key = _number_key(match['number']), subpart
        references.setdefault(key, match['article'] + match['subpart'])
    return references


def _article_headings(document: Document) -> dict[str, list[EvidenceSpan | None]]:
    headings: dict[str, list[EvidenceSpan | None]] = defaultdict(list)
    for page in document.pages:
        spans = list(_units(document, page))
        for index, span in enumerate(spans):
            heading = _HEADING.match(span.quote)
            if heading is None:
                continue
            target = span
            if not span.quote[heading.end():].strip(' ：:。．.、'):
                following = spans[index + 1] if index + 1 < len(spans) else None
                target = None
                if following and not _HEADING.match(following.quote):
                    target = replace(span, char_end=following.char_end,
                                     quote=page.text[span.char_start:following.char_end])
            headings[_number_key(heading['number'])].append(target)
    return headings


def select_related_evidence(document: Document, anchor: EvidenceSpan, *,
                            budget: int = 480, strategy: str = 'linked', max_hops: int = 2) -> dict:
    """Select whole excerpts and their explicit reference paths under one shared budget."""
    if budget < 0 or strategy not in {'linked', 'nearby'} or max_hops not in {1, 2}:
        raise ValueError('证据预算、选择方式或引用深度无效')
    page = next((p for p in document.pages if p.page == anchor.page), None)
    if (document.document_id != anchor.document_id or page is None
            or not 0 <= anchor.char_start < anchor.char_end <= len(page.text)
            or page.text[anchor.char_start:anchor.char_end] != anchor.quote):
        raise ValueError('主证据与原文位置不符')

    used = 0
    selected = []
    seen = set()
    omitted = 0
    unresolved = []
    unresolved_count = 0

    def add_unresolved(source: EvidenceSpan, reference: str, reason: str) -> None:
        nonlocal unresolved_count
        unresolved_count += 1
        if len(unresolved) < 3:
            unresolved.append({'reference': reference, 'from_evidence_id': source.evidence_id,
                               'reason': reason})

    def overlaps_anchor(span: EvidenceSpan) -> bool:
        return (span.page == anchor.page and span.char_start < anchor.char_end
                and anchor.char_start < span.char_end)

    def add_excerpt(span: EvidenceSpan, relation: str, path: list[dict]) -> bool:
        nonlocal used, omitted
        if overlaps_anchor(span) or span.evidence_id in seen:
            return False
        seen.add(span.evidence_id)
        if used + len(span.quote) > budget or len(selected) == 3:
            omitted += 1
            return False
        used += len(span.quote)
        selected.append({**span.to_dict(), 'relation': relation, 'reference_path': path})
        return True

    nearby = islice(_units(document, page, anchor.char_end), 3)
    if strategy == 'nearby':
        for span in nearby:
            add_excerpt(span, 'nearby', [])
    else:
        frontier = [(anchor, [])]
        for span in nearby:
            if not _QUALIFIER.match(span.quote):
                break
            if add_excerpt(span, 'qualifier', []):
                frontier.append((span, []))

        articles = None
        for _ in range(max_hops):
            following = []
            for source, path in frontier:
                for (number, subpart), reference in _numbered_references(source.quote).items():
                    if subpart:
                        add_unresolved(source, reference, 'subpart')
                        continue
                    if articles is None:
                        articles = _article_headings(document)
                    targets = articles.get(number, [])
                    if len(targets) > 1:
                        add_unresolved(source, reference, 'ambiguous')
                        continue
                    if not targets or (target := targets[0]) is None:
                        add_unresolved(source, reference, 'missing')
                        continue
                    trace = [*path, {'article': reference, 'from_evidence_id': source.evidence_id,
                                     'to_evidence_id': target.evidence_id}]
                    if add_excerpt(target, 'reference', trace):
                        following.append((target, trace))
            if not following:
                break
            frontier = following
        else:
            for source, _ in frontier:
                for (number, subpart), reference in _numbered_references(source.quote).items():
                    targets = articles.get(number, []) if articles is not None else []
                    target = targets[0] if len(targets) == 1 else None
                    if subpart or target is None or (target.evidence_id not in seen and not overlaps_anchor(target)):
                        add_unresolved(source, reference, 'depth_limit')
    return {'related': selected, 'extra_quote_chars': used, 'omitted': omitted,
            'unresolved_references': unresolved, 'unresolved_reference_count': unresolved_count}
