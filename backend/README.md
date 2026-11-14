# Backend（FastAPI）

将 Qwen-Agent 的合同核验逻辑封装为 HTTP 接口。

## 运行

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

> 端口使用 `8001`，因为本机 `8000` 已被其它项目占用。

## 接口

- `GET  /api/health`：健康检查。
- `POST /api/contract/analyze`：multipart 上传 `question` 与 `files`，返回 `{question, answer, files}`。
- `POST /api/checklist/run`：multipart 输入可选身份 `role`，以及 PDF/TXT `file`、条款 `text`、核验引文 JSON `evidence` 三者之一，返回最多五条有原文依据的待确认事项。
- `POST /api/checklist/consequence`：输入 `{template, parameters}`，返回不同条件下的金额、计算式及缺项。
- `POST /api/vam/run`：输入 `query`，可选 `evidence`、`role`、`objective`、`template`、`actions` 与实验评分设置。返回 `run_id`、情景树、方案的条件后果及计算式。
- `POST /api/vam/compare`：输入 `{run_id, actions, triggers?, weights?}`，在同一情景上重算方案结果与实验综合分，无需再次调用模型。
- `POST /api/vam/deepen`：输入 `{result: {run_id}, leaf_id}`，沿当前末端情景继续推演一层。
- `POST /api/vam/export`：输入 `{result: {run_id}}`，返回该版本的 Markdown 报告。
- `POST /api/evidence/search`：JSON `{filename, query}`，返回关键词在 PDF 中的页码和坐标（用于前端高亮）。

示例：

```powershell
curl.exe -X POST http://127.0.0.1:8001/api/contract/analyze `
  -F "question=请核验退款承诺" `
  -F "files=@demo_data/promo_gym.pdf" `
  -F "files=@demo_data/contract_gym.pdf"
```

## 说明

- 核心逻辑在 `app/services/contract_service.py` 与 `app/services/vam_service.py`，复用 Qwen-Agent `Assistant` / `vam_sandbox` 与 MCP 工具。
- 上传文件临时保存到 `backend/uploads/`。
- 推演保留最近 32 份内存快照，当前供单进程原型使用。重启或快照淘汰后需重新推演。
- 开启实验评分时，默认使用 [Intern-Decision 2B](../intern_service/README.md) 的本地评分服务。页面和报告会展示实际评分模型。要切换评分后端，可显式设置 `VAM_SCORER_PROVIDER`。
- 长任务用 `run_in_threadpool` 放到线程池，避免阻塞事件循环。
- 生产模式：先在 `frontend` 下运行 `npm run build` 生成 `frontend/dist`，再启动后端，FastAPI 会托管 React 构建产物。
