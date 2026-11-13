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

### 合同情景推演与决策评分

- 双 Agent：发散推演 + 收敛评估；
- React Flow 决策树；
- 分支评分排序、继续推演、回溯、导出 Markdown 报告；
- 明确标注“情景推演，不是真实预测”。

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
