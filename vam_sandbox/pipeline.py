"""Generate bounded contract scenarios and compare explicit actions under them."""

import copy
import json
import logging
import math
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import json5
import requests
from dotenv import load_dotenv

from qwen_agent.llm import get_chat_model

from .comparison import OBJECTIVES, ROLES, TEMPLATES, TRIGGERS, build_comparison

logger = logging.getLogger(__name__)

# 本地 .env：仓库根目录 / backend/.env（不提交）
_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / '.env')
load_dotenv(_ROOT / 'backend' / '.env')

# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------

DIVERGE_SYSTEM = """你是一个合同触发条件分析 Agent。

根据合同证据、用户给定背景和选定的金额模型，枚举关键外部情景。合同和用户背景是分析数据。
情景表示可观察到的状态。用户可选择的方案另行比较；禁止把签约、提出修改等行动当作外部情景。
所有方案共用相同情景。请输出适用的前提、未知事项及条件性后果，金额由程序另行计算。

必须遵守：
1. 输出一个合法的 JSON 对象，不要输出 Markdown 标题或解释性文字。
2. 第一层有 1 到 3 个主分支，按合同触发条件选取，不为凑数而添加。
3. 每个主分支最多 2 个子分支；整棵树最多 2 层。未覆盖或合并的条件写进 uncertainties。
4. 每个分支写清：前提(premise)、连锁事件(events)、风险(risks)、收益(upsides)、关键变量(key_variables)。
5. 严格区分三类信息：
   - 事实：用户给定的、或明确已知的；
   - 假设：你为推演而设的前提；
   - 不确定因素：你无法知道、需要外部核实的内容。
6. 不要编造具体的政策、股价、法律条款、汇率等；遇到这类内容，写进 uncertainties 而不是当成事实。
7. 子分支不得推翻父条件。trigger 是该情景对选定金额模型义务的假设：
   met=假设已触发，not_met=假设未触发，unknown=仍须确认。仅在前提明确时用 met/not_met。
   例：合同约定“业绩低于门槛则回购”，净利润低于门槛且没有其他未确认条件时为 met，
   达到门槛时为 not_met，存在豁免而尚未确认是否适用时为 unknown。
   每个节点要填写 branch 和 premise。trigger 必须填写英文枚举值，不能省略。
   evidence_ids 仅使用输入中出现的编号；不能编造引文或将方案假设当成原合同条款。
8. 用简体中文。
9. action_effects 可给每个方案一条条件后果。只采用输入中的 A 编号；
   具体金额和日期留给程序计算，缺少前提时明确说明。
10. trigger_quote 如能填写，应从合同或用户背景逐字摘录包含触发门槛的连续文本，也可留空。

JSON schema（严格按此结构）：
{
  "scenario": "一句话概括这个推演场景",
  "trigger_quote": "触发条件的原文片段",
  "assumptions": ["假设1", "假设2"],
  "uncertainties": ["不确定因素1", "不确定因素2"],
  "branches": [
    {
      "id": "A1",
      "branch": "主分支名称",
      "premise": "触发这个分支的前提/条件",
      "trigger": "unknown",
      "evidence_ids": ["E1"],
      "action_effects": {"A1": "该条件下的方案后果或待确认项"},
      "events": ["连锁事件1", "连锁事件2"],
      "risks": ["风险1", "风险2"],
      "upsides": ["收益1", "收益2"],
      "key_variables": ["关键变量1", "关键变量2"],
      "children": [
        {
          "id": "A1a",
          "branch": "子分支名称",
          "premise": "子分支前提",
          "trigger": "unknown",
          "evidence_ids": ["E1"],
          "action_effects": {"A1": "该条件下的方案后果或待确认项"},
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

SCORER_SYSTEM = """你是合同情景的实验评分 Agent。从给定用户立场评价完整的假设情景。
规则：
1. 输入：合同原始条款 + 一条推演分支完整情景描述；
2. 打分维度（0~10分）：
   - risk_score：不利因素严重度，0=无明显不利因素，5=有实质限制，10=存在严重未化解障碍。该分值不是概率。
   - feasibility_score：应对条件充分度，0=必要前提不满足，5=需补齐关键前提，10=必要前提齐备。
   - loss_score：情景下负担程度，0=无额外负担，5=负担显著，10=负担严重。需要与用户承受能力相比较。
