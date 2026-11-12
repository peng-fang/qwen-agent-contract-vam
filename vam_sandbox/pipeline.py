"""双 Agent 对赌协议推演流水线。

只依赖 Qwen-Agent 的 LLM 抽象（`get_chat_model`），不引入额外框架。
两个 Agent 都是同一类 LLM 的不同"角色提示词"，采用"先发散、后收敛"的两段式调用，
而不是自由多轮 Group Chat——这样能稳定拿到结构化 JSON，也便于控制分支数量。

约定（写死在提示词与 normalize 层）：
- 树最多 2 层；
- 第一层最多 3 个主分支，第二层每个节点最多 2 个子分支；
- 只评估叶子情景，叶子数量被天然限制在 6 个左右；
- 评估 Agent 只给子分数，总分由 Python 按固定权重计算，避免模型"随口排第一"。
"""

import copy
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import json5

from qwen_agent.llm import get_chat_model

# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------

DIVERGE_SYSTEM = """你是一个"对赌协议/关键决策"的发散推演 Agent。

用户会给你一个对赌协议条款，或一个关键人生/商业决策。你的任务不是预测未来，而是基于现实常识，
枚举有限但关键的情景分支，帮助用户看清"如果这样，接下来可能发生什么"。

必须遵守：
1. 输出一个合法的 JSON 对象，不要输出 Markdown 标题或解释性文字。
2. 第一层必须正好 3 个主分支；如果一件事只有两个明显结果，也要补一个"中性/意外"分支。
3. 每个主分支下面至少 1 个、最多 2 个子分支；整棵树最多 2 层。
4. 每个分支写清：前提(premise)、连锁事件(events)、风险(risks)、收益(upsides)、关键变量(key_variables)。
5. 严格区分三类信息：
   - 事实：用户给定的、或明确已知的；
   - 假设：你为推演而设的前提；
   - 不确定因素：你无法知道、需要外部核实的内容。
6. 不要编造具体的政策、股价、法律条款、汇率等；遇到这类内容，写进 uncertainties 而不是当成事实。
7. 用简体中文。

JSON schema（严格按此结构）：
{
  "scenario": "一句话概括这个推演场景",
  "assumptions": ["假设1", "假设2"],
  "uncertainties": ["不确定因素1", "不确定因素2"],
  "branches": [
    {
      "id": "A1",
      "branch": "主分支名称",
      "premise": "触发这个分支的前提/条件",
      "events": ["连锁事件1", "连锁事件2"],
      "risks": ["风险1", "风险2"],
      "upsides": ["收益1", "收益2"],
      "key_variables": ["关键变量1", "关键变量2"],
      "children": [
        {
          "id": "A1a",
          "branch": "子分支名称",
          "premise": "子分支前提",
          "events": ["..."],
          "risks": ["..."],
          "upsides": ["..."],
          "key_variables": ["..."],
          "children": []
        }
      ]
    }
  ]
}
"""

EVALUATE_SYSTEM = """你是一个"决策评估"Agent，负责收敛推演结果。

你会收到一棵已经生成好的情景树。请给每个"叶子情景"打分，只给子分数，不要自己算总分。

评分标尺（都用 0-10 或 0-1 的数值）：
- benefit：收益，0=完全无收益，10=收益极大；
- risk：风险，0=几乎无风险，10=极高风险；
- probability：主观发生概率，0 到 1 之间，各情景之间不需要和为 1；
- cost：代价，0=几乎无代价，10=代价极高；
- opportunity_cost：机会成本，0=没有错过什么，10=错过极重要的替代方案。

对每个叶子给出：
- recommendation：一句话建议；
- reasons：2-4 条打分理由。

最后给出 best_leaf_id 和 overall_advice。

输出一个合法 JSON 对象，不要 Markdown。schema：
{
  "evaluations": [
    {
      "leaf_id": "A1a",
      "benefit": 8,
      "risk": 3,
      "probability": 0.6,
      "cost": 4,
      "opportunity_cost": 5,
      "recommendation": "一句话建议",
      "reasons": ["理由1", "理由2"]
    }
  ],
  "best_leaf_id": "A1a",
  "overall_advice": "整体建议，2-4 句"
}
"""

DEEPEN_SYSTEM = """你是一个"发散推演"Agent，负责沿某个已经选定的情景继续往下推演一层。

你会收到一条已经走到某一步的路径。请基于该路径的前提和已知信息，继续枚举它的下一层子分支。

必须遵守：
1. 输出一个合法 JSON 对象，格式只包含一个 branches 数组，不要输出 scenario/assumptions 等其它字段。
2. 输出 2-3 个子分支；每个子分支必须有 children: []（子分支就是新的叶子）。
3. 每个子分支写清：branch、premise、events、risks、upsides、key_variables。
4. 基于现实常识推演；区分"假设"和"不确定因素"，不要编造具体政策、股价、法律条款、汇率。
5. 用简体中文。

JSON schema：
{
  "branches": [
    {
      "id": "X1",
      "branch": "下一层分支名称",
      "premise": "前提",
      "events": ["..."],
      "risks": ["..."],
      "upsides": ["..."],
      "key_variables": ["..."],
      "children": []
    }
  ]
}
"""

