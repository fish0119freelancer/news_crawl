import os
import re
from datetime import datetime
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem,
    PageBreak, Table, TableStyle, Image
)
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.units import mm

# ========= 字體設定 =========
FONT_CHINESE = "./biaokai.ttc"   # 標楷體，請確認路徑正確
FONT_ENGLISH = "./Times New Roman.ttf"

if os.path.exists(FONT_CHINESE):
    pdfmetrics.registerFont(TTFont("Biaokai", FONT_CHINESE, subfontIndex=0))
else:
    print("⚠️ 找不到 biaokai.ttc，將使用預設字體")
if os.path.exists(FONT_ENGLISH):
    pdfmetrics.registerFont(TTFont("TimesNewRoman", FONT_ENGLISH))

# ========= 顏色設定 =========
PRIMARY_COLOR = colors.HexColor("#0A3D62")
SECONDARY_COLOR = colors.HexColor("#3C6382")
HIGHLIGHT_COLOR = colors.HexColor("#60A3BC")
ACCENT_COLOR = colors.HexColor("#F8C291")

# ========= 樣式設定 =========
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(
    name="ReportTitle", fontName="Biaokai", fontSize=28, leading=34,
    textColor=PRIMARY_COLOR, alignment=1, spaceAfter=20
))
styles.add(ParagraphStyle(
    name="ReportSubtitle", fontName="Biaokai", fontSize=16, leading=20,
    textColor=SECONDARY_COLOR, alignment=1, spaceAfter=30
))
styles.add(ParagraphStyle(
    name="ChineseHeading1", fontName="Biaokai", fontSize=20, leading=24,
    spaceAfter=12, spaceBefore=12, textColor=PRIMARY_COLOR
))
styles.add(ParagraphStyle(
    name="ChineseHeading2", fontName="Biaokai", fontSize=16, leading=20,
    spaceAfter=10, leftIndent=8, textColor=SECONDARY_COLOR
))
styles.add(ParagraphStyle(
    name="ChineseHeading3", fontName="Biaokai", fontSize=14, leading=18,
    spaceAfter=8, leftIndent=16, textColor=HIGHLIGHT_COLOR
))
styles.add(ParagraphStyle(
    name="ChineseBody", fontName="Biaokai", fontSize=12, leading=18,
    spaceAfter=8, textColor=colors.black
))
styles.add(ParagraphStyle(
    name="Quote", fontName="Biaokai", fontSize=12, leading=18,
    leftIndent=20, spaceAfter=8, textColor=SECONDARY_COLOR, italic=True
))

# ========= 工具函式 =========
def fix_markdown_headings(lines):
    corrected = []
    section_h2 = ["摘要", "導讀", "學習路徑", "原文連結"]
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            corrected.append(line)
            continue
        # 第一行強制 H1
        if i == 0 and stripped.startswith("#"):
            corrected.append("# " + stripped.lstrip("# ").strip() + "\n")
            continue
        if any(stripped.lstrip("# ").startswith(sec) for sec in section_h2):
            corrected.append("## " + stripped.lstrip("# ").strip() + "\n")
            continue
        corrected.append(line)
    return corrected

def convert_markdown_links(text: str) -> str:
    return re.sub(r"\[(.*?)\]\((.*?)\)", r'<a href="\2">\1</a>', text)

def add_page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont("Biaokai", 9)
    canvas.setFillColor(SECONDARY_COLOR)
    # 頁眉
    canvas.drawString(20 * mm, 285 * mm, "每日生醫新聞解讀")
    # 頁碼
    canvas.setFillColor(colors.grey)
    canvas.drawRightString(200 * mm, 15 * mm, f"第 {doc.page} 頁")
    canvas.restoreState()

def build_cover(title, subtitle):
    cover = []
    top_bar = Table([[""]], colWidths=[460], rowHeights=[30])
    top_bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PRIMARY_COLOR)]))
    cover.append(top_bar)
    cover.append(Spacer(1, 40))
    # Logo (可選)
    if os.path.exists("logo.jpg"):
        logo = Image("logo.jpg", width=300, height=300)
        logo.hAlign = "CENTER"
        cover.append(logo)
        cover.append(Spacer(1, 20))
    cover.append(Paragraph(title, styles["ReportTitle"]))
    cover.append(Paragraph(subtitle, styles["ReportSubtitle"]))
    cover.append(Spacer(1, 20))
    cover.append(Paragraph(f"產出日期：{datetime.now().strftime('%Y/%m/%d')}", styles["ChineseBody"]))
    cover.append(PageBreak())
    return cover