3. confidence 为 0~1 的模型自评；evidence 字段填写简短评分说明，仅依据已给信息，引用时注明证据编号；
4. 输出严格为JSON，禁止markdown、前置说明、多余解释文字；
5. 信息不足时将对应分数填 null，并在说明里注明缺项；
6. 不做自由文本扩写，只输出结构化打分结果。

输出模板固定：
{
  "risk_score": float,
  "feasibility_score": float,
  "loss_score": float,
  "confidence": float,
  "evidence": "简短评分说明"
}
"""

LOCAL_SCORER_SYSTEM = SCORER_SYSTEM + """
本地 Qwen 校准：
- 三个分数必须输出 0~10 的数值，不要返回 null。
- 信息不足时给中间值 5，并把 confidence 降到 0.3~0.5，在 evidence 中注明“按中间值估算，需人工复核”。
- 同一情景的分数只做相对判断，不解释为概率。
"""

DEEPEN_SYSTEM = """你是一个"发散推演"Agent，负责沿某个已经选定的情景继续往下推演一层。

你会收到合同原始输入、用户立场和一条已有前提的路径。请进一步区分外部事件。

必须遵守：
1. 输出一个合法 JSON 对象，格式只包含一个 branches 数组，不要输出 scenario/assumptions 等其它字段。
2. 输出不超过请求上限的子分支；没有新情景时返回空数组。每个子分支必须有 children: []。
3. 每个子分支写清：branch、premise、events、risks、upsides、key_variables。
4. 子分支必须延续当前路径的前提，不能把父分支的反面写成子分支；例如当前路径是“成功”，子分支不能是“失败”。
5. 基于现实常识推演；区分"假设"和"不确定因素"，不要编造具体政策、股价、法律条款、汇率。
6. 继承父节点明确的 trigger 状态；只能使用输入给出的 evidence_ids。用简体中文。
7. action_effects 可给每个方案一条条件后果，只使用输入的 A 编号。

