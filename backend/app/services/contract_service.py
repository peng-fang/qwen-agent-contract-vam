"""合同核验后端服务：把 Qwen-Agent 的 Agent 逻辑封装成可直接调用的函数。

只做同步的"提交问题 → 拿到最终回答"，不负责 HTTP。长任务由 FastAPI 放到线程池执行。
"""

import hashlib
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

from qwen_agent.agents import Assistant

ROOT = Path(__file__).resolve().parents[3]
MCP_SERVER = ROOT / 'mcp_servers' / 'contract_tools.py'
_ANSWER_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_LOCK = threading.Lock()
_NO_TOOL_NOTE = """

本次请求未启用计算工具：不要调用或虚构工具结果。若问题确实需要精确金额计算，直接说明需要切换完整核验。"""


SYSTEM_MESSAGE = """你是"签之前"消费合同核验助手，服务对象是准备签约的普通消费者。
支持健身、培训、租房等场景。你会收到宣传材料和/或实际合同。重点核验五类条款：
退款、违约金、自动续费/续租、服务期限、额外收费。

最重要：先做"金额审计"，再谈条款。金额审计表逐项写：
项目 | 合同原文（文件名+页码+短引文） | 金额/比例/计算基数 | 是否明确 | 风险或需核实点。

金额审计必须检查：
- 单价 × 数量 = 总价，是否对得上；
- 押金/订金/预付款是否另计，一次性付款是否包含押金；
- 支付渠道费、汇率损失、跨境汇款费由谁承担；
- 电费/水费/燃气费的单价、上限、超额部分从哪里扣；
- 提前退租、逾期、违约时最多损失多少；
- 自动续租/续费条件；
- 物业费、管理费、网费、清洁费、维修费、印花税等是否另收。

回答规则：
1. 先判断用户问的是"全面核验"还是"单点问题"。单点问题先直接回答，不要强行输出五类条款大表。
2. 如果只收到合同、没有宣传材料：宣传列写"未提供"，合同列仍必须提取原文；不要因为缺宣传就把合同条款也写成"证据不足"。
3. 如果合同明确写"不自动续租/不设续租权"，应写"合同明确不自动续租"，不要判成证据不足。
4. 只有材料确实没写、或正文没读取到，才写"证据不足/合同未约定"，并说明缺什么。
5. 如果只拿到文件名、没有读到正文，直接说"未读取到正文，请上传可复制文本 PDF 或 OCR 版"，不要把五类条款全部判证据不足。
6. 判定比较时只用三个标签：一致 / 矛盾 / 证据不足。不要把"矛盾"直接说成"违法"。
7. 涉及租金、押金、总成本时，调用 MCP 工具 calculate_lease_upfront；涉及健身/培训退款时调用 calculate_refund 或 calculate_total_cost。展示公式、中间值和最终金额，不要心算。
8. 最后给"签约前问题清单"，每条都能直接拿去问中介/销售。
9. 用中文回答，保持简洁。页码只能来自材料原文；无法确认时写"页码待核对"，不要编造。
10. 本工具只做材料核对和风险提示，不构成法律意见。
"""


def _build_bot(files: Optional[List[str]] = None, use_tools: bool = True):
    llm_cfg = {
        'model': os.getenv('OLLAMA_MODEL', 'qwen2.5:7b'),
        'model_server': os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434/v1'),
        'api_key': os.getenv('OLLAMA_API_KEY', 'ollama'),
        'generate_cfg': {
            'max_tokens': int(os.getenv('CONTRACT_MAX_TOKENS', '2048')),
            'temperature': 0.1,
            'max_input_tokens': int(os.getenv('CONTRACT_MAX_INPUT_TOKENS', '12000')),
        },
    }
    mcp_tools = [{
        'mcpServers': {
            'contract': {
                'command': sys.executable,
                'args': [str(MCP_SERVER)],
            }
        }
    }]
    return Assistant(
        llm=llm_cfg,
        name='签之前',
        description='合同核验',
        system_message=SYSTEM_MESSAGE + ('' if use_tools else _NO_TOOL_NOTE),
        function_list=mcp_tools if use_tools else [],
        files=files or [],
        rag_cfg={
            'rag_keygen_strategy': 'none',
            'max_ref_token': 8000,
        },
    )


def _needs_tools(question: str) -> bool:
    """Only pay MCP startup/tool-prompt cost when the question asks for a calculation."""
    return bool(re.search(
        r'计算|算一下|多少钱|总价|总成本|金额|退款金额|违约金是多少|手续费是多少|汇率|分期|首付',
        question,
    ))


def _answer_cache_key(file_paths: List[str], question: str, use_tools: bool) -> str:
    digest = hashlib.sha256()
    for path in file_paths:
        with open(path, 'rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
    digest.update(question.strip().encode('utf-8'))
    digest.update(b'tools' if use_tools else b'no-tools')
    return digest.hexdigest()


def _cached_answer(key: str) -> Optional[str]:
    now = time.monotonic()
    with _CACHE_LOCK:
        item = _ANSWER_CACHE.get(key)
        if not item:
            return None
        expires, answer = item
        if expires <= now:
            _ANSWER_CACHE.pop(key, None)
            return None
        return answer


def _store_answer(key: str, answer: str) -> None:
    try:
        ttl = max(60, int(os.getenv('CONTRACT_CACHE_TTL_SECONDS', '1800')))
    except ValueError:
        ttl = 1800
    with _CACHE_LOCK:
        if len(_ANSWER_CACHE) > 64:
            _ANSWER_CACHE.clear()
        _ANSWER_CACHE[key] = (time.monotonic() + ttl, answer)


def _response_text(response) -> str:
    if not response:
        return ''
    try:
        content = response[-1].get('content') if isinstance(response[-1], dict) else getattr(response[-1], 'content', '')
    except (IndexError, AttributeError):
        return ''
    return content if isinstance(content, str) else str(content or '')


def analyze_contract_stream(file_paths: List[str], question: str):
    """Yield cumulative answer snapshots from the Qwen-Agent stream."""
    if not question.strip():
        raise ValueError('question is empty')

    use_tools = _needs_tools(question)
    cache_key = _answer_cache_key(file_paths, question, use_tools)
    cached = _cached_answer(cache_key)
    if cached is not None:
        yield cached
        return

    bot = _build_bot(files=file_paths, use_tools=use_tools)
    messages = [{'role': 'user', 'content': question}]
    last = ''
    for response in bot.run(messages):
        text = _response_text(response)
        if text and text != last:
            last = text
            yield text
    if last.strip():
        _store_answer(cache_key, last)


def analyze_contract(file_paths: List[str], question: str) -> str:
    """输入已保存到本地的文件路径列表和用户问题，返回最终回答文本。"""
    last = ''
    for chunk in analyze_contract_stream(file_paths, question):
        last = chunk
    return last
