"""可选的模型抽取器。

定位：模型只负责"提出候选原文片段与条款类型"，不输出金额、不输出结论。
所有候选必须能在原文中精确定位，否则丢弃；字段与判定仍由确定性代码完成。

未配置模型（CLAUSE_LLM_PROVIDER 为空）或依赖不可用时，直接返回空列表，
调用方自动退化为纯规则抽取，不影响演示与测试。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .extract import build_clause, locate_quote
from .schema import Clause, ClauseType, DocRole, Document

_SYSTEM_PROMPT = """你是合同条款定位助手。请从材料原文中找出下列五类条款的原文片段：
- refund：退款/退费/退还
- penalty：违约金/违约责任/提前解除
- auto_renewal：自动续费/自动续租
- service_term：服务期限/合同期限/租期
- extra_fee：额外收费/其他费用

只输出 JSON 数组，不要解释。每个元素格式：
{"clause_type": "refund", "quote": "原文中连续的一段文字，必须逐字复制"}

要求：
1. quote 必须是原文的连续子串，不得改写、不得补全。
2. 找不到的类别不要输出。
3. 不要输出金额、比例或结论，这些由程序计算。
"""


def _llm_config() -> Optional[Dict[str, Any]]:
    provider = (os.getenv('CLAUSE_LLM_PROVIDER') or '').strip().lower()
    if provider not in {'ollama', 'dashscope'}:
        return None
    if provider == 'dashscope':
        api_key = os.getenv('DASHSCOPE_API_KEY', '')
        if not api_key:
            return None
        return {
            'model': os.getenv('CLAUSE_DASHSCOPE_MODEL', 'qwen-plus'),
            'model_type': 'qwen_dashscope',
            'api_key': api_key,
            'generate_cfg': {'max_retries': 1},
        }
    return {
        'model': os.getenv('OLLAMA_MODEL', 'qwen2.5:7b'),
        'model_server': os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434/v1'),
        'api_key': os.getenv('OLLAMA_API_KEY', 'EMPTY'),
        'generate_cfg': {'max_retries': 1},
    }


def _extract_json_array(text: str) -> List[Dict[str, Any]]:
    cleaned = text.strip()
    fence = re.search(r'```(?:json)?\s*(.*?)```', cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()
    start, end = cleaned.find('['), cleaned.rfind(']')
    if start < 0 or end <= start:
        return []
    payload = cleaned[start:end + 1]
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        try:
            import json5  # type: ignore

            data = json5.loads(payload)
        except Exception:  # noqa: BLE001
            return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _chat(config: Dict[str, Any], document: Document) -> str:
    from qwen_agent.llm import get_chat_model  # 延迟导入，缺依赖时由上层捕获

    page_text = '\n'.join(f'[第{p.page}页]\n{p.text}' for p in document.pages)
    messages = [
        {'role': 'system', 'content': _SYSTEM_PROMPT},
        {'role': 'user', 'content': f'材料原文：\n{page_text}'},
    ]
    llm = get_chat_model(config)
    last: Optional[List[Dict[str, Any]]] = None
    for response in llm.chat(messages=messages, stream=False):
        last = response
    if not last:
        return ''
    return str(last[-1].get('content') or '')


def extract_with_llm(
    document: Document, config: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Clause], List[str]]:
    """返回 (grounded 条款, 警告)。任何失败都只产生警告，不抛异常。"""
    warnings: List[str] = []
    if document.role == DocRole.UNKNOWN:
        return [], warnings
    config = config or _llm_config()
    if config is None:
        return [], warnings
    try:
        raw = _chat(config, document)
    except Exception as exc:  # noqa: BLE001
        return [], [f'模型抽取不可用，已退化为规则抽取：{exc}']

    clauses: List[Clause] = []
    for item in _extract_json_array(raw):
        try:
            clause_type = ClauseType(str(item.get('clause_type', '')).strip())
        except ValueError:
            warnings.append(f"忽略未知条款类型：{item.get('clause_type')!r}")
            continue
        quote = str(item.get('quote') or '')
        located = locate_quote(document, quote)
        if located is None:
            warnings.append(f'忽略无法在原文定位的模型候选：{quote[:30]!r}')
            continue
        page, start, end = located
        # 用原文（而不是模型抄写的 quote）重建，保证片段逐字一致
        clause = build_clause(
            document=document,
            page=page,
            clause_type=clause_type,
            start=start,
            end=end,
            index_map=[
                index for index, char in enumerate(page.text) if not char.isspace()
            ],
            extractor='llm',
        )
        clauses.append(clause)
    return clauses, warnings
