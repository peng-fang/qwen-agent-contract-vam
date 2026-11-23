"""Paired development cases for retrieving qualifications and referenced clauses."""

import argparse
import json
import sys
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clause_extraction.evidence_links import select_related_evidence
from clause_extraction.schema import DocRole, Document, EvidenceSpan, PageText

CASES = (
    ('refund', '开课前后，报名后七天内都可以申请退款。',
     '报名后七天内可以申请退款。',
     '本条在开课前后均适用。', '本条仅在开课前适用。', False),
    ('renewal', '会员按月自动续费，可以随时取消，无需提前通知。',
     '会员按月自动续费，取消条件见第八条。',
     '第八条 会员取消续费无需提前通知。',
     '第八条 会员取消续费须提前三十日通知。', True),
    ('materials', '线上课程免收100元材料费。',
     '课程材料费为100元，收费例外见第六条。',
     '第六条 线上课程免收材料费。',
     '第六条 线上课程也须缴纳材料费。', True),
)

OTHER_TERMS = ('会员可在工作日上午九时到下午六时之间将联系方式及通信地址的变更通知送交服务中心。'
               '\n办理资料变更时应出示证件原件。')


def cases():
    for family, promo, main, aligned, opposed, separate_page in CASES:
        for verdict, qualifier in (('consistent', aligned), ('conflict', opposed)):
            case_id = f'{family}-{verdict}'
            if separate_page:
                pages = [PageText(1, f'{main}\n{OTHER_TERMS}'), PageText(2, qualifier)]
            else:
                pages = [PageText(1, f'{main}\n{qualifier}\n{OTHER_TERMS}')]
            document = Document(case_id, 'contract.txt', DocRole.CONTRACT, pages)
            anchor = EvidenceSpan(case_id, document.filename, document.role, 1, 'p1', 0, len(main), main)
            yield family, verdict, promo, document, anchor, qualifier


def evaluate(budget):
    rows = []
    for family, gold, promo, document, anchor, qualifier in cases():
        full = '\n'.join(page.text for page in document.pages)
        for method in ('full', 'nearby', 'linked', 'anchor_only'):
            related = (select_related_evidence(document, anchor, budget=budget, strategy=method)['related']
                       if method in {'nearby', 'linked'} else [])
            text = full if method == 'full' else '\n'.join([anchor.quote, *(s['quote'] for s in related)])
            rows.append({'case': document.document_id, 'family': family, 'method': method,
                         'gold': gold, 'qualifier_present': qualifier in text,
                         'promo': promo, 'contract': text, 'contract_chars': len(text), 'related': related})
    return rows


def run_ollama(rows, model, port):
    # Deliberately use only the installed model on the local service.
    opener = build_opener(ProxyHandler({}))
    url = f'http://127.0.0.1:{port}'
    with opener.open(url + '/api/tags', timeout=5) as response:
        models = {item['name']: item['digest'] for item in json.load(response)['models']}
    if model not in models:
        raise ValueError(f'模型尚未安装：{model}')
    prompt = ('你比较宣传承诺与合同文字。使用合同主句和适用条件一起判断。若无法确认主句是否受缺失的条件约束，'
              '选 insufficient。适用范围或义务矛盾选 conflict。范围与义务一致选 consistent。只返回 JSON。')
    schema = {'type': 'object', 'properties': {
        'verdict': {'type': 'string', 'enum': ['consistent', 'conflict', 'insufficient']},
        'reason': {'type': 'string'},
    }, 'required': ['verdict', 'reason'], 'additionalProperties': False}
    for row in rows:
        body = {'model': model, 'stream': False, 'format': schema,
                'options': {'temperature': 0, 'seed': 7, 'num_ctx': 4096, 'num_predict': 220},
                'messages': [{'role': 'system', 'content': prompt}, {'role': 'user', 'content':
                              f"宣传：{row['promo']}\n合同：{row['contract']}"}]}
        request = Request(url + '/api/chat', data=json.dumps(body).encode('utf-8'),
                          headers={'Content-Type': 'application/json'})
        with opener.open(request, timeout=90) as response:
            result = json.load(response)
        content = result['message']['content']
        try:
            prediction = json.loads(content).get('verdict')
        except (ValueError, AttributeError):
            prediction = None
        row.update(prediction=prediction, response=content,
                   input_tokens=result.get('prompt_eval_count'), output_tokens=result.get('eval_count'))
        print(f"{row['case']} / {row['method']}: {prediction}", flush=True)
    return {'name': model, 'digest': models[model], 'system_prompt': prompt}


def summarize(rows):
    summary = {}
    for method in ('full', 'nearby', 'linked', 'anchor_only'):
        group = [row for row in rows if row['method'] == method]
        scores = {'n': len(group), 'qualifiers_retrieved': sum(row['qualifier_present'] for row in group),
                  'contract_chars': sum(row['contract_chars'] for row in group)}
        if all('prediction' in row for row in group):
            scores['correct'] = sum(row['prediction'] == row['gold'] for row in group)
            scores['both_variants_correct'] = sum(
                all(row['prediction'] == row['gold'] for row in group if row['family'] == family)
                for family, *_ in CASES
            )
            for field in ('input_tokens', 'output_tokens'):
                values = [row[field] for row in group]
                scores[field] = sum(values) if all(value is not None for value in values) else None
        summary[method] = scores
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--budget', type=int, default=48, help='额外引文的字符预算')
    parser.add_argument('--out', type=Path, help='保存逐案 JSON')
    parser.add_argument('--live', action='store_true', help='实际调用本机 Ollama')
    parser.add_argument('--model', default='qwen2.5:7b')
    parser.add_argument('--ollama-port', type=int, default=11434)
    args = parser.parse_args()
    if args.budget < 0:
        parser.error('--budget 必须为非负数')
    rows = evaluate(args.budget)
    model = None
    try:
        if args.live:
            model = run_ollama(rows, args.model, args.ollama_port)
    finally:
        summary = summarize(rows)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps({'protocol': 'linked-evidence-dev-v1',
                'extra_quote_chars_budget': args.budget, 'model': model, 'summary': summary, 'rows': rows,
            }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
