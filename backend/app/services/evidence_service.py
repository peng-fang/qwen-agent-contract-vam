"""证据定位服务：在已上传的 PDF 中查找关键词，返回页码与坐标。

坐标使用 PDF 点单位（与 pdf.js 的 viewport 基础坐标一致），前端按渲染缩放比例换算即可。
"""

from pathlib import Path
from typing import List

import pdfplumber

from app.routers.contract import UPLOAD_DIR


def _safe_path(filename: str) -> Path:
    name = Path(filename or '').name
    path = UPLOAD_DIR / name
    if not path.exists():
        raise FileNotFoundError(f'file not found: {name}')
    return path


def search(filename: str, query: str) -> List[dict]:
    query = (query or '').strip()
    if not query:
        raise ValueError('query is empty')

    path = _safe_path(filename)
    matches: List[dict] = []

    with pdfplumber.open(path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ''
            if query not in text:
                continue
            for line in page.extract_text_lines():
                line_text = line.get('text') or ''
                if query in line_text:
                    matches.append({
                        'page': page_index,
                        'x0': float(line['x0']),
                        'top': float(line['top']),
                        'x1': float(line['x1']),
                        'bottom': float(line['bottom']),
                        'text': line_text,
                    })

    return matches
