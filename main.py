# main.py (RSS 版 + 關鍵字篩選可開關 + LLM 摘要 + PDF)
import os
import re
from datetime import datetime
from pathlib import Path

from summarize_with_llm import generate_news_summary_and_opinion, llm_batch_summarize
from report_generator import format_report
from fetch_articles import fetch_today_from_rss
from generate_pdf_summary import md_to_pdf

# ====== FLAG：是否啟用關鍵字篩選 ======
USE_KEYWORDS = False   # ← 直接改這個 True / False 就能切換

# ====== 關鍵字設定（可用 keywords.txt 覆蓋） ======
DEFAULT_KEYWORDS = [
    "智慧座艙", "smart cockpit", "smart cabin", "座艙", "cockpit",
    "infotainment", "IVI", "HMI", "车机", "車機", "中控", "語音助理", "車載語音",
    "AR-HUD", "HUD", "抬頭顯示", "儀表板", "中控屏", "多屏",
    "車用", "automotive", "in-vehicle", "domain controller", "車規", "SoC", "MCU",
    "以太網", "Ethernet", "LIN", "CAN", "CAN-FD", "MOST",
    "ADAS", "自動駕駛", "autonomous", "感測器", "雷達", "LiDAR", "毫米波", "超聲波",
    "攝影機", "camera", "融合", "sensor fusion",
    "車聯網", "V2X", "5G", "OTA", "FOTA", "SOTA", "SDV", "software-defined",
    "功能安全", "ISO 26262", "ASIL", "cybersecurity", "UN R155", "UN R156",
    "Qualcomm", "Snapdragon", "Cockpit", "NVIDIA", "Orin", "Drive", "Horizon Robotics",
    "地平線", "Ambarella", "Black Sesame", "黑芝麻", "瑞薩", "Renesas",
    "NXP", "TI", "Infineon", "MediaTek", "聯發科", "Samsung", "Intel", "AMD",
]

KEYWORDS_FILE = "keywords.txt"
KEYWORD_MODE = "OR"  # OR / AND


def load_keywords(path: str) -> list[str]:
    if Path(path).exists():
        with open(path, "r", encoding="utf-8") as f:
            kws = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
        if kws:
            return kws
    return DEFAULT_KEYWORDS


KEYWORDS = load_keywords(KEYWORDS_FILE)


def _word_boundary_pattern(kw: str) -> re.Pattern:
    if re.fullmatch(r"[A-Za-z0-9\-\+_/\.]+", kw):
        return re.compile(rf"\b{re.escape(kw)}\b", flags=re.IGNORECASE)
    return re.compile(re.escape(kw), flags=re.IGNORECASE)


KW_PATTERNS = [(_word_boundary_pattern(kw), kw) for kw in KEYWORDS]


def keyword_hits(text: str) -> list[str]:
    hits = []
    for pat, raw in KW_PATTERNS:
        if pat.search(text):
            hits.append(raw)
    return hits


def article_match(article: dict) -> tuple[bool, list[str]]:
    """檢查文章是否符合關鍵字"""
    if not USE_KEYWORDS:  # ← 不啟用篩選時直接全部通過
        return True, []

    title = article.get("title", "") or ""
    desc = article.get("summary", "") or ""
    body = article.get("text", "") or ""
    cats = " ".join(article.get("categories", []) or [])
    blob = " ".join([title, desc, body, cats]).lower()

    hits = keyword_hits(blob)
    if KEYWORD_MODE == "AND":
        ok = all(any(h.lower() == kw.lower() for h in hits) for kw in KEYWORDS)
    else:
        ok = len(hits) > 0
    return ok, hits


# ===== 初始化檔案與日期 =====
today_str = datetime.today().strftime("%Y%m%d")
md_filename = f"news_report_{today_str}.md"
pdf_filename = f"news_summary_{today_str}.pdf"

Path(md_filename).unlink(missing_ok=True)

# ===== 讀取 RSS URL =====
with open("urls.txt", "r", encoding="utf-8") as f:
    urls = [line.strip() for line in f if line.strip()]

total_sources = len(urls)
success_count = 0
fail_count = 0
success_sources = 0
skipped_by_keyword = 0

print(f"🔍 共 {total_sources} 個來源網站，開始掃描今天的新文章...")
if USE_KEYWORDS:
    print(f"🧲 關鍵字篩選：已啟用 ({KEYWORD_MODE})，關鍵字數量：{len(KEYWORDS)}")
else:
    print("🧲 關鍵字篩選：已停用，所有文章都會處理")

# ===== 主迴圈 =====
for idx, url in enumerate(urls, 1):
    try:
        print(f"\n📡 [{idx}/{total_sources}] 掃描來源：{url}")
        today_articles = fetch_today_from_rss(url)

        if not today_articles:
            print(f"⚠️ 今日無新文章：{url}")
            continue

        print(f"📰 發現 {len(today_articles)} 篇新文章")
        source_success = 0

        for i, article in enumerate(today_articles, 1):
            try:
                if "text" not in article:
                    article["text"] = article.get("summary", "")

                ok, hits = article_match(article)
                if not ok:
                    skipped_by_keyword += 1
                    print(f"  ⏭️ 關鍵字未命中：{article.get('title','(無標題)')}")
                    continue

                print(f"  ⏳ [{i}/{len(today_articles)}] 處理文章：{article['title']} ｜🎯 命中：{', '.join(hits[:6])}{'…' if len(hits) > 6 else ''}")

                summary_and_opinion = generate_news_summary_and_opinion(article)
                report = format_report(article, summary_and_opinion)

                with open(md_filename, "a", encoding="utf-8") as f:
                    f.write(report + "\n\n-----------------------------------------------------------------------------------------\n\n")

                print(f"  ✅ 成功：{article['title']}")
                success_count += 1
                source_success += 1

            except Exception as article_err:
                print(f"  ❌ 文章處理失敗：{article.get('title','(無標題)')} → {article_err}")
                fail_count += 1

        if source_success > 0:
            success_sources += 1

    except Exception as source_err:
        print(f"❌ 來源處理失敗：{url} → {source_err}")
        fail_count += 1

# ===== 統計報告 =====
print("\n📊 爬蟲完成")
print(f"✔️ 成功處理文章數：{success_count}")
if USE_KEYWORDS:
    print(f"⤴️ 關鍵字未命中而略過：{skipped_by_keyword}")
print(f"❌ 失敗文章數：{fail_count}")
print(f"📄 成功來源總數：{success_sources}／{total_sources}")

# ===== 產出 PDF =====
md_to_pdf(md_filename, pdf_filename)
print(f"✅ PDF 已完成：{pdf_filename}")
