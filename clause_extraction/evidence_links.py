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


def select_related_evidence(document: Document, anchor: EvidenceSpan, *,
                            budget: int = 480, strategy: str = 'linked') -> dict:
    """Select whole excerpts from one document with a budget for extra quote characters."""
    if budget < 0 or strategy not in {'linked', 'nearby'}:
        raise ValueError('证据预算或选择方式无效')
    page = next((p for p in document.pages if p.page == anchor.page), None)
    if (document.document_id != anchor.document_id or page is None
            or not 0 <= anchor.char_start < anchor.char_end <= len(page.text)
            or page.text[anchor.char_start:anchor.char_end] != anchor.quote):
        raise ValueError('主证据与原文位置不符')

    candidates: list[tuple[str, EvidenceSpan]] = []
    # Skip punctuation between the anchor and the next original unit.
    nearby = list(islice(_units(document, page, anchor.char_end), 3))
    if strategy == 'nearby':
        candidates.extend(('nearby', span) for span in nearby)
    else:
        for span in nearby:
            if not _QUALIFIER.match(span.quote):
                break
            candidates.append(('qualifier', span))
        reference_text = [anchor.quote, *(span.quote for _, span in candidates)]
        referenced = {m.group(1) for quote in reference_text for m in _REFERENCE.finditer(quote)}
        if referenced:
            headings: dict[str, list[EvidenceSpan | None]] = defaultdict(list)
            for source_page in document.pages:
                spans = list(_units(document, source_page))
                for index, span in enumerate(spans):
                    heading = _HEADING.match(span.quote)
                    if heading and heading.group(1) in referenced:
                        target = span
                        if not span.quote[heading.end():].strip(' ：:。．.、'):
                            following = spans[index + 1] if index + 1 < len(spans) else None
                            target = None
                            if following and not _HEADING.match(following.quote):
                                target = replace(span, char_end=following.char_end,
                                                 quote=source_page.text[span.char_start:following.char_end])
                        headings[heading.group(1)].append(target)
            for targets in headings.values():
                if len(targets) == 1 and (target := targets[0]) is not None:
                    candidates.append(('reference', target))

    used = 0
    selected = []
    seen = set()
    omitted = 0
    for relation, span in candidates:
        overlaps_anchor = (span.page == anchor.page and span.char_start < anchor.char_end
                           and anchor.char_start < span.char_end)
        if overlaps_anchor or span.evidence_id in seen:
            continue
        seen.add(span.evidence_id)
        if used + len(span.quote) > budget or len(selected) == 3:
            omitted += 1
            continue
        used += len(span.quote)
        selected.append({**span.to_dict(), 'relation': relation})
    return {'related': selected, 'extra_quote_chars': used, 'omitted': omitted}
