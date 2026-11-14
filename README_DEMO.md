# 签之前：合同核验 + 合同情景推演与决策评分

基于 [QwenLM/Qwen-Agent](https://github.com/QwenLM/Qwen-Agent) 的课程项目。

当前架构：

```text
React + TypeScript + Vite + Tailwind + shadcn/ui 风格组件
        │
        │  /api
        ▼
FastAPI + Qwen-Agent + MCP + Ollama / DashScope
```

> Gradio 旧前端已移除；仓库只保留 React 前端和 FastAPI 后端。

## 功能

### 合同核验

- 上传宣传材料与合同（PDF/Word/TXT）；
- 抽取退款、违约金、自动续费、服务期限、额外收费五类条款；
- 判定“一致 / 矛盾 / 证据不足”；
- 双栏 PDF 证据定位与关键词高亮；
- MCP 工具计算退款、总成本、租房首期。

### 宣传 vs 合同

- 条款结构化抽取与跨文档匹配；
- 五类条款逐项对照：主结论统一为「一致 / 矛盾 / 证据不足」三分类，表格同时给出六标签细分（一致、矛盾、合同未约定、宣传未提及、双方未约定、证据不足）；
- 每条结论附 `evidence_id`（文档 ID + 页码 + 字符区间），可点击回查 PDF 页码，也可调用 `GET /api/contract/evidence/{evidence_id}` 按 ID 反查；
- 确定性证据复核：逐条校验页码、字符区间、原文切片与字段重算是否自洽（不调用模型，也不是另一个 Agent）；
- 合同风险评分与红线：按条款冲突、承诺未写进合同、自动续费无通知期等规则给出 0–100 分与红线清单。

### 合同版本对比

- 上传旧版与新版合同，按五类条款比较金额、比例、期限、通知期和条件；
- 输出每类条款的新增 / 删除 / 变更 / 未变，并附两边可回查的证据 ID。

### 证据链

- 条款对照页的证据可直接回查 PDF 页码；
- 每条证据带稳定 `evidence_id`，支持按 ID 反查原文；
- 推演评分表的“依据”可查看评分输入片段；
- 没有可回查页码时明确提示“未关联合同 PDF”，不编造证据。

### 合同情景推演与决策评分

- 两段式调用：同一模型的两个角色提示词，先发散生成情景树，再逐叶子打分（不是两个独立 Agent，也不是自由多轮对话）；
- 三个子分数（违约风险 / 可行性 / 预期损失）任一缺失时，总分记为「信息不足」，不参与排序，也不用默认值补齐；
- 评分后端支持 Intern sidecar / 外部评分 API / 本地模型；sidecar 失败会自动回退并在结果中标明；
- React Flow 决策树；
- 分支评分排序、继续推演、回溯、导出 Markdown 报告；
- 明确标注“情景推演，不是真实预测”。

### 资金流

- ECharts 累计成本曲线（当前为**演示数据**，未接后端现金流接口；页面已明确标注）。

## 启动

### 一键启动（离线包推荐）

```powershell
.\start.ps1              # 默认 8001，自动打开浏览器
.\start.ps1 -NoBrowser   # 不打开浏览器
.\start.bat               # 也可以直接双击
```

脚本会依次检查 Python 依赖、前端 `dist`，然后启动 FastAPI 并托管前端；按 Ctrl+C 停止。
离线包已包含 `frontend/dist`，不需要联网执行 `npm install`。

启动后自检：

```powershell
python scripts/smoke_api.py --base http://127.0.0.1:8001
```

### 开发模式（前后端分离）

```powershell
# 终端 1：后端
cd backend
..\.venv312\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001

# 终端 2：前端
cd frontend
npm install
npm run dev
```

打开：<http://localhost:5173>

> 端口使用 `8001`，因为本机 `8000` 已被其它项目占用。

### 离线与降级行为（均已实测）

| 场景 | 行为 |
| --- | --- |
| 没有 Ollama / DashScope | 条款对照、风险评分、证据复核、评测全部可用；推演页提示「推演服务不可用：未检测到可用的模型或评分服务…」，不会白屏 |
| 后端停止、只托管前端静态文件 | 对照页给出「无法连接条款对照服务…请确认后端已在 8001 端口启动」的可读提示，控制台无未捕获异常 |
| 评分 sidecar 停止 | 自动回退外部评分 API → 本地模型，结果中标注回退原因；三者都不可用时给出可读错误 |

> 开发模式下 Vite 会把 `/api` 代理到 `127.0.0.1:8001`；生产/离线模式下由 FastAPI 直接托管 `frontend/dist`。

## 目录

```text
backend/
  app/main.py                 # FastAPI 入口 + 静态托管
  app/routers/                # contract / clauses / vam / evidence
  app/services/               # Qwen-Agent 与 vam_sandbox 封装
  app/schemas.py
  requirements.txt

frontend/
  src/App.tsx                 # 五个页面：合同核验 / 宣传 vs 合同 / 版本对比 / 情景推演 / 资金流
  src/components/
    ContractPage.tsx          # 双栏 PDF 高亮
    ClauseComparePage.tsx     # 五类条款对照 + 风险评分 + 证据回查
    VersionComparePage.tsx    # 合同版本对比
    VamPage.tsx               # React Flow 决策树
    CashflowPage.tsx          # ECharts 资金流（演示数据）
    PdfViewer.tsx
    EvidenceDrawer.tsx
    BrandLogo.tsx
    ui/                       # shadcn 风格基础组件
  vite.config.ts

clause_extraction/            # 规则抽取、跨文档匹配、evidence_id、风险与版本对比
vam_sandbox/                  # 两段式（发散 + 打分）推演流水线
mcp_servers/contract_tools.py # 退款/租金计算 MCP 工具
tests/                        # 条款抽取、证据链、VAM 树与新增能力回归测试
eval_data/                    # 合成标注数据（50 组）
scripts/build_eval_dataset.py # 重建合成数据
scripts/eval_clauses.py       # 评测脚本（规则路径，真实跑分）
scripts/smoke_api.py          # 端到端冒烟自检
start.ps1 / start.bat         # 一键启动
reports/                      # 评测报告与看板
```

## 评测（规则路径，真实跑分）

- 数据：`eval_data/` 50 组合成宣传/合同（40 组模板 + 10 组改写），标签见 `eval_data/labels.json`；
- 脚本：`python scripts/eval_clauses.py`（不联网、不调用模型）；
- 本次结果：
  - 条款抽取 Macro-F1 **0.985**（Precision 0.997 / Recall 0.974）；
  - 跨文档匹配 Macro-F1 **0.941**（六标签）/ **0.955**（三分类），准确率 **0.956**；
  - 证据定位准确率 **0.974**（296/304）；
  - 分子集：模板 1.000 / 1.000 / 1.000；改写 0.654 / 0.321 / 0.600。
- 报告：`reports/eval_report.md`；看板：`reports/eval_dashboard.html`；原始指标：`reports/eval_metrics.json`。

说明：模板子集标签与规则口径一致，接近满分只代表实现一致性；改写子集（同义表达）更能反映规则路径的真实短板。数字仅代表该合成数据集，不代表真实合同分布。

## 已知限制

1. 规则抽取覆盖常见中文合同句式，复杂例外条款仍可能漏抽；模型抽取是可选增强，未配置模型时只用规则。
2. 本地 7B 模型的评估分数存在波动，部分推演可能给出相同分数；三个子分数缺失时总分为「信息不足」。
3. 只支持可提取文本的 PDF；扫描件需要 OCR。
4. 资金流图当前是演示数据，尚未接后端现金流接口。
5. 评测数据为合成模板数据，数字只代表规则路径在该数据集上的表现，不代表真实合同分布。
6. 结果仅用于风险提示，不构成法律或投资意见。
