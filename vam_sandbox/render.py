"""Render contract scenario results as Markdown or a standalone HTML tree."""

import html
import re
from typing import Any, Dict, List

from .comparison import ENUM_LABELS, OBJECTIVES, PARAMETERS, ROLES, TEMPLATES, TRIGGERS

_LEGEND = """
<div style="display:flex;gap:14px;flex-wrap:wrap;margin:8px 0 14px 0;font-size:13px;">
  <span><span style="display:inline-block;width:12px;height:12px;background:#e8f5e9;border:1px solid #43a047;border-radius:3px;"></span> 不利因素较低（&lt;4）</span>
  <span><span style="display:inline-block;width:12px;height:12px;background:#fff8e1;border:1px solid #f9a825;border-radius:3px;"></span> 中风险（4-6）</span>
  <span><span style="display:inline-block;width:12px;height:12px;background:#ffebee;border:1px solid #e53935;border-radius:3px;"></span> 高风险（≥7）</span>
</div>
"""

_CSS = """
<style>
.vam-wrap { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; color:#1f2937; line-height:1.55; }
.vam-title { font-size:20px; font-weight:700; margin:6px 0 4px; }
.vam-sub { color:#6b7280; font-size:13px; margin-bottom:10px; }
.vam-list { margin:4px 0 10px; padding-left:18px; }
.vam-list li { margin:2px 0; font-size:13px; }
ul.vam-tree, ul.vam-tree ul { list-style:none; margin:6px 0 0 0; padding-left:20px; border-left:2px solid #e5e7eb; }
ul.vam-tree { border-left:none; padding-left:0; }
.vam-node { margin:6px 0; }
.vam-node summary { cursor:pointer; font-weight:600; padding:6px 8px; border-radius:6px; background:#f3f4f6; border:1px solid #e5e7eb; }
.vam-node summary:hover { background:#eef2ff; }
.vam-node summary .score { font-weight:700; color:#1d4ed8; margin-left:6px; }
.vam-leaf summary { font-weight:700; }
.vam-meta { margin:6px 0 2px 8px; padding:8px 10px; background:#fff; border:1px solid #e5e7eb; border-radius:6px; }
.vam-meta .label { font-weight:700; color:#374151; }
.vam-meta ul { margin:4px 0 0; padding-left:16px; }
.vam-meta li { margin:2px 0; font-size:13px; }
.risk-low { background:#e8f5e9 !important; border-color:#a5d6a7 !important; }
.risk-mid { background:#fff8e1 !important; border-color:#ffe082 !important; }
.risk-high { background:#ffebee !important; border-color:#ef9a9a !important; }
.badge { display:inline-block; padding:1px 7px; border-radius:10px; font-size:12px; color:#fff; }
</style>
"""


def _risk_class(risk: float | None) -> str:
    if risk is None:
        return ''
    if risk >= 7:
        return 'risk-high'
    if risk >= 4:
        return 'risk-mid'
    return 'risk-low'


def _badge(risk: float | None) -> str:
    if risk is None:
        return '<span class="badge" style="background:#475569;">未评分</span>'
    if risk >= 7:
        return '<span class="badge" style="background:#e53935;">高风险</span>'
    if risk >= 4:
        return '<span class="badge" style="background:#f9a825;">中风险</span>'
    return '<span class="badge" style="background:#43a047;">低风险</span>'


def _fmt(value: Any, digits: int = 1) -> str:
    if value is None:
        return '待确认'
    if isinstance(value, float):
        return f'{value:.{digits}f}'
    return str(value)


def _meta_list(title: str, items: List[str]) -> str:
    if not items:
        return ''
    lis = ''.join(f'<li>{html.escape(i)}</li>' for i in items)
    return (
        f'<div class="vam-meta"><span class="label">{html.escape(title)}：</span>'
        f'<ul>{lis}</ul></div>'
    )


