# Intern-Decision 2B sidecar

独立的决策打分服务，避免把 `torch/transformers` 装进 Qwen-Agent 主环境。

- 模型：`internlm/Intern-Decision-2B`（Apache-2.0）
- 输入：合同原文 + 一条推演分支情景
- 输出：`risk_score / feasibility_score / loss_score / confidence / evidence`
- 端口：`8010`

## 环境

官方 README 建议 **Python 3.12+**。建议单独建 venv：

```powershell
cd D:\港大NLP\project_deepseek\Qwen-Agent\intern_service
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> 6GB 显存建议 `INTERN_DTYPE=bfloat16`；显存不足时改 `INTERN_DEVICE=cpu`，但会慢很多。

## 启动

```powershell
cd D:\港大NLP\project_deepseek\Qwen-Agent\intern_service
$env:INTERN_DEVICE  = 'cuda'
$env:INTERN_DTYPE   = 'bfloat16'
$env:INTERN_MODEL   = 'internlm/Intern-Decision-2B'
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8010
```

首次请求会下载模型到 `intern_service/models/intern-decision-2b`，需要几 GB 磁盘。

健康检查：

```powershell
curl.exe http://127.0.0.1:8010/health
```

## 接到主后端

在 `backend/.env` 里设置：

```env
VAM_SCORER_PROVIDER=intern
VAM_INTERN_URL=http://127.0.0.1:8010/score
```

然后重启 FastAPI：

```powershell
cd D:\港大NLP\project_deepseek\Qwen-Agent\backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

主后端会按分支逐个调用 sidecar，返回新的 5 字段评分。

## 说明

- Intern-Decision 是**结构化打分模型**，不是聊天模型；它不生成长篇解释。
- 因此 `evidence` 使用输入情景片段，并标注“输入依据”，不是模型自由生成的原文引用。
- 模型权重与 `intern_service/models/` 已在 `.gitignore` 中，不会提交。
