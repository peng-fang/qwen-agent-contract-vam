"""Rank paired clauses for semantic review using observable wording and fields."""

from __future__ import annotations

import re

_SCOPE = tuple(re.compile(pattern, re.I) for pattern in (
    r'开(?:课|工)前|before (?:the )?(?:start|class)',
    r'开(?:课|工)后|after (?:the )?(?:start|class)',
    r'仅限|仅在|仅适用|只在|only if|only when|subject to',
    r'除非|除外|但书|unless|except',
    r'提前|通知期|notice|in advance',
))
_NEGATION = re.compile(r'不(?:收|退|赔|扣|另|予|得|用)|无须|无需|免(?:费|收)|一分不扣|'
                       r'\b(?:no|not|never|non-refundable|without)\b', re.I)
_REFERENCE = re.compile(r'前述|上述|该(?:费用|期限|条件)|第[零一二三四五六七八九十百0-9]+条|'
                        r'\b(?:aforementioned|such (?:fee|period)|section \d+)\b', re.I)
_QUANTITIES = ('amounts', 'rates', 'per_unit_amounts', 'notice_days')


def eligible_matches(matches: list[dict]) -> list[dict]:
    return [item for item in matches if all((item.get(side) or {}).get('evidences')
                                            for side in ('promo', 'contract'))]


def priority(match: dict) -> dict:
    promo = match['promo']
    contract = match['contract']
    texts = ['\n'.join(item['quote'] for item in side['evidences']) for side in (promo, contract)]
    scopes = [{i for i, pattern in enumerate(_SCOPE) if pattern.search(text)} for text in texts]
    negatives = [bool(_NEGATION.search(text)) for text in texts]
    numeric = [{key for key in _QUANTITIES if side['fields'].get(key) not in (None, [])}
               for side in (promo, contract)]
    flags = []
    if scopes[0] != scopes[1]:
        flags.append(('适用阶段或限定词不同', 3))
    if negatives[0] != negatives[1]:
        flags.append(('双方否定措辞不对称', 3))
    if any(_REFERENCE.search(text) for text in texts):
        flags.append(('存在可能需要追溯的引用', 2))
    if numeric[0] != numeric[1]:
        flags.append(('双方可比较的金额或通知字段不同', 2))
    if match['verdict'] == 'consistent' and flags:
        flags.append(('规则判一致，但存在需要对齐的差异', 1))
    if match['verdict'] == 'unclear':
        flags.append(('规则未给出确定结论', 1))
    return {'clause_type': match['clause_type'], 'score': sum(weight for _, weight in flags),
            'signals': [reason for reason, _ in flags]}
