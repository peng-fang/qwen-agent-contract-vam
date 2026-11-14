"""生成 50 组合成标注数据（宣传材料 vs 合同）。

数据完全由模板生成，目的是给"规则路径"一个可复现的评测集：
- 每个案例是一对 .txt（单页），覆盖五类条款；
- 标签独立于抽取/匹配代码写死在模板里（pair -> expected verdict），
  生成时会用规则匹配器自检一遍，不一致直接报错，避免标签与实现漂移。

注意：这是合成模板数据，不代表真实合同分布。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clause_extraction import ClauseType, DocRole, analyze_files  # noqa: E402

OUTPUT = ROOT / 'eval_data'
CASES_DIR = OUTPUT / 'cases'

CLAUSE_TYPES = ['refund', 'penalty', 'auto_renewal', 'service_term', 'extra_fee']

PROMO: Dict[str, Dict[str, Optional[str]]] = {
    'refund': {
        'none': None,
        'full': '会员未上课可申请退款，未上课全额退款。',
        'nofee': '退费不收取任何手续费。',
        'rate20': '退费收取 20% 手续费。',
        'rate10': '退费收取 10% 手续费。',
    },
    'penalty': {
        'none': None,
        'rate30': '提前解约需支付 30% 违约金。',
        'rate20': '提前解约需支付 20% 违约金。',
    },
    'auto_renewal': {
        'none': None,
        'auto7': '到期后自动续费一年，提前 7 日通知。',
        'auto15': '到期后自动续费一年，提前 15 日通知。',
        'noauto': '本会员不自动续费，到期自动终止。',
    },
    'service_term': {
        'none': None,
        'datesA': '服务期限为2026年1月1日至2026年12月31日。',
        'datesB': '服务期限为2026年2月1日至2027年1月31日。',
    },
    'extra_fee': {
        'none': None,
        'free': '无任何额外收费，全部免费。',
        'fees': '储物柜 200 元/年，体测 100 元/次。',
    },
}

CONTRACT: Dict[str, Dict[str, Optional[str]]] = {
    'refund': {
        'none': None,
        'full': '乙方未上课可全额退款。',
        'rate20': '退费时扣除 20% 手续费。',
        'rate10': '退费时扣除 10% 手续费。',
        'cap12': '已上课超过 12 节的不予退费。',
    },
    'penalty': {
        'none': None,
        'rate30': '提前解除合同需支付 30% 违约金。',
        'rate20': '提前解除合同需支付 20% 违约金。',
    },
    'auto_renewal': {
        'none': None,
        'auto7': '合同期满后自动续费一年，提前 7 日通知。',
        'auto15': '合同期满后自动续费一年，提前 15 日通知。',
        'noauto': '本合同不自动续费，到期自动终止。',
    },
    'service_term': {
        'none': None,
        'datesA': '服务期限为2026年1月1日至2026年12月31日。',
        'datesB': '服务期限为2026年2月1日至2027年1月31日。',
    },
    'extra_fee': {
        'none': None,
        'free': '本课程无任何额外收费。',
        'fees': '储物柜 200 元/年，体测 100 元/次。',
        'fees2': '储物柜 300 元/年，体测 100 元/次。',
    },
}

PAIRS: Dict[str, List[Tuple[str, str, str]]] = {
    'refund': [
        ('full', 'rate20', 'conflict'),
        ('nofee', 'rate20', 'conflict'),
        ('rate20', 'rate10', 'conflict'),
        ('full', 'cap12', 'conflict'),
        ('rate20', 'rate20', 'consistent'),
        ('full', 'full', 'consistent'),
        ('full', 'none', 'missing_in_contract'),
        ('none', 'rate20', 'missing_in_promo'),
        ('none', 'none', 'missing_both'),
        ('nofee', 'full', 'unclear'),
    ],
    'penalty': [
        ('rate30', 'rate30', 'consistent'),
        ('rate30', 'rate20', 'conflict'),
        ('rate30', 'none', 'missing_in_contract'),
        ('none', 'rate30', 'missing_in_promo'),
        ('none', 'none', 'missing_both'),
        ('rate20', 'rate20', 'consistent'),
    ],
    'auto_renewal': [
        ('auto7', 'auto7', 'consistent'),
        ('auto7', 'auto15', 'conflict'),
        ('noauto', 'auto7', 'conflict'),
        ('none', 'auto7', 'missing_in_promo'),
        ('auto7', 'none', 'missing_in_contract'),
        ('none', 'none', 'missing_both'),
        ('noauto', 'noauto', 'consistent'),
        ('auto7', 'noauto', 'unclear'),
        ('noauto', 'none', 'missing_in_contract'),
        ('none', 'noauto', 'missing_in_promo'),
    ],
    'service_term': [
        ('datesA', 'datesA', 'consistent'),
        ('datesA', 'datesB', 'conflict'),
        ('datesA', 'none', 'missing_in_contract'),
        ('none', 'datesA', 'missing_in_promo'),
        ('none', 'none', 'missing_both'),
        ('datesB', 'datesB', 'consistent'),
    ],
    'extra_fee': [
        ('free', 'fees', 'conflict'),
        ('fees', 'fees2', 'conflict'),
        ('fees', 'fees', 'consistent'),
        ('free', 'free', 'consistent'),
        ('free', 'none', 'missing_in_contract'),
        ('none', 'fees', 'missing_in_promo'),
        ('none', 'none', 'missing_both'),
        ('fees', 'none', 'missing_in_contract'),
        ('none', 'free', 'missing_in_promo'),
    ],
}

PROMO_FILLER = '本材料用于课程介绍。'
CONTRACT_FILLER = '本协议用于课程报名。'

# 10 组"改写/同义表达"用例：标签按语义写死，不迁就规则命中。
# 规则路径在这些改写上会漏抽或判错，评测报告会单独列出该子集。
PARAPHRASES = [
    {
        'id': 'para_001',
        'promo': {'refund': '课程未开始前可申请退款，不扣手续费。'},
        'contract': {'refund': '开课前退费不收取手续费。'},
        'expected': {'refund': 'consistent'},
    },
    {
        'id': 'para_002',
        'promo': {'extra_fee': '报名费已包含全部课程材料，无需另付。'},
        'contract': {'extra_fee': '教材费 300 元/年，另收。'},
        'expected': {'extra_fee': 'conflict'},
    },
    {
        'id': 'para_003',
        'promo': {'auto_renewal': '会员到期后按月自动扣费，可提前 7 天取消。'},
        'contract': {'auto_renewal': '会员期满自动续费，提前 7 日通知。'},
        'expected': {'auto_renewal': 'consistent'},
    },
    {
        'id': 'para_004',
        'promo': {'penalty': '随时可终止，不收取任何违约费用。'},
        'contract': {'penalty': '提前终止需支付剩余费用 30% 的违约金。'},
        'expected': {'penalty': 'conflict'},
    },
    {
        'id': 'para_005',
        'promo': {'service_term': '课程有效期一年，自 2026 年 3 月 1 日起算。'},
        'contract': {'service_term': '服务期限为2026年3月1日至2027年2月28日。'},
        'expected': {'service_term': 'consistent'},
    },
    {
        'id': 'para_006',
        'promo': {'refund': '7 天内无理由退课，全额返还。'},
        'contract': {'refund': '乙方在开课 7 日内可全额退款。'},
        'expected': {'refund': 'consistent'},
    },
    {
        'id': 'para_007',
        'promo': {'service_term': '课程共 48 周，自 2026 年 3 月 1 日开始。'},
        'contract': {'service_term': '服务期限为 2026 年 3 月 1 日至 2027 年 6 月 30 日。'},
        'expected': {'service_term': 'conflict'},
    },
    {
        'id': 'para_008',
        'promo': {'auto_renewal': '到期自动结束，不会扣款。'},
        'contract': {'auto_renewal': '期满自动续费一年。'},
        'expected': {'auto_renewal': 'conflict'},
    },
    {
        'id': 'para_009',
        'promo': {'extra_fee': '不收取教材费与服装费。'},
        'contract': {'extra_fee': '教材费、服装费均已包含在学费内。'},
        'expected': {'extra_fee': 'consistent'},
    },
    {
        'id': 'para_010',
        'promo': {'penalty': '提前终止只需结清已上课时费用，无额外罚金。'},
        'contract': {'penalty': '提前退课需支付剩余课时费 20% 的违约金。'},
        'expected': {'penalty': 'conflict'},
    },
]


def _compose(sentences: Dict[str, Optional[str]], filler: str) -> Tuple[str, Dict[str, str]]:
    lines: List[str] = []
    gold: Dict[str, str] = {}
    for clause_type in CLAUSE_TYPES:
        sentence = sentences.get(clause_type)
        if sentence:
            lines.append(sentence)
            gold[clause_type] = sentence
    if not lines:
        lines.append(filler)
    return '\n'.join(lines) + '\n', gold


def _write_case(
    case_id: str,
    split: str,
    promo_sentences: Dict[str, Optional[str]],
    contract_sentences: Dict[str, Optional[str]],
    expected: Dict[str, str],
) -> Dict[str, object]:
    promo_text, promo_gold = _compose(promo_sentences, PROMO_FILLER)
    contract_text, contract_gold = _compose(contract_sentences, CONTRACT_FILLER)

    promo_name = f'{case_id}_promo.txt'
    contract_name = f'{case_id}_contract.txt'
    (CASES_DIR / promo_name).write_text(promo_text, encoding='utf-8')
    (CASES_DIR / contract_name).write_text(contract_text, encoding='utf-8')

    return {
        'id': case_id,
        'split': split,
        'scenario': 'gym_training',
        'promo_file': f'cases/{promo_name}',
        'contract_file': f'cases/{contract_name}',
        'expected_verdicts': expected,
        'gold_clauses': {
            'promo': promo_gold,
            'contract': contract_gold,
        },
    }


def build() -> Dict[str, object]:
    if CASES_DIR.exists():
        shutil.rmtree(CASES_DIR)
    CASES_DIR.mkdir(parents=True, exist_ok=True)

    cases = []
    template_cases = []
    for index in range(40):
        case_id = f'case_{index + 1:03d}'
        promo_sentences = {
            clause_type: PROMO[clause_type][PAIRS[clause_type][index % len(PAIRS[clause_type])][0]]
            for clause_type in CLAUSE_TYPES
        }
        contract_sentences = {
            clause_type: CONTRACT[clause_type][PAIRS[clause_type][index % len(PAIRS[clause_type])][1]]
            for clause_type in CLAUSE_TYPES
        }
        expected = {
            clause_type: PAIRS[clause_type][index % len(PAIRS[clause_type])][2]
            for clause_type in CLAUSE_TYPES
        }
        case = _write_case(case_id, 'template', promo_sentences, contract_sentences, expected)
        template_cases.append(case)
        cases.append(case)

    for item in PARAPHRASES:
        expected = {clause_type: 'missing_both' for clause_type in CLAUSE_TYPES}
        expected.update(item['expected'])
        cases.append(_write_case(
            item['id'], 'paraphrase', item['promo'], item['contract'], expected,
        ))

    # 自检只针对模板子集：模板标签与规则口径一致；改写子集保留真实差异
    mismatches = []
    for case in template_cases:
        bundle = analyze_files([
            (str(OUTPUT / case['promo_file']), DocRole.PROMO),
            (str(OUTPUT / case['contract_file']), DocRole.CONTRACT),
        ])
        predicted = {match.clause_type.value: match.verdict.value for match in bundle.matches}
        for clause_type, expected in case['expected_verdicts'].items():
            if predicted.get(clause_type) != expected:
                mismatches.append(
                    f"{case['id']}/{clause_type}: 期望 {expected}，实际 {predicted.get(clause_type)}"
                )
    if mismatches:
        raise SystemExit('模板子集自检失败：\n' + '\n'.join(mismatches[:20]))

    labels = {
        'dataset': 'synthetic-contract-promo-v1',
        'description': '40 组模板 + 10 组改写，共 50 组合成宣传/合同（单页 txt）',
        'case_count': len(cases),
        'splits': {
            'template': len(template_cases),
            'paraphrase': len(cases) - len(template_cases),
        },
        'clause_types': CLAUSE_TYPES,
        'cases': cases,
    }
    (OUTPUT / 'labels.json').write_text(
        json.dumps(labels, ensure_ascii=False, indent=2), encoding='utf-8',
    )

    counts: Dict[str, int] = {}
    for case in cases:
        for verdict in case['expected_verdicts'].values():
            counts[verdict] = counts.get(verdict, 0) + 1
    print(f"生成 {len(cases)} 组到 {CASES_DIR}")
    print('标签分布：', json.dumps(counts, ensure_ascii=False))
    return labels


if __name__ == '__main__':
    build()
