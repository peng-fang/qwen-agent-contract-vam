"""合同情景推演与决策评分服务：复用 vam_sandbox 的两段式（发散 + 打分）流水线。"""

import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vam_sandbox import deepen_leaf, find_leaf_path, render_markdown_report, run_sandbox  # noqa: E402


def _public(result: Dict[str, Any]) -> Dict[str, Any]:
    """只返回前端需要、且可 JSON 序列化的字段。"""
    tree = result.get('tree', {})
    return {
        'query': result.get('query', ''),
        'scenario': tree.get('scenario', ''),
        'assumptions': tree.get('assumptions', []),
        'uncertainties': tree.get('uncertainties', []),
        'tree': tree,
        'ranked': result.get('ranked', []),
        'best': result.get('best', {}),
        'scoring': result.get('scoring', {}),
    }


def run(query: str) -> Dict[str, Any]:
    if not query or not query.strip():
        raise ValueError('query is empty')
    return _public(run_sandbox(query))


def deepen(result: Dict[str, Any], leaf_id: str) -> Dict[str, Any]:
    if not result or not leaf_id:
        raise ValueError('result and leaf_id are required')
    path: List[str] = find_leaf_path(result, leaf_id)
    return _public(deepen_leaf(result, path))


def export_markdown(result: Dict[str, Any]) -> str:
    if not result:
        raise ValueError('result is required')
    return render_markdown_report(result)
