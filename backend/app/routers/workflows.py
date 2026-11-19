"""Versioned, additive endpoints for the four contract workflows."""
from typing import Literal

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, ConfigDict, Field, StrictInt, FiniteFloat

from app.services import workflow_store as store, report_dialogue, verification_tasks
from app.services.workflow_llm import ModelUnavailable

router = APIRouter(prefix='/api/workflows', tags=['workflows'])


def execute(fn, *args):
    try:
        return fn(*args)
    except store.RevisionConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except KeyError:
        raise HTTPException(404, '记录不存在或已清理') from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except ModelUnavailable as exc:
        raise HTTPException(502, str(exc)) from None


class ChatStart(BaseModel):
    report_id: str = Field(pattern=r'^[a-f0-9]{32}$')


class ChatTurn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    risk_ids: list[str] = Field(default_factory=list, max_length=20)
    revision: int = Field(ge=1)


class Facts(BaseModel):
    model_config = ConfigDict(extra='forbid')
    used_sessions: StrictInt | None = Field(None, ge=0, le=10000)
    total_paid: FiniteFloat | None = Field(None, ge=0, le=1e9)
    unit_price: FiniteFloat | None = Field(None, ge=0, le=1e9)
    request_day: StrictInt | None = Field(None, ge=0, le=36500)
    request_phase: Literal['开课前', '开课后'] | None = None


class Supplement(BaseModel):
    revision: int = Field(ge=1)
    facts: Facts


@router.post('/conversations')
def create_chat(req: ChatStart):
    return execute(report_dialogue.conversation, req.report_id)


@router.get('/conversations/{conversation_id}')
def get_chat(conversation_id: str):
    return execute(store.get, 'conversations', conversation_id)


@router.post('/conversations/{conversation_id}/messages')
def chat(conversation_id: str, req: ChatTurn):
    if not req.question.strip():
        raise HTTPException(422, '请输入问题')
    return execute(report_dialogue.ask, conversation_id, req.question, req.risk_ids, req.revision)


@router.get('/verifications/{task_id}')
def get_verification(task_id: str):
    return execute(lambda: verification_tasks.public(store.get('verifications', task_id)))


@router.post('/verifications/{task_id}/facts')
def add_facts(task_id: str, req: Supplement):
    return execute(verification_tasks.supplement, task_id, req.facts.model_dump(exclude_none=True), req.revision)


