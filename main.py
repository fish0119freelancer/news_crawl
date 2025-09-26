# main.py
# RSS + 關鍵字篩選(可開關) + 領域分組 + 每領域最多5篇 + LLM 摘要 + PDF
import os
import re
from datetime import datetime
from pathlib import Path

from summarize_with_llm import generate_news_summary_and_opinion, llm_batch_summarize
from report_generator import format_report
from fetch_articles import fetch_today_from_rss
from generate_pdf_summary import md_to_pdf

# ====== FLAG：是否啟用關鍵字篩選 ======
USE_KEYWORDS = True   # ← True 啟用關鍵字篩選，False 全部文章都會處理

# ====== FLAG：每個領域最多處理幾篇 ======
MAX_PER_DOMAIN = 5

# ====== 關鍵字設定（可用 keywords.txt 覆蓋） ======
DEFAULT_KEYWORDS = [
    # 生理訊號 / 醫療裝置
    "biomedical signal", "biosignal", "ECG", "EEG", "EMG", "PPG", "rPPG", "BCG", "stethoscope", "heart sound",
    "wearable", "wearable device", "smart wearable", "medical device", "biosensor", "sensor fusion",

    # 外泌體 / 精準醫療
    "extracellular vesicle", "extracellular vesicles", "exosome", "exosomes",
    "liquid biopsy", "circulating nucleic acid", "circulating tumor DNA", "ctDNA",

    # 神經科學 / 心理學
    "neuroscience", "brain", "brain-computer interface", "BCI", "neurotechnology",
    "cognitive neuroscience", "neuroimaging", "EEG-based", "fMRI", "psychology", "behavioral science",
    "mental health", "psychiatry",

    # AI / 數據分析
    "artificial intelligence", "machine learning", "deep learning", "computer vision", "medical imaging",
    "medical AI", "signal processing", "digital health", "telemedicine", "remote monitoring",

    # 產業趨勢 / 法規
    "medtech", "healthtech", "biotech", "precision medicine", "regulatory", "FDA", "MDR", "TFDA",
    "CE mark", "market analysis",

    # 生科基礎研究
    "cell biology", "molecular biology", "genetics", "genomics", "proteomics", "transcriptomics",
    "epigenetics", "immunology", "stem cell", "cancer biology", "developmental biology", "metabolism", "biochemistry",
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
    if not USE_KEYWORDS:
        return True, []
    text = " ".join([
        article.get("title", "") or "",
        article.get("summary", "") or "",
        article.get("text", "") or "",
        " ".join(article.get("categories", []) or [])
    ])
    hits = keyword_hits(text)
    if KEYWORD_MODE == "AND":
        ok = all(any(h.lower() == kw.lower() for h in hits) for kw in KEYWORDS)
    else:
        ok = len(hits) > 0
    return ok, hits

# ====== 領域分組（每組最多 MAX_PER_DOMAIN 篇） ======
DOMAIN_MAP = {
    "signal": [
        "biomedical signal", "biosignal", "ECG", "EEG", "EMG", "PPG", "rPPG", "BCG",
        "stethoscope", "heart sound", "wearable", "wearable device", "smart wearable",
        "medical device", "biosensor", "sensor fusion"
    ],
    "extracellular": [
        "extracellular vesicle", "extracellular vesicles", "exosome", "exosomes",
        "liquid biopsy", "circulating nucleic acid", "circulating tumor DNA", "ctDNA"
    ],
    "neuro": [
        "neuroscience", "brain", "brain-computer interface", "BCI", "neurotechnology",
        "cognitive neuroscience", "neuroimaging", "EEG-based", "fMRI",
        "psychology", "behavioral science", "mental health", "psychiatry"
    ],
    "ai": [
        "artificial intelligence", "machine learning", "deep learning", "computer vision",
        "medical imaging", "medical AI", "signal processing", "digital health",
        "telemedicine", "remote monitoring"
    ],
    "industry": [
        "medtech", "healthtech", "biotech", "precision medicine", "regulatory",
        "FDA", "MDR", "TFDA", "CE mark", "market analysis"
    ],
    "basicbio": [
        "cell biology", "molecular biology", "genetics", "genomics", "proteomics",
        "transcriptomics", "epigenetics", "immunology", "stem cell", "cancer biology",
        "developmental biology", "metabolism", "biochemistry"
    ]
}

def classify_domain(text: str) -> str:
    t = text.lower()
    for domain, kws in DOMAIN_MAP.items():
        if any(k.lower() in t for k in kws):
            return domain
    return "other"

domain_count = {d: 0 for d in DOMAIN_MAP}

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
print(f"⚖️ 每個領域最多處理 {MAX_PER_DOMAIN} 篇文章")

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

                # 分類領域並檢查數量限制
                fulltext = " ".join([article.get("title",""), article.get("summary",""), article.get("text","")])
                domain = classify_domain(fulltext)
                if domain in domain_count and domain_count[domain] >= MAX_PER_DOMAIN:
                    print(f"  🚫 {article.get('title')} 已達 {domain} 上限 {MAX_PER_DOMAIN}")
                    continue

                print(f"  ⏳ [{i}/{len(today_articles)}] 處理文章：{article['title']} ｜🎯 命中：{', '.join(hits[:6])}{'…' if len(hits) > 6 else ''}")
                summary_and_opinion = generate_news_summary_and_opinion(article)
                report = format_report(article, summary_and_opinion)

                with open(md_filename, "a", encoding="utf-8") as f:
                    f.write(report + "\n\n" + "-"*90 + "\n\n")

                success_count += 1
                source_success += 1
                if domain in domain_count:
                    domain_count[domain] += 1

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
