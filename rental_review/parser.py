"""租房合同解析与条款切分。

只负责“把文件变成可核验的文本 + 条款片段”，不做风险判断。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

import pdfplumber


@dataclass
class Clause:
    clause_id: str
    page: int
    text: str

    def to_dict(self) -> dict:
        return {'clause_id': self.clause_id, 'page': self.page, 'text': self.text}


@dataclass
class ParsedContract:
    filename: str
    file_type: str
    pages: List[str]
    clauses: List[Clause]

    @property
    def text(self) -> str:
        return '\n'.join(self.pages)

    def to_dict(self) -> dict:
        return {
            'filename': self.filename,
            'file_type': self.file_type,
            'pages': [{'page': i + 1, 'text': text} for i, text in enumerate(self.pages)],
            'clauses': [c.to_dict() for c in self.clauses],
        }


_ARTICLE_RE = re.compile(r'(?m)(?=第[一二三四五六七八九十百零〇\d]{1,12}[条條])')


def normalize_text(text: str) -> str:
    return re.sub(r'\s+', '', text or '')


def _split_page(page_text: str, page: int, counter: List[int]) -> List[Clause]:
    text = (page_text or '').replace('\u3000', ' ').strip()
    if not text:
        return []

    chunks = [c.strip() for c in _ARTICLE_RE.split(text) if c.strip()]
    if len(chunks) > 1:
        # 有明确的“第 X 条”标题：一条一条保留，避免把多条合并成一个片段
        clauses: List[Clause] = []
        for chunk in chunks:
            if len(chunk) < 8 and clauses:
                clauses[-1].text = f'{clauses[-1].text}\n{chunk}'
                continue
            counter[0] += 1
            clauses.append(Clause(f'C{counter[0]}', page, chunk))
        return clauses

    # 没有条款标题时按空行/句号切成不超过 600 字的片段
    chunks = [c.strip() for c in re.split(r'\n\s*\n|(?<=[。；;])\s*', text) if c.strip()]

    clauses = []
    buffer = ''
    for chunk in chunks:
        if len(buffer) + len(chunk) <= 700:
            buffer = f'{buffer}\n{chunk}'.strip()
            continue
        if buffer:
            counter[0] += 1
            clauses.append(Clause(f'C{counter[0]}', page, buffer))
        buffer = chunk
    if buffer:
        counter[0] += 1
        clauses.append(Clause(f'C{counter[0]}', page, buffer))
    return clauses


def _read_pdf(path: Path) -> List[str]:
    pages: List[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or '')
    return pages


def _read_docx(path: Path) -> List[str]:
    from docx import Document

    doc = Document(str(path))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    # DOCX 没有可靠页码，按内容长度虚拟分页，至少 1 页
    pages: List[str] = []
    buffer = ''
    for paragraph in paragraphs:
        if len(buffer) + len(paragraph) > 1800 and buffer:
            pages.append(buffer)
            buffer = paragraph
        else:
            buffer = f'{buffer}\n{paragraph}'.strip()
    if buffer or not pages:
        pages.append(buffer)
    return pages


def _read_text(path: Path) -> List[str]:
    text = path.read_text(encoding='utf-8', errors='ignore')
    pages = [p.strip() for p in text.split('\f')]
    return pages or ['']


def parse_contract(path: str, filename: str | None = None) -> ParsedContract:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    name = filename or file_path.name

    if suffix == '.pdf':
        pages = _read_pdf(file_path)
        file_type = 'pdf'
    elif suffix == '.docx':
        pages = _read_docx(file_path)
        file_type = 'docx'
    elif suffix in {'.txt', '.md'}:
        pages = _read_text(file_path)
        file_type = 'text'
    else:
        raise ValueError('只支持 PDF、DOCX、TXT、MD 格式')

    counter = [0]
    clauses: List[Clause] = []
    for index, page_text in enumerate(pages, start=1):
        clauses.extend(_split_page(page_text, index, counter))

    if not clauses:
        raise ValueError('没有从文件中读取到可分析的条款文本')

    return ParsedContract(filename=name, file_type=file_type, pages=pages, clauses=clauses)


__all__ = ['Clause', 'ParsedContract', 'normalize_text', 'parse_contract']
