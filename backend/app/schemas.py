"""Pydantic 请求/响应模型。"""

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field, FiniteFloat, StrictBool, StrictInt, model_validator


class ContractAnalyzeResponse(BaseModel):
    question: str
    answer: str
    files: List[str]


class HealthResponse(BaseModel):
    status: str


class VamEvidenceInput(BaseModel):
    file_id: str = Field(pattern=r'^[a-f0-9]{32}\.[pP][dD][fF]$')
    filename: str = Field(min_length=1, max_length=240)
    page: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=2400)


class VamAction(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    terms: str = Field(default='', max_length=1200)
    parameters: Dict[str, str | StrictInt | FiniteFloat | StrictBool | None] = Field(default_factory=dict, max_length=16)


class VamWeights(BaseModel):
    risk_score: StrictInt = Field(default=40, ge=0, le=100)
    feasibility_score: StrictInt = Field(default=35, ge=0, le=100)
    loss_score: StrictInt = Field(default=25, ge=0, le=100)

    @model_validator(mode='after')
    def check_total(self):
        if sum(self.model_dump().values()) != 100:
            raise ValueError('三项评分权重合计须为 100。')
        return self


class VamStudy(BaseModel):
    role: Literal['tenant', 'landlord', 'company', 'investor', 'other'] | None = None
    objective: Literal['cash', 'liability', 'timing', 'equity'] | None = None
    template: Literal['qualitative', 'repurchase', 'lease_exit'] = 'qualitative'
    actions: List[VamAction] = Field(default_factory=list, max_length=3)
    experimental_scoring: StrictBool = False
    weights: VamWeights = Field(default_factory=VamWeights)

    @model_validator(mode='after')
    def check_study(self):
        labels = [action.label.strip() for action in self.actions]
        if '' in labels or len(set(labels)) != len(labels):
            raise ValueError('每个方案须有不同的非空名称。')
        if self.experimental_scoring and (not self.role or not self.objective):
            raise ValueError('开启实验评分前，请先选择身份和关注目标。')
        return self


class VamRunRequest(VamStudy):
    query: str = Field(max_length=12000)
    evidence: List[VamEvidenceInput] = Field(default_factory=list, max_length=6)


class VamCompareRequest(BaseModel):
    run_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    actions: List[VamAction] = Field(max_length=3)
    triggers: Dict[str, Literal['met', 'not_met', 'unknown']] = Field(default_factory=dict, max_length=10)
    weights: VamWeights | None = None


class VamDeepenRequest(BaseModel):
    result: Dict[str, Any]
    leaf_id: str


class VamExportRequest(BaseModel):
    result: Dict[str, Any]


class VamResult(BaseModel):
    run_id: str
    query: str
    scenario: str
    assumptions: List[str]
    uncertainties: List[str]
    tree: Dict[str, Any]
    ranked: List[Dict[str, Any]]
    best: Dict[str, Any]
    study: Dict[str, Any]
    comparison: Dict[str, Any]
    warnings: List[str]


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
    evidence_review: Dict[str, Any]
    risk: Dict[str, Any]


class EvidenceResolveResponse(BaseModel):
    evidence_id: str
    document_id: str
    filename: str
    role: str
    page: int
    char_start: int
    char_end: int
    quote: str
    context: str
    verified: bool


class VersionDiffDocument(BaseModel):
    document_id: str
    filename: str


class VersionCompareResponse(BaseModel):
    old_document: VersionDiffDocument
    new_document: VersionDiffDocument
    summary: Dict[str, int]
    rows: List[Dict[str, Any]]
    method: str
