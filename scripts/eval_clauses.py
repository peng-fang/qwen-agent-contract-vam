"""条款抽取 / 跨文档匹配 / 证据定位评测（规则路径，真实跑分）。

用法：
    python scripts/eval_clauses.py

读取 eval_data/labels.json，对每个案例重新读取 50 对 txt 材料，运行规则抽取与匹配，
计算：
- 条款抽取（五类，文档级存在性）Precision / Recall / F1；
- 跨文档匹配六标签 Macro-F1 与三分类 Macro-F1、准确率、混淆矩阵；
- 证据定位准确率（页码 + 字符区间回读一致 + 与金标句重叠）。

输出 reports/eval_metrics.json、eval_report.md、eval_dashboard.html。
不联网、不调用模型；数字全部来自本次运行。
"""

from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clause_extraction import (  # noqa: E402
    DocRole,
    Document,
    PageText,
    analyze_documents,
    analyze_files,
)
from clause_extraction.schema import Clause  # noqa: E402

DATA = ROOT / 'eval_data'
REPORTS = ROOT / 'reports'

CLAUSE_TYPES = ['refund', 'penalty', 'auto_renewal', 'service_term', 'extra_fee']
CLAUSE_LABELS = {
    'refund': '退款',
    'penalty': '违约金',
    'auto_renewal': '自动续费/续租',
    'service_term': '服务期限',
    'extra_fee': '额外收费',
}
VERDICTS = [
    'consistent',
    'conflict',
    'missing_in_contract',
    'missing_in_promo',
    'missing_both',
    'unclear',
]
VERDICT_LABELS = {
    'consistent': '一致',
    'conflict': '矛盾',
    'missing_in_contract': '合同未约定',
    'missing_in_promo': '宣传未提及',
    'missing_both': '双方未约定',
    'unclear': '证据不足',
}
GROUPS = ['consistent', 'conflict', 'insufficient']
GROUP_LABELS = {'consistent': '一致', 'conflict': '矛盾', 'insufficient': '证据不足'}
GROUP_OF = {
    'consistent': 'consistent',
    'conflict': 'conflict',
    'missing_in_contract': 'insufficient',
    'missing_in_promo': 'insufficient',
    'missing_both': 'insufficient',
    'unclear': 'insufficient',
}


def _round(value: float) -> float:
    return round(float(value), 4)


def _prf(tp: int, fp: int, fn: int) -> Dict[str, Any]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        'tp': tp,
        'fp': fp,
        'fn': fn,
        'precision': _round(precision),
        'recall': _round(recall),
        'f1': _round(f1),
    }


def _norm(text: str) -> str:
    return ''.join(ch for ch in text if not ch.isspace() and ch not in '。；;！？，,')


def _quote_matches(quote: str, gold_sentence: str) -> bool:
    left, right = _norm(quote), _norm(gold_sentence)
    if not left or not right:
        return False
    return left in right or right in left


def _evidence_status(candidates: List[Clause], document: Document,
                     gold_sentence: Optional[str]) -> str:
    if gold_sentence is None:
        return 'unexpected_clause' if candidates else 'not_annotated'
    if not candidates:
        return 'missing_clause'

    # The eval fixtures use single-page text and annotate a reference sentence.
    page_text = next((page.text for page in document.pages if page.page == 1), '')
    has_valid_location = False
    for clause in candidates:
        evidence = clause.evidence
        if evidence.page != 1 or not 0 <= evidence.char_start < evidence.char_end <= len(page_text):
            continue
        if page_text[evidence.char_start:evidence.char_end] != evidence.quote:
            continue
        has_valid_location = True
        if _quote_matches(evidence.quote, gold_sentence):
            return 'located'
    return 'different_excerpt' if has_valid_location else 'invalid_location'


