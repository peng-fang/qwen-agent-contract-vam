"""Find reviewable related excerpts using source positions, without model calls."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import replace
from itertools import islice

from .schema import Document, EvidenceSpan, PageText

_NUMBER = r'[0-9０-９一二三四五六七八九十百零〇两]+'
_HEADING = re.compile(rf'^第\s*({_NUMBER})\s*条')
_REFERENCE = re.compile(rf'(?:见|按照|依据|依照|参照|以|受)\s*第\s*({_NUMBER})\s*条')
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


def _unique_articles(document: Document) -> dict[str, EvidenceSpan]:
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
            headings[heading.group(1)].append(target)
    return {number: targets[0] for number, targets in headings.items()
            if len(targets) == 1 and targets[0] is not None}


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
    def add_excerpt(span: EvidenceSpan, relation: str, path: list[dict]) -> bool:
        nonlocal used, omitted
        overlaps_anchor = (span.page == anchor.page and span.char_start < anchor.char_end
                           and anchor.char_start < span.char_end)
        if overlaps_anchor or span.evidence_id in seen:
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
                references = dict.fromkeys(match.group(1) for match in _REFERENCE.finditer(source.quote))
                if not references:
                    continue
                if articles is None:
                    articles = _unique_articles(document)
                for number in references:
                    target = articles.get(number)
                    if target is None:
                        continue
                    trace = [*path, {'article': f'第{number}条', 'from_evidence_id': source.evidence_id,
                                     'to_evidence_id': target.evidence_id}]
                    if add_excerpt(target, 'reference', trace):
                        following.append((target, trace))
            if not following:
                break
            frontier = following
    return {'related': selected, 'extra_quote_chars': used, 'omitted': omitted}
