"""对赌协议推演沙盘：对话输入 + 决策树可视化输出 + 分支继续推演/回溯 + 导出报告。

运行：
    .venv\\Scripts\\python.exe examples\\assistant_vam_sandbox.py

前端用 Gradio 5 自带的 gr.HTML 渲染原生可交互决策树，无需 React/ECharts。
"""

import sys
import time
import traceback
from pathlib import Path

import gradio as gr

# 保证从仓库根目录运行时能导入 vam_sandbox 包
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vam_sandbox import (
    deepen_leaf,
    find_leaf_path,
    render_markdown_report,
    render_sandbox_html,
    run_sandbox,
)

EXAMPLES = [
    [
        '创业者 A 融资 1000 万元，签对赌：3 年内净利润累计达到 3000 万元；'
        '否则按年化 8% 回购投资人股份，或向投资人补偿股权。行业处于扩张期，请推演 3 年后可能的结局和最优策略。'
    ],
    [
        '港大 CS 硕士，纠结「转 RIS 机器人方向」还是「留在 CS 做大模型 Agent 方向」。'
        '请推演未来 3 年两条路的发展分支，并比较风险和机会成本。'
    ],
]

ERR_TMPL = (
    '<div style="color:#b91c1c;font-family:monospace;white-space:pre-wrap;">'
    '推演失败：{err}\n\n{tb}</div>'
)


def _leaf_choices(result):
    if not result:
        return []
    return [
        (f'{" → ".join(r["path"])}｜{r["branch"]}', r['leaf_id'])
        for r in result.get('ranked', [])
    ]


def _leaf_value(result):
    ranked = result.get('ranked', []) if result else []
    return ranked[0]['leaf_id'] if ranked else None


def _summary(result):
    best = result.get('best', {})
    ranked = result.get('ranked', [])
    lines = ['### 推荐结果', '']
    if best:
        lines.append(
            f'- **最优路径**：{" → ".join(best.get("path", []))}（{best.get("branch", "")}）'
            f'，总分 {best.get("total_score", 0)} / 100'
        )
    lines.append('')
    lines.append('| 排序 | 分支 | 总分 | 风险 | 概率 | 收益 | 代价 | 机会成本 |')
    lines.append('| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |')
    for i, r in enumerate(ranked, 1):
        lines.append(
            f'| {i} | {r.get("branch", "")} | {r.get("total_score", 0)} '
            f'| {r.get("risk", 0)} | {r.get("probability", 0):.2f} '
            f'| {r.get("benefit", 0)} | {r.get("cost", 0)} | {r.get("opportunity_cost", 0)} |'
        )
    return '\n'.join(lines)


def _raw(result):
    return {
        'scenario': result['tree'].get('scenario'),
        'assumptions': result['tree'].get('assumptions'),
        'uncertainties': result['tree'].get('uncertainties'),
        'tree': result['tree'],
        'ranked': result['ranked'],
        'raw_diverge': result.get('raw_diverge'),
        'raw_eval': result.get('raw_eval'),
    }


def run(query, state, history):
    query = (query or '').strip()
    if not query:
        return (
            '<div style="color:#b91c1c;">请输入要推演的对赌条款或决策背景。</div>',
            '### 结果\n\n（等待输入）',
            {},
            None,
            history,
            gr.update(choices=[]),
        )

    try:
        result = run_sandbox(query)
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        return (
            ERR_TMPL.format(err=e, tb=tb[-1500:]),
            '### 推演失败\n\n请重试，或换更简洁的描述。',
            {},
            None,
            history,
            gr.update(choices=[]),
        )

    return (
        render_sandbox_html(result),
        _summary(result),
        _raw(result),
        result,
        [],
        gr.update(choices=_leaf_choices(result), value=_leaf_value(result)),
    )