def _bundle(case: Dict[str, Any]):
    """支持两种数据形式：文件对（调参集）或内联文本（冻结留出集）。"""
    if 'promo_text' in case and 'contract_text' in case:
        documents = [
            Document(
                document_id=f"{case['id']}-promo",
                filename=f"{case['id']}_promo.txt",
                role=DocRole.PROMO,
                pages=[PageText(page=1, text=case['promo_text'])],
            ),
            Document(
                document_id=f"{case['id']}-contract",
                filename=f"{case['id']}_contract.txt",
                role=DocRole.CONTRACT,
                pages=[PageText(page=1, text=case['contract_text'])],
            ),
        ]
        return analyze_documents(documents)
    return analyze_files([
        (str(DATA / case['promo_file']), DocRole.PROMO),
        (str(DATA / case['contract_file']), DocRole.CONTRACT),
    ])


def evaluate(cases: List[Dict[str, Any]], split: Optional[str] = None, *,
             diagnostics: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    selected = [case for case in cases if split is None or case.get('split') == split]

    extraction_counts = {
        clause_type: {'tp': 0, 'fp': 0, 'fn': 0} for clause_type in CLAUSE_TYPES
    }
    evidence_counts = {
        clause_type: {'correct': 0, 'total': 0} for clause_type in CLAUSE_TYPES
    }
    gold_verdicts: List[str] = []
    predicted_verdicts: List[str] = []
    match_errors: List[Dict[str, Any]] = []
    case_records: List[Dict[str, Any]] = []

    for case in selected:
        bundle = _bundle(case)
        documents = {document.role: document for document in bundle.documents}
        sides = {key: {} for key in ('promo', 'contract')}

        for role_key, role in (('promo', DocRole.PROMO), ('contract', DocRole.CONTRACT)):
            document = documents[role]
            gold_clauses = case['gold_clauses'].get(role_key, {})
            by_type = {clause_type: [] for clause_type in CLAUSE_TYPES}
            for clause in bundle.clauses:
                if clause.evidence.document_id == document.document_id:
                    by_type[clause.clause_type.value].append(clause)
            for clause_type in CLAUSE_TYPES:
                candidates = by_type[clause_type]
                gold = clause_type in gold_clauses
                predicted = bool(candidates)
                if gold and predicted:
                    extraction_counts[clause_type]['tp'] += 1
                elif gold:
                    extraction_counts[clause_type]['fn'] += 1
                elif predicted:
                    extraction_counts[clause_type]['fp'] += 1

                gold_sentence = gold_clauses.get(clause_type)
                status = _evidence_status(candidates, document, gold_sentence)
                if gold:
                    evidence_counts[clause_type]['total'] += 1
                    evidence_counts[clause_type]['correct'] += int(status == 'located')
                if diagnostics is not None:
                    sides[role_key][clause_type] = {
                        'status': status,
                        'gold_sentence': gold_sentence,
                        'candidates': [clause.to_dict() for clause in candidates],
                    }

        matches = {match.clause_type.value: match for match in bundle.matches}
        match_errors_case = []
        for clause_type, gold_verdict in case['expected_verdicts'].items():
            match = matches.get(clause_type)
            predicted_verdict = match.verdict.value if match is not None else 'missing_both'
            gold_verdicts.append(gold_verdict)
            predicted_verdicts.append(predicted_verdict)
            if diagnostics is not None:
                promo = sides['promo'][clause_type]
                contract = sides['contract'][clause_type]
                diagnostics.append({
                    'case': case['id'],
                    'split': case['split'],
                    'clause_type': clause_type,
                    'gold': gold_verdict,
                    'predicted': predicted_verdict,
                    'gold_group': GROUP_OF[gold_verdict],
                    'predicted_group': GROUP_OF[predicted_verdict],
                    'promo': promo,
                    'contract': contract,
                    'reasons': list(match.reasons) if match is not None else [],
                    'compared': match.compared if match is not None else {},
                })
            if gold_verdict != predicted_verdict:
                match_errors_case.append({
                    'clause_type': clause_type,
                    'clause_label': CLAUSE_LABELS[clause_type],
                    'gold': gold_verdict,
                    'predicted': predicted_verdict,
                })
                match_errors.append({'case': case['id'], 'split': case['split'], **match_errors_case[-1]})

        case_records.append({
            'id': case['id'],
            'split': case['split'],
            'match_errors': match_errors_case,
            'extraction_gold': {
                key: sorted(case['gold_clauses'].get(key, {})) for key in ('promo', 'contract')
            },
            'extraction_predicted': {
                role_key: sorted({
                    clause.clause_type.value for clause in bundle.clauses
                    if clause.evidence.document_id == documents[role].document_id
                })
                for role_key, role in (('promo', DocRole.PROMO), ('contract', DocRole.CONTRACT))
            },
        })

    extraction_by_type = {
        clause_type: _prf(**counts) for clause_type, counts in extraction_counts.items()
    }
    macro_f1 = sum(item['f1'] for item in extraction_by_type.values()) / len(CLAUSE_TYPES)
    total_tp = sum(item['tp'] for item in extraction_counts.values())
    total_fp = sum(item['fp'] for item in extraction_counts.values())
    total_fn = sum(item['fn'] for item in extraction_counts.values())
    extraction_overall = {
        **_prf(total_tp, total_fp, total_fn),
        'macro_f1': _round(macro_f1),
        'documents': len(selected) * 2,
    }

    # 六标签与三分类
    confusion = {
        gold: {pred: 0 for pred in VERDICTS} for gold in VERDICTS
    }
    label_stats = {label: {'tp': 0, 'fp': 0, 'fn': 0} for label in VERDICTS}
    for gold, pred in zip(gold_verdicts, predicted_verdicts):
        confusion[gold][pred] += 1
        for label in VERDICTS:
            if gold == label and pred == label:
                label_stats[label]['tp'] += 1
            elif gold == label:
                label_stats[label]['fn'] += 1
            elif pred == label:
                label_stats[label]['fp'] += 1

    by_label = {label: _prf(**stats) for label, stats in label_stats.items()}
    supported = [stats for label, stats in by_label.items() if stats['tp'] + stats['fn'] > 0]
    macro_f1_six = sum(item['f1'] for item in supported) / len(supported) if supported else 0.0
    accuracy = sum(1 for gold, pred in zip(gold_verdicts, predicted_verdicts) if gold == pred)
    accuracy = accuracy / len(gold_verdicts) if gold_verdicts else 0.0

    group_stats = {group: {'tp': 0, 'fp': 0, 'fn': 0} for group in GROUPS}
    for gold, pred in zip(gold_verdicts, predicted_verdicts):
        gold_group, pred_group = GROUP_OF[gold], GROUP_OF[pred]
        for group in GROUPS:
            if gold_group == group and pred_group == group:
                group_stats[group]['tp'] += 1
            elif gold_group == group:
                group_stats[group]['fn'] += 1
            elif pred_group == group:
                group_stats[group]['fp'] += 1
    by_group = {group: _prf(**stats) for group, stats in group_stats.items()}
    macro_f1_three = sum(item['f1'] for item in by_group.values()) / len(GROUPS)

    evidence_total = sum(item['total'] for item in evidence_counts.values())
    evidence_correct = sum(item['correct'] for item in evidence_counts.values())
    evidence_accuracy = evidence_correct / evidence_total if evidence_total else 0.0
    evidence_by_type = {
        clause_type: {
            'correct': counts['correct'],
            'total': counts['total'],
            'accuracy': _round(counts['correct'] / counts['total']) if counts['total'] else 0.0,
        }
        for clause_type, counts in evidence_counts.items()
    }

    return {
        'case_count': len(selected),
        'extraction': {
            'overall': extraction_overall,
            'by_clause_type': extraction_by_type,
        },
        'matching': {
            'accuracy': _round(accuracy),
            'macro_f1_6': _round(macro_f1_six),
            'macro_f1_3': _round(macro_f1_three),
            'by_label': by_label,
            'by_group': by_group,
            'confusion': confusion,
            'errors': match_errors,
            'error_count': len(match_errors),
        },
        'evidence': {
            'correct': evidence_correct,
            'total': evidence_total,
            'accuracy': _round(evidence_accuracy),
            'by_clause_type': evidence_by_type,
        },
        'cases': case_records,
    }


def _fmt(value: float) -> str:
    return f'{value:.3f}'


def _extraction_table(results: Dict[str, Any]) -> str:
    lines = [
        '| 条款 | Precision | Recall | F1 | TP | FP | FN |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |',
    ]
    for clause_type in CLAUSE_TYPES:
        item = results['extraction']['by_clause_type'][clause_type]
        lines.append(
            f"| {CLAUSE_LABELS[clause_type]} | {_fmt(item['precision'])} | "
            f"{_fmt(item['recall'])} | {_fmt(item['f1'])} | {item['tp']} | "
            f"{item['fp']} | {item['fn']} |"
        )
    overall = results['extraction']['overall']
    lines.append(
        f"| **宏平均** | | | **{_fmt(overall['macro_f1'])}** | {overall['tp']} | "
        f"{overall['fp']} | {overall['fn']} |"
    )
    return '\n'.join(lines)


def _match_table(results: Dict[str, Any]) -> str:
    lines = [
        '| 标签 | Precision | Recall | F1 | 支持数（TP+FN） |',
        '| --- | ---: | ---: | ---: | ---: |',
    ]
    for label in VERDICTS:
        item = results['matching']['by_label'][label]
        lines.append(
            f"| {VERDICT_LABELS[label]} | {_fmt(item['precision'])} | "
            f"{_fmt(item['recall'])} | {_fmt(item['f1'])} | {item['tp'] + item['fn']} |"
        )
    return '\n'.join(lines)


def _confusion_table(results: Dict[str, Any]) -> str:
    header = '| 金标 \\ 预测 | ' + ' | '.join(VERDICT_LABELS[label] for label in VERDICTS) + ' |'
    lines = [header, '| --- | ' + ' | '.join('---:' for _ in VERDICTS) + ' |']
    for gold in VERDICTS:
        row = [str(results['matching']['confusion'][gold][pred]) for pred in VERDICTS]
        lines.append(f'| {VERDICT_LABELS[gold]} | ' + ' | '.join(row) + ' |')
    return '\n'.join(lines)


def _evidence_table(results: Dict[str, Any]) -> str:
    lines = ['| 条款 | 正确/总数 | 准确率 |', '| --- | ---: | ---: |']
    for clause_type in CLAUSE_TYPES:
        item = results['evidence']['by_clause_type'][clause_type]
        lines.append(
            f"| {CLAUSE_LABELS[clause_type]} | {item['correct']}/{item['total']} | "
            f"{_fmt(item['accuracy'])} |"
        )
    evidence = results['evidence']
    lines.append(f"| **总体** | {evidence['correct']}/{evidence['total']} | **{_fmt(evidence['accuracy'])}** |")
    return '\n'.join(lines)


def _errors_section(results: Dict[str, Any]) -> str:
    errors = results['matching']['errors']
    if not errors:
        return '无匹配错误。'
    lines = ['| 案例 | 子集 | 条款 | 金标 | 预测 |', '| --- | --- | --- | --- | --- |']
    for error in errors[:30]:
        lines.append(
            f"| {error['case']} | {error['split']} | {error['clause_label']} | "
            f"{VERDICT_LABELS[error['gold']]} | {VERDICT_LABELS[error['predicted']]} |"
        )
    if len(errors) > 30:
        lines.append(f'| … | | | | 另有 {len(errors) - 30} 条，见 eval_metrics.json |')
    return '\n'.join(lines)


def render_markdown(labels: Dict[str, Any], overall: Dict[str, Any],
                    by_split: Dict[str, Dict[str, Any]]) -> str:
    generated = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    template, paraphrase = by_split['template'], by_split['paraphrase']
    lines = [
        '# 条款抽取与跨文档匹配评测报告',
        '',
        f'- 运行时间：{generated}',
        f"- 数据集：{labels['dataset']}（{labels['description']}）",
        f"- 案例数：{labels['case_count']}（模板 {labels['splits']['template']}，改写 {labels['splits']['paraphrase']}）",
        '- 运行路径：规则抽取 + 确定性匹配（未配置模型，未调用模型）',
        '- 指标说明：抽取为文档级「是否存在该类条款」；匹配为五类条款 × 案例的六标签分类。',
        '',
        '> 数据为模板 + 改写合成的中文单页文本，不是真实合同分布；数字只代表规则路径在该数据集上的表现。',
        '',
        '## 一、总体结果',
        '',
        '| 指标 | 数值 |',
        '| --- | ---: |',
        f"| 条款抽取 Macro-F1 | {_fmt(overall['extraction']['overall']['macro_f1'])} |",
        f"| 条款抽取 Precision / Recall | {_fmt(overall['extraction']['overall']['precision'])} / {_fmt(overall['extraction']['overall']['recall'])} |",
        f"| 跨文档匹配 Macro-F1（六标签） | {_fmt(overall['matching']['macro_f1_6'])} |",
        f"| 跨文档匹配 Macro-F1（三分类） | {_fmt(overall['matching']['macro_f1_3'])} |",
        f"| 跨文档匹配 准确率 | {_fmt(overall['matching']['accuracy'])} |",
        f"| 证据定位准确率 | {_fmt(overall['evidence']['accuracy'])}（{overall['evidence']['correct']}/{overall['evidence']['total']}） |",
        '',
        '## 二、分子集结果',
        '',
        '| 子集 | 案例 | 抽取 Macro-F1 | 匹配 Macro-F1（六标签） | 匹配准确率 | 证据定位 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |',
    ]
    for name, label in (('template', '模板'), ('paraphrase', '改写')):
        result = by_split[name]
        lines.append(
            f"| {label} | {result['case_count']} | "
            f"{_fmt(result['extraction']['overall']['macro_f1'])} | "
            f"{_fmt(result['matching']['macro_f1_6'])} | "
            f"{_fmt(result['matching']['accuracy'])} | "
            f"{_fmt(result['evidence']['accuracy'])} |"
        )

    lines += [
        '',
        '## 三、条款抽取（五类）',
        '',
        _extraction_table(overall),
        '',
        '## 四、跨文档匹配（六标签）',
        '',
        _match_table(overall),
        '',
        '## 五、混淆矩阵',
        '',
        _confusion_table(overall),
        '',
        '## 六、证据定位',
        '',
        '判定标准：页码一致；`page.text[char_start:char_end] == quote`；quote 与金标句在去除空白/句末标点后互相包含。',
        '',
        _evidence_table(overall),
        '',
        '## 七、匹配错误样例',
        '',
        _errors_section(overall),
        '',
        '## 八、结论与限制',
        '',
        f"1. 模板子集（{template['case_count']} 组）抽取 {_fmt(template['extraction']['overall']['macro_f1'])} / "
        f"匹配 {_fmt(template['matching']['macro_f1_6'])} / 证据 {_fmt(template['evidence']['accuracy'])}；"
        '标签与规则口径一致，接近满分验证的是实现一致性。',
        f"2. 改写子集（{paraphrase['case_count']} 组）抽取 {_fmt(paraphrase['extraction']['overall']['macro_f1'])} / "
        f"匹配 {_fmt(paraphrase['matching']['macro_f1_6'])} / 证据 {_fmt(paraphrase['evidence']['accuracy'])}。"
        '本轮补充的同义词、否定/条件表达与「起始日 + 时长 vs 起止日期」换算正是针对这类改写；'
        '改写样本只有 10 组，规则与样本高度重合，提升幅度不能外推为真实合同的泛化能力。',
        '3. 规则仍是字面匹配：未覆盖的表达（方言、英文、复杂嵌套条件、跨句指代）会继续漏抽。'
        '已另建 40 组独立留出集（`eval_data/heldout/`），基线见 `reports/eval_heldout_report.md`；'
        '留出集数字明显低于本报告，说明本报告的 1.000 主要来自规则与调参样本重合。',
        '4. 证据定位只覆盖单页 txt；PDF 多页、扫描件与 OCR 尚未纳入本评测。',
        '5. 未使用模型路径；若配置 `CLAUSE_LLM_PROVIDER`，模型只提议片段，定位与判定仍由确定性代码完成，需另跑模型对照。',
        '6. 结果仅用于课程项目评测，不构成法律意见。',
    ]
    return '\n'.join(lines) + '\n'


def render_dashboard(labels: Dict[str, Any], overall: Dict[str, Any],
                     by_split: Dict[str, Dict[str, Any]]) -> str:
    def card(title: str, value: str, note: str) -> str:
        return (
            '<div class="card"><div class="card-title">'
            + html.escape(title)
            + '</div><div class="card-value">'
            + html.escape(value)
            + '</div><div class="card-note">'
            + html.escape(note)
            + '</div></div>'
        )

    split_rows = ''.join(
        f"<tr><td>{'模板' if key == 'template' else '改写'}</td>"
        f"<td>{value['case_count']}</td>"
        f"<td>{_fmt(value['extraction']['overall']['macro_f1'])}</td>"
        f"<td>{_fmt(value['matching']['macro_f1_6'])}</td>"
        f"<td>{_fmt(value['matching']['accuracy'])}</td>"
        f"<td>{_fmt(value['evidence']['accuracy'])}</td></tr>"
        for key, value in by_split.items()
    )
    paraphrase = by_split['paraphrase']
    warn = (
        f"模板子集 {by_split['template']['case_count']} 组，匹配 Macro-F1 "
        f"{_fmt(by_split['template']['matching']['macro_f1_6'])}；"
        f"改写子集仅 {paraphrase['case_count']} 组，匹配 Macro-F1 "
        f"{_fmt(paraphrase['matching']['macro_f1_6'])}。"
        '本轮规则补充与这 10 组改写高度重合，接近满分只说明覆盖了这批表达，不能推断真实合同分布。'
    )
    extraction_rows = ''.join(
        f"<tr><td>{CLAUSE_LABELS[clause_type]}</td>"
        f"<td>{_fmt(item['precision'])}</td><td>{_fmt(item['recall'])}</td>"
        f"<td>{_fmt(item['f1'])}</td></tr>"
        for clause_type, item in overall['extraction']['by_clause_type'].items()
    )
    match_rows = ''.join(
        f"<tr><td>{VERDICT_LABELS[label]}</td>"
        f"<td>{_fmt(item['precision'])}</td><td>{_fmt(item['recall'])}</td>"
        f"<td>{_fmt(item['f1'])}</td><td>{item['tp'] + item['fn']}</td></tr>"
        for label, item in overall['matching']['by_label'].items()
    )
    confusion_rows = ''.join(
        '<tr><th>'
        + VERDICT_LABELS[gold]
        + '</th>'
        + ''.join(
            f"<td>{overall['matching']['confusion'][gold][pred]}</td>" for pred in VERDICTS
        )
        + '</tr>'
        for gold in VERDICTS
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>条款抽取与匹配评测看板</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin: 0; font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
         background: #f6f8fb; color: #1f2937; }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px 56px; }}
  h1 {{ font-size: 26px; margin: 0 0 6px; }}
  .sub {{ color: #6b7280; font-size: 13px; line-height: 1.7; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
            gap: 14px; margin: 24px 0; }}
  .card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 16px; }}
  .card-title {{ font-size: 12px; color: #6b7280; }}
  .card-value {{ font-size: 28px; font-weight: 700; margin: 6px 0 2px; color: #1d4ed8; }}
  .card-note {{ font-size: 12px; color: #9ca3af; }}
  section {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 10px;
             padding: 18px; margin-top: 18px; }}
  h2 {{ font-size: 16px; margin: 0 0 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ border-bottom: 1px solid #eef1f5; padding: 8px; text-align: left; }}
  th {{ color: #6b7280; font-weight: 600; background: #f9fafb; }}
  .note {{ font-size: 12px; color: #6b7280; line-height: 1.8; }}
  .warn {{ background: #fffbeb; border: 1px solid #fde68a; color: #92400e;
           border-radius: 8px; padding: 10px 12px; font-size: 13px; line-height: 1.7; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>条款抽取与跨文档匹配 · 评测看板</h1>
  <div class="sub">
    数据集：{html.escape(labels['dataset'])} · {labels['case_count']} 组
    （模板 {labels['splits']['template']} / 改写 {labels['splits']['paraphrase']}）<br>
    运行路径：规则抽取 + 确定性匹配（未调用模型） · 数据为合成模板，非真实合同分布
  </div>

  <div class="cards">
    {card('条款抽取 Macro-F1', _fmt(overall['extraction']['overall']['macro_f1']), '五类条款，文档级存在性')}
    {card('匹配 Macro-F1（六标签）', _fmt(overall['matching']['macro_f1_6']), '一致/矛盾/四类缺失或证据不足')}
    {card('匹配 Macro-F1（三分类）', _fmt(overall['matching']['macro_f1_3']), '一致/矛盾/证据不足')}
    {card('证据定位准确率', _fmt(overall['evidence']['accuracy']), f"{overall['evidence']['correct']}/{overall['evidence']['total']} 条")}
  </div>

  <div class="warn">
    {html.escape(warn)}
  </div>

  <section>
    <h2>分子集结果</h2>
    <table>
      <thead><tr><th>子集</th><th>案例</th><th>抽取 Macro-F1</th><th>匹配 Macro-F1</th><th>匹配准确率</th><th>证据定位</th></tr></thead>
      <tbody>{split_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>条款抽取（五类）</h2>
    <table>
      <thead><tr><th>条款</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead>
      <tbody>{extraction_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>跨文档匹配（六标签）</h2>
    <table>
      <thead><tr><th>标签</th><th>Precision</th><th>Recall</th><th>F1</th><th>支持数</th></tr></thead>
      <tbody>{match_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>混淆矩阵（行=金标，列=预测）</h2>
    <table>
      <thead><tr><th>金标 \\ 预测</th>{''.join(f'<th>{VERDICT_LABELS[label]}</th>' for label in VERDICTS)}</tr></thead>
      <tbody>{confusion_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>口径与限制</h2>
    <div class="note">
      抽取指标：文档级判断某类条款是否被抽出。<br>
      匹配指标：每个案例的五类条款与六标签金标比较；Macro-F1 只对金标中出现的标签取平均。<br>
      证据定位：页码一致 + 字符区间回读等于 quote + quote 与金标句互相包含。<br>
      只覆盖单页 txt；PDF 多页、扫描件、模型抽取路径未纳入本次评测。
    </div>
  </section>
</div>
</body>
</html>
"""


def main() -> None:
    labels = json.loads((DATA / 'labels.json').read_text(encoding='utf-8'))
    cases = labels['cases']

    overall = evaluate(cases)
    by_split = {
        split: evaluate(cases, split)
        for split in ('template', 'paraphrase')
    }

    REPORTS.mkdir(parents=True, exist_ok=True)
    metrics = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'environment': {
            'extractor': 'rules',
            'model_used': False,
            'python': sys.version.split()[0],
        },
        'dataset': {
            'name': labels['dataset'],
            'description': labels['description'],
            'case_count': labels['case_count'],
            'splits': labels['splits'],
        },
        'overall': overall,
        'by_split': by_split,
    }
    (REPORTS / 'eval_metrics.json').write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    (REPORTS / 'eval_report.md').write_text(
        render_markdown(labels, overall, by_split), encoding='utf-8',
    )
    (REPORTS / 'eval_dashboard.html').write_text(
        render_dashboard(labels, overall, by_split), encoding='utf-8',
    )

    print('==== 评测结果（规则路径，未调用模型） ====')
    print(f"案例数：{overall['case_count']}")
    print(f"条款抽取 Macro-F1：{overall['extraction']['overall']['macro_f1']:.3f}")
    print(f"匹配 Macro-F1（六标签）：{overall['matching']['macro_f1_6']:.3f}")
    print(f"匹配 Macro-F1（三分类）：{overall['matching']['macro_f1_3']:.3f}")
    print(f"匹配准确率：{overall['matching']['accuracy']:.3f}")
    print(f"证据定位：{overall['evidence']['correct']}/{overall['evidence']['total']} "
          f"= {overall['evidence']['accuracy']:.3f}")
    for split, result in by_split.items():
        print(
            f"[{split}] 抽取 {result['extraction']['overall']['macro_f1']:.3f} / "
            f"匹配 {result['matching']['macro_f1_6']:.3f} / "
            f"证据 {result['evidence']['accuracy']:.3f}"
        )
    print(f'报告已写入 {REPORTS}')


if __name__ == '__main__':
    main()