# ---------------------------------------------------------------------------
# LLM 调用与 JSON 解析
# ---------------------------------------------------------------------------


def default_llm_cfg() -> Dict[str, Any]:
    """默认本地 Ollama；设 VAM_LLM_PROVIDER=dashscope 可切到 DashScope 更强模型。"""
    provider = os.getenv('VAM_LLM_PROVIDER', 'ollama').strip().lower()
    if provider == 'dashscope':
        return {
            'model': os.getenv('VAM_DASHSCOPE_MODEL', 'qwen-plus-latest'),
            'model_type': 'qwen_dashscope',
            'api_key': os.getenv('DASHSCOPE_API_KEY', ''),
            'generate_cfg': {
                'max_tokens': 2048,
                'temperature': 0.2,
                'max_input_tokens': 12000,
            },
        }
    return {
        'model': os.getenv('OLLAMA_MODEL', 'qwen2.5:7b'),
        'model_server': os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434/v1'),
        'api_key': os.getenv('OLLAMA_API_KEY', 'ollama'),
        'generate_cfg': {
            'max_tokens': 2048,
            'temperature': 0.2,
            'max_input_tokens': 12000,
        },
    }


def _chat(cfg: Dict[str, Any], system: str, user: str, temperature: float, max_tokens: int) -> str:
    cfg = copy.deepcopy(cfg)
    gen = dict(cfg.get('generate_cfg') or {})
    gen['temperature'] = temperature
    gen['max_tokens'] = max_tokens
    cfg['generate_cfg'] = gen

    llm = get_chat_model(cfg)
    messages = [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user},
    ]
    output = llm.chat(messages=messages, stream=False)
    return output[-1]['content']


def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or '').strip()
    # 去掉 ```json ... ``` 代码块
    fences = re.findall(r'```(?:json)?\s*(.*?)```', text, re.S)
    if fences:
        text = fences[0].strip()
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1 or end <= start:
        raise ValueError('输出中没有找到 JSON 对象')
    return json5.loads(text[start:end + 1])


def _generate_json(
    cfg: Dict[str, Any],
    system: str,
    user: str,
    temperature: float,
    max_tokens: int,
    attempts: int = 2,
) -> Tuple[Dict[str, Any], str]:
    last_err: Optional[Exception] = None
    for _ in range(attempts):
        try:
            raw = _chat(cfg, system, user, temperature, max_tokens)
            return _extract_json(raw), raw
        except Exception as e:  # noqa: BLE001
            last_err = e
            user = f'{user}\n\n（上一次输出无法解析为 JSON：{e}。请只输出一个合法 JSON 对象，不要任何 Markdown 说明。）'
    raise RuntimeError(f'连续多次无法生成合法 JSON，最后错误：{last_err}')


# ---------------------------------------------------------------------------
# 归一化与评分
# ---------------------------------------------------------------------------

_MAX_DEPTH = 2
_MAX_BRANCHES_L1 = 3
_MAX_BRANCHES_L2 = 2


