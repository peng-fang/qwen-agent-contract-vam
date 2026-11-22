"""Compare one-turn refund clarification policies on invented development cases."""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clause_extraction import DocRole, Document, PageText, analyze_documents
from clause_extraction.amounts import _refund_check
from clause_extraction.refund_questions import QUESTIONS, missing_user_facts, next_refund_question


@dataclass(frozen=True)
class Case:
    id: str
    contract: str
    known: dict
    answers: dict
    needed: tuple[str, ...]
    final_status: str
    amount: float | None = None


CAP = '每节原价300元。超过12节不予退费，退费扣除20%手续费。'
SPLIT_CAP = '每节原价300元。超过12节不予退费；退费扣除20%手续费。'
WINDOW = '报名后7日内可以申请退款，退款扣除20%手续费。'
PHASE = '仅开课前可以申请退款，退款扣除20%手续费。'
PAYMENT = '学费4800元。'
CASES = (
    Case('cap-over', CAP, {}, {'used_sessions': 13, 'total_paid': 4800}, ('used_sessions',), 'not_applicable'),
    Case('cap-within', CAP, {}, {'used_sessions': 8, 'total_paid': 4800}, ('used_sessions', 'total_paid'), 'applicable', 1440),
    Case('cap-exact', PAYMENT + CAP, {}, {'used_sessions': 12}, ('used_sessions',), 'applicable', 240),
    Case('window-late', WINDOW, {}, {'request_day': 9, 'total_paid': 4800}, ('request_day',), 'not_applicable'),
    Case('window-within', PAYMENT + WINDOW, {}, {'request_day': 7}, ('request_day',), 'applicable', 3840),
    Case('phase-after', PHASE, {}, {'request_phase': '开课后', 'total_paid': 4800}, ('request_phase',), 'not_applicable'),
    Case('phase-before', PAYMENT + PHASE, {}, {'request_phase': '开课前'}, ('request_phase',), 'applicable', 3840),
    Case('payment-only', '可以申请退款，退款扣除20%手续费。', {}, {'total_paid': 4800}, ('total_paid',), 'applicable', 3840),
    Case('unit-price', '学费4800元。退费扣除20%手续费。', {'used_sessions': 8}, {'unit_price': 300}, ('unit_price',), 'applicable', 1440),
    Case('fixed-result', PAYMENT + CAP, {'used_sessions': 13}, {}, (), 'not_applicable'),
    Case('missing-fee-rule', '可以申请退款。', {}, {'total_paid': 4800}, (), 'insufficient'),
    Case('multiple-phases', '开课前可以退款，开课后退款扣除20%手续费。', {}, {}, (), 'insufficient'),
    Case('split-fee-rule', PAYMENT + SPLIT_CAP, {'used_sessions': 8}, {}, (), 'applicable', 1440),
)

PROMPT = ('你要核验退款。根据合同和已知事实，从 candidate_fields 选一个你最想向用户确认的字段。'
          '如果无需追问，或用户提供这些字段也无法解决当前问题，选 none。只返回 JSON，字段 field。')


def model_picker(model, port):
    opener = build_opener(ProxyHandler({}))
    url = f'http://127.0.0.1:{port}'
    with opener.open(url + '/api/tags', timeout=5) as response:
        installed = {item['name']: item['digest'] for item in json.load(response)['models']}
    if model not in installed:
        raise ValueError(f'模型尚未安装：{model}')

    def pick(case, fields):
        payload = {'contract': case.contract, 'confirmed': case.known,
                   'candidate_fields': {field: QUESTIONS[field][0] for field in sorted(fields)}}
        schema = {'type': 'object', 'properties': {'field': {'type': 'string', 'enum': [*sorted(fields), 'none']}},
                  'required': ['field'], 'additionalProperties': False}
        body = {'model': model, 'stream': False, 'format': schema,
                'options': {'temperature': 0, 'seed': 7, 'num_ctx': 4096, 'num_predict': 70},
                'messages': [{'role': 'system', 'content': PROMPT},
                             {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)}]}
        request = Request(url + '/api/chat', data=json.dumps(body).encode('utf-8'),
                          headers={'Content-Type': 'application/json'})
        with opener.open(request, timeout=90) as response:
            result = json.load(response)
        text = result['message']['content']
        try:
            field = json.loads(text).get('field')
        except (ValueError, AttributeError):
            field = None
        return {'field': field, 'raw': text, 'input_tokens': result.get('prompt_eval_count'),
                'output_tokens': result.get('eval_count'), 'invalid': field not in {*fields, 'none'}}

    return pick, {'name': model, 'digest': installed[model], 'prompt': PROMPT}


