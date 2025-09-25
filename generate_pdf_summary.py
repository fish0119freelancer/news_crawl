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

pdfmetrics.registerFont(TTFont("Biaokai", FONT_CHINESE, subfontIndex=0))
pdfmetrics.registerFont(TTFont("TimesNewRoman", FONT_ENGLISH))

# ========= 顏色設定 =========
PRIMARY_COLOR = colors.HexColor("#0A3D62")     # 深藍
SECONDARY_COLOR = colors.HexColor("#3C6382")  # 灰藍
HIGHLIGHT_COLOR = colors.HexColor("#60A3BC")  # 淺藍
ACCENT_COLOR = colors.HexColor("#F8C291")     # 橘色

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
    """
    校正 LLM 產出的 markdown 標題層級：
    - 第一行標題用 H1 (#)
    - 新聞摘要、產業解讀、給新人的補充導讀、原文連結 → H2 (##)
    """
    corrected = []
    section_h2 = ["新聞摘要", "產業解讀", "給新人的補充導讀", "原文連結"]

    for i, line in enumerate(lines):
        stripped = line.strip()

        # 跳過空行
        if not stripped:
            corrected.append(line)
            continue

        # 第一個非空行 → 強制 H1
        if i == 0 and stripped.startswith("#"):
            corrected.append("# " + stripped.lstrip("# ").strip() + "\n")
            continue

        # 檢查是否是關鍵 section
        if any(stripped.lstrip("# ").startswith(sec) for sec in section_h2):
            corrected.append("## " + stripped.lstrip("# ").strip() + "\n")
            continue

        # 其他行保持原樣
        corrected.append(line)

    return corrected

def convert_markdown_links(text: str) -> str:
    return re.sub(r"\[(.*?)\]\((.*?)\)", r'<a href="\2">\1</a>', text)

def add_page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont("Biaokai", 9)
    canvas.setFillColor(SECONDARY_COLOR)

    # 頁眉
    canvas.drawString(20 * mm, 285 * mm, "律芯科技｜汽車產業動向分析報告")
    canvas.drawRightString(200 * mm, 285 * mm, "steadybeat.com")

    # 頁腳（頁碼）
    canvas.setFillColor(colors.grey)
    canvas.drawRightString(200 * mm, 15 * mm, f"第 {doc.page} 頁")
    canvas.restoreState()

def build_cover(title, subtitle):
    cover = []

    # ===== 上方藍色橫條 =====
    top_bar = Table([[""]], colWidths=[460], rowHeights=[30])
    top_bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PRIMARY_COLOR),
    ]))
    cover.append(top_bar)
    cover.append(Spacer(1, 40))

    # ===== Logo =====
    try:
        logo = Image("logo.png", width=492, height=90)
        logo.hAlign = "CENTER"
        cover.append(logo)
        cover.append(Spacer(1, 20))
    except Exception as e:
        print(f"⚠️ 無法載入 logo.png：{e}")

    # ===== 公司名稱、標題、副標題 =====
    cover.append(Paragraph("律芯科技", styles["ReportSubtitle"]))
    cover.append(Spacer(1, 10))
    cover.append(Paragraph(title, styles["ReportTitle"]))
    cover.append(Paragraph(subtitle, styles["ReportSubtitle"]))
    cover.append(Spacer(1, 40))

    # ===== 日期 =====
    cover.append(Paragraph(f"產出日期：{datetime.now().strftime('%Y/%m/%d')}", styles["ChineseBody"]))
    cover.append(Spacer(1, 200))

    # ===== 底部公司資訊灰條 =====
    bottom_bar = Table(
        [[Paragraph("律芯科技 ｜ steadybeat.com", styles["ChineseBody"])]],
        colWidths=[460], rowHeights=[25]
    )
    bottom_bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.lightgrey),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TEXTCOLOR", (0, 0), (-1, -1), PRIMARY_COLOR),
    ]))
    cover.append(bottom_bar)

    cover.append(PageBreak())
    return cover

def styled_heading(text):
    tbl = Table(
        [[Paragraph(text, ParagraphStyle(
            "HeadingInBox",
            parent=styles["ChineseHeading1"],
            textColor=colors.HexColor("#D4AF37"),  # 金色文字
            fontSize=20,
            leading=24
        ))]],
        colWidths=[460]
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#2C2C2C")),  # 深灰背景
        ("BOX", (0, 0), (-1, -1), 1.2, colors.HexColor("#1A1A1A")),   # 更深灰邊框
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return tbl


# ========= Markdown 轉 PDF 主流程 =========
def md_to_pdf(md_file, output_file="news_report.pdf"):
    story = []
    with open(md_file, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

        # 在這裡先校正
        lines = fix_markdown_headings(raw_lines)

    buffer, list_buffer = [], []
    in_learning_path = False
    learning_items = []

    def flush_buffer():
        nonlocal buffer
        if buffer:
            text = " ".join(buffer).strip()
            if text:
                text = convert_markdown_links(text)
                story.append(Paragraph(text, styles["ChineseBody"]))
                story.append(Spacer(1, 8))
            buffer = []

    def flush_list():
        nonlocal list_buffer
        if list_buffer:
            items = [ListItem(Paragraph(convert_markdown_links(it), styles["ChineseBody"])) for it in list_buffer]
            story.append(ListFlowable(items, bulletType="bullet"))
            story.append(Spacer(1, 8))
            list_buffer = []

    def flush_learning_path():
        nonlocal learning_items
        if learning_items:
            story.append(Paragraph("學習路徑：", styles["ChineseHeading3"]))
            items = [ListItem(Paragraph(it, styles["ChineseBody"])) for it in learning_items]
            story.append(ListFlowable(items, bulletType="bullet", leftIndent=20))
            story.append(Spacer(1, 8))
            learning_items = []

    for line in lines:
        line = line.strip()
        if not line:
            if in_learning_path:
                flush_learning_path()
                in_learning_path = False
            else:
                flush_buffer()
                flush_list()
            continue

        if line.startswith("## 學習路徑"):
            flush_buffer()
            flush_list()
            story.append(Paragraph("學習路徑", styles["ChineseHeading2"]))
            in_learning_path = True
            learning_items = []

        elif in_learning_path and re.match(r"^\d+\.\s+", line):
            item = re.sub(r"^\d+\.\s+", "", line).strip()
            learning_items.append(item)

        elif line.startswith("### "):
            flush_buffer()
            flush_list()
            story.append(Paragraph(line[4:], styles["ChineseHeading3"]))

        elif line.startswith("## "):
            flush_buffer()
            flush_list()
            story.append(Paragraph(line[3:], styles["ChineseHeading2"]))

        elif line.startswith("# "):
            flush_buffer()
            flush_list()
            story.append(styled_heading(line[2:]))

        elif line.startswith("> "):
            flush_buffer()
            flush_list()
            story.append(Paragraph(convert_markdown_links(line[2:]), styles["Quote"]))

        elif line.startswith("- "):
            flush_buffer()
            list_buffer.append(line[2:])

        else:
            buffer.append(line)

    if in_learning_path:
        flush_learning_path()
    flush_buffer()
    flush_list()

    # 加封面與輸出
    doc = SimpleDocTemplate(output_file, pagesize=A4,
                            rightMargin=24, leftMargin=24,
                            topMargin=36, bottomMargin=36)
    story = build_cover("汽車產業動向分析報告", "每日產業趨勢與觀點") + story
    doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)
    print(f"✅ 已輸出 PDF：{output_file}")

if __name__ == "__main__":
    md_to_pdf("news_report_20250924.md")