def styled_heading(text):
    tbl = Table(
        [[Paragraph(text, ParagraphStyle(
            "HeadingInBox",
            parent=styles["ChineseHeading1"],
            textColor=colors.HexColor("#D4AF37"),
            fontSize=20,
            leading=24
        ))]], colWidths=[460]
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#2C2C2C")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return tbl

# ========= 主要功能 =========
def extract_references_from_md(md_file):
    """
    讀取 markdown 檔，回傳:
    - cleaned_paragraphs: list[str]
    - references: list[str] (如果有原文連結)
    """
    paragraphs = []
    references = []
    with open(md_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    lines = fix_markdown_headings(lines)
    buf = []
    for line in lines:
        if line.strip().startswith("http"):
            references.append(line.strip())
        if line.strip() == "---":
            if buf:
                paragraphs.append("\n".join(buf).strip())
                buf = []
        else:
            buf.append(line.rstrip())
    if buf:
        paragraphs.append("\n".join(buf).strip())
    return paragraphs, references

def generate_pdf(paragraphs, references=None, output_file="news_summary.pdf"):
    """
    將多段 markdown 文字直接轉為 PDF
    paragraphs: list[str]
    """
    story = build_cover("每日生醫新聞報告", "技術導讀與學習地圖")
    for block in paragraphs:
        lines = fix_markdown_headings(block.splitlines())
        buffer, list_buffer = [], []
        in_learning = False
        learning_items = []

        def flush_buffer():
            nonlocal buffer
            if buffer:
                text = " ".join(buffer).strip()
                if text:
                    story.append(Paragraph(convert_markdown_links(text), styles["ChineseBody"]))
                    story.append(Spacer(1, 8))
                buffer.clear()

        def flush_list():
            nonlocal list_buffer
            if list_buffer:
                items = [ListItem(Paragraph(convert_markdown_links(it), styles["ChineseBody"])) for it in list_buffer]
                story.append(ListFlowable(items, bulletType="bullet"))
                story.append(Spacer(1, 8))
                list_buffer.clear()

        def flush_learning():
            nonlocal learning_items
            if learning_items:
                story.append(Paragraph("學習路徑：", styles["ChineseHeading3"]))
                items = [ListItem(Paragraph(it, styles["ChineseBody"])) for it in learning_items]
                story.append(ListFlowable(items, bulletType="bullet", leftIndent=20))
                story.append(Spacer(1, 8))
                learning_items.clear()

        for line in lines:
            l = line.strip()
            if not l:
                if in_learning:
                    flush_learning(); in_learning=False
                else:
                    flush_buffer(); flush_list()
                continue

            if l.startswith("## 學習路徑"):
                flush_buffer(); flush_list()
                story.append(Paragraph("學習路徑", styles["ChineseHeading2"]))
                in_learning = True; learning_items=[]
            elif in_learning and re.match(r"^\d+\.\s+", l):
                learning_items.append(re.sub(r"^\d+\.\s+", "", l).strip())
            elif l.startswith("### "):
                flush_buffer(); flush_list()
                story.append(Paragraph(l[4:], styles["ChineseHeading3"]))
            elif l.startswith("## "):
                flush_buffer(); flush_list()
                story.append(Paragraph(l[3:], styles["ChineseHeading2"]))
            elif l.startswith("# "):
                flush_buffer(); flush_list()
                story.append(styled_heading(l[2:]))
            elif l.startswith("> "):
                flush_buffer(); flush_list()
                story.append(Paragraph(convert_markdown_links(l[2:]), styles["Quote"]))
            elif l.startswith("- "):
                flush_buffer(); list_buffer.append(l[2:])
            else:
                buffer.append(l)

        if in_learning: flush_learning()
        flush_buffer(); flush_list()
        story.append(Spacer(1, 12))

    doc = SimpleDocTemplate(output_file, pagesize=A4,
                            rightMargin=24, leftMargin=24,
                            topMargin=36, bottomMargin=36)
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    print(f"✅ 已輸出 PDF：{output_file}")
