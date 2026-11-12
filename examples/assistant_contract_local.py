"""Local demo: consumer-contract vs. promotional-claims checker.

Run from the repository root:
    .venv\\Scripts\\python.exe examples\\assistant_contract_local.py

The app uses an OpenAI-compatible local Ollama endpoint and two MCP tools from
mcp_servers/contract_tools.py. It is a feasibility demo, not legal advice.
"""

import os
import sys
from pathlib import Path

from qwen_agent.agents import Assistant
from qwen_agent.gui import WebUI

ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER = ROOT / 'mcp_servers' / 'contract_tools.py'

MODEL = os.getenv('OLLAMA_MODEL', 'qwen2.5:7b')
MODEL_SERVER = os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434/v1')

SYSTEM_MESSAGE = """你是“签之前”消费合同核验助手，服务对象是准备签约的普通消费者。
支持健身、培训、租房等场景。你会收到宣传材料和/或实际合同。重点核验五类条款：
退款、违约金、自动续费/续租、服务期限、额外收费。

最重要：先做“金额审计”，再谈条款。金额审计表逐项写：
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
1. 先判断用户问的是“全面核验”还是“单点问题”。单点问题先直接回答，不要强行输出五类条款大表。
2. 如果只收到合同、没有宣传材料：宣传列写“未提供”，合同列仍必须提取原文；不要因为缺宣传就把合同条款也写成“证据不足”。
3. 如果合同明确写“不自动续租/不设续租权”，应写“合同明确不自动续租”，不要判成证据不足。
4. 只有材料确实没写、或正文没读取到，才写“证据不足/合同未约定”，并说明缺什么。
5. 如果只拿到文件名、没有读到正文，直接说“未读取到正文，请上传可复制文本 PDF 或 OCR 版”，不要把五类条款全部判证据不足。
6. 判定比较时只用三个标签：一致 / 矛盾 / 证据不足。不要把“矛盾”直接说成“违法”。
7. 涉及租金、押金、总成本时，调用 MCP 工具 calculate_lease_upfront；涉及健身/培训退款时调用 calculate_refund 或 calculate_total_cost。展示公式、中间值和最终金额，不要心算。
8. 最后给“签约前问题清单”，每条都能直接拿去问中介/销售。
9. 用中文回答，保持简洁。页码只能来自材料原文；无法确认时写“页码待核对”，不要编造。
10. 本工具只做材料核对和风险提示，不构成法律意见。
"""


def build_bot() -> Assistant:
    llm_cfg = {
        'model': MODEL,
        'model_server': MODEL_SERVER,
        'api_key': os.getenv('OLLAMA_API_KEY', 'ollama'),
        'generate_cfg': {
            'max_tokens': 2048,
            'temperature': 0.1,
            'max_input_tokens': 12000,
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
        description=(
            '<div>上传宣传材料与合同，先核对月租/押金/总价/手续费，再核验五类条款并计算金额。</div>'
            '<div style="margin-top:12px;">'
            '<a href="http://127.0.0.1:7861" target="_blank" rel="noopener" '
            'style="display:block;text-align:center;padding:10px 12px;'
            'background:linear-gradient(135deg,#2563eb,#7c3aed);color:#fff;'
            'border-radius:8px;text-decoration:none;font-weight:600;'
            'box-shadow:0 3px 10px rgba(37,99,235,.25);">'
            '🚀 打开对赌协议推演沙盘 →'
            '</a>'
            '</div>'
        ),
        system_message=SYSTEM_MESSAGE,
        function_list=mcp_tools,
        rag_cfg={
            'rag_keygen_strategy': 'none',
            'max_ref_token': 8000,
        },
    )


def main():
    bot = build_bot()
    chatbot_config = {
        'input.placeholder': '一次只上传一份合同（宣传材料另开一轮），然后点问题或直接问金额/条款。',
        'prompt.suggestions': [
            {'text': '退款条款：宣传承诺与合同条款是否一致？请引用原文和页码。'},
            {'text': '违约金条款：合同如何约定？请引用原文和页码。'},
            {'text': '自动续费条款：是否存在自动续费/自动续租？如何取消？'},
            {'text': '服务期限条款：合同期限多长？与宣传材料是否一致？'},
            {'text': '额外收费条款：除主费用外还有哪些收费？请计算总成本。'},
        ],
    }
    WebUI(bot, chatbot_config=chatbot_config).run(
        server_name='127.0.0.1',
        server_port=7860,
    )


if __name__ == '__main__':
    main()
