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
- `POST /api/vam/run`：JSON `{query}`，返回情景树、排序和推荐路径。
- `POST /api/vam/deepen`：JSON `{result, leaf_id}`，沿叶子继续推演一层。
- `POST /api/vam/export`：JSON `{result}`，返回 Markdown 报告文本。
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
- 长任务用 `run_in_threadpool` 放到线程池，避免阻塞事件循环。
- 生产模式：先 `cd frontend && npm run build` 生成 `frontend/dist`，再启动后端，FastAPI 会自动托管 Vue 构建产物（根路径返回 `index.html`）。
