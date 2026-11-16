"""条款结构化抽取与跨文档匹配的数据契约。

设计原则：
- 抽取层可以引入模型，但模型只负责"提出候选原文片段"；
- 页码/字符偏移、字段归一化、冲突判定全部由确定性代码完成；
- 所有结构可 JSON 序列化，便于 FastAPI 返回和测试断言。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class ClauseType(str, Enum):
    """项目约定的五类条款。"""

    REFUND = 'refund'
    PENALTY = 'penalty'
    AUTO_RENEWAL = 'auto_renewal'
    SERVICE_TERM = 'service_term'
    EXTRA_FEE = 'extra_fee'


CLAUSE_LABELS: Dict[ClauseType, str] = {
    ClauseType.REFUND: '退款',
    ClauseType.PENALTY: '违约金',
    ClauseType.AUTO_RENEWAL: '自动续费/续租',
    ClauseType.SERVICE_TERM: '服务期限',
    ClauseType.EXTRA_FEE: '额外收费',
}


class DocRole(str, Enum):
    """材料在比对中的角色。"""

    PROMO = 'promo'
    CONTRACT = 'contract'
    UNKNOWN = 'unknown'


class Verdict(str, Enum):
    """跨文档比对结论。沿用项目既有口径，并补足"单边缺失"的情况。"""

    CONSISTENT = 'consistent'              # 一致
    CONFLICT = 'conflict'                  # 矛盾
    MISSING_IN_CONTRACT = 'missing_in_contract'  # 宣传有、合同未约定
    MISSING_IN_PROMO = 'missing_in_promo'        # 合同有、宣传未提及
    MISSING_BOTH = 'missing_both'          # 两边都没有
    UNCLEAR = 'unclear'                    # 两边都有，但缺少可比字段


VERDICT_LABELS: Dict[Verdict, str] = {
    Verdict.CONSISTENT: '一致',
    Verdict.CONFLICT: '矛盾',
    Verdict.MISSING_IN_CONTRACT: '合同未约定',
    Verdict.MISSING_IN_PROMO: '宣传未提及',
    Verdict.MISSING_BOTH: '双方均未约定',
    Verdict.UNCLEAR: '证据不足',
}


class VerdictGroup(str, Enum):
    """三层主结论：与课程/文档口径保持一致，六标签细分归入其三。"""

    CONSISTENT = 'consistent'
    CONFLICT = 'conflict'
    INSUFFICIENT = 'insufficient'


VERDICT_GROUPS: Dict[Verdict, VerdictGroup] = {
    Verdict.CONSISTENT: VerdictGroup.CONSISTENT,
    Verdict.CONFLICT: VerdictGroup.CONFLICT,
    Verdict.MISSING_IN_CONTRACT: VerdictGroup.INSUFFICIENT,
    Verdict.MISSING_IN_PROMO: VerdictGroup.INSUFFICIENT,
    Verdict.MISSING_BOTH: VerdictGroup.INSUFFICIENT,
    Verdict.UNCLEAR: VerdictGroup.INSUFFICIENT,
}

VERDICT_GROUP_LABELS: Dict[VerdictGroup, str] = {
    VerdictGroup.CONSISTENT: '一致',
    VerdictGroup.CONFLICT: '矛盾',
    VerdictGroup.INSUFFICIENT: '证据不足',
}


def verdict_group(verdict: Verdict) -> VerdictGroup:
    return VERDICT_GROUPS[verdict]


@dataclass
class PageText:
    """单页文本。page 从 1 开始。"""

    page: int
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return {'page': self.page, 'text': self.text}


@dataclass
class Document:
    """一份已读入内存的材料。"""

    document_id: str
    filename: str
    role: DocRole
    pages: List[PageText] = field(default_factory=list)

    def full_text(self) -> str:
        return '\n'.join(p.text for p in self.pages)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'document_id': self.document_id,
            'filename': self.filename,
            'role': self.role.value,
            'pages': [p.to_dict() for p in self.pages],
        }


@dataclass
class EvidenceSpan:
    """可回查的原文位置：文件 + 页码 + 字符区间 + 原文片段。"""

    document_id: str
    filename: str
    role: DocRole
    page: int
    chunk_id: str
    char_start: int
    char_end: int
    quote: str

    @property
    def evidence_id(self) -> str:
        """稳定证据 ID：同一文件、同一页、同一字符区间永远得到同一个 ID。"""
        return f'ev-{self.document_id}-p{self.page}-c{self.char_start}-{self.char_end}'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'evidence_id': self.evidence_id,
            'document_id': self.document_id,
            'filename': self.filename,
            'role': self.role.value,
            'page': self.page,
            'chunk_id': self.chunk_id,
            'char_start': self.char_start,
            'char_end': self.char_end,
            'quote': self.quote,
        }


@dataclass
class Clause:
    """一个结构化条款。

    fields 里的键固定为：
    - amounts: 金额列表（float，单位元）
    - rates: 比例列表（0-1 的小数，例如 20% -> 0.2）
    - per_unit_amounts: [{"amount": 200.0, "unit": "年"}]
    - durations: [{"value": 1, "unit": "年"}]
    - dates: ISO 日期字符串列表
    - notice_days: 提前通知天数，可为 None
    - conditions: 条件标签列表，例如 "used_sessions>12:no_refund"
    - flags: 布尔标记，例如 full_refund / free_of_charge / auto_renewal
    - clause_ref: 合同条号，例如 "第三条"
    """

    clause_type: ClauseType
    evidence: EvidenceSpan
    fields: Dict[str, Any]
    confidence: float = 0.5
    extractor: str = 'rules'  # rules | llm

    def to_dict(self) -> Dict[str, Any]:
        return {
            'clause_type': self.clause_type.value,
            'clause_label': CLAUSE_LABELS[self.clause_type],
            'evidence': self.evidence.to_dict(),
            'fields': _jsonable(self.fields),
            'confidence': round(float(self.confidence), 3),
            'extractor': self.extractor,
        }


@dataclass
class MatchResult:
    """一个条款类型的跨文档比对结果。"""

    clause_type: ClauseType
    verdict: Verdict
    reasons: List[str]
    promo: Optional[Dict[str, Any]] = None
    contract: Optional[Dict[str, Any]] = None
    compared: Dict[str, Any] = field(default_factory=dict)
    amount: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        group = VERDICT_GROUPS[self.verdict]
        return {
            'clause_type': self.clause_type.value,
            'clause_label': CLAUSE_LABELS[self.clause_type],
            'verdict': self.verdict.value,
            'verdict_label': VERDICT_LABELS[self.verdict],
            'verdict_group': group.value,
            'verdict_group_label': VERDICT_GROUP_LABELS[group],
            'reasons': list(self.reasons),
            'promo': _jsonable(self.promo),
            'contract': _jsonable(self.contract),
            'compared': _jsonable(self.compared),
            'amount': _jsonable(self.amount) if self.amount is not None else None,
        }


@dataclass
class ExtractionBundle:
    """一次完整抽取 + 匹配的结果。"""

    documents: List[Document] = field(default_factory=list)
    clauses: List[Clause] = field(default_factory=list)
    matches: List[MatchResult] = field(default_factory=list)
    extractor: str = 'rules'
    warnings: List[str] = field(default_factory=list)
    evidence_review: Dict[str, Any] = field(default_factory=dict)
    risk: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'documents': [d.to_dict() for d in self.documents],
            'clauses': [c.to_dict() for c in self.clauses],
            'matches': [m.to_dict() for m in self.matches],
            'extractor': self.extractor,
            'warnings': list(self.warnings),
            'evidence_review': _jsonable(self.evidence_review),
            'risk': _jsonable(self.risk),
        }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value
