"""把本地材料读成按页文本。

PDF 依赖 pdfplumber；未安装时抛 DocumentReadError，由调用方决定降级或提示。
.txt / .md 直接按单页读入，便于回归测试不依赖 PDF 解析库。
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from .schema import Document, DocRole, PageText


class DocumentReadError(RuntimeError):
    """材料无法读取（缺依赖、文件损坏、格式不支持）。"""


def read_pages(path: str) -> List[PageText]:
    file_path = Path(path)
    if not file_path.is_file():
        raise DocumentReadError(f'文件不存在：{file_path}')

    suffix = file_path.suffix.lower()
    if suffix in {'.txt', '.md'}:
        text = file_path.read_text(encoding='utf-8', errors='replace')
        return [PageText(page=1, text=text)]

    if suffix != '.pdf':
        raise DocumentReadError(f'不支持的格式：{suffix or "无后缀"}')

    try:
        import pdfplumber  # noqa: F401  (延迟导入，避免核心逻辑强依赖)
    except ImportError as exc:  # pragma: no cover - 仅在缺依赖时触发
        raise DocumentReadError(
            '未安装 pdfplumber，无法读取 PDF；可先安装 pdfplumber 或改用 .txt 材料'
        ) from exc

    pages: List[PageText] = []
    try:
        with pdfplumber.open(str(file_path)) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                pages.append(PageText(page=index, text=page.extract_text() or ''))
    except Exception as exc:  # noqa: BLE001
        raise DocumentReadError(f'PDF 解析失败：{file_path.name}: {exc}') from exc

    if not pages:
        raise DocumentReadError(f'PDF 没有可读取的页面：{file_path.name}')
    return pages


def load_document(
    path: str, role: DocRole, document_id: str = '', filename: str = '',
) -> Document:
    """filename 允许传入上传时的原始文件名（落盘名可能是 uuid）。"""
    file_path = Path(path)
    return Document(
        document_id=document_id or file_path.stem,
        filename=filename or file_path.name,
        role=role,
        pages=read_pages(path),
    )
