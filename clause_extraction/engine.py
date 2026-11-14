"""编排：读材料 -> 抽取 -> 跨文档匹配。"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple

from .extract import extract_document
from .llm_extractor import extract_with_llm
from .match import match_documents
from .pdf_reader import load_document
from .schema import Clause, DocRole, Document, ExtractionBundle


def infer_role(filename: str) -> DocRole:
    lowered = filename.lower()
    if re.search(r'promo|advert|flyer|leaflet|宣传|广告|海报', lowered):
        return DocRole.PROMO
    if re.search(r'contract|agreement|合同|协议|条款', lowered):
        return DocRole.CONTRACT
    return DocRole.UNKNOWN


def analyze_documents(
    documents: Sequence[Document], use_llm: bool = False,
) -> ExtractionBundle:
    clauses: List[Clause] = []
    warnings: List[str] = []
    used_llm = False

    for document in documents:
        doc_clauses = extract_document(document)
        if use_llm:
            llm_clauses, llm_warnings = extract_with_llm(document)
            warnings.extend(llm_warnings)
            if llm_clauses:
                used_llm = True
                existing = {clause.clause_type for clause in doc_clauses}
                for clause in llm_clauses:
                    if clause.clause_type in existing:
                        continue
                    doc_clauses.append(clause)
                    existing.add(clause.clause_type)
        clauses.extend(doc_clauses)

    if not any(document.role == DocRole.PROMO for document in documents):
        warnings.append('未识别到宣传材料，跨文档匹配只输出合同单边结果')
    if not any(document.role == DocRole.CONTRACT for document in documents):
        warnings.append('未识别到合同，跨文档匹配只输出宣传单边结果')

    matches = match_documents(list(documents), clauses)
    return ExtractionBundle(
        documents=list(documents),
        clauses=clauses,
        matches=matches,
        extractor='rules+llm' if used_llm else 'rules',
        warnings=warnings,
    )


def analyze_files(
    specs: Iterable[Tuple[str, Optional[DocRole]]], use_llm: bool = False,
) -> ExtractionBundle:
    """specs: [(文件路径, 角色或 None)]；角色为 None 时按文件名推断。"""
    documents: List[Document] = []
    for index, (path, role) in enumerate(specs, start=1):
        document = load_document(
            path=path,
            role=role or infer_role(path),
            document_id=f'doc{index}',
        )
        documents.append(document)
    return analyze_documents(documents, use_llm=use_llm)
