"""合同情景推演与决策评分：两段式角色提示，嵌入 Qwen-Agent。

流水线：
1. 发散角色提示：生成结构化情景分支树。
2. 评估角色提示：给每个叶子情景打分（同一模型，不是独立 Agent）。
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
