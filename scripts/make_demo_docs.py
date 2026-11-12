"""Generate two small Chinese PDFs for the local RAG demo.

The text is intentionally synthetic and only used to exercise the pipeline:
promotional claims vs. contract clauses.
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "demo_data"
FONT_PATH = Path(r"C:\Windows\Fonts\simhei.ttf")

pdfmetrics.registerFont(TTFont("SimHei", str(FONT_PATH)))
TITLE = ParagraphStyle("title", fontName="SimHei", fontSize=18, leading=26, spaceAfter=10)
H2 = ParagraphStyle("h2", fontName="SimHei", fontSize=13, leading=20, spaceBefore=8, spaceAfter=4)
BODY = ParagraphStyle("body", fontName="SimHei", fontSize=10.5, leading=17)


def p(text: str, style=BODY):
    return Paragraph(text, style)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("SimHei", 8)
    canvas.drawRightString(200 * mm, 12 * mm, f"第 {doc.page} 页")
    canvas.restoreState()


def build_promo():
    path = OUT_DIR / "promo_gym.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=20 * mm, bottomMargin=18 * mm)
    story = [
        p("星跃健身 · 2026 年卡限时优惠", TITLE),
        p("活动时间：2026 年 1 月 1 日—2026 年 3 月 31 日"),
        Spacer(1, 5 * mm),
        p("一、年卡价格", H2),
        p("年卡仅需 4800 元，包含 48 节私教课，平均每节课低至 100 元。"),
        p("二、退费承诺", H2),
        p("我们承诺：会员可随时退费，未上课全额退款，绝不收取任何手续费。"),
        p("三、收费承诺", H2),
        p("年卡 4800 元一口价，无任何额外收费，储物柜、体测、约课服务全部免费。"),
        p("四、服务承诺", H2),
        p("不满意随时退，剩余课时按购买价折算，7 个工作日内到账。"),
        Spacer(1, 8 * mm),
        p("本宣传页仅供活动说明，具体服务内容以双方签署的合同为准。"),
    ]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return path


def build_contract():
    path = OUT_DIR / "contract_gym.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=20 * mm, bottomMargin=18 * mm)
    story = [
        p("星跃健身服务合同", TITLE),
        p("合同编号：XY-2026-001"),
        p("甲方（消费者）：__________　乙方（经营者）：星跃健身有限公司"),
        p("第一条 服务期限", H2),
        p("本合同服务期限为 2026 年 1 月 1 日至 2026 年 12 月 31 日。"),
        p("第二条 服务费用", H2),
        p("年卡费用为人民币 4800 元，包含 48 节私教课。会员另行购买私教课的，按每节 300 元计价。"),
        p("第三条 退费规则", H2),
        p("会员申请退费的，已上课时按课程原价每节 300 元结算，并在剩余学费中扣除 20% 的手续费。"),
        p("已开卡且已上课时超过 12 节的，不支持退费。退费申请须本人到店提交书面材料。"),
        p("第四条 违约责任", H2),
        p("会员提前解除合同的，应向乙方支付合同总金额 30% 的违约金。"),
        PageBreak(),
        p("第五条 自动续费", H2),
        p("服务期限届满前 7 日内，会员未以书面形式通知不续费的，视为同意自动续费一年，乙方可从会员绑定的支付账户中扣划下一年度年卡费用。"),
        p("第六条 其他费用", H2),
        p("储物柜使用费为 200 元/年；体测服务费为 100 元/次；私教课改约收取 50 元/次的手续费。上述费用不包含在年卡费用中。"),
        p("第七条 争议解决", H2),
        p("因本合同产生的争议，双方应协商解决；协商不成的，提交乙方所在地人民法院诉讼解决。"),
        Spacer(1, 12 * mm),
        p("甲方签字：__________　乙方盖章：__________"),
        p("签署日期：____ 年 __ 月 __ 日"),
    ]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return path


if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    print(build_promo())
    print(build_contract())
