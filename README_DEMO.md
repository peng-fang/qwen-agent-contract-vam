# 签之前：合同核验 + 签约前必问清单

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
- 五类条款逐项对照，标记一致 / 矛盾 / 缺失；
- 点击“查看原文”打开 PDF 对应页，并高亮原文片段。

### 证据链

- 条款对照页的证据可直接回查 PDF 页码；
- 合同核验定位到的 PDF 原文可带入必问清单，后端会按同一页复核引文；
- 没有可回查页码时明确提示“未关联合同 PDF”，不编造证据。

### 签约前必问清单

- 上传单份 PDF/TXT、粘贴条款，或带入核验原文。可选填用户身份；
- Qwen 找出待确认事项，生成触发条件、可能后果和可直接复制的问题。后端按给定材料核对引文；
- Intern-Decision 2B 对问题标注确认顺序，信息不足时可不定级；
- 支持在适用卡片中填写已确认的参数，估算回购或提前退租的条件金额。

验收时打开“签约前必问清单”，选择“填入租赁示例”，再生成清单。查看押金与违约金问题的原文、复制问题并试算。押金 5000 元、违约金 10000 元、其他费用为 0 且无上限时，叠加与抵扣分别为 15000 元和 10000 元。

课程评测可用同一组人工复核的租赁、消费服务和采购合同，对比直接问答、Qwen 清单和 Qwen 清单加 Intern 优先级。重点测前三项覆盖、引文支持和问题可执行性。

### 资金流

- ECharts 累计成本曲线（当前为示例数据，可接后端 cashflow 接口）。

## 启动

### 1. 后端

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

> 端口使用 `8001`，因为本机 `8000` 已被其它项目占用。

### 2. 前端开发模式

```powershell
cd frontend
npm install
npm run dev
```

打开：<http://localhost:5173>

Vite 会把 `/api` 代理到 `http://127.0.0.1:8001`。

### 3. 生产模式

```powershell
cd frontend
npm run build

cd ..\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

打开：<http://127.0.0.1:8001>

FastAPI 会自动托管 `frontend/dist`。

## 目录

```text
backend/
  app/main.py                 # FastAPI 入口 + 静态托管
  app/routers/                # contract / vam / evidence
  app/services/               # Qwen-Agent 与 vam_sandbox 封装
  app/schemas.py
  requirements.txt

frontend/
  src/App.tsx                 # 三个页面：合同核验 / 合同情景推演与决策评分 / 资金流
  src/components/
    ContractPage.tsx          # 双栏 PDF 高亮
    VamPage.tsx               # React Flow 决策树
    CashflowPage.tsx          # ECharts 资金流
    PdfViewer.tsx
    BrandLogo.tsx
    ui/                       # shadcn 风格基础组件
  vite.config.ts

vam_sandbox/                  # 双 Agent 推演流水线
mcp_servers/contract_tools.py # 退款/租金计算 MCP 工具
```

## 已知限制

1. 本地 `qwen2.5:7b` 会编造页码，证据定位仍以关键词高亮为主，后续应改为结构化 `evidence_id`。
2. 7B 模型的评估分数存在波动，部分推演可能给出相同分数。
3. 只支持可提取文本的 PDF；扫描件需要 OCR。
4. 资金流图当前是示例数据，尚未接后端现金流接口。
5. 结果仅用于风险提示，不构成法律或投资意见。