def deepen(selected, state, history):
    if not state:
        return (
            gr.update(),
            '### 尚未推演\n\n请先输入背景并点击「开始推演」。',
            gr.update(),
            state,
            history,
            gr.update(choices=[]),
        )
    if not selected:
        return (
            gr.update(),
            '### 请先选择要展开的叶子分支。',
            gr.update(),
            state,
            history,
            gr.update(choices=_leaf_choices(state), value=_leaf_value(state)),
        )

    try:
        path = find_leaf_path(state, selected)
        new_result = deepen_leaf(state, path)
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        return (
            ERR_TMPL.format(err=e, tb=tb[-1500:]),
            '### 展开失败\n\n请重试。',
            gr.update(),
            state,
            history,
            gr.update(choices=_leaf_choices(state), value=selected),
        )

    new_history = history + [state]
    return (
        render_sandbox_html(new_result),
        _summary(new_result),
        _raw(new_result),
        new_result,
        new_history,
        gr.update(choices=_leaf_choices(new_result), value=_leaf_value(new_result)),
    )


def back(state, history):
    if not state:
        return (
            gr.update(),
            '### 尚未推演\n\n请先输入背景并点击「开始推演」。',
            gr.update(),
            state,
            history,
            gr.update(choices=[]),
        )
    if not history:
        return (
            render_sandbox_html(state),
            '### 已经是最初结果\n\n没有可回溯的上一步。',
            _raw(state),
            state,
            history,
            gr.update(choices=_leaf_choices(state), value=_leaf_value(state)),
        )

    prev = history[-1]
    return (
        render_sandbox_html(prev),
        _summary(prev),
        _raw(prev),
        prev,
        history[:-1],
        gr.update(choices=_leaf_choices(prev), value=_leaf_value(prev)),
    )


def export_report(state):
    if not state:
        return None
    md = render_markdown_report(state)
    out_dir = ROOT / 'demo_data'
    out_dir.mkdir(exist_ok=True)
    ts = time.strftime('%Y%m%d_%H%M%S')
    path = out_dir / f'vam_report_{ts}.md'
    path.write_text(md, encoding='utf-8')
    return str(path)


def build_demo() -> gr.Blocks:
    with gr.Blocks(title='对赌协议推演沙盘') as demo:
        gr.Markdown(
            '# 对赌协议推演沙盘\n'
            '输入对赌条款或关键决策背景，系统用两个 Agent 先生成情景分支、再打分排序，'
            '最后渲染成可展开的决策树。结果只是情景推演，不是真实预测，也不构成投资或法律建议。'
        )

        state = gr.State(None)
        history = gr.State([])

        with gr.Row():
            with gr.Column(scale=1):
                query = gr.Textbox(
                    label='对赌条款 / 决策背景',
                    lines=6,
                    placeholder='例：融资 1000 万，3 年净利润对赌 3000 万，否则年化 8% 回购或股权补偿……',
                )
                run_btn = gr.Button('开始推演', variant='primary')

                leaf_selector = gr.Dropdown(
                    label='选择叶子分支',
                    choices=[],
                    interactive=True,
                )
                with gr.Row():
                    deepen_btn = gr.Button('沿此分支继续推演')
                    back_btn = gr.Button('回溯一步')
                export_btn = gr.Button('导出 Markdown 报告')
                export_file = gr.File(label='下载报告')

                summary = gr.Markdown('### 结果\n\n（等待输入）')
                with gr.Accordion('原始 JSON（调试用）', open=False):
                    raw_json = gr.JSON(label='结构化输出')

            with gr.Column(scale=2):
                tree = gr.HTML(label='决策树')

        gr.Examples(EXAMPLES, inputs=query, label='示例')

        run_btn.click(
            fn=run,
            inputs=[query, state, history],
            outputs=[tree, summary, raw_json, state, history, leaf_selector],
        )
        deepen_btn.click(
            fn=deepen,
            inputs=[leaf_selector, state, history],
            outputs=[tree, summary, raw_json, state, history, leaf_selector],
        )
        back_btn.click(
            fn=back,
            inputs=[state, history],
            outputs=[tree, summary, raw_json, state, history, leaf_selector],
        )
        export_btn.click(
            fn=export_report,
            inputs=[state],
            outputs=[export_file],
        )

    return demo


if __name__ == '__main__':
    build_demo().queue(default_concurrency_limit=2).launch(
        server_name='127.0.0.1',
        server_port=7861,
    )
