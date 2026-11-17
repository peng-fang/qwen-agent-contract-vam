"""Render selected checklist questions as a printable PDF."""

from __future__ import annotations

import os
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, Iterable, List
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

_FONT_NAME = 'Helvetica'
_FONT_REGISTERED = False

_FONT_CANDIDATES = (
    os.getenv('CHECKLIST_PDF_FONT', ''),
    r'C:\Windows\Fonts\simhei.ttf',
    r'C:\Windows\Fonts\Deng.ttf',
    r'C:\Windows\Fonts\NotoSansSC-VF.ttf',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
)

_PRIORITY_LABELS = {
    'must_confirm': '签前必须确认',
    'should_confirm': '建议确认',
    'reference': '留作记录',
}


def _font_name() -> str:
    global _FONT_NAME, _FONT_REGISTERED
    if _FONT_REGISTERED:
        return _FONT_NAME
    _FONT_REGISTERED = True
    for candidate in _FONT_CANDIDATES:
        if not candidate or not os.path.isfile(candidate):
            continue
        try:
            pdfmetrics.registerFont(TTFont('ChecklistCJK', candidate))
            _FONT_NAME = 'ChecklistCJK'
            return _FONT_NAME
        except Exception:
            continue
    return _FONT_NAME


def _text(value: Any, limit: int = 2400) -> str:
    return escape(str(value or '').strip()[:limit]).replace('\n', '<br/>')


def _evidence_lines(item: Dict[str, Any]) -> Iterable[str]:
    for source in (item.get('evidence') or [])[:3]:
        if not isinstance(source, dict):
            continue
        page = source.get('page')
        filename = source.get('filename') or '合同原文'
        location = f'{filename} · 第 {page} 页' if page else str(filename)
        yield f'{location}：{_text(source.get("quote"), 700)}'


def build_checklist_pdf(items: List[Dict[str, Any]], role: str = '', scope: str = '') -> bytes:
    font = _font_name()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title='签约前必问清单',
        author='签之前',
    )
    base = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'ChecklistTitle', parent=base['Title'], fontName=font,
        fontSize=20, leading=27, spaceAfter=6, textColor=colors.HexColor('#111827'),
    )
    meta_style = ParagraphStyle(
        'ChecklistMeta', parent=base['Normal'], fontName=font,
        fontSize=9, leading=14, textColor=colors.HexColor('#6b7280'), spaceAfter=10,
    )
    heading_style = ParagraphStyle(
        'ChecklistHeading', parent=base['Heading2'], fontName=font,
        fontSize=12, leading=18, spaceBefore=8, spaceAfter=4,
        textColor=colors.HexColor('#1f2937'),
    )
    body_style = ParagraphStyle(
        'ChecklistBody', parent=base['BodyText'], fontName=font,
        fontSize=9.5, leading=15, spaceAfter=4, textColor=colors.HexColor('#374151'),
    )
    question_style = ParagraphStyle(
        'ChecklistQuestion', parent=body_style, fontSize=10.5, leading=17,
        leftIndent=8, textColor=colors.HexColor('#1e3a8a'),
    )
    evidence_style = ParagraphStyle(
        'ChecklistEvidence', parent=body_style, fontSize=8, leading=12,
        leftIndent=8, textColor=colors.HexColor('#6b7280'),
    )

    story = [
        Paragraph('签约前必问清单', title_style),
        Paragraph(
            f'身份：{_text(role or "未指定")} · 分析范围：{_text(scope or "合同材料")} · '
            f'共 {len(items)} 条 · 生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M")}',
            meta_style,
        ),
    ]
    for index, item in enumerate(items, start=1):
        priority = _PRIORITY_LABELS.get(item.get('priority'), '暂未定级')
        story.append(Paragraph(f'{index}. {_text(item.get("title"), 200)}', heading_style))
        story.append(Paragraph(f'优先级：{priority}', body_style))
        story.append(Paragraph(f'什么时候会遇到：{_text(item.get("trigger"), 500)}', body_style))
        story.append(Paragraph(f'可能后果：{_text(item.get("consequence"), 800)}', body_style))
        story.append(Paragraph('可以这样问：', body_style))
        story.append(Paragraph(_text(item.get('question'), 800), question_style))
        evidence = list(_evidence_lines(item))
        if evidence:
            story.append(Paragraph('原文依据：', body_style))
            for line in evidence:
                story.append(Paragraph(line, evidence_style))
        story.append(Spacer(1, 8))

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        '本清单由「签之前」根据已读取的合同文本生成，仅用于签约前沟通和风险提示，不构成法律意见。',
        meta_style,
    ))
    doc.build(story)
    return buffer.getvalue()
