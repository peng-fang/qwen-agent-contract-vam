"""FastAPI 后端入口。

运行：
    cd backend
    ..\\venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001

生产形态：若 `frontend/dist` 存在，FastAPI 会同时托管 Vue 构建产物。
"""

from pathlib import Path
import os
import sys
import threading

# 让仓库内自带的 qwen_agent 源码可直接导入（离线包不依赖 pip install -e .）
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers import clauses, contract, evidence, vam
from app.routers import checklist
from app.schemas import HealthResponse

app = FastAPI(title='签之前 API', version='0.1.0')


def _warm_ollama_models() -> None:
    if os.getenv('MODEL_PRELOAD', '1').strip().lower() in {'0', 'false', 'no'}:
        return
    base = os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434/v1').rstrip('/')
    if base.endswith('/v1'):
        base = base[:-3]
    models = []
    for name in (
        os.getenv('OLLAMA_MODEL', 'qwen2.5:7b'),
        os.getenv('ANALYZE_MODEL', ''),
        os.getenv('JUDGE_MODEL', ''),
    ):
        name = (name or '').strip()
        if name and name not in models:
            models.append(name)
    for model in models:
        try:
            requests.post(
                f'{base}/api/generate',
                json={
                    'model': model,
                    'prompt': 'ping',
                    'stream': False,
                    'keep_alive': os.getenv('MODEL_PRELOAD_KEEP_ALIVE', '30m'),
                    'options': {'num_predict': 1},
                },
                timeout=90,
            )
        except Exception:
            # 预热失败不影响服务启动，首次请求会自行加载
            pass


@app.on_event('startup')
def warm_models_on_startup() -> None:
    threading.Thread(target=_warm_ollama_models, name='model-preload', daemon=True).start()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        'http://localhost:5173',
        'http://127.0.0.1:5173',
    ],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(contract.router)
app.include_router(clauses.router)
app.include_router(vam.router)
app.include_router(checklist.router)
app.include_router(evidence.router)


@app.get('/api/health', response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status='ok')


DIST = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'

if DIST.exists():
    assets = DIST / 'assets'
    if assets.exists():
        app.mount('/assets', StaticFiles(directory=assets), name='assets')

    @app.get('/{full_path:path}', include_in_schema=False)
    async def spa(full_path: str):
        """SPA fallback：非 API 请求回退到 index.html。"""
        if full_path:
            candidate = (DIST / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(DIST):
                return FileResponse(candidate)
        return FileResponse(DIST / 'index.html')
