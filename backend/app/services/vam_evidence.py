"""Resolve selected evidence against the PDF saved by contract verification."""

import re
from pathlib import Path

import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError

from app.routers.contract import UPLOAD_DIR
from app.schemas import VamEvidenceInput


def resolve_evidence(selection: list[VamEvidenceInput]) -> list[dict]:
    evidence = []
    seen = set()
    upload_root = UPLOAD_DIR.resolve()
    for selected in selection:
        path = (upload_root / selected.file_id).resolve()
        if path.parent != upload_root or not path.is_file():
            raise ValueError('找不到所选合同，请回到合同核验重新定位。')
        try:
            with pdfplumber.open(path) as pdf:
                if selected.page > len(pdf.pages):
                    raise ValueError('该证据页码超出合同范围。')
                page = pdf.pages[selected.page - 1]
                source = page.extract_text() or ''
        except (OSError, ValueError, PDFSyntaxError) as exc:
            raise ValueError('无法读取所选合同页，请回到核验页重新定位。') from exc
        quote = selected.quote.strip()
        words = quote.split()
        match = re.search(r'\s+'.join(re.escape(word) for word in words), source) if words else None
        if match is None:
            raise ValueError(f'第 {selected.page} 页无法核对所选引文，请重新定位。')
        key = selected.file_id, selected.page, match.start(), match.end()
        if key in seen:
            continue
        seen.add(key)
        evidence.append({
            'id': f'E{len(evidence) + 1}',
            'filename': Path(selected.filename).name,
            'page': selected.page,
            'char_start': match.start(),
            'char_end': match.end(),
            'quote': match.group(),
        })
    return evidence
