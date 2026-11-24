# 签之前：合同核验 + 签约前必问清单

基于 [QwenLM/Qwen-Agent](https://github.com/QwenLM/Qwen-Agent) 的课程项目。

> **🚀 进入项目并操作：<http://127.0.0.1:8001/>**
>
> 先在仓库根目录运行 `.\start.ps1`（或双击 `start.bat`），再点击入口。开发模式使用 <http://127.0.0.1:5173/>。GitHub 不能运行本项目的 FastAPI 后端，所以这是本机启动后的入口，不是公网 Demo。

新增报告连续追问、补充参数续办、付款计划与语义复核的运行方式及验收见 [四项合同工作流](docs/contract-workflows.md)。

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

- 上传宣传材料与合同：PDF / Word（.docx）/ TXT / MD；
- 抽取退款、违约金、自动续费、服务期限、额外收费五类条款（支持中文、英文与中英混写）；
- 判定“一致 / 矛盾 / 证据不足”；
- 双栏 PDF 证据定位与关键词高亮；
- MCP 工具计算退款、总成本、租房首期；
- 问答涉及金额时，先用确定性规则核验适用条件与参数；未通过则在回答前显示“金额适用条件未全部满足”，不把模型数字当作结算依据。

> Word 支持来自 Qwen-Agent 的文档解析器（依赖 `python-docx`，已固定在 `requirements.txt`）。
> 已用程序生成的 .docx 实测解析成功；但 `合同核验` 的完整回答仍需本地/远程模型。

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

- 输入格式：PDF / TXT / MD；**不支持 .docx**（条款抽取器会返回“不支持的格式：.docx”）；
- 条款结构化抽取与跨文档匹配；
- 支持中文、英文与中英混写；口语/方言表达（退钱、扣钱、不加钱、顺延、赔/罚钱）和英文条款（refund、cancellation fee、auto-renewal、service term、additional fee）均可识别；
- 比例与金额单位归一：百分之五、两成/三成、100 元/期、元/节、5 percent、100 HKD per month；期限与通知期支持中英文（提前 30 天 / 30 days notice）；
- 五类条款逐项对照：主结论统一为「一致 / 矛盾 / 证据不足」三分类，表格同时给出六标签细分（一致、矛盾、合同未约定、宣传未提及、双方未约定、证据不足）；
- 每条结论附 `evidence_id`（文档 ID + 页码 + 字符区间），可点击回查 PDF 页码，也可调用 `GET /api/contract/evidence/{evidence_id}` 按 ID 反查；
- 确定性证据复核：逐条校验页码、字符区间、原文切片与字段重算是否自洽（不调用模型，也不是另一个 Agent）；
- 合同风险评分与红线：按条款冲突、承诺未写进合同、自动续费无通知期等规则给出 0–100 分与红线清单；
- 金额适用条件核验（确定性，不调用模型）：先校验退款资格、已上课节数上限（如 12 节）、申请期限、手续费/违约金是否叠加、实付金额与单价等条件，再给金额；
  - 条件不满足：明确写“不适用”及原因，不给数字；
  - 条件或参数不足：按情形分档（如 ≤12 节 / >12 节），每档给触发条件与公式，缺参数时金额为空；
  - 每个金额和条件都带 `evidence_id`，可点击回查原文；无法定位的条件不进入计算。

### 合同版本对比

- 输入格式：PDF / TXT / MD；不支持 .docx；
- 上传旧版与新版合同，按五类条款比较金额、比例、期限、通知期和条件；
- 输出每类条款的新增 / 删除 / 变更 / 未变，并附两边可回查的证据 ID。

### 证据链

- 条款对照页的证据可直接回查 PDF 页码；
- 每条证据带稳定 `evidence_id`，支持按 ID 反查原文；
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

> 情景推演（`/api/vam/*`）的后端接口与 `vam_sandbox/` 仍然保留，测试也仍在运行；前端已不再提供推演页面，主流程改为上面的条款核验与签约前清单。

## 启动

### 一键启动（离线包推荐）

```powershell
.\start.ps1              # 默认 8001，自动打开浏览器
.\start.ps1 -NoBrowser   # 不打开浏览器
.\start.ps1 -Python C:\path\to\python.exe   # 指定 Python 解释器
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
| 没有 Ollama / DashScope，或评分服务不可用 | 条款对照、风险评分、证据复核、评测全部可用；情景评分默认 `cascade`（Intern 2B → 本地 Qwen），两者都不可用时接口返回 502 与中文提示（如“模型暂时未能生成可用情景，请检查模型服务后重试”），页面显示可读错误，不白屏 |
| 后端停止、只托管前端静态文件 | 对照页给出「无法连接条款对照服务…请确认后端已在 8001 端口启动」的可读提示，控制台无未捕获异常 |

> 开发模式下 Vite 会把 `/api` 代理到 `127.0.0.1:8001`；生产/离线模式下由 FastAPI 直接托管 `frontend/dist`。

## 目录

```text
backend/
  app/main.py                 # FastAPI 入口 + 静态托管
  app/routers/                # contract / clauses / checklist / vam / evidence
  app/services/               # Qwen-Agent、clause、checklist 与 vam_sandbox 封装
  app/schemas.py
  requirements.txt

frontend/
  src/App.tsx                 # 四个页面：合同核验 / 宣传 vs 合同 / 版本对比 / 必问清单
  src/components/
    ContractPage.tsx          # 双栏 PDF 高亮 + 流式问答 + 金额条件提示
    ClauseComparePage.tsx     # 五类条款对照 + 金额条件核验 + 风险评分 + 证据回查
    VersionComparePage.tsx    # 合同版本对比
    ChecklistPage.tsx         # 签约前必问清单（工作区共享文件）
    ChecklistEvidenceLocator.tsx # 清单页 PDF 证据定位
    ChecklistEstimate.tsx     # 清单条件金额试算
    RentalReviewPanel.tsx     # 合同风险审查（分类/法域/流式）
    AskAssistantDrawer.tsx    # 带问题问助手
    MarkdownAnswer.tsx        # 模型回答 Markdown 渲染
    PdfViewer.tsx
    EvidenceDrawer.tsx
    BrandLogo.tsx
    ui/                       # shadcn 风格基础组件
  lib/                        # api / checklist / vam 类型与请求
  vite.config.ts

clause_extraction/            # 规则抽取、跨文档匹配、evidence_id、金额条件核验、风险与版本对比
rental_review/                # 合同类型识别、条款理解、风险审查、法律检索与 Judge
vam_sandbox/                  # 两段式（发散 + 打分）推演流水线
mcp_servers/contract_tools.py # 退款/租金计算 MCP 工具
tests/                        # 条款、证据链、清单、风险审查、VAM 树等回归测试
eval_data/                    # 调参 50 组 + 留出 v1 40 组 + 留出 v2 40 组
scripts/build_eval_dataset.py # 重建合成数据
scripts/eval_clauses.py       # 调参集评测脚本（规则路径，真实跑分）
scripts/eval_heldout.py       # 留出集评测脚本（--dataset heldout / heldout_v2）
scripts/smoke_api.py          # 端到端冒烟自检
start.ps1 / start.bat         # 一键启动
reports/                      # 评测报告与看板（含 eval_heldout_*）
```

## 评测（规则路径，真实跑分）

- 验证环境：Python 3.12.14（依赖版本见 `requirements.txt`，均为该环境 `pip freeze` 的实测版本）；Node 22.22.2 / npm 10.9.1（仅重建前端时需要）。
- 数据：`eval_data/` 50 组合成宣传/合同（40 组模板 + 10 组改写），标签见 `eval_data/labels.json`；
- 脚本：`python scripts/eval_clauses.py`（不联网、不调用模型）；
- 本次结果（2026-11-15，补充同义表达与日期换算规则后）：
  - 条款抽取 Macro-F1 **1.000**（Precision 1.000 / Recall 1.000）；
  - 跨文档匹配 Macro-F1 **1.000**（六标签）/ **1.000**（三分类），准确率 **1.000**；
  - 证据定位准确率 **1.000**（304/304）；
  - 分子集：模板 1.000 / 1.000 / 1.000；改写 1.000 / 1.000 / 1.000。
- 报告：`reports/eval_report.md`；看板：`reports/eval_dashboard.html`；原始指标：`reports/eval_metrics.json`。

说明：改写子集只有 10 组，本轮补充的关键词与换算规则正是针对这批表达，因此从 0.654 / 0.321 提升到 1.000 属于“覆盖了这批样本”，**不能**外推为真实合同的泛化能力。模板子集接近满分只代表实现一致性。

独立留出集 v1（40 组，口语/英文混写/跨句指代/嵌套条件/数字单位，冻结后参与过本轮扩展的调试参考）**扩展前**基线：

- 条款抽取 Macro-F1 **0.600**（P 1.000 / R 0.458）
- 跨文档匹配 Macro-F1 **0.346**（六标签）/ **0.424**（三分类），准确率 **0.825**
- 其中金标「矛盾」19 条只判对 1 条（Recall 0.053）
- 报告：`reports/eval_heldout_report.md`；看板：`reports/eval_heldout_dashboard.html`

> v1 含方言与英文样本，本轮扩展规则时已查看其表达，因此 **v1 不再是干净基线**；扩展后 v1 回升到抽取 0.825 / 匹配 0.637 / 准确率 0.885，只用于说明覆盖前后的变化。

第二批独立留出集 v2（40 组：方言 8、英文 8、中英混写 8、跨句指代 6、嵌套 5、数字单位 5；2026-11-19 冻结，`sha256=f86cdfff…`，规则扩展完成后只运行一次）：

- 条款抽取 Macro-F1 **0.973**（P 0.975 / R 0.975）
- 跨文档匹配 Macro-F1 **0.860**（六标签）/ **0.856**（三分类），准确率 **0.940**
- 证据定位 **78/80 = 0.975**
- 分类别：英文 0.995、方言 0.810、混写 0.768、指代 0.778、嵌套 0.667、数字单位 0.933（均为六标签匹配 F1）
- 报告：`reports/eval_heldout_v2_report.md`；看板：`reports/eval_heldout_v2_dashboard.html`

**两批对比**：调参集 1.000 / 旧 v1 扩展前 0.346 / 旧 v1 扩展后 0.637（已污染）/ 新 v2 0.860。v2 仍低于调参集，说明规则对固定表达的拟合仍强于真实改写；跨句指代与嵌套条件最弱。

### 复查与主证据相关的条款

在「宣传 vs 合同」点击「查看原文」，证据抽屉会显示可识别的相邻限定句及明确引用的编号条款。PDF 补充片段可跳到对应页，原文位置也可由证据 ID 回查。同号条款有多处时不猜测。当前只识别同页紧接的限定句和同文档内的一跳条号引用，核验结果仍按原有流程生成。

使用虚构材料复跑取证与本地模型对照：

```powershell
python scripts/eval_linked_evidence.py --out ./local-eval/linked-evidence.json
# 本机已有 Ollama 和 qwen2.5:7b 时，增加 --live 测试模型结论。
python scripts/eval_linked_evidence.py --live --out ./local-eval/linked-evidence-ollama.json
```

脚本固定主句，对比全文、附近片段、成组证据和仅主句。默认给附近片段与成组证据同样的 48 个额外引文字符，并单独记录模型服务实际报告的 token。三类各一对开发样例用于检查机制，尚未用于独立测试。

复盘某一条核验结果时，可以把逐案记录和本次报告输出到单独目录：

```powershell
python scripts/eval_heldout.py --dataset heldout_v2 --diagnostics --output-dir ./local-eval
```

`eval_heldout_v2_diagnostics.json` 包含数据文件哈希、各案例的金标和预测标签、双方抽取字段、原文及位置、匹配理由。按 `case` 和 `clause_type` 查询可复盘对应结果。双方各自的证据状态如下：

| 状态 | 含义 |
| --- | --- |
| `located` | 页码和字符区间可回查，且引文与标注句匹配 |
| `missing_clause` | 有标注，但没有抽到该类条款 |
| `invalid_location` | 抽到条款，但所有候选引文均无法按位置回查 |
| `different_excerpt` | 有可回查的引文，但没有一处与标注句匹配 |
| `unexpected_clause` | 抽到该类条款，但这一侧没有对应标注 |
| `not_annotated` | 这一侧没有对应标注，也没有抽到该类条款 |

`summary.verdict_mismatches` 统计六标签不一致的条数，`summary.mismatches_with_both_evidence_located` 统计其中双方均定位到标注句的条数。定位检查只覆盖引文与标注句的匹配，判断结论是否得到引文支持仍需复盘。

## 已知限制

1. 规则抽取覆盖常见中文、英文与中英混写合同句式；第二批留出集上匹配 F1 0.860，跨句指代（0.778）和嵌套条件（0.667）仍是短板，`前述费用`、`该期限` 与「除非…否则…」的极性会漏判或读反。模型抽取是可选增强，未配置模型时只用规则。
2. 本地 7B 模型的评估分数存在波动，部分推演可能给出相同分数；三个子分数缺失时总分为「信息不足」。
3. 条款对照与版本对比只支持可提取文本的 PDF / TXT / MD，不接受 .docx；Word 仅在 Qwen-Agent 的合同核验路径可用。扫描件需要 OCR。
4. 评测数据为合成/人工构造文本，数字只代表规则路径在这些数据集上的表现，不代表真实合同分布；改写子集只有 10 组，v2 留出集也只有 40 组。
5. 清单与情景评分依赖本地或远程模型；未配置模型时清单页会明确提示不可用，情景推演只有后端接口、前端无页面。
6. 金额条件核验只覆盖退款与违约金的常见条件（节数上限、期限、手续费/违约金叠加、实付与单价）；地方性上限、机构自定义规则仍需人工确认。合同问答只在回答前提示“未通过核验”，不会删除模型已生成的数字。
7. 结果仅用于风险提示，不构成法律或投资意见。