def evaluate(pick=None):
    rows = []
    for case in CASES:
        documents = [Document(case.id, 'contract.txt', DocRole.CONTRACT, [PageText(1, case.contract)])]
        bundle = analyze_documents(documents)
        match = next(match for match in bundle.matches if match.clause_type.value == 'refund')
        initial = _refund_check(match, bundle.clauses, documents, case.known)
        fields = missing_user_facts(initial)
        question = next_refund_question(initial)
        strategies = [('all_missing', fields, None),
                      ('eligibility_first', [question['field']] if question else [], None)]
        if pick:
            selection = pick(case, fields) if fields else None
            asked = [selection['field']] if selection and selection['field'] in fields else []
            strategies.append(('model_pick', asked, selection))
        for method, asked, selection in strategies:
            supplied = {field: case.answers[field] for field in asked if field in case.answers}
            result = _refund_check(match, bundle.clauses, documents, {**case.known, **supplied})
            amounts = [item['amount'] for item in result['scenarios'] if item['amount'] is not None]
            terminal = result['status'] in {'applicable', 'not_applicable'}
            correct = (result['status'] == case.final_status
                       and (amounts == [case.amount] if case.amount is not None else not amounts))
            rows.append({'case': case.id, 'method': method, 'contract': case.contract, 'known': case.known,
                         'initial_status': initial['status'], 'candidate_fields': fields, 'asked': asked,
                         'supplied': supplied, 'unnecessary_fields': sorted(set(asked) - set(case.needed)),
                         'expected_status': case.final_status, 'expected_amount': case.amount,
                         'observed_status': result['status'], 'amounts': amounts, 'correct': correct,
                         'terminal': terminal, 'model': selection})
        print(case.id, ' / '.join(f'{method}: {asked}' for method, asked, _ in strategies), flush=True)
    return rows


def summarize(rows):
    summary = {}
    for method in dict.fromkeys(row['method'] for row in rows):
        group = [row for row in rows if row['method'] == method]
        active = [row for row in group if row['expected_status'] != 'insufficient'
                  and row['initial_status'] not in {'applicable', 'not_applicable'}]
        summary[method] = {
            'cases': len(group),
            'active_resolvable_cases': len(active),
            'correct_completion_within_one_turn': sum(row['terminal'] and row['correct'] for row in active),
            'incorrect_terminal_results': sum(row['terminal'] and not row['correct'] for row in group),
            'total_fields_asked': sum(len(row['asked']) for row in group),
            'unnecessary_fields_asked': sum(len(row['unnecessary_fields']) for row in group),
            'invalid_model_choices': sum(bool(row['model'] and row['model']['invalid']) for row in group),
        }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--model', default='qwen2.5:7b')
    parser.add_argument('--ollama-port', type=int, default=11434)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    pick, model = model_picker(args.model, args.ollama_port) if args.live else (None, None)
    rows = evaluate(pick)
    summary = summarize(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({'protocol': 'refund-questions-dev-v1', 'model': model,
                                       'summary': summary, 'rows': rows}, ensure_ascii=False, indent=2) + '\n',
                            encoding='utf-8')


if __name__ == '__main__':
    main()