def _as_str_list(value: Any, limit: int = 8) -> List[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        s = str(item).strip()
        if s:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def _normalize_node(node: Any, depth: int, counter: Dict[str, int]) -> Dict[str, Any]:
    if not isinstance(node, dict):
        node = {}
    counter['n'] += 1
    node_id = str(node.get('id') or f'n{counter["n"]}').strip()
    children = node.get('children') if depth < _MAX_DEPTH else None
    if not isinstance(children, list):
        children = []
    max_kids = _MAX_BRANCHES_L1 if depth == 0 else _MAX_BRANCHES_L2
    children = children[:max_kids]

    return {
        'id': node_id,
        'branch': str(node.get('branch') or '未命名分支').strip(),
        'premise': str(node.get('premise') or '').strip(),
        'events': _as_str_list(node.get('events')),
        'risks': _as_str_list(node.get('risks')),
        'upsides': _as_str_list(node.get('upsides')),
        'key_variables': _as_str_list(node.get('key_variables')),
        'children': [_normalize_node(c, depth + 1, counter) for c in children],
    }


def normalize_tree(tree: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(tree, dict):
        raise ValueError('推演结果不是 JSON 对象')
    branches = tree.get('branches')
    if not isinstance(branches, list) or not branches:
        raise ValueError('推演结果缺少 branches 数组')

    counter = {'n': 0}
    return {
        'scenario': str(tree.get('scenario') or '未命名推演场景').strip(),
        'assumptions': _as_str_list(tree.get('assumptions'), 10),
        'uncertainties': _as_str_list(tree.get('uncertainties'), 10),
        'branches': [_normalize_node(b, 0, counter) for b in branches[:_MAX_BRANCHES_L1]],
    }


def iter_leaves(node: Dict[str, Any], path: List[str]) -> List[Tuple[List[str], Dict[str, Any]]]:
    """返回所有叶子节点：(从根到叶的 id 路径, 节点)。"""
    current_path = path + [node['id']]
    if not node['children']:
        return [(current_path, node)]
    leaves: List[Tuple[List[str], Dict[str, Any]]] = []
    for child in node['children']:
        leaves.extend(iter_leaves(child, current_path))
    return leaves


def _clamp(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _score(evaluation: Dict[str, Any]) -> float:
    benefit = _clamp(evaluation.get('benefit'), 0, 10, 5)
    risk = _clamp(evaluation.get('risk'), 0, 10, 5)
    probability = _clamp(evaluation.get('probability'), 0, 1, 0.5)
    cost = _clamp(evaluation.get('cost'), 0, 10, 5)
    opportunity_cost = _clamp(evaluation.get('opportunity_cost'), 0, 10, 5)

    # 0-100 的加权分：收益 25 + 低风险 25 + 概率 20 + 低成本 15 + 低机会成本 15
    score = (
        25 * benefit / 10
        + 25 * (10 - risk) / 10
        + 20 * probability
        + 15 * (10 - cost) / 10
        + 15 * (10 - opportunity_cost) / 10
    )
    return round(score, 1)


def normalize_evaluations(
    evaluations: Dict[str, Any],
    leaf_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    if not isinstance(evaluations, dict):
        raise ValueError('评估结果不是 JSON 对象')
    rows = evaluations.get('evaluations')
    if not isinstance(rows, list):
        raise ValueError('评估结果缺少 evaluations 数组')

    table: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        leaf_id = str(row.get('leaf_id') or '').strip()
        if leaf_id not in leaf_ids:
            continue
        table[leaf_id] = {
            'benefit': _clamp(row.get('benefit'), 0, 10, 5),
            'risk': _clamp(row.get('risk'), 0, 10, 5),
            'probability': _clamp(row.get('probability'), 0, 1, 0.5),
            'cost': _clamp(row.get('cost'), 0, 10, 5),
            'opportunity_cost': _clamp(row.get('opportunity_cost'), 0, 10, 5),
            'recommendation': str(row.get('recommendation') or '').strip(),
            'reasons': _as_str_list(row.get('reasons'), 6),
        }

    # 对缺漏的叶子补默认值，避免渲染空评分
    for leaf_id in leaf_ids:
        if leaf_id not in table:
            table[leaf_id] = {
                'benefit': 5,
                'risk': 5,
                'probability': 0.5,
                'cost': 5,
                'opportunity_cost': 5,
                'recommendation': '',
                'reasons': [],
            }
    return table


def _branch_label_for_path(tree: Dict[str, Any], path: List[str]) -> str:
    node = _find_node(tree, path)
    if node is None:
        return ' -> '.join(path)
    return node['branch']


def _find_node(tree: Dict[str, Any], path: List[str]) -> Optional[Dict[str, Any]]:
    nodes = tree['branches']
    for i, node_id in enumerate(path):
        node = next((n for n in nodes if n['id'] == node_id), None)
        if node is None:
            return None
        if i == len(path) - 1:
            return node
        nodes = node['children']
    return None


def compute_scores(tree: Dict[str, Any], evals: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    leaves = iter_leaves_with_path(tree)
    ranked: List[Dict[str, Any]] = []
    leaf_map: Dict[str, Dict[str, Any]] = {}

    for path, node in leaves:
        leaf_id = node['id']
        e = evals[leaf_id]
        total = _score(e)
        node['evaluation'] = {
            'leaf_id': leaf_id,
            'benefit': e['benefit'],
            'risk': e['risk'],
            'probability': e['probability'],
            'cost': e['cost'],
            'opportunity_cost': e['opportunity_cost'],
            'recommendation': e['recommendation'],
            'reasons': e['reasons'],
            'total_score': total,
        }
        leaf_map[leaf_id] = node['evaluation']
        ranked.append({
            'path': path,
            'branch': _branch_label_for_path(tree, path),
            'leaf_id': leaf_id,
            **node['evaluation'],
        })

    ranked.sort(key=lambda r: r['total_score'], reverse=True)

    # 把子节点风险向上传播，用于父节点着色
    _propagate_risk(tree)

    best = ranked[0] if ranked else {}
    return ranked, best


def iter_leaves_with_path(tree: Dict[str, Any]) -> List[Tuple[List[str], Dict[str, Any]]]:
    leaves: List[Tuple[List[str], Dict[str, Any]]] = []
    for root in tree['branches']:
        leaves.extend(iter_leaves(root, []))
    return leaves


def _propagate_risk(tree: Dict[str, Any]) -> None:
    def walk(node: Dict[str, Any]) -> float:
        if not node['children']:
            risk = node.get('evaluation', {}).get('risk', 5)
            node['_risk'] = risk
            return risk
        child_risks = [walk(c) for c in node['children']]
        node['_risk'] = max(child_risks) if child_risks else 5
        return node['_risk']

    for root in tree['branches']:
        walk(root)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def _build_eval_user(tree: Dict[str, Any]) -> str:
    return (
        '情景树如下（JSON）：\n\n'
        + json5.dumps(tree, ensure_ascii=False, indent=2)
        + '\n\n请给每个叶子情景打分。'
    )


def _evaluate_and_finish(
    cfg: Dict[str, Any],
    tree: Dict[str, Any],
    query: str,
    raw_diverge: Dict[str, Any],
    diverge_text: str,
) -> Dict[str, Any]:
    leaves = iter_leaves_with_path(tree)
    leaf_ids = [path[-1] for path, _ in leaves]
    eval_raw, eval_text = _generate_json(
        cfg, EVALUATE_SYSTEM, _build_eval_user(tree), temperature=0.1, max_tokens=2048
    )
    evals = normalize_evaluations(eval_raw, leaf_ids)
    ranked, best = compute_scores(tree, evals)
    return {
        'query': query,
        'tree': tree,
        'ranked': ranked,
        'best': best,
        'raw_diverge': raw_diverge,
        'raw_eval': eval_raw,
        'diverge_text': diverge_text,
        'eval_text': eval_text,
    }


def _path_context(tree: Dict[str, Any], path: List[str]) -> str:
    nodes = tree['branches']
    parts: List[str] = []
    for i, node_id in enumerate(path):
        node = next((n for n in nodes if n['id'] == node_id), None)
        if node is None:
            break
        parts.append(f'{i + 1}. {node["branch"]}（前提：{node.get("premise") or "无"}）')
        nodes = node['children']
    return '\n'.join(parts)


def find_leaf_path(result: Dict[str, Any], leaf_id: str) -> List[str]:
    for r in result.get('ranked', []):
        if r.get('leaf_id') == leaf_id:
            return r['path']
    raise ValueError(f'找不到叶子分支：{leaf_id}')


def deepen_leaf(
    result: Dict[str, Any],
    path: List[str],
    llm_cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """沿某个叶子分支继续往下推演一层，并重新评估整棵树。"""
    cfg = llm_cfg or default_llm_cfg()
    tree = copy.deepcopy(result['tree'])
    node = _find_node(tree, path)
    if node is None:
        raise ValueError('找不到要展开的分支')
    if node['children']:
        raise ValueError('该分支已经有子节点，请选择一个叶子分支继续推演')

    user = '已选路径：\n' + _path_context(tree, path) + '\n\n请继续推演该情景的下一层子分支。'
    raw, text = _generate_json(cfg, DEEPEN_SYSTEM, user, temperature=0.3, max_tokens=1536)
    branches = raw.get('branches')
    if not isinstance(branches, list) or not branches:
        raise ValueError('下一层推演结果缺少 branches 数组')

    counter = {'n': 0}
    children = [_normalize_node(b, _MAX_DEPTH, counter) for b in branches[:3]]
    # 用父节点 id 做前缀，避免不同层级的叶子 id 冲突
    for child in children:
        if not child['id'].startswith(node['id'] + '.'):
            child['id'] = f"{node['id']}.{child['id']}"
    node['children'] = children
    node.pop('evaluation', None)

    return _evaluate_and_finish(cfg, tree, result['query'], result.get('raw_diverge', {}), result.get('diverge_text', ''))


def run_sandbox(query: str, llm_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    query = (query or '').strip()
    if not query:
        raise ValueError('请输入要推演的对赌条款或决策背景')

    cfg = llm_cfg or default_llm_cfg()

    diverge_user = f'请推演下面这件事的有限情景分支：\n\n{query}'
    tree_raw, diverge_text = _generate_json(
        cfg, DIVERGE_SYSTEM, diverge_user, temperature=0.3, max_tokens=2048
    )
    tree = normalize_tree(tree_raw)
    return _evaluate_and_finish(cfg, tree, query, tree_raw, diverge_text)
