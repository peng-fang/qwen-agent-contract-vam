"""Pydantic 请求/响应模型。"""

from typing import Any, Dict, List

from pydantic import BaseModel


class ContractAnalyzeResponse(BaseModel):
    question: str
    answer: str
    files: List[str]


class HealthResponse(BaseModel):
    status: str


class VamRunRequest(BaseModel):
    query: str


class VamDeepenRequest(BaseModel):
    result: Dict[str, Any]
    leaf_id: str


class VamExportRequest(BaseModel):
    result: Dict[str, Any]


class VamResult(BaseModel):
    query: str
    scenario: str
    assumptions: List[str]
    uncertainties: List[str]
    tree: Dict[str, Any]
    ranked: List[Dict[str, Any]]
    best: Dict[str, Any]


class VamExportResponse(BaseModel):
    markdown: str


class EvidenceSearchRequest(BaseModel):
    filename: str
    query: str


class EvidenceMatch(BaseModel):
    page: int
    x0: float
    top: float
    x1: float
    bottom: float
    text: str


class EvidenceSearchResponse(BaseModel):
    matches: List[EvidenceMatch]


class ClauseExtractionResponse(BaseModel):
    documents: List[Dict[str, Any]]
    clauses: List[Dict[str, Any]]
    matches: List[Dict[str, Any]]
    extractor: str
    warnings: List[str]
