"""对赌协议推演沙盘：双 Agent 情景仿真，嵌入 Qwen-Agent。

流水线：
1. 推演 Agent（发散）：生成结构化情景分支树。
2. 评估 Agent（收敛）：给每个叶子情景打分。
3. Python 侧做确定性加权评分与排序，避免模型自由排名的随意性。
4. 前端渲染成可交互决策树。

这不是"预测未来"，而是基于假设的有限情景推演；结果不构成投资或法律建议。
"""

from .pipeline import deepen_leaf, find_leaf_path, run_sandbox
from .render import render_markdown_report, render_sandbox_html

__all__ = [
    'run_sandbox',
    'deepen_leaf',
    'find_leaf_path',
    'render_sandbox_html',
    'render_markdown_report',
]
