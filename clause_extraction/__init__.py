"""条款结构化抽取与跨文档匹配（角色 B）。

对外入口：
- analyze_files([(path, role)], use_llm=False) -> ExtractionBundle
- analyze_documents([Document], use_llm=False) -> ExtractionBundle
"""

from .engine import analyze_documents, analyze_files, infer_role
from .extract import extract_document, extract_fields, locate_quote
from .match import match_documents
from .pdf_reader import DocumentReadError, load_document, read_pages
from .registry import (
    EvidenceNotFound,
    document_id_for,
    register_document,
    resolve_evidence,
)
from .review import review_bundle
from .risk import assess_risk
from .schema import (
    CLAUSE_LABELS,
    VERDICT_GROUP_LABELS,
    VERDICT_GROUPS,
    VERDICT_LABELS,
    Clause,
    ClauseType,
    DocRole,
    Document,
    EvidenceSpan,
    ExtractionBundle,
    MatchResult,
    PageText,
    Verdict,
    VerdictGroup,
    verdict_group,
)
from .version_diff import diff_documents

__all__ = [
    'analyze_documents',
    'analyze_files',
    'infer_role',
    'extract_document',
    'extract_fields',
    'locate_quote',
    'match_documents',
    'DocumentReadError',
    'load_document',
    'read_pages',
    'EvidenceNotFound',
    'document_id_for',
    'register_document',
    'resolve_evidence',
    'review_bundle',
    'assess_risk',
    'diff_documents',
    'CLAUSE_LABELS',
    'VERDICT_LABELS',
    'VERDICT_GROUPS',
    'VERDICT_GROUP_LABELS',
    'Clause',
    'ClauseType',
    'DocRole',
    'Document',
    'EvidenceSpan',
    'ExtractionBundle',
    'MatchResult',
    'PageText',
    'Verdict',
    'VerdictGroup',
    'verdict_group',
]
