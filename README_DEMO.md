# 本地 Demo：Qwen-Agent 合同核验 + 对赌协议推演

这是基于 [QwenLM/Qwen-Agent](https://github.com/QwenLM/Qwen-Agent) 的最小可运行验证，支持健身/培训/租房合同核验，以及对赌协议/关键决策的情景推演。不是法律或投资建议工具。

两个应用：

| 应用 | 端口 | 启动脚本 |
| --- | --- | --- |
| 合同核验「签之前」 | <http://127.0.0.1:7860> | `start_demo.ps1` |
| 对赌协议推演沙盘 | <http://127.0.0.1:7861> | `start_vam_demo.ps1` |

> 合同核验页右上角有「🚀 打开对赌协议推演沙盘 →」按钮，点击会在新标签页打开 7861。

## 一键启动（合同核验）

在仓库根目录（本文件所在目录）运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_demo.ps1
```

浏览器打开：<http://127.0.0.1:7860>

脚本会检查 Ollama、检查 `qwen2.5:7b` 是否已下载，然后启动 Gradio 应用。

## 一键启动（对赌协议推演）

```powershell
powershell -ExecutionPolicy Bypass -File .\start_vam_demo.ps1
```

浏览器打开：<http://127.0.0.1:7861>

## 演示步骤

### A. 健身房合同

1. 点击「点击上传」，同时选中：
   - `demo_data/promo_gym.pdf`（宣传材料）
   - `demo_data/contract_gym.pdf`（实际合同）
2. 输入：`请核验退款承诺，并引用两份材料的原文和页码。`
3. 再输入：`我上了 8 节课，现在退费，按合同能退多少钱？只回答金额测算。`
4. 预期：调用 MCP 工具 `contract-calculate_refund`，得到退款 1920 元、损失 2880 元。

### B. 租房合同

1. 一次只上传一份租赁合同；宣传材料另开一轮，避免两份无关合同互相干扰。
2. 点右侧「推荐对话」里的 5 个条款问题：
   - 退款条款：宣传承诺与合同条款是否一致？
   - 违约金条款：合同如何约定？
   - 自动续费条款：是否存在自动续费/自动续租？如何取消？
   - 服务期限条款：合同期限多长？与宣传材料是否一致？
   - 额外收费条款：除主费用外还有哪些收费？请计算总成本。
3. 涉及金额时，模型会调用 `calculate_lease_upfront` 或退款工具，展示总租金、押金、首期总额、渠道费和电费超额。

### C. 对赌协议推演沙盘

1. 打开 <http://127.0.0.1:7861>。
2. 输入对赌条款或关键决策背景，例如：
   - `创业者融资 1000 万，签对赌：3 年净利润累计达到 3000 万，否则年化 8% 回购或股权补偿。`
3. 点「开始推演」。
4. 两个 Agent 依次工作：
   - 推演 Agent 生成最多 2 层的情景分支树；
   - 评估 Agent 给每个叶子情景打分；
   - Python 按固定权重算总分并排序，前端渲染成可展开决策树。
5. 结果包含「推荐路径 + 决策树 + 原始 JSON」，可点击节点查看事件、风险、收益和理由。
6. 交互操作：
   - 在「选择叶子分支」下拉里选一个叶子，点「沿此分支继续推演」，就会往下多推演一层；
   - 点「回溯一步」回到上一棵树，方便对比不同分支；
   - 点「导出 Markdown 报告」下载完整推演报告。

## 技术链路

```text
Gradio 5 WebUI (browser)
  -> Qwen-Agent Assistant
     -> Memory: PDF parser -> page chunks -> hybrid retrieval
     -> Ollama OpenAI-compatible endpoint: qwen2.5:7b
     -> MCP stdio server: mcp_servers/contract_tools.py
        -> calculate_refund / calculate_total_cost / calculate_lease_upfront
  -> streamed answer back to Gradio
```

- 前端和后端由同一个 Python 进程提供，没有独立 Node 服务。
- 模型默认 `qwen2.5:7b`（Ollama，Q4，约 4.7 GB），可用环境变量覆盖：
  - `OLLAMA_MODEL`
  - `OLLAMA_BASE_URL`
- 对赌推演沙盘可切 DashScope 更强模型：
  ```powershell
  $env:VAM_LLM_PROVIDER = 'dashscope'
  $env:DASHSCOPE_API_KEY  = '你的 key'
  $env:VAM_DASHSCOPE_MODEL = 'qwen-plus-latest'   # 可选，默认 qwen-plus-latest
  ```
- MCP 服务由 Qwen-Agent 按需拉起；工具出现在右侧「插件」栏。

## 新增/修改的文件

| 文件 | 作用 |
| --- | --- |
| `examples/assistant_contract_local.py` | 本地合同核验 Gradio 应用 |
| `examples/assistant_vam_sandbox.py` | 对赌协议推演沙盘 Gradio 应用 |
| `vam_sandbox/pipeline.py` | 双 Agent 推演 + 评估流水线 |
| `vam_sandbox/render.py` | 决策树 HTML 渲染 |
| `mcp_servers/contract_tools.py` | 退款 / 总成本 / 租房首期 MCP stdio server |
| `scripts/make_demo_docs.py` | 生成两份中文演示 PDF |
| `demo_data/*.pdf` | 模拟宣传材料与合同 |
| `start_demo.ps1` | 启动合同核验应用 |
| `start_vam_demo.ps1` | 启动对赌推演沙盘 |
| `demo_data/ui_*.png` | 浏览器端验证截图 |

## 已验证

- 官方 MCP server `@modelcontextprotocol/server-everything`：发现 18 个工具；模型调用 `everything-get-sum` 得到 42。
- 自定义 MCP server：发现 `contract-calculate_refund`、`contract-calculate_total_cost`、`contract-calculate_lease_upfront`；UI 中实际调用并返回 1920 元 / 100,100 港币。
- 两 PDF 上传、RAG 检索、流式回答、工具调用均在真实 Chrome 中跑通。
- 右侧推荐对话已改为 5 个条款问题：退款、违约金、自动续费、服务期限、额外收费，可直接逐条点选。
- 对赌推演沙盘：双 Agent 流水线跑通，前端渲染决策树；示例得到「达成对赌 82 分 / 未达成-8% 回购 53.5 分 / 未达成-股权补偿 51.5 分 / 中性 56 分」。

## 已知限制

1. `qwen2.5:7b` 会编造页码：实测把合同第 1 页的退费条款写成「第 4 页」。页码必须由结构化抽取层提供，不能只靠模型。
2. 本地 7B 对「输出完整五类条款表」和「立即给金额」的指令遵循不稳定，长回答会挤占计算结论。
3. 只支持可提取文本的 PDF；扫描件需要 OCR。
4. 两份无关合同一起上传会互相干扰检索；建议一次只放一份合同，宣传材料单独一轮。
5. 表格类 PDF 的单元格可能被解析器漏掉（付款渠道费率、水电费行），金额必须回看原文表格。
6. 结果只用于发现「宣传 vs 合同」的不一致和需核实问题，不构成违法判断或法律意见。
7. Gradio 首次加载约 15–20 秒；首次模型请求有 10 秒左右加载时间。
