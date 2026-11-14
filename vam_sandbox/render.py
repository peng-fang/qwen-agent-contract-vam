"""把推演结果渲染成一张自包含的可交互 HTML 决策树。

不依赖 React/ECharts，只用原生 <details>/<ul> 和少量 CSS，方便直接放进 Gradio 的 gr.HTML。
每个叶子节点显示总分、风险等级、收益/风险/概率/代价/机会成本，可展开看连锁事件、风险和理由。
"""

import html
from typing import Any, Dict, List

_LEGEND = """
<div style="display:flex;gap:14px;flex-wrap:wrap;margin:8px 0 14px 0;font-size:13px;">
  <span><span style="display:inline-block;width:12px;height:12px;background:#e8f5e9;border:1px solid #43a047;border-radius:3px;"></span> 低风险（≤3）</span>
  <span><span style="display:inline-block;width:12px;height:12px;background:#fff8e1;border:1px solid #f9a825;border-radius:3px;"></span> 中风险（4-6）</span>
  <span><span style="display:inline-block;width:12px;height:12px;background:#ffebee;border:1px solid #e53935;border-radius:3px;"></span> 高风险（≥7）</span>
</div>
"""

_CSS = """
<style>
.vam-wrap { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; color:#1f2937; line-height:1.55; }
.vam-title { font-size:20px; font-weight:700; margin:6px 0 4px; }
.vam-sub { color:#6b7280; font-size:13px; margin-bottom:10px; }
.vam-best { border:1px solid #c8e6c9; background:#f1f8e9; border-radius:8px; padding:10px 12px; margin:10px 0 14px; }
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
        return '<span class="badge" style="background:#9ca3af;">信息不足</span>'
    if risk >= 7:
        return '<span class="badge" style="background:#e53935;">高风险</span>'
    if risk >= 4:
        return '<span class="badge" style="background:#f9a825;">中风险</span>'
    return '<span class="badge" style="background:#43a047;">低风险</span>'


def _fmt(value: Any, digits: int = 1) -> str:
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
    score_text = '信息不足' if score is None else f'{_fmt(score)}分'
    summary = (
        f'{label} {_badge(risk)}'
        f'<span class="score">{score_text}</span>'
    )
    inner = ''
    if node.get('premise'):
        inner += _meta_list('前提', [node['premise']])
    inner += _meta_list('连锁事件', node.get('events', []))
    inner += _meta_list('收益', node.get('upsides', []))
    inner += _meta_list('风险', node.get('risks', []))
    inner += _meta_list('关键变量', node.get('key_variables', []))
    if ev.get('evidence'):
        inner += _meta_list('证据依据', [ev['evidence']])

    def _fmt_score(v: Any) -> str:
        return '信息不足' if v is None else _fmt(v)

    metrics = (
        f'<div class="vam-meta"><span class="label">评分：</span>'
        f'违约风险 {_fmt_score(ev.get("risk_score"))} / 10；'
        f'落地可行性 {_fmt_score(ev.get("feasibility_score"))} / 10；'
        f'预期损失 {_fmt_score(ev.get("loss_score"))} / 10；'
        f'置信度 {_fmt_score(ev.get("confidence"))}'
        f'</div>'
    )
    inner = metrics + inner

    return (
        f'<li class="vam-node vam-leaf"><details open><summary class="{cls}">{summary}</summary>'
        f'{inner}</details></li>'
    )


def _best_block(best: Dict[str, Any]) -> str:
    if not best:
        return ''
    path = ' → '.join(html.escape(p) for p in best.get('path', []))
    total = best.get('total_score')
    total_text = '信息不足' if total is None else f'{_fmt(total)} / 100'
    return (
        '<div class="vam-best">'
        f'<b>推荐路径：</b>{path}<br>'
        f'<b>分支：</b>{html.escape(best.get("branch", ""))}<br>'
        f'<b>总分：</b>{total_text}'
        '</div>'
    )


def _render_node_markdown(node: Dict[str, Any], depth: int, lines: List[str]) -> None:
    prefix = '#' * min(depth + 3, 6)
    lines.append(f'{prefix} {"　" * (depth)} {node["branch"]}')
    if node.get('premise'):
        lines.append(f'- 前提：{node["premise"]}')
    for key, title in [('events', '连锁事件'), ('upsides', '收益'), ('risks', '风险'), ('key_variables', '关键变量')]:
        items = node.get(key, [])
        if items:
            lines.append(f'- {title}：')
            lines.extend(f'  - {i}' for i in items)
    ev = node.get('evaluation')
    if ev:
        def _md(v: Any) -> str:
            return '信息不足' if v is None else str(v)
        lines.append(
            f'- 评分：总分 {_md(ev.get("total_score"))}；'
            f'违约风险 {_md(ev.get("risk_score"))} / 10；'
            f'落地可行性 {_md(ev.get("feasibility_score"))} / 10；'
            f'预期损失 {_md(ev.get("loss_score"))} / 10；'
            f'置信度 {_md(ev.get("confidence"))}'
        )
        if ev.get('evidence'):
            lines.append(f'- 证据依据：{ev["evidence"]}')
    for child in node.get('children', []):
        _render_node_markdown(child, depth + 1, lines)


def render_markdown_report(result: Dict[str, Any]) -> str:
    tree = result.get('tree', {})
    ranked = result.get('ranked', [])
    best = result.get('best', {})

    lines: List[str] = [
        '# 合同情景推演与决策评分报告',
        '',
        f'## 场景\n\n{tree.get("scenario", "")}',
        '',
        '> 本报告为有限情景推演，不构成投资或法律建议。',
        '',
    ]

    if tree.get('assumptions'):
        lines.append('## 假设')
        lines.extend(f'- {a}' for a in tree['assumptions'])
        lines.append('')
    if tree.get('uncertainties'):
        lines.append('## 不确定因素')
        lines.extend(f'- {u}' for u in tree['uncertainties'])
        lines.append('')

    if best:
        path = ' → '.join(best.get('path', []))
        total = best.get('total_score')
        total_text = '信息不足' if total is None else f'{total} / 100'
        lines.append('## 推荐路径')
        lines.append(f'- **{path}**（{best.get("branch", "")}），总分 {total_text}')
        lines.append('')

    if ranked:
        lines.append('## 分支评分排序')
        lines.append('')
        lines.append('| 排序 | 分支 | 总分 | 违约风险 | 可行性 | 预期损失 | 置信度 |')
        lines.append('| --- | --- | ---: | ---: | ---: | ---: | ---: |')
        for i, r in enumerate(ranked, 1):
            def _cell(v: Any) -> str:
                return '信息不足' if v is None else str(v)
            lines.append(
                f'| {i} | {r.get("branch", "")} | {_cell(r.get("total_score"))} '
                f'| {_cell(r.get("risk_score"))} | {_cell(r.get("feasibility_score"))} '
                f'| {_cell(r.get("loss_score"))} | {_cell(r.get("confidence"))} |'
            )
        lines.append('')

    lines.append('## 情景树详情')
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
        + _best_block(result.get('best', {}))
        + _LEGEND
        + ass
        + unc
        + f'<ul class="vam-tree">{body}</ul>'
        + '</div>'
    )