def _render_node(node: Dict[str, Any], depth: int) -> str:
    risk = node.get('_risk')
    cls = _risk_class(risk)
    label = html.escape(node['branch'])

    if node['children']:
        summary = f'{label} {_badge(risk)}'
        inner = ''
        if node.get('premise'):
            inner += _meta_list('前提', [node['premise']])
        inner += _meta_list('连锁事件', node.get('events', []))
        inner += _meta_list('关键变量', node.get('key_variables', []))
        children = ''.join(_render_node(c, depth + 1) for c in node['children'])
        open_attr = ' open' if depth == 0 else ''
        return (
            f'<li class="vam-node"><details{open_attr}><summary class="{cls}">{summary}</summary>'
            f'{inner}<ul class="vam-tree">{children}</ul></details></li>'
        )

    # 叶子节点
    ev = node.get('evaluation', {})
    score = ev.get('total_score')
    summary = (
        f'{label} {_badge(risk)}'
        + (f'<span class="score">实验评分 {_fmt(score)}</span>' if score is not None else '')
    )
    inner = ''
    if node.get('premise'):
        inner += _meta_list('前提', [node['premise']])
    inner += _meta_list('连锁事件', node.get('events', []))
    inner += _meta_list('收益', node.get('upsides', []))
    inner += _meta_list('风险', node.get('risks', []))
    inner += _meta_list('关键变量', node.get('key_variables', []))
    if ev.get('evidence'):
        inner += _meta_list('模型评分说明', [ev['evidence']])

    def _fmt_score(v: Any) -> str:
        return '信息不足' if v is None else _fmt(v)

    metrics = (
        f'<div class="vam-meta"><span class="label">评分：</span>'
        f'不利程度 {_fmt_score(ev.get("risk_score"))} / 10；'
        f'应对条件 {_fmt_score(ev.get("feasibility_score"))} / 10；'
        f'条件负担 {_fmt_score(ev.get("loss_score"))} / 10；'
        f'模型自评 {_fmt_score(ev.get("confidence"))}'
        f'</div>'
    )
    inner = metrics + inner

    return (
        f'<li class="vam-node vam-leaf"><details open><summary class="{cls}">{summary}</summary>'
        f'{inner}</details></li>'
    )


def _md(value: Any) -> str:
    text = _fmt(value, 2).replace('\r', '').replace('\n', ' ')
    return re.sub(r'([\\`*_{}\[\]()#+\-.!|>~])', r'\\\1', html.escape(text, quote=False).replace('&gt;', '>'))


def _render_node_markdown(node: Dict[str, Any], depth: int, lines: List[str]) -> None:
    prefix = '#' * min(depth + 3, 6)
    lines.append(f'{prefix} {node["id"]} {_md(node["branch"])}')
    if node.get('premise'):
        lines.append(f'- 前提：{_md(node["premise"])}')
    trigger = node.get('trigger', 'unknown')
    lines.append(f'- 假设：{TRIGGERS.get(trigger, "待确认")}')
    if node.get('trigger_override'):
        lines.append(f'- 用户设定的计算状态：{TRIGGERS[node["trigger_override"]]}')
    if node.get('evidence_ids'):
        lines.append(f'- 关联原文：{", ".join(node["evidence_ids"])}')
    for key, title in [('events', '连锁事件'), ('upsides', '收益'), ('risks', '风险'), ('key_variables', '关键变量')]:
        items = node.get(key, [])
        if items:
            lines.append(f'- {title}：')
            lines.extend(f'  - {_md(i)}' for i in items)
    ev = node.get('evaluation')
    if ev and ev.get('status') != 'disabled':
        status = {'valid': '可用', 'missing': '信息不足', 'invalid': '模型返回非法分值', 'error': '评分调用失败'}
        lines.append(
            f'- 实验评分（{status.get(ev.get("status"), "待确认")}）：综合分 {_fmt(ev.get("total_score"))}；'
            f'不利程度 {_fmt(ev.get("risk_score"))} / 10；'
            f'应对条件 {_fmt(ev.get("feasibility_score"))} / 10；'
            f'条件负担 {_fmt(ev.get("loss_score"))} / 10；'
            f'模型自评 {_fmt(ev.get("confidence"), 2)}'
        )
        if ev.get('scorer_model'):
            lines.append(f'- 评分模型：{_md(ev["scorer_model"])}')
        if ev.get('evidence'):
            lines.append(f'- 模型评分说明：{_md(ev["evidence"])}')
    for child in node.get('children', []):
        _render_node_markdown(child, depth + 1, lines)


