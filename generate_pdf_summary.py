import os
import re
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors

# ========= 字體設定 =========
FONT_CHINESE = "./NotoSansTC-VariableFont_wght.ttf"  # 可換成 NotoSansTC.ttf
FONT_ENGLISH = "./Times New Roman.ttf"

if not os.path.exists(FONT_CHINESE):
    raise FileNotFoundError(f"❌ 找不到中文字體：{FONT_CHINESE}")
if not os.path.exists(FONT_ENGLISH):
    raise FileNotFoundError(f"❌ 找不到英文字體：{FONT_ENGLISH}")

pdfmetrics.registerFont(TTFont("NotoSansTC", FONT_CHINESE))
pdfmetrics.registerFont(TTFont("TimesNewRoman", FONT_ENGLISH))

# ========= 樣式設定 =========
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="ChineseHeading1", fontName="NotoSansTC", fontSize=18, leading=22, spaceAfter=12, spaceBefore=12))
styles.add(ParagraphStyle(name="ChineseHeading2", fontName="NotoSansTC", fontSize=16, leading=20, spaceAfter=10, leftIndent=12))
styles.add(ParagraphStyle(name="ChineseHeading3", fontName="NotoSansTC", fontSize=14, leading=18, spaceAfter=8, leftIndent=24))
styles.add(ParagraphStyle(name="ChineseBody", fontName="NotoSansTC", fontSize=12, leading=16, spaceAfter=8))
styles.add(ParagraphStyle(name="Quote", fontName="NotoSansTC", fontSize=12, leading=16, leftIndent=20, spaceAfter=8, textColor="gray"))
styles.add(ParagraphStyle(name="Link", fontName="TimesNewRoman", fontSize=12, leading=16, textColor=colors.blue, underline=True))
styles.add(ParagraphStyle(name="LearningPath", fontName="NotoSansTC", fontSize=12, leading=18, textColor=colors.darkblue, spaceAfter=10))

# ========= Markdown 超連結轉換 =========
def convert_markdown_links(text: str) -> str:
    """把 [文字](url) → <a href="url">文字</a>"""
    return re.sub(r"\[(.*?)\]\((.*?)\)", r'<a href="\2">\1</a>', text)

# ========= Markdown 轉 PDF =========
def md_to_pdf(md_file, output_file="news_report.pdf"):
    story = []
    with open(md_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    buffer = []      # 暫存一般段落
    list_buffer = [] # 暫存清單
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
            text = " ➝ ".join(learning_items)
            story.append(Paragraph(text, styles["LearningPath"]))
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

        elif in_learning_path and re.match(r"^\d+\.\s+", line):  # 學習路徑清單
            item = re.sub(r"^\d+\.\s+", "", line).strip()
            learning_items.append(item)

        elif line.startswith("### "):  # 小標題
            flush_buffer()
            flush_list()
            story.append(Paragraph(line[4:], styles["ChineseHeading3"]))
        elif line.startswith("## "):  # 中標題
            flush_buffer()
            flush_list()
            story.append(Paragraph(line[3:], styles["ChineseHeading2"]))
        elif line.startswith("# "):  # 大標題
            flush_buffer()
            flush_list()
            story.append(Paragraph(line[2:], styles["ChineseHeading1"]))
        elif line.startswith("> "):  # 引用
            flush_buffer()
            flush_list()
            story.append(Paragraph(convert_markdown_links(line[2:]), styles["Quote"]))
        elif line.startswith("- "):  # 無序清單
            flush_buffer()
            list_buffer.append(line[2:])
        else:
            buffer.append(line)

    # 收尾
    if in_learning_path:
        flush_learning_path()
    flush_buffer()
    flush_list()

    # 輸出 PDF
    doc = SimpleDocTemplate(output_file, pagesize=A4)
    doc.build(story)
    print(f"✅ 已輸出 PDF：{output_file}")


if __name__ == "__main__":
    md_to_pdf("news_report.md")
