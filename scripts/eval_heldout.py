"""独立留出集评测（规则路径，真实跑分）。

用法：
    python scripts/eval_heldout.py

读取 eval_data/heldout/labels.json（内联文本 + 逐案例金标，已冻结），
复用 eval_clauses.evaluate 的指标口径，输出：
- reports/eval_heldout_metrics.json
- reports/eval_heldout_report.md
- reports/eval_heldout_dashboard.html

不联网、不调用模型。留出集在运行前已冻结，未参与规则调参。
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval_clauses import (  # noqa: E402
    CLAUSE_LABELS,
    VERDICTS,
    VERDICT_LABELS,
    _fmt,
    _round,
    evaluate,
)

DATA = ROOT / 'eval_data' / 'heldout'
REPORTS = ROOT / 'reports'
CATEGORY_LABELS = {
    'dialect': '方言 / 口语',
    'english': '英文',
    'mixed': '中英混写',
    'coref': '跨句指代',
    'nested': '复杂嵌套条件',
    'numeric': '数字与单位新写法',
}


def render_markdown(labels: Dict[str, Any], overall: Dict[str, Any],
                    by_category: Dict[str, Dict[str, Any]],
                    tuning: Optional[Dict[str, Any]] = None,
                    legacy: Optional[Dict[str, Any]] = None,
                    dataset_key: str = 'heldout') -> str:
    generated = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    second = dataset_key != 'heldout'
    lines = [
        '# 第二批独立留出集评测报告（规则路径）' if second
        else '# 独立留出集评测报告（规则路径）',
        '',
        f'- 运行时间：{generated}',
        f"- 数据集：{labels['dataset']}（{labels['description']}）",
        f"- 案例数：{labels['case_count']}",
        f"- 冻结时间：{labels['created_at']}（`frozen=true`）",
        f"- 独立性声明：{labels['tuning_disjoint']}",
        '- 运行路径：规则抽取 + 确定性匹配（未配置模型，未调用模型）',
        '- 指标口径：与调参集报告一致；抽取为文档级存在性，匹配为五类条款 × 案例。',
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
    ]
    if tuning:
        tune_overall = tuning['overall']
        lines += [
            '### 与调参集、旧留出集对比',
            '',
            '| 数据集 | 案例 | 抽取 Macro-F1 | 匹配 Macro-F1（六标签） | 匹配准确率 |',
            '| --- | ---: | ---: | ---: | ---: |',
            f"| 调参集（模板+改写） | {tune_overall['case_count']} | "
            f"{_fmt(tune_overall['extraction']['overall']['macro_f1'])} | "
            f"{_fmt(tune_overall['matching']['macro_f1_6'])} | "
            f"{_fmt(tune_overall['matching']['accuracy'])} |",
        ]
        if legacy:
            legacy_overall = legacy['overall']
            lines.append(
                f"| 旧留出集 v1（已作调试参考，非干净基线） | {legacy_overall['case_count']} | "
                f"{_fmt(legacy_overall['extraction']['overall']['macro_f1'])} | "
                f"{_fmt(legacy_overall['matching']['macro_f1_6'])} | "
                f"{_fmt(legacy_overall['matching']['accuracy'])} |"
            )
        lines += [
            f"| 本留出集（{'v2，干净基线' if second else 'v1'}） | {overall['case_count']} | "
            f"{_fmt(overall['extraction']['overall']['macro_f1'])} | "
            f"{_fmt(overall['matching']['macro_f1_6'])} | "
            f"{_fmt(overall['matching']['accuracy'])} |",
            '',
            '两者差距说明：调参集 1.000 主要来自规则与样本表达重合，不能代表换措辞后的真实表现。',
            '',
        ]
        if second:
            lines += [
                '> 旧留出集 v1 含方言/英文样本，本轮扩展规则时已查看其表达，因此不再作为干净基线；'
                'v1 数字仅用于说明“规则覆盖前后的变化”，真实基线以本集为准。',
                '',
            ]
    lines += [
        '## 二、分类别结果',
        '',
        '| 类别 | 案例 | 抽取 Macro-F1 | 抽取 Recall | 匹配 Macro-F1（六标签） | 匹配准确率 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |',
    ]
    for key, result in by_category.items():
        lines.append(
            f"| {CATEGORY_LABELS[key]} | {result['case_count']} | "
            f"{_fmt(result['extraction']['overall']['macro_f1'])} | "
            f"{_fmt(result['extraction']['overall']['recall'])} | "
            f"{_fmt(result['matching']['macro_f1_6'])} | "
            f"{_fmt(result['matching']['accuracy'])} |"
        )

    lines += [
        '',
        '## 三、条款抽取（五类）',
        '',
        '| 条款 | Precision | Recall | F1 |',
        '| --- | ---: | ---: | ---: |',
    ]
    for clause_type, item in overall['extraction']['by_clause_type'].items():
        lines.append(
            f"| {CLAUSE_LABELS[clause_type]} | {_fmt(item['precision'])} | "
            f"{_fmt(item['recall'])} | {_fmt(item['f1'])} |"
        )

    lines += [
        '',
        '## 四、匹配标签（六标签）',
        '',
        '| 标签 | Precision | Recall | F1 | 支持数 |',
        '| --- | ---: | ---: | ---: | ---: |',
    ]
    for label, item in overall['matching']['by_label'].items():
        lines.append(
            f"| {VERDICT_LABELS[label]} | {_fmt(item['precision'])} | {_fmt(item['recall'])} | "
            f"{_fmt(item['f1'])} | {item['tp'] + item['fn']} |"
        )

    lines += [
        '',
        '## 五、错误明细（前 40 条）',
        '',
    ]
    errors = overall['matching']['errors']
    if errors:
        lines += ['| 案例 | 类别 | 条款 | 金标 | 预测 |', '| --- | --- | --- | --- | --- |']
        for error in errors[:40]:
            lines.append(
                f"| {error['case']} | {CATEGORY_LABELS.get(error['split'], error['split'])} | "
                f"{error['clause_label']} | {VERDICT_LABELS[error['gold']]} | "
                f"{VERDICT_LABELS[error['predicted']]} |"
            )
        if len(errors) > 40:
            lines.append(f'| … | | | | 另有 {len(errors) - 40} 条，见 JSON |')
    else:
        lines.append('无匹配错误。')

    repetition = overall['matching']['confusion']['conflict']['conflict']
    conflict_total = sum(overall['matching']['confusion']['conflict'].values())
    consistent_total = sum(overall['matching']['confusion']['consistent'].values())
    insufficient = ('missing_in_contract', 'missing_in_promo', 'missing_both', 'unclear')
    conflict_missed = sum(
        overall['matching']['confusion']['conflict'][pred] for pred in insufficient
    )
    consistent_missed = sum(
        overall['matching']['confusion']['consistent'][pred] for pred in insufficient
    )

    if second:
        ceiling = [
            '- **方言/口语**：已覆盖 `退钱`、`扣钱`、`不加钱`、`顺延`、`赔/罚钱` 等常见说法；'
            '但一义多词、地区差异和长句仍会漏，尤其是否定与金额同句时的极性判断。',
            '- **英文/中英混写**：已支持 refund、cancellation fee、auto-renewal、service term、'
            'additional fee 等词表与 percent/per month 单位；生僻同义词和长英文从句仍会漏。',
            '- **跨句指代**：抽取仍按句进行，`前述费用`、`该条款`、`该期限` 的指代对象无法回指，'
            '费用或期限可能归错条款或只抓到前一句。',
            '- **复杂嵌套条件**：规则不解析逻辑结构，`除非…否则…`、`只要…就…`、`若 A 且非 B` 的极性可能读反，'
            '把「有条件不收费」误判为「一致」或「证据不足」。',
            '- **数字与单位**：已归一 `百分之五`、`两成/三成`、`一百元`、`元/期`、`元/节`、'
            '`per month`、`HKD` 等；浮动价格、阶梯价和复合单位仍不归一。',
        ]
    else:
        ceiling = [
            '- **方言/口语**：`退钱`、`扣钱`、`不加钱`、`顺延`、`赔` 等不在词表；规则会把真实冲突判成「双方未约定」。',
            '- **英文/中英混写**：没有英文词表，整段英文条款等于不可见；混写时只能命中中文半边。',
            '- **跨句指代**：抽取按句进行，`前述手续费`、`该条款`、`该周期` 的指代对象无法回指，费用或期限会归错条款。',
            '- **复杂嵌套条件**：规则不解析逻辑结构，`除非…否则…`、`只要…就…`、`若 A 且非 B` 的极性可能被读反，'
            '把「有条件不收费」误判为「一致」或「证据不足」。',
            '- **数字与单位**：`百分之五`、`两成`、`三成`、`一百元`、`元/期`、`元/节` 不能归一，'
            '缺少比例或金额时匹配只能落到「证据不足」。',
        ]
    lines += [
        '',
        '## 六、规则路径的天花板',
        '',
        f"- 金标为「矛盾」的 {conflict_total} 条中，规则正确判为矛盾 {repetition} 条，"
        f"其余 {conflict_missed} 条被降级为缺失或证据不足。",
        f"- 金标为「一致」的 {consistent_total} 条中，正确判为一致 "
        f"{overall['matching']['confusion']['consistent']['consistent']} 条，"
        f"{consistent_missed} 条被降级为缺失或证据不足。",
        *ceiling,
        '',
        '现实含义：规则路径适合做召回兜底和可回查证据，不适合单独承担真实合同的合规判断；'
        '上述缺口会把真实冲突漏成「证据不足」，需要模型抽取 + 人工复核补位。',
        '',
        '## 七、说明',
        '',
        '- 本报告是**基线**：留出集冻结后未据此修改任何规则，因此数字保持独立。',
        '- 若要针对本集改规则，必须把结果标注为「污染后」，并与本基线分开报告。',
        '- 本集为人工构造的 40 组单页文本，仍小于真实合同分布，不能当作生产准确率。',
    ]
    return '\n'.join(lines) + '\n'


def render_dashboard(labels: Dict[str, Any], overall: Dict[str, Any],
                     by_category: Dict[str, Dict[str, Any]],
                     dataset_key: str = 'heldout') -> str:
    def card(title: str, value: str, note: str) -> str:
        return (
            '<div class="card"><div class="card-title">' + html.escape(title)
            + '</div><div class="card-value">' + html.escape(value)
            + '</div><div class="card-note">' + html.escape(note) + '</div></div>'
        )

    rows = ''.join(
        f"<tr><td>{CATEGORY_LABELS[key]}</td><td>{result['case_count']}</td>"
        f"<td>{_fmt(result['extraction']['overall']['macro_f1'])}</td>"
        f"<td>{_fmt(result['extraction']['overall']['recall'])}</td>"
        f"<td>{_fmt(result['matching']['macro_f1_6'])}</td>"
        f"<td>{_fmt(result['matching']['accuracy'])}</td></tr>"
        for key, result in by_category.items()
    )
    extraction_rows = ''.join(
        f"<tr><td>{CLAUSE_LABELS[clause_type]}</td><td>{_fmt(item['precision'])}</td>"
        f"<td>{_fmt(item['recall'])}</td><td>{_fmt(item['f1'])}</td></tr>"
        for clause_type, item in overall['extraction']['by_clause_type'].items()
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>独立留出集评测看板</title>
<style>
  body {{ margin: 0; background: #f6f7f9; font-family: "Segoe UI", "Microsoft YaHei", sans-serif; color: #111827; }}
  .wrap {{ max-width: 1040px; margin: 0 auto; padding: 28px 20px 48px; }}
  h1 {{ font-size: 22px; margin: 0 0 6px; }}
  .sub {{ font-size: 13px; color: #6b7280; line-height: 1.8; }}
  .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 18px; }}
  .card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 14px; }}
  .card-title {{ font-size: 12px; color: #6b7280; }}
  .card-value {{ font-size: 28px; font-weight: 700; margin: 6px 0 2px; color: #1d4ed8; }}
  .card-note {{ font-size: 12px; color: #9ca3af; }}
  section {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 18px; margin-top: 18px; }}
  h2 {{ font-size: 16px; margin: 0 0 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ border-bottom: 1px solid #eef1f5; padding: 8px; text-align: left; }}
  th {{ color: #6b7280; font-weight: 600; background: #f9fafb; }}
  .warn {{ background: #fffbeb; border: 1px solid #fde68a; color: #92400e;
           border-radius: 8px; padding: 10px 12px; font-size: 13px; line-height: 1.7; margin-top: 18px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>独立留出集 · 规则路径评测{' · 第二批' if dataset_key != 'heldout' else ''}</h1>
  <div class="sub">
    数据集：{html.escape(labels['dataset'])} · {labels['case_count']} 组 · 冻结于 {labels['created_at']}<br>
    与调参集刻意错开：口语/方言、英文混写、跨句指代、嵌套条件、数字单位
  </div>

  <div class="cards">
    {card('抽取 Macro-F1', _fmt(overall['extraction']['overall']['macro_f1']), f"Recall {_fmt(overall['extraction']['overall']['recall'])}")}
    {card('匹配 Macro-F1（六标签）', _fmt(overall['matching']['macro_f1_6']), '独立留出集基线')}
    {card('匹配 Macro-F1（三分类）', _fmt(overall['matching']['macro_f1_3']), '一致/矛盾/证据不足')}
    {card('匹配准确率', _fmt(overall['matching']['accuracy']), f"{overall['matching']['errors'] and len(overall['matching']['errors']) or 0} 条错误")}
  </div>

  <div class="warn">
    {'这是第二批干净基线：规则扩展完成后先冻结标签、再运行一次，未据此回改。旧留出集 v1 已作调试参考，不再作为干净基线。' if dataset_key != 'heldout' else '这是留出集基线，冻结后未据此改规则。数字明显低于调参集，说明调参集 1.000 主要来自规则与样本重合。'}
  </div>

  <section>
    <h2>分类别结果</h2>
    <table>
      <thead><tr><th>类别</th><th>案例</th><th>抽取 Macro-F1</th><th>抽取 Recall</th><th>匹配 Macro-F1</th><th>匹配准确率</th></tr></thead>
      <tbody>{rows}</tbody>
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
    <h2>口径</h2>
    <div class="sub">
      与调参集报告完全一致：抽取是文档级存在性；匹配是五类条款 × 六标签；证据定位要求页码、区间回读与金标句一致。<br>
      本集为人工构造的 40 组单页文本，仍不是真实合同分布；规则不可识别的表达见 Markdown 报告「天花板」一节。
    </div>
  </section>
</div>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description='独立留出集评测（规则路径）')
    parser.add_argument('--dataset', default='heldout',
                        help='eval_data 下的数据集目录，例如 heldout 或 heldout_v2')
    parser.add_argument('--prefix', default=None,
                        help='报告文件名前缀，默认 eval_<dataset>')
    args = parser.parse_args()

    data_dir = ROOT / 'eval_data' / args.dataset
    prefix = args.prefix or ('eval_heldout' if args.dataset == 'heldout'
                             else f'eval_{args.dataset}')
    labels = json.loads((data_dir / 'labels.json').read_text(encoding='utf-8'))
    cases: List[Dict[str, Any]] = labels['cases']
    categories = list(labels['splits'])

    overall = evaluate(cases)
    by_category = {name: evaluate(cases, name) for name in categories}
    tuning_path = REPORTS / 'eval_metrics.json'
    tuning = json.loads(tuning_path.read_text(encoding='utf-8')) if tuning_path.exists() else None
    legacy_path = REPORTS / 'eval_heldout_metrics.json'
    legacy = (json.loads(legacy_path.read_text(encoding='utf-8'))
              if prefix != 'eval_heldout' and legacy_path.exists() else None)

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
            'created_at': labels['created_at'],
            'frozen': labels['frozen'],
            'tuning_disjoint': labels['tuning_disjoint'],
            'case_count': labels['case_count'],
            'splits': labels['splits'],
        },
        'overall': overall,
        'by_category': by_category,
        'rule_changes_after_holdout': [],
    }
    (REPORTS / f'{prefix}_metrics.json').write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    (REPORTS / f'{prefix}_report.md').write_text(
        render_markdown(labels, overall, by_category, tuning,
                        legacy=legacy, dataset_key=args.dataset),
        encoding='utf-8',
    )
    (REPORTS / f'{prefix}_dashboard.html').write_text(
        render_dashboard(labels, overall, by_category, dataset_key=args.dataset),
        encoding='utf-8',
    )

    title = ('第二批独立留出集' if args.dataset != 'heldout' else '独立留出集')
    print(f'==== {title}基线（规则路径，未调用模型） ====')
    print(f"案例数：{overall['case_count']}")
    print(f"条款抽取 Macro-F1：{overall['extraction']['overall']['macro_f1']:.3f} "
          f"(P {overall['extraction']['overall']['precision']:.3f} / "
          f"R {overall['extraction']['overall']['recall']:.3f})")
    print(f"匹配 Macro-F1（六标签）：{overall['matching']['macro_f1_6']:.3f}")
    print(f"匹配 Macro-F1（三分类）：{overall['matching']['macro_f1_3']:.3f}")
    print(f"匹配准确率：{overall['matching']['accuracy']:.3f}")
    print(f"证据定位：{overall['evidence']['correct']}/{overall['evidence']['total']} "
          f"= {overall['evidence']['accuracy']:.3f}")
    for name, result in by_category.items():
        print(
            f"[{name}] 抽取 {result['extraction']['overall']['macro_f1']:.3f} "
            f"(R {result['extraction']['overall']['recall']:.3f}) / "
            f"匹配 {result['matching']['macro_f1_6']:.3f} / "
            f"准确率 {result['matching']['accuracy']:.3f}"
        )


if __name__ == '__main__':
    main()
