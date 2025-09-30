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
from reportlab.lib.utils import ImageReader

# ========= 字體設定 =========
FONT_CHINESE = "./biaokai.ttc"
FONT_ENGLISH = "./Times New Roman.ttf"
TOP_BAR_HEIGHT = 12 * mm

if os.path.exists(FONT_CHINESE):
    pdfmetrics.registerFont(TTFont("Biaokai", FONT_CHINESE, subfontIndex=0))
else:
    print("⚠️ 找不到 biaokai.ttc，將使用預設字體")
if os.path.exists(FONT_ENGLISH):
    pdfmetrics.registerFont(TTFont("TimesNewRoman", FONT_ENGLISH))

# ========= 顏色 =========
PRIMARY_COLOR = colors.HexColor("#0A3D62")
SECONDARY_COLOR = colors.HexColor("#3C6382")
HIGHLIGHT_COLOR = colors.HexColor("#60A3BC")
GOLD = colors.HexColor("#D4AF37")
BLACK = colors.HexColor("#2C2C2C")

# ========= 樣式 =========
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
    name="ChineseBody", fontName="Biaokai", fontSize=12, leading=18,
    spaceAfter=8, textColor=colors.black
))
styles.add(ParagraphStyle(
    name="ChineseHeading3", fontName="Biaokai", fontSize=14, leading=18,
    spaceAfter=8, leftIndent=16, textColor=HIGHLIGHT_COLOR
))
styles.add(ParagraphStyle(
    name="Quote", fontName="Biaokai", fontSize=12, leading=18,
    leftIndent=20, spaceAfter=8, textColor=SECONDARY_COLOR, italic=True
))
styles.add(ParagraphStyle(
    name="TOCItem", fontName="Biaokai", fontSize=12, leading=16,
    leftIndent=20, textColor=PRIMARY_COLOR
))

# ========= 背景與頁碼 =========
def add_page_background(canvas, doc):
    canvas.saveState()
    # 淺藍背景
    canvas.setFillColorRGB(0.96, 0.98, 1)
    canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
    # 深藍橫條
    canvas.setFillColor(PRIMARY_COLOR)
    canvas.rect(0, A4[1] - TOP_BAR_HEIGHT, A4[0], TOP_BAR_HEIGHT, fill=1, stroke=0)
    # 右下角波浪感
    canvas.setFillColor(colors.Color(0.3, 0.6, 0.6, alpha=0.1))
    canvas.circle(A4[0] - 100, 50, 120, stroke=0, fill=1)
    # 浮水印
    if os.path.exists("logo.jpg"):
        try:
            logo = ImageReader("logo.jpg")
            canvas.saveState()
            try:
                canvas.setFillAlpha(0.08)
            except Exception:
                pass
            canvas.drawImage(logo, A4[0]/2 - 250, A4[1]/2 - 250,
                             width=500, height=500, preserveAspectRatio=True, mask='auto')
            canvas.restoreState()
        except Exception as e:
            print(f"⚠️ 浮水印載入失敗：{e}")
    canvas.restoreState()

def add_page_number_with_bg(canvas, doc):
    add_page_background(canvas, doc)
    canvas.saveState()
    canvas.setFont("Biaokai", 10)
    canvas.setFillColor(colors.whitesmoke)
    header_y = A4[1] - (TOP_BAR_HEIGHT / 2) + 1.5 * mm
    canvas.drawString(20 * mm, header_y, "每日生醫新聞解讀")
    canvas.setFont("Biaokai", 9)
    canvas.setFillColor(colors.grey)
    canvas.drawRightString(200 * mm, 15 * mm, f"第 {canvas.getPageNumber()} 頁")
    canvas.restoreState()

# ========= 工具 =========
def fix_markdown_headings(lines):
    corrected = []
    section_h3 = ["摘要", "導讀", "學習路徑", "原文連結"]
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            corrected.append(line)
            continue
        if i == 0 and s.startswith("#"):
            corrected.append("# " + s.lstrip("# ").strip() + "\n")
            continue
        if any(s.lstrip("# ").startswith(sec) for sec in section_h3):
            corrected.append("### " + s.lstrip("# ").strip() + "\n")
            continue
        corrected.append(line)
    return corrected

def convert_markdown_links(t):
    return re.sub(r"\[(.*?)\]\((.*?)\)", r'<a href="\2">\1</a>', t)

