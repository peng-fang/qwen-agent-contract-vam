"""Paired comparison of conversation history and confirmed refund facts."""

import argparse
import json
import sys
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clause_extraction import DocRole, Document, PageText, analyze_documents
from clause_extraction.amounts import _refund_check
from scripts.eval_refund_questions import CAP

FIELDS = ('used_sessions', 'total_paid')
MODES = ('full_history', 'recent_messages', 'confirmed_state')
PROMPT = ('读取当前核验需要的两个事实：已上课节数 used_sessions 和实付金额 total_paid。'
          '正式更正覆盖之前同一字段，假设试算不覆盖正式事实。只用所给信息；未知字段用 null。返回 JSON。')
QUESTION = '现在按实际情况核验退款，当前确认的已上课节数和实付是多少？'


def cases():
    initial = [{'role': 'user', 'text': '我已经上了8节，实际交了4800元。',
                'confirmed': {'used_sessions': 8, 'total_paid': 4800}}]
    for pair, prior, field, new, hypothetical, correction, actual in (
        ('sessions', initial, 'used_sessions', 13, '假设我上了13节，结果会怎样？',
         '前面课时说错了，实际已经上了13节。', (8, 4800)),
        ('payment', initial, 'total_paid', 6000, '如果交的是6000元，会退多少？先试算一下。',
         '费用这里我更正一下，实际交了6000元。', (8, 4800)),
        ('second-update', [*initial, {'role': 'user', 'text': '刚看过记录，确实是9节，之前说的8节不准。',
                                      'confirmed': {'used_sessions': 9}}],
         'used_sessions', 15, '我想单独看看假设上了15节的情况。', '又核对了一遍，实际是15节，请按这个更正。', (9, 4800)),
    ):
        for intent, text in (('assumption', hypothetical), ('correction', correction)):
            change = {'role': 'user', 'text': text,
                      'confirmed' if intent == 'correction' else 'assumptions': {field: new}}
            history = [*prior, {'role': 'assistant', 'text': '我已记录，请告诉我还要核对什么。'},
                       change, {'role': 'assistant', 'text': '收到，你可以继续问退款。'}]
            gold = dict(zip(FIELDS, actual))
            if intent == 'correction':
                gold[field] = new
            expected = {('sessions', 'assumption'): ('applicable', 1440),
                        ('sessions', 'correction'): ('not_applicable', None),
                        ('payment', 'assumption'): ('applicable', 1440),
                        ('payment', 'correction'): ('applicable', 2400),
                        ('second-update', 'assumption'): ('applicable', 1140),
                        ('second-update', 'correction'): ('not_applicable', None)}[pair, intent]
            yield f'{pair}-{intent}', history, gold, expected


def context(history, mode):
    if mode == 'confirmed_state':
        facts = {}
        for message in history:
            facts.update(message.get('confirmed', {}))
        return {'confirmed_facts': facts, 'question': QUESTION}
    messages = history if mode == 'full_history' else history[-2:]
    return {'messages': [{key: message[key] for key in ('role', 'text')} for message in messages],
            'question': QUESTION}


def client(model, port):
    opener = build_opener(ProxyHandler({}))
    base = f'http://127.0.0.1:{port}'
    with opener.open(base + '/api/tags', timeout=5) as response:
        installed = {item['name']: item['digest'] for item in json.load(response)['models']}
    if model not in installed:
        raise ValueError(f'模型尚未安装：{model}')

    def read(view):
        schema = {'type': 'object', 'properties': {
            'used_sessions': {'type': ['integer', 'null']}, 'total_paid': {'type': ['number', 'null']},
        }, 'required': list(FIELDS), 'additionalProperties': False}
        body = {'model': model, 'stream': False, 'format': schema,
                'options': {'temperature': 0, 'seed': 7, 'num_ctx': 4096, 'num_predict': 80},
                'messages': [{'role': 'system', 'content': PROMPT},
                             {'role': 'user', 'content': json.dumps(view, ensure_ascii=False)}]}
        request = Request(base + '/api/chat', data=json.dumps(body).encode('utf-8'),
                          headers={'Content-Type': 'application/json'})
        with opener.open(request, timeout=90) as response:
            result = json.load(response)
        raw = result['message']['content']
        try:
            predicted = json.loads(raw)
            sessions = predicted['used_sessions']
            paid = predicted['total_paid']
            if sessions is not None and (type(sessions) is not int or not 0 <= sessions <= 10000):
                raise ValueError('invalid sessions')
            if paid is not None and (type(paid) not in (int, float) or not 0 <= paid <= 1e9):
                raise ValueError('invalid payment')
        except (ValueError, KeyError, TypeError):
            predicted = None
        return predicted, {'raw': raw, 'input_tokens': result.get('prompt_eval_count'),
                           'output_tokens': result.get('eval_count')}

    return read, {'name': model, 'digest': installed[model], 'system_prompt': PROMPT}


def evaluate(read=None):
    rows = []
    documents = [Document('demo', 'contract.txt', DocRole.CONTRACT, [PageText(1, CAP)])]
    bundle = analyze_documents(documents)
    match = next(match for match in bundle.matches if match.clause_type.value == 'refund')
    for case, history, expected_facts, expected_result in cases():
        for mode in MODES if read else ('confirmed_state',):
            view = context(history, mode)
            facts, usage = read(view) if read else (view['confirmed_facts'], {})
            status = amount = None
            if facts is not None:
                check = _refund_check(match, bundle.clauses, documents,
                                      {field: facts[field] for field in FIELDS if facts.get(field) is not None})
                status = check['status']
                if status == 'applicable' and len(check['scenarios']) == 1:
                    amount = check['scenarios'][0]['amount']
            rows.append({'case': case, 'mode': mode, 'context': view, 'expected_facts': expected_facts,
                         'predicted_facts': facts, 'expected_refund': expected_result, 'refund': [status, amount],
                         'facts_correct': facts == expected_facts, 'refund_correct': (status, amount) == expected_result,
                         'wrong_supplied_fields': sum(facts.get(field) not in (None, expected_facts[field])
                                                      for field in FIELDS) if facts is not None else None,
                         **usage})
            print(f'{case} / {mode}: {facts} → {status}, {amount}', flush=True)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--model', default='qwen2.5:7b')
    parser.add_argument('--ollama-port', type=int, default=11434)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    read, model = client(args.model, args.ollama_port) if args.live else (None, None)
    rows = evaluate(read)
    summary = {}
    for mode in dict.fromkeys(row['mode'] for row in rows):
        batch = [row for row in rows if row['mode'] == mode]
        tokens = [row.get('input_tokens') for row in batch]
        summary[mode] = {'n': len(batch), 'correct_facts': sum(row['facts_correct'] for row in batch),
                         'correct_refunds': sum(row['refund_correct'] for row in batch),
                         'wrong_supplied_fields': sum(row['wrong_supplied_fields'] or 0 for row in batch),
                         'invalid_outputs': sum(row['predicted_facts'] is None for row in batch),
                         'input_tokens': sum(tokens) if all(token is not None for token in tokens) else None}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({'protocol': 'refund-memory-dev-v1', 'model': model,
                                        'summary': summary, 'rows': rows}, ensure_ascii=False, indent=2) + '\n',
                             encoding='utf-8')


if __name__ == '__main__':
    main()