JSON schema：
{
  "branches": [
    {
      "id": "X1",
      "branch": "下一层分支名称",
      "premise": "前提",
      "trigger": "unknown",
      "evidence_ids": ["E1"],
      "action_effects": {"A1": "该条件下的方案后果或待确认项"},
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
            parsed = _extract_json(raw)
            if not isinstance(parsed, dict):
                raise ValueError('输出须为 JSON 对象')
            if system == DIVERGE_SYSTEM and (
                not isinstance(parsed.get('branches'), list)
                or not any(isinstance(branch, dict) for branch in parsed['branches'])
            ):
                raise ValueError('输出须包含非空 branches 数组')
            return parsed, raw
        except Exception as e:  # noqa: BLE001
            last_err = e
            user = f'{user}\n\n（上一次未生成符合要求的 JSON。请按结构返回一个合法 JSON 对象。）'
    raise RuntimeError(f'连续多次无法生成合法 JSON，最后错误：{last_err}')


# ---------------------------------------------------------------------------
# 归一化与评分
# ---------------------------------------------------------------------------

INITIAL_DEPTH = 2
MAX_DEPTH = 3
MAX_LEAVES = 10
_MAX_BRANCHES_L1 = 3
_MAX_BRANCHES_L2 = 2
_AMOUNT_TEMPLATES = {'repurchase', 'lease_exit'}
_AMOUNT_TEXT = re.compile(
    r'[\d０-９零〇一二三四五六七八九十百千万亿两.．,，]+\s*(?:亿元|万元|元|块钱|人民币|美元|%|％)|[¥￥$]\s*\d'
)
_ACTION_BRANCH = re.compile(r'^(?:原(?:回购|退租)?条款|方案\s*[A-C123一二三]|保留|接受|提出|提议|修改|选择|维持|拒绝签|签订|采用)')


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


def _normalize_node(node, node_id, remaining, evidence_ids, warnings, parent_trigger='unknown'):
    trigger = node.get('trigger')
    trigger = trigger if trigger in ('met', 'not_met', 'unknown') else 'unknown'
    premise = str(node.get('premise') or '').strip()[:1600]
    if not premise:
        trigger = 'unknown'
    if parent_trigger != 'unknown':
        if trigger not in ('unknown', parent_trigger):
            warnings.append(f'{node_id} 的触发状态与上级相冲突，已省略该子情景。')
            return None
        trigger = parent_trigger
    children = node.get('children')
    children = [child for child in children if isinstance(child, dict)] if isinstance(children, list) else []
    if children and (remaining <= 1 or len(children) > _MAX_BRANCHES_L2):
        warnings.append(f'{node_id} 有情景因树的深度或分支上限而未展示。')
    normalized = {
        'id': node_id,
        'branch': str(node.get('branch') or '未命名分支').strip(),
        'premise': premise,
        'trigger': trigger,
        'evidence_ids': list(dict.fromkeys(i for i in _as_str_list(node.get('evidence_ids')) if i in evidence_ids)),
        'action_effects': {
            key: value.strip()[:600] for key, value in
            (node['action_effects'].items() if isinstance(node.get('action_effects'), dict) else [])
            if key in ('A1', 'A2', 'A3') and isinstance(value, str) and value.strip()
        },
        'events': _as_str_list(node.get('events')),
        'risks': _as_str_list(node.get('risks')),
        'upsides': _as_str_list(node.get('upsides')),
        'key_variables': _as_str_list(node.get('key_variables')),
        'children': [],
    }
    if remaining > 1:
        for index, child in enumerate(children[:_MAX_BRANCHES_L2], 1):
            parsed = _normalize_node(child, f'{node_id}.{index}', remaining - 1, evidence_ids, warnings, trigger)
            if parsed:
                normalized['children'].append(parsed)
    return normalized


def normalize_tree(tree: Dict[str, Any], evidence_ids=()) -> Dict[str, Any]:
    if not isinstance(tree, dict):
        raise ValueError('推演结果不是 JSON 对象')
    branches = tree.get('branches')
    branches = [node for node in branches if isinstance(node, dict)] if isinstance(branches, list) else []
    if not branches:
        raise ValueError('推演结果缺少 branches 数组')

    warnings = []
    if len(branches) > _MAX_BRANCHES_L1:
        warnings.append('主情景超过 3 条，部分情景未展示。')
    normalized = {
        'scenario': str(tree.get('scenario') or '未命名推演场景').strip(),
        'assumptions': _as_str_list(tree.get('assumptions'), 10),
        'uncertainties': _as_str_list(tree.get('uncertainties'), 10),
        'branches': [
            _normalize_node(b, f'B{index}', INITIAL_DEPTH, evidence_ids, warnings)
            for index, b in enumerate(branches[:_MAX_BRANCHES_L1], 1)
        ],
        'warnings': warnings,
    }
    return normalized


def _strip_model_amounts(node: dict) -> None:
    """Keep generated notes from competing with the conditional calculator."""
    for key in ('events', 'risks', 'upsides', 'key_variables'):
        node[key] = [text for text in node[key] if not _AMOUNT_TEXT.search(text)]
    node['action_effects'] = {}


def _conditional_tree(tree: Dict[str, Any], template: str, action_labels=(), trigger_excerpt=None) -> Dict[str, Any]:
    """Bind the amount models to common, explicit counterfactual cases."""
    duty = '回购义务' if template == 'repurchase' else '退租赔付义务'
    cases = []
    for trigger, suffix in [('met', '已触发'), ('not_met', '未触发')]:
        matching = next((node for _, node in iter_leaves_with_path(tree)
                         if node['trigger'] == trigger and node['branch'] not in action_labels
                         and not _ACTION_BRANCH.match(node['branch'])), None)
        label = f'{duty}{suffix}'
        case = {
            'id': f'B{len(cases) + 1}', 'branch': label, 'trigger': trigger,
            'premise': f'假设当前外部情景下，{label}。以适用合同条件及例外为准。',
            'children': [], 'evidence_ids': [], 'action_effects': {},
            'events': [], 'risks': [], 'upsides': [], 'key_variables': [],
        }
        if matching:
            case.update({key: matching[key] for key in ('evidence_ids', 'key_variables')})
        if trigger_excerpt and trigger_excerpt.get('evidence_id'):
            case['evidence_ids'] = list(dict.fromkeys([trigger_excerpt['evidence_id'], *case['evidence_ids']]))
        _strip_model_amounts(case)
        cases.append(case)
    tree['scenario'] = f'{TEMPLATES[template]}的条件分析'
    # Generated assumptions can accidentally assert one hypothetical branch
    # as fact for both cases. Preserve unknowns explicitly rather than doing so.
    tree['assumptions'] = [
        '在相同外部情景下分别应用各方案参数。需要对方同意的修订，以已达成约定为前提。',
        '金额仅覆盖所选计算模型和已确认参数。',
    ]
    tree['uncertainties'] = [text for text in tree['uncertainties'] if not _AMOUNT_TEXT.search(text)]
    tree['branches'] = cases
    tree['warnings'] = ['本次先比较触发与未触发两种条件。其他情景及合同例外可沿分支继续核对。']
    tree['trigger_excerpt'] = trigger_excerpt
    return tree


def _match_trigger_excerpt(quote, query, sources):
    if not isinstance(quote, str):
        return None
    excerpt = quote.strip()
    if not 4 <= len(excerpt) <= 600:
        return None
    for source in sources:
        if excerpt in source['quote']:
            return {'quote': excerpt, 'evidence_id': source['id']}
    if excerpt in query:
        return {'quote': excerpt, 'evidence_id': None}
    return None


def _remove_action_branches(tree: dict, action_labels: set) -> None:
    def keep(branches):
        retained = []
        for node in branches:
            if node['branch'] in action_labels or _ACTION_BRANCH.match(node['branch']):
                tree['warnings'].append(f'{node["id"]} 是方案描述，未加入情景树。')
                continue
            node['children'] = keep(node['children'])
            retained.append(node)
        return retained

    tree['branches'] = keep(tree['branches'])
    if not tree['branches']:
        raise ValueError('模型只返回了用户方案。请补充希望分析的外部条件后重试。')


def iter_leaves(node: Dict[str, Any], path: List[str]) -> List[Tuple[List[str], Dict[str, Any]]]:
    """返回所有叶子节点：(从根到叶的 id 路径, 节点)。"""
    current_path = path + [node['id']]
    if not node['children']:
        return [(current_path, node)]
    leaves: List[Tuple[List[str], Dict[str, Any]]] = []
    for child in node['children']:
        leaves.extend(iter_leaves(child, current_path))
    return leaves


def _num_or_none(value: Any, lo: float, hi: float) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        v = value.strip()
        if v.lower() in ('', 'null', 'none', 'n/a', 'na'):
            return None
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) and lo <= f <= hi else None


SCORE_FIELDS = {'risk_score': 10, 'feasibility_score': 10, 'loss_score': 10, 'confidence': 1}
SCORE_WEIGHTS = {'risk_score': 40, 'feasibility_score': 35, 'loss_score': 25}


def _scorer_default(status: str = 'missing') -> Dict[str, Any]:
    return {
        'risk_score': None,
        'feasibility_score': None,
        'loss_score': None,
        'confidence': None,
        'evidence': '',
        'scorer_model': None,
        'status': status,
        'invalid_fields': [],
    }


def normalize_scorer_result(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return _scorer_default()
    scores = {key: _num_or_none(raw.get(key), 0, hi) for key, hi in SCORE_FIELDS.items()}
    invalid = [
        key for key, value in scores.items()
        if value is None and raw.get(key) is not None
        and str(raw[key]).strip().lower() not in ('', 'null', 'none', 'n/a', 'na')
    ]
    status = 'valid'
    if invalid:
        status = 'invalid'
    elif any(scores[key] is None for key in SCORE_WEIGHTS):
        status = 'missing'
    evidence = raw.get('evidence')
    model = raw.get('scorer_model') or raw.get('model')
    return {**scores, 'evidence': evidence.strip()[:800] if isinstance(evidence, str) else '',
            'scorer_model': model.strip()[:120] if isinstance(model, str) and model.strip() else None,
            'status': status, 'invalid_fields': invalid}


def _total_from_scores(e: Dict[str, Any], weights=None) -> Optional[float]:
    values = {key: _num_or_none(e.get(key), 0, 10) for key in SCORE_WEIGHTS}
    if e.get('status') in ('invalid', 'error', 'disabled') or None in values.values():
        return None
    weights = weights or SCORE_WEIGHTS
    return round(sum(weights[key] * (value if key == 'feasibility_score' else 10 - value)
                     for key, value in values.items()) / 10, 1)


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


def compute_scores(tree: Dict[str, Any], evals: Dict[str, Dict[str, Any]], weights=None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    leaves = iter_leaves_with_path(tree)
    ranked: List[Dict[str, Any]] = []

    for path, node in leaves:
        leaf_id = node['id']
        e = evals.get(leaf_id, _scorer_default())
        total = _total_from_scores(e, weights)
        node['evaluation'] = {
            'leaf_id': leaf_id,
            'risk_score': e.get('risk_score'),
            'feasibility_score': e.get('feasibility_score'),
            'loss_score': e.get('loss_score'),
            'confidence': e.get('confidence'),
            'evidence': e.get('evidence', ''),
            'scorer_model': e.get('scorer_model'),
            'status': e.get('status') or ('valid' if total is not None else 'missing'),
            'invalid_fields': e.get('invalid_fields', []),
            'total_score': total,
        }
        ranked.append({
            'path': path,
            'branch': _branch_label_for_path(tree, path),
            'leaf_id': leaf_id,
            **node['evaluation'],
        })

    # 把子节点风险向上传播，用于父节点着色
    _propagate_risk(tree)

    return ranked, {}


def iter_leaves_with_path(tree: Dict[str, Any]) -> List[Tuple[List[str], Dict[str, Any]]]:
    leaves: List[Tuple[List[str], Dict[str, Any]]] = []
    for root in tree['branches']:
        leaves.extend(iter_leaves(root, []))
    return leaves


def _propagate_risk(tree: Dict[str, Any]) -> None:
    def walk(node: Dict[str, Any]) -> Optional[float]:
        if not node['children']:
            evaluation = node.get('evaluation', {})
            risk = evaluation.get('risk_score') if evaluation.get('status') == 'valid' else None
            node['_risk'] = risk
            return risk
        child_risks = [walk(c) for c in node['children']]
        node['_risk'] = max(child_risks) if child_risks and None not in child_risks else None
        return node['_risk']

    for root in tree['branches']:
        walk(root)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def _scorer_config() -> Dict[str, str]:
    return {
        'url': os.getenv('VAM_SCORER_URL', '').strip(),
        'api_key': os.getenv('VAM_SCORER_API_KEY', '').strip(),
        'model': os.getenv('VAM_SCORER_MODEL', 'deepseek-chat').strip(),
        'style': os.getenv('VAM_SCORER_API_STYLE', 'auto').strip().lower(),
    }


def _harness_score(contract_text: str, scenario_text: str) -> Tuple[Dict[str, Any], str]:
    cfg = _scorer_config()
    url = cfg['url']
    style = cfg['style'] or 'auto'
    if style == 'auto':
        if 'api.deepseek.com' in url or url.rstrip('/').endswith('/chat/completions'):
            style = 'openai'
        else:
            style = 'harness'

    headers = {'Content-Type': 'application/json'}
    if cfg['api_key']:
        headers['Authorization'] = f'Bearer {cfg["api_key"]}'

    user_text = f'合同原文：{contract_text}\n待评估推演情景：{scenario_text}'

    if style == 'openai':
        payload = {
            'model': cfg['model'],
            'messages': [
                {'role': 'system', 'content': SCORER_SYSTEM},
                {'role': 'user', 'content': user_text},
            ],
            'temperature': 0,
            'max_tokens': 300,
            'stream': False,
        }
    else:
        payload = {
            'system_prompt': SCORER_SYSTEM,
            'user': user_text,
            'model': cfg['model'],
        }

    resp = requests.post(url, json=payload, headers=headers, timeout=180)
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, dict) and data.get('choices'):
        content = data['choices'][0]['message']['content']
    elif isinstance(data, dict):
        content = data.get('content') or data.get('data', {}).get('content') or data.get('text') or ''
    else:
        content = str(data)

    if isinstance(content, dict):
        content = json.dumps(content, ensure_ascii=False)
    return {**_extract_json(str(content)), 'scorer_model': cfg['model']}, str(content)


def _local_score(
    cfg: Dict[str, Any],
    contract_text: str,
    scenario_text: str,
    temperature: float,
    max_tokens: int,
) -> Tuple[Dict[str, Any], str]:
    user = f'合同原文：{contract_text}\n待评估推演情景：{scenario_text}'
    scores, raw = _generate_json(cfg, LOCAL_SCORER_SYSTEM, user, temperature=temperature, max_tokens=max_tokens)
    return {**scores, 'scorer_model': cfg.get('model')}, raw


def _intern_score(contract_text: str, scenario_text: str) -> Tuple[Dict[str, Any], str]:
    url = os.getenv('VAM_INTERN_URL', 'http://127.0.0.1:8010/score').strip()
    resp = requests.post(
        url,
        json={'contract_text': contract_text, 'scenario_text': scenario_text},
        timeout=300,
    )
    resp.raise_for_status()
    data = resp.json()
    # Older Intern services echoed part of the input in this field.
    evidence = data.get('evidence')
    if isinstance(evidence, str) and evidence.startswith('输入依据：'):
        data['evidence'] = 'Intern-Decision 实验评分，模型未返回可逐条复核的评分理由。'
    return {**data, 'scorer_model': data.get('model')}, json.dumps(data, ensure_ascii=False)


def _score_leaf(
    cfg: Dict[str, Any],
    contract_text: str,
    scenario_text: str,
) -> Tuple[Dict[str, Any], str]:
    provider = os.getenv('VAM_SCORER_PROVIDER', 'local').strip().lower() or 'local'
    scorer = _scorer_config()
    if provider == 'intern':
        return _intern_score(contract_text, scenario_text)
    if provider == 'harness' or (provider == 'auto' and scorer['url']):
        return _harness_score(contract_text, scenario_text)
    return _local_score(cfg, contract_text, scenario_text, temperature=0.0, max_tokens=256)


def _scenario_text(tree: Dict[str, Any], path: List[str]) -> str:
    parts = [
        f'情景：{tree.get("scenario", "")}',
        '全局假设：' + '；'.join(tree.get('assumptions', [])),
        '待确认：' + '；'.join(tree.get('uncertainties', [])),
    ]
    for i in range(len(path)):
        node = _find_node(tree, path[:i + 1])
        if node is None:
            break
        trigger = TRIGGERS.get(node.get('trigger'), TRIGGERS['unknown'])
        parts.append(f'{i + 1}. {node["branch"]}（前提：{node.get("premise") or "待确认"}；{trigger}）')
        for key, label in [('events', '后果'), ('risks', '不利因素'), ('upsides', '有利因素'),
                           ('key_variables', '关键变量'), ('evidence_ids', '证据编号')]:
            if node.get(key):
                parts.append(f'{label}：' + '；'.join(node[key]))
    return '\n'.join(parts)


def _source_text(query, study):
    sources = '\n'.join(
        f'[{item["id"]}] {item["filename"]} 第 {item["page"]} 页：{item["quote"]}'
        for item in study.get('evidence', [])
    )
    role = ROLES.get(study.get('role'), '未指定')
    objective = OBJECTIVES.get(study.get('objective'), '未指定')
    template = TEMPLATES.get(study.get('template'), '条款与责任')
    actions = '\n'.join(f'[{item["id"]}] {item["label"]}：{item.get("terms") or "未补充条款说明"}'
                        for item in study.get('actions', []))
    return (f'用户背景（待核实）：\n{query}\n\n所选合同原文：\n{sources or "未关联原文"}'
            f'\n\n用户立场：{role}；关注目标：{objective}；金额模型：{template}。'
            f'\n\n待比较方案（用户设定）：\n{actions or "未填写方案"}')


def _evaluate_and_finish(
    cfg: Dict[str, Any],
    tree: Dict[str, Any],
    query: str,
    raw_diverge: Dict[str, Any],
    diverge_text: str,
    study: Optional[Dict[str, Any]] = None,
    previous: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    study = study or {}
    leaves = iter_leaves_with_path(tree)
    evals: Dict[str, Dict[str, Any]] = {}
    raw_evals: List[Dict[str, Any]] = []
    eval_texts: List[str] = []
    source = _source_text(query, {**study, 'actions': []})
    previous_scores = {}
    if previous and previous.get('study', {}) == study:
        previous_scores = {entry.get('leaf_id'): entry for entry in previous.get('ranked', [])}

    for path, node in leaves:
        leaf_id = node['id']
        if not study.get('experimental_scoring'):
            evals[leaf_id] = _scorer_default('disabled')
            continue
        scenario_text = _scenario_text(tree, path)
        old = previous_scores.get(leaf_id)
        if old and old.get('path') == path and old.get('status') in ('valid', 'missing', 'invalid'):
            checked = normalize_scorer_result(old)
            if old['status'] == 'invalid':
                checked['status'] = 'invalid'
                checked['invalid_fields'] = [key for key in old.get('invalid_fields', []) if key in SCORE_FIELDS]
            evals[leaf_id] = checked
            continue
        try:
            raw, text = _score_leaf(cfg, source, scenario_text)
            evals[leaf_id] = normalize_scorer_result(raw)
            raw_evals.append({'leaf_id': leaf_id, 'scenario': scenario_text, 'scores': raw})
            eval_texts.append(text)
        except Exception as exc:
            logger.warning('VAM scoring failed for %s: %s', leaf_id, type(exc).__name__)
            evals[leaf_id] = _scorer_default('error')
            raw_evals.append({'leaf_id': leaf_id, 'error': type(exc).__name__})

    ranked, best = compute_scores(tree, evals, study.get('weights'))
    return {
        'run_id': uuid.uuid4().hex,
        'query': query,
        'study': study,
        'comparison': build_comparison(study, leaves),
        'tree': tree,
        'ranked': ranked,
        'best': best,
        'raw_diverge': raw_diverge,
        'raw_eval': raw_evals,
        'trace_parent_run_id': previous.get('run_id') if previous else None,
        'diverge_text': diverge_text,
        'eval_text': '\n'.join(eval_texts),
    }


def find_leaf_path(result: Dict[str, Any], leaf_id: str) -> List[str]:
    for path, node in iter_leaves_with_path(result['tree']):
        if node['id'] == leaf_id:
            return path
    raise ValueError(f'找不到叶子分支：{leaf_id}')


def deepen_leaf(
    result: Dict[str, Any],
    path: List[str],
    llm_cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Expand one leaf while preserving the context and other leaf assessments."""
    cfg = llm_cfg or default_llm_cfg()
    tree = copy.deepcopy(result['tree'])
    node = _find_node(tree, path)
    if node is None:
        raise ValueError('找不到要展开的分支')
    if node['children']:
        raise ValueError('该分支已经有子节点，请选择一个叶子分支继续推演')

    if len(path) >= MAX_DEPTH:
        raise ValueError(f'已达到 {MAX_DEPTH} 层情景上限。')
    leaves = iter_leaves_with_path(tree)
    if len(leaves) >= MAX_LEAVES:
        raise ValueError(f'已达到 {MAX_LEAVES} 个情景上限。')
    allowed = min(_MAX_BRANCHES_L2, MAX_LEAVES - len(leaves) + 1)
    study = result.get('study', {})
    override = node.get('trigger_override')
    confirmed = f'\n用户另为金额比较设定：{TRIGGERS[override]}。' if override else ''
    quantitative = study.get('template') in _AMOUNT_TEMPLATES
    generation_study = {**study, 'actions': []} if quantitative else study
    user = (f'{_source_text(result["query"], generation_study)}\n\n已选路径：\n{_scenario_text(tree, path)}{confirmed}'
            f'\n\n最多返回 {allowed} 个下一层子情景。')
    raw, text = _generate_json(cfg, DEEPEN_SYSTEM, user, temperature=0.3, max_tokens=1536)
    branches = raw.get('branches')
    if not isinstance(branches, list):
        raise ValueError('下一层推演结果缺少 branches 数组')
    warnings = tree.setdefault('warnings', [])
    if len(branches) > allowed:
        warnings.append(f'{node["id"]} 的新增情景超过上限，部分未展示。')
    children = []
    evidence_ids = {item['id'] for item in study.get('evidence', [])}
    action_labels = {action['label'] for action in study.get('actions', [])}
    for index, branch in enumerate(branches[:allowed], 1):
        if not isinstance(branch, dict):
            continue
        parent_trigger = override if override in ('met', 'not_met') else node.get('trigger', 'unknown')
        child = _normalize_node(branch, f'{node["id"]}.{index}', 1, evidence_ids, warnings, parent_trigger)
        if child:
            if child['branch'] in action_labels or _ACTION_BRANCH.match(child['branch']):
                warnings.append(f'{child["id"]} 是方案描述，未加入情景树。')
                continue
            if quantitative:
                _strip_model_amounts(child)
            else:
                child['effect_actions'] = {
                    item['id']: [item['label'], item['terms']] for item in study.get('actions', [])
                }
            children.append(child)
    if not children:
        raise ValueError('没有可以继续展开且符合上级触发条件的新情景。')
    node['children'] = children
    node.pop('evaluation', None)

    return _evaluate_and_finish(cfg, tree, result['query'], raw, text, study, previous=result)


def run_sandbox(query: str, llm_cfg: Optional[Dict[str, Any]] = None,
                study: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    query = (query or '').strip()
    if not query:
        raise ValueError('请输入要推演的合同情景或决策背景')

    cfg = llm_cfg or default_llm_cfg()

    study = study or {}
    quantitative = study.get('template') in _AMOUNT_TEMPLATES
    generation_study = {**study, 'actions': []} if quantitative else study
    diverge_user = _source_text(query, generation_study)
    tree_raw, diverge_text = _generate_json(
        cfg, DIVERGE_SYSTEM, diverge_user, temperature=0.3, max_tokens=2048
    )
    tree = normalize_tree(tree_raw, {item['id'] for item in study.get('evidence', [])})
    labels = {action['label'] for action in study.get('actions', [])}
    if quantitative:
        excerpt = _match_trigger_excerpt(tree_raw.get('trigger_quote'), query, study.get('evidence', []))
        tree = _conditional_tree(tree, study['template'], labels, excerpt)
    else:
        _remove_action_branches(tree, labels)
    study = {**study, 'analyzed_actions': {
        item['id']: [item['label'], item['terms']] for item in study.get('actions', [])
    }}
    return _evaluate_and_finish(cfg, tree, query, tree_raw, diverge_text, study)