def build_cover(title, subtitle):
    cover = []
    # 上方深藍條
    top_bar = Table([[""]], colWidths=[460], rowHeights=[20])
    top_bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PRIMARY_COLOR)]))
    cover.append(top_bar)
    cover.append(Spacer(1, 40))
    # logo
    if os.path.exists("logo.jpg"):
        cover.append(Image("logo.jpg", width=200, height=200))
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
            parent=styles["ChineseBody"],
            textColor=GOLD,
            fontSize=20,
            leading=24
        ))]], colWidths=[460]
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLACK),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return tbl

# ========= 主流程 =========
def extract_references_from_md(md_file):
    paragraphs = []
    refs = []
    with open(md_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
    lines = fix_markdown_headings(lines)
    buf = []
    for line in lines:
        if line.strip().startswith("http"):
            refs.append(line.strip())
        if line.strip() == "---":
            if buf:
                paragraphs.append("\n".join(buf).strip())
                buf = []
        else:
            buf.append(line.rstrip())
    if buf:
        paragraphs.append("\n".join(buf).strip())
    return paragraphs, refs

def md_to_pdf(md_file, output_file="news_summary.pdf"):
    paragraphs, refs = extract_references_from_md(md_file)
    generate_pdf(paragraphs, refs, output_file=output_file)

def generate_pdf(paragraphs, references=None, output_file="news_summary.pdf"):
    story = build_cover("每日生醫新聞報告", "技術導讀與學習地圖")
    toc_entries = []  # 存 H2
    h2_titles = []

    # === 先掃描並建出內容 ===
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
                    flush_learning(); in_learning = False
                else:
                    flush_buffer(); flush_list()
                continue

            if l.startswith("# "):  # H1
                flush_buffer(); flush_list()
                story.append(PageBreak())
                story.append(Spacer(1, 200))
                story.append(Paragraph(l[2:].strip(), ParagraphStyle(
                    "CategoryPage",
                    fontName="Biaokai",
                    fontSize=28,
                    textColor=PRIMARY_COLOR,
                    alignment=1
                )))
                story.append(PageBreak())

            elif l.startswith("## "):  # H2
                flush_buffer(); flush_list()
                bookmark = f"h2_{len(toc_entries)}"
                story.append(Paragraph(f'<a name="{bookmark}"/>', styles["ChineseBody"]))
                story.append(styled_heading(l[3:].strip()))
                toc_entries.append((l[3:].strip(), bookmark))
                h2_titles.append(l[3:].strip())

            elif l.startswith("### "):  # H3
                flush_buffer(); flush_list()
                story.append(Paragraph(l[4:], styles["ChineseHeading3"]))

            elif l.startswith("## 學習路徑"):
                flush_buffer(); flush_list()
                story.append(Paragraph("學習路徑", styles["ChineseHeading3"]))
                in_learning = True; learning_items = []

            elif in_learning and re.match(r"^\d+\.\s+", l):
                learning_items.append(re.sub(r"^\d+\.\s+", "", l).strip())

            elif l.startswith("> "):
                flush_buffer(); flush_list()
                story.append(Paragraph(convert_markdown_links(l[2:]), styles["Quote"]))

            elif l.startswith("- "):
                flush_buffer(); list_buffer.append(l[2:])

            else:
                buffer.append(l)

        if in_learning: flush_learning()
        flush_buffer(); flush_list()
        # 🔥 每篇文章後換頁
        story.append(PageBreak())

    # === 目錄頁放在封面後 ===
    toc_page = [Paragraph("目錄", ParagraphStyle(
        "TOCHeading",
        fontName="Biaokai",
        fontSize=20,
        leading=24,
        textColor=PRIMARY_COLOR,
        spaceAfter=12
    ))]
    for title, bookmark in toc_entries:
        toc_page.append(Paragraph(f'<link href="#{bookmark}">{title}</link>', styles["TOCItem"]))
    story[1:1] = toc_page  # 插入封面後（成為第二頁）

    # === 輸出 title.txt ===
    with open("title.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(h2_titles))
    print(f"📝 已輸出所有 H2 標題到 title.txt，共 {len(h2_titles)} 筆")

    # === 建立 PDF ===
    doc = SimpleDocTemplate(
        output_file, pagesize=A4,
        rightMargin=24, leftMargin=24,
        topMargin=36, bottomMargin=36
    )
    doc.build(story, onFirstPage=add_page_number_with_bg, onLaterPages=add_page_number_with_bg)
    print(f"✅ 已輸出 PDF：{output_file}")


if __name__ == "__main__":
    today_str = datetime.today().strftime("%Y%m%d")
    md_filename = f"news_report_{today_str}.md"
    pdf_filename = f"news_summary_{today_str}.pdf"
    md_to_pdf(md_filename, pdf_filename)
    print(f"✅ PDF 已完成：{pdf_filename}")
