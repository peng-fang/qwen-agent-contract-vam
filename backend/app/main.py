"""FastAPI 后端入口。

运行：
    cd backend
    ..\\venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001

生产形态：若 `frontend/dist` 存在，FastAPI 会同时托管 Vue 构建产物。
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers import clauses, contract, evidence, vam
from app.schemas import HealthResponse

app = FastAPI(title='签之前 API', version='0.1.0')

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
