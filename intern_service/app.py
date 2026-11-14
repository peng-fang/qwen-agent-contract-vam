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
from pydantic import BaseModel, Field

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


class PriorityItem(BaseModel):
    id: str = Field(pattern=r'^C[1-9][0-9]?$')
    title: str = Field(max_length=80)
    trigger: str = Field(max_length=250)
    consequence: str = Field(max_length=500)
    question: str = Field(max_length=350)
    quotes: list[str] = Field(min_length=1, max_length=3)


class PriorityRequest(BaseModel):
    role: str = Field(max_length=80)
    items: list[PriorityItem] = Field(min_length=1, max_length=20)


@app.post('/priority')
def priority(req: PriorityRequest) -> Dict[str, Any]:
    engine = _load_engine()
    criteria = {
        'must_confirm': '签前必须确认：关系到重大金额、自动扣款、重要期限、退出或主要履约责任；含糊时会显著影响签约决定',
        'should_confirm': '建议确认：有具体执行影响，提前问清可减少争议，但通常不改变核心交易条件',
        'reference': '留作记录：影响较小，或所给条款已有明确答案',
        'insufficient': '暂未定级：无法根据所给信息判断其影响或必要性',
    }
    inputs = []
    for item in req.items:
        quotes = ' / '.join(item.quotes)
        inputs.append(f'[{item.id}] {item.title}\n原文：{quotes}\n条件：{item.trigger}'
                      f'\n可能后果：{item.consequence}\n问题：{item.question}')
    request = {
        'state': f'用户身份：{req.role}\n签约前待确认事项：\n' + '\n\n'.join(inputs),
        'questions': {
            item.id: {
                'type': 'choice',
                'instructions': f'结合用户身份和原文，为 {item.id} 的问题选择签约前确认优先级。只使用该事项的材料。',
                'criteria': criteria,
            } for item in req.items
        },
    }
    result = engine.predict(request)
    return {
        'model': result.get('model', 'Intern-Decision-2B'),
        'priorities': {item.id: result['answers'][item.id]['choice'] for item in req.items},
    }


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
                'instructions': '从用户立场评估不利因素严重度：0=无明显不利因素，5=有实质限制，10=有严重未化解障碍。非概率。',
                'criteria': criteria,
            },
            'feasibility_score': {
                'type': 'score',
                'instructions': '评估应对条件充分度：0=必要条件不满足，5=需补齐关键前提，10=必要条件齐备。',
                'criteria': criteria,
            },
            'loss_score': {
                'type': 'score',
                'instructions': '从用户立场评估情景下的负担程度：0=无额外负担，5=负担显著，10=负担严重。',
                'criteria': criteria,
            },
        },
    }
    result = engine.predict(request)
    answers = result['answers']
    confidence = sum(answers[k]['confidence'] for k in answers) / len(answers)
    return {
        'risk_score': round(float(answers['risk_score']['score']), 3),
        'feasibility_score': round(float(answers['feasibility_score']['score']), 3),
        'loss_score': round(float(answers['loss_score']['score']), 3),
        'confidence': round(float(confidence), 4),
        'evidence': 'Intern-Decision 实验评分，模型未返回可逐条复核的评分理由。',
        'model': result.get('model', 'Intern-Decision-2B'),
        'backend': result.get('backend', 'hf'),
        'timing': result.get('timing', {}),
    }
