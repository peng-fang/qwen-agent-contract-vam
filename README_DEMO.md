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
>
> VAM 评分和清单优先级默认采用级联：Intern-Decision 2B 快速决策，低置信度或失败时回退本地 Qwen；Intern 与 Qwen 均可单独配置。

## 功能

### 合同核验

- 上传宣传材料与合同（PDF/Word/TXT）；
- 抽取退款、违约金、自动续费、服务期限、额外收费五类条款；
- 判定“一致 / 矛盾 / 证据不足”；
- 双栏 PDF 证据定位与关键词高亮；
- MCP 工具计算退款、总成本、租房首期。

### 合同风险审查

- 在“合同核验”页上传一份合同（PDF/DOCX/TXT）；
- 支持“自动识别”合同类型，也可手动覆盖为：住宅租赁 / 健身培训 / 采购买卖 / 劳动合同 / 借款担保 / 消费电商 / 加盟特许经营 / 争议解决 / 其他未识别；
- 无法稳定归入已知类型时，按“其他合同”做通用风险审查（格式条款、单方变更/解除、付款退款、验收、违约、争议解决），并提示人工确认类型；
- 开始前可选择法域：**中国内地** 或 **中国香港**，两套法律依据不混用；
- 条款理解 Agent 抽取价款、押金、期限、续约、解除、违约金、验收/维修等事实；
- 风险审查 Agent 提出风险候选，必须带原文 quote；条款足够时要求 5–8 条；
- 法律检索 Agent 先查本地条文要旨库：
  - 内地：《民法典》、劳动合同法、消费者权益保护法、电子商务法、商业特许经营管理条例、仲裁法、民事诉讼法等；
  - 香港：Cap. 7 业主与租客条例、Cap. 458 不合情理合约条例、Cap. 26 货品售卖条例、Cap. 163 放债人条例、Cap. 609 仲裁条例、Cap. 362 商品说明条例等；香港没有专门加盟披露法例，加盟条目会明确标注；
- 本地库没有命中时，可通过官方域名白名单（gov.cn / npc.gov.cn / elegislation.gov.hk / hklii.hk 等）做官方网页检索兜底；结果标记“官方网页”并缓存，核验失败的转人工复核；
- 交叉验证 Agent 检查押金/违约金叠加、验收/尾款、竞业/补偿、仲裁/诉讼冲突等组合风险；
- Judge Agent 逐条质疑证据与法律依据，标记“证据支持 / 待人工复核 / 已驳回”；
- 结果按 **高风险 → 中风险 → 低风险** 排序，高风险优先展示；
- 风险卡片可直接“带着问题问助手”，保留原有对话核验入口。

### 宣传 vs 合同

- 条款结构化抽取与跨文档匹配；
- 五类条款逐项对照，标记一致 / 矛盾 / 缺失；
- 点击“查看原文”打开 PDF 对应页，并高亮原文片段。

### 证据链

- 条款对照页的证据可直接回查 PDF 页码；
- 合同核验定位到的 PDF 原文可带入必问清单，后端会按同一页复核引文；
- 没有可回查页码时明确提示“未关联合同 PDF”，不编造证据。

### 签约前必问清单

- 工作区共享合同：可同时使用多份合同、粘贴条款和核验原文，生成时合并为同一材料集；
- 上传单份 PDF/TXT、粘贴条款，或带入核验原文。可选填用户身份；
- Qwen 找出待确认事项，生成触发条件、可能后果和可直接复制的问题。后端按给定材料核对引文；
- 右侧提供 PDF 证据定位：关键词搜索、跳页、高亮；
- 风险卡和“宣传 vs 合同”的矛盾条目可加入必问清单，再次点击可取消；
- 可勾选需要的问题并导出为中文 PDF；
- 优先级默认 `CHECKLIST_PRIORITY_PROVIDER=cascade`：规则先排明显项，模糊项交给 Intern-Decision 2B；2B 置信度低时再由 Qwen 复核；`qwen`/`hybrid`/`intern` 保留为对照模式；
- 支持在适用卡片中填写已确认的参数，估算回购或提前退租的条件金额。

验收时打开“签约前必问清单”，选择“填入租赁示例”，再生成清单。查看押金与违约金问题的原文、复制问题并试算。押金 5000 元、违约金 10000 元、其他费用为 0 且无上限时，叠加与抵扣分别为 15000 元和 10000 元。

课程评测可用同一组人工复核的租赁、消费服务和采购合同，对比直接问答、Qwen 清单和 Qwen 清单加 Intern 优先级。重点测前三项覆盖、引文支持和问题可执行性。

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
  src/App.tsx                 # 三个页面：合同核验 / 宣传 vs 合同 / 签约前必问清单
  src/components/
    ContractPage.tsx          # 双栏 PDF 高亮
    ClauseComparePage.tsx     # 宣传与合同条款对照
    ChecklistPage.tsx         # 签约前必问清单
    PdfViewer.tsx
    BrandLogo.tsx
    ui/                       # shadcn 风格基础组件
  vite.config.ts

mcp_servers/contract_tools.py # 退款/租金计算 MCP 工具
```

## 已知限制

1. 本地 `qwen2.5:7b` 会编造页码，证据定位仍以关键词高亮为主，后续应改为结构化 `evidence_id`。
2. 7B 模型的评估分数存在波动，部分推演可能给出相同分数。
3. 只支持可提取文本的 PDF；扫描件需要 OCR。
4. 结果仅用于风险提示，不构成法律或投资意见。