def render_markdown_report(result: Dict[str, Any]) -> str:
    tree = result.get('tree', {})
    study = result.get('study', {})
    actions = {action['id']: action for action in study.get('actions', [])}
    comparison = result.get('comparison', {})

    lines: List[str] = [
        '# 合同情景分析与方案比较报告',
        '',
        f'## 场景\n\n{_md(tree.get("scenario", ""))}',
        '',
        '> 本报告为有限情景推演，不构成投资或法律建议。',
        '',
        f'- 记录：{result.get("run_id", "—")}',
        f'- 用户身份：{ROLES.get(study.get("role"), "未指定")}',
        f'- 关注目标：{OBJECTIVES.get(study.get("objective"), "未指定")}',
        f'- 分析方式：{TEMPLATES.get(study.get("template"), "条款与责任")}',
        f'- 用户背景：{_md(result.get("query", ""))}',
        '',
    ]

    lines.extend(['## 所选合同原文', ''])
    for item in study.get('evidence', []):
        lines.append(f'- **{item["id"]}** {_md(item["filename"])} · 第 {item["page"]} 页：{_md(item["quote"])}')
    if not study.get('evidence'):
        lines.append('未关联 PDF 原文。')
    if tree.get('trigger_excerpt'):
        excerpt = tree['trigger_excerpt']
        lines.append(f'- 供核对的条件片段（{excerpt["evidence_id"] or "用户背景"}）：{_md(excerpt["quote"])}')
    for key, heading in [('assumptions', '情景假设'), ('uncertainties', '待确认项'), ('warnings', '情景覆盖说明')]:
        if tree.get(key):
            lines.extend(['', f'## {heading}', ''])
            lines.extend(f'- {_md(item)}' for item in tree[key])

    if actions:
        if comparison.get('direction') == 'receive':
            lines.append('\n> 金额按合同约定的应收口径展示，实际收款仍取决于履行情况。\n')
        lines.extend(['', '## 比较方案与用户设定的参数', ''])
        for aid, action in actions.items():
            lines.append(f'### {aid} {_md(action["label"])}')
            if action['terms']:
                lines.append(f'- 假设条款：{_md(action["terms"])}')
            params = action.get('parameters', {})
            for key, label in PARAMETERS.get(study.get('template'), {}).items():
                value = params.get(key)
                if value not in (None, ''):
                    lines.append(f'- {label}：{_md(ENUM_LABELS.get(str(value), value))}')
            if params.get('early_exit_applies') is True:
                lines.append('- 用户已确认退租时间及通知/豁免条件适用。')
            peak = comparison.get('max_amounts', {}).get(aid)
            if peak is not None:
                lines.append(f'- 已列情景中的该项最高金额：{peak:,.2f} 元。')
        lines.extend(['', '## 同一情景下的方案后果', ''])
        for scenario in comparison.get('scenarios', []):
            lines.extend([
                f'### {scenario["leaf_id"]} {_md(scenario["branch"])}',
                f'- 计算前提：{TRIGGERS[scenario["trigger"]]}',
                f'- 比较：{_md(scenario["reason"])}',
            ])
            if scenario['preferred_action_ids']:
                names = '、'.join(actions[key]['label'] for key in scenario['preferred_action_ids'])
                lines.append(f'- 符合当前目标的方案：{_md(names)}')
            for cell in scenario['cells']:
                lines.append(f'- **{_md(actions[cell["action_id"]]["label"])}**')
                if cell['amount'] is not None:
                    lines.append(f'  - 条件金额：{cell["amount"]:,.2f} 元。计算式：{_md(cell["formula"])}')
                if cell['cap'] is not None:
                    lines.append(f'  - 责任上限：{cell["cap"]:,.2f} 元')
                if cell['payment_days'] is not None:
                    lines.append(f'  - 触发后付款期限：{cell["payment_days"]} 天')
                if cell['missing'] and study.get('template') != 'qualitative':
                    lines.append(f'  - 待确认：{_md("、".join(cell["missing"]))}')
                if cell.get('effect'):
                    lines.append(f'  - 模型推演：{_md(cell["effect"])}')
    if study.get('experimental_scoring'):
        weights = study['weights']
        lines.extend(['', '## 实验评分量表', '',
                      f'- 权重：不利程度 {weights["risk_score"]}%、应对条件 {weights["feasibility_score"]}%、'
                      f'条件负担 {weights["loss_score"]}%。',
                      '- 三项量表均为 0 至 10。综合分用于观察情景特征，方案比较依据上面的条件后果。',
                      '- 不利程度和条件负担取反后加权。模型自评未经概率校准。'])

    lines.extend(['', '## 情景树详情'])
    lines.append('')
    for node in tree.get('branches', []):
        _render_node_markdown(node, 0, lines)
    return '\n'.join(lines) + '\n'


def render_sandbox_html(result: Dict[str, Any]) -> str:
    tree = result.get('tree', {})
    branches = tree.get('branches', [])
    scenario = html.escape(tree.get('scenario', ''))
    assumptions = tree.get('assumptions', [])
    uncertainties = tree.get('uncertainties', [])

    body = ''.join(_render_node(b, 0) for b in branches)
    if not body:
        body = '<li class="vam-node">（无分支）</li>'

    ass = _meta_list('假设', assumptions) if assumptions else ''
    unc = _meta_list('不确定因素', uncertainties) if uncertainties else ''

    return (
        _CSS
        + '<div class="vam-wrap">'
        + f'<div class="vam-title">{scenario}</div>'
        + '<div class="vam-sub">对赌协议 / 关键决策 · 有限情景推演（非真实预测，仅供参考）</div>'
        + _LEGEND
        + ass
        + unc
        + f'<ul class="vam-tree">{body}</ul>'
        + '</div>'
    )
