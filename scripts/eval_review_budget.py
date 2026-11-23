"""Compare which paired clauses to send for semantic review under a fixed item budget."""

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]

from jsonschema import ValidationError, validate
from app.services.semantic_review import (
    SYSTEM, ModelUnavailable, review_payload, review_schema, validated_items,
)
from clause_extraction.review_priority import eligible_matches, priority
from scripts.eval_clauses import GROUP_OF, _bundle


def prepare(cases, seed):
    candidates = []
    unroutable_errors = 0
    for case in cases:
        base = _bundle(case).to_dict()
        eligible = {match['clause_type']: match for match in eligible_matches(base['matches'])}
        for match in base['matches']:
            kind = match['clause_type']
            gold = GROUP_OF[case['expected_verdicts'][kind]]
            predicted = GROUP_OF[match['verdict']]
            if kind not in eligible:
                unroutable_errors += int(gold != predicted)
                continue
            candidates.append({'id': f"{case['id']}:{kind}", 'gold': gold, 'rule': predicted,
                               'priority': priority(match), 'payload': review_payload(base, {}, [match])})
    random.Random(seed).shuffle(candidates)
    return candidates, unroutable_errors


def selections(candidates, budget):
    return {
        'fixed_order': candidates[:budget],
        'unclear_first': sorted(candidates, key=lambda row: row['rule'] != 'insufficient')[:budget],
        'signal_priority': sorted(candidates, key=lambda row: -row['priority']['score'])[:budget],
    }


def local_reviewer(model, port):
    opener = build_opener(ProxyHandler({}))
    base = f'http://127.0.0.1:{port}'
    with opener.open(base + '/api/tags', timeout=5) as response:
        installed = {item['name']: item['digest'] for item in json.load(response)['models']}
    if model not in installed:
        raise ValueError(f'模型尚未安装：{model}')

    def review(payload):
        schema = review_schema(payload)
        body = {'model': model, 'stream': False, 'format': schema,
                'options': {'temperature': 0, 'seed': 7, 'num_ctx': 4096, 'num_predict': 550},
                'messages': [{'role': 'system', 'content': SYSTEM},
                             {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]}
        request = Request(base + '/api/chat', data=json.dumps(body).encode('utf-8'),
                          headers={'Content-Type': 'application/json'})
        with opener.open(request, timeout=90) as response:
            result = json.load(response)
        raw = result['message']['content']
        verdict = error = None
        try:
            output = json.loads(raw)
            validate(output, schema)
            verdict = GROUP_OF[validated_items(output, payload)[0]['verdict']]
        except (ValueError, ValidationError, ModelUnavailable) as exc:
            error = str(exc)
        return {'verdict': verdict, 'validation_error': error, 'raw': raw,
                'input_tokens': result.get('prompt_eval_count'), 'output_tokens': result.get('eval_count')}

    return review, {'name': model, 'digest': installed[model], 'system_prompt': SYSTEM}


def summarize(plans, opinions):
    summary = {}
    for method, rows in plans.items():
        result = {'reviewed_ids': [row['id'] for row in rows],
                  'selected_rule_errors': sum(row['rule'] != row['gold'] for row in rows),
                  'selected_missed_conflicts': sum(row['gold'] == 'conflict' and row['rule'] != 'conflict' for row in rows)}
        if opinions is not None:
            decisions = [(row, opinions[row['id']]) for row in rows]
            fixes = sum(row['rule'] != row['gold'] and opinion['verdict'] == row['gold']
                        for row, opinion in decisions)
            regressions = sum(row['rule'] == row['gold'] and opinion['verdict'] not in (None, row['gold'])
                              for row, opinion in decisions)
            conflict_fixes = sum(row['gold'] == 'conflict' and row['rule'] != 'conflict'
                                 and opinion['verdict'] == 'conflict' for row, opinion in decisions)
            tokens = [opinion['input_tokens'] for _, opinion in decisions]
            result.update(fixes=fixes, fixed_missed_conflicts=conflict_fixes,
                          regressions=regressions, net_fixes=fixes - regressions,
                          invalid_opinions=sum(opinion['verdict'] is None for _, opinion in decisions),
                          input_tokens=sum(tokens) if all(token is not None for token in tokens) else None)
        summary[method] = result
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--budget', type=int, default=8)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--model', default='qwen2.5:7b')
    parser.add_argument('--ollama-port', type=int, default=11434)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.budget < 1:
        parser.error('--budget 必须为正数')
    data = (ROOT / 'eval_data/heldout_v2/labels.json').read_bytes()
    candidates, unroutable = prepare(json.loads(data)['cases'], args.seed)
    plans = selections(candidates, args.budget)
    opinions = model = None
    if args.live:
        review, model = local_reviewer(args.model, args.ollama_port)
        union = {row['id']: row for rows in plans.values() for row in rows}
        opinions = {}
        for item_id, row in union.items():
            opinions[item_id] = review(row['payload'])
            print(item_id, row['rule'], '→', opinions[item_id]['verdict'], flush=True)
    report = {'protocol': 'review-budget-dev-v2', 'dataset_sha256': hashlib.sha256(data).hexdigest(),
              'seed': args.seed, 'budget': args.budget, 'model': model, 'eligible_count': len(candidates),
              'eligible_rule_errors': sum(row['rule'] != row['gold'] for row in candidates),
              'ineligible_rule_errors': unroutable, 'summary': summarize(plans, opinions),
              'candidates': candidates, 'model_opinions': opinions}
    print(json.dumps({key: report[key] for key in ('eligible_count', 'eligible_rule_errors',
                                                   'ineligible_rule_errors', 'summary')}, ensure_ascii=False, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
