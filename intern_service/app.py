r"""Intern-Decision 2B sidecar service.

独立进程运行，避免把 torch/transformers 装进 Qwen-Agent 主环境。

启动：
    cd intern_service
    py -3.13 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    .\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8010

首次请求会下载/加载模型，之后复用同一个 DecisionEngine。
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title='Intern-Decision Scorer', version='0.1.0')

ROOT = Path(__file__).resolve().parent
MODEL_ID = os.getenv('INTERN_MODEL', 'internlm/Intern-Decision-2B')
CHECKPOINT = Path(os.getenv('INTERN_CHECKPOINT', str(ROOT / 'models' / 'intern-decision-2b')))
DEVICE = os.getenv('INTERN_DEVICE', 'cuda')
DTYPE = os.getenv('INTERN_DTYPE', 'bfloat16')
HF_TOKEN = os.getenv('HF_TOKEN', '')

_engine = None
_lock = threading.Lock()


class ScoreRequest(BaseModel):
    contract_text: str
    scenario_text: str


def _load_engine():
    global _engine
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine
        CHECKPOINT.mkdir(parents=True, exist_ok=True)
        if not any(CHECKPOINT.glob('*.safetensors')):
            from huggingface_hub import snapshot_download
            snapshot_download(
                repo_id=MODEL_ID,
                local_dir=str(CHECKPOINT),
                token=HF_TOKEN or None,
            )
        sys.path.insert(0, str(CHECKPOINT))
        from inference import DecisionEngine  # type: ignore

        _engine = DecisionEngine(
            checkpoint=str(CHECKPOINT),
            device=DEVICE,
            dtype=DTYPE,
        )
        return _engine


@app.get('/health')
def health():
    return {'status': 'ok', 'model': MODEL_ID, 'checkpoint': str(CHECKPOINT), 'loaded': _engine is not None}


@app.post('/score')
def score(req: ScoreRequest) -> Dict[str, Any]:
    engine = _load_engine()
    criteria = {str(i): f'{i} 分' for i in range(11)}
    request = {
        'state': f'合同原文：\n{req.contract_text}\n\n待评估推演情景：\n{req.scenario_text}',
        'questions': {
            'risk_score': {
                'type': 'score',
                'instructions': '评估违约风险：0 分=极低，10 分=极高。',
                'criteria': criteria,
            },
            'feasibility_score': {
                'type': 'score',
                'instructions': '评估该情景方案的落地可行性：0 分=完全不可行，10 分=非常可行。',
                'criteria': criteria,
            },
            'loss_score': {
                'type': 'score',
                'instructions': '评估情景发生后的预期损失：0 分=几乎没有损失，10 分=损失极大。',
                'criteria': criteria,
            },
        },
    }
    result = engine.predict(request)
    answers = result['answers']
    confidence = sum(answers[k]['confidence'] for k in answers) / len(answers)
    evidence = f'输入依据：{req.scenario_text[:180]}'
    return {
        'risk_score': round(float(answers['risk_score']['score']), 3),
        'feasibility_score': round(float(answers['feasibility_score']['score']), 3),
        'loss_score': round(float(answers['loss_score']['score']), 3),
        'confidence': round(float(confidence), 4),
        'evidence': evidence,
        'model': result.get('model', 'Intern-Decision-2B'),
        'backend': result.get('backend', 'hf'),
        'timing': result.get('timing', {}),
    }
