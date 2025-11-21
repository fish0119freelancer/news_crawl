# main.py
# RSS + 關鍵字篩選(可開關) + 領域分組 + 每領域最多5篇 + LLM 摘要 + PDF (含可點擊目錄)
import json
import os
import re
from datetime import datetime
from pathlib import Path

from summarize_with_llm import generate_news_summary_and_opinion, llm_batch_summarize
from report_generator import format_report
from fetch_articles import fetch_today_from_rss
from generate_pdf_summary import md_to_pdf

# ====== FLAG：是否啟用關鍵字篩選 ======
USE_KEYWORDS = True   # True 啟用關鍵字篩選，False 全部文章都會處理
MAX_PER_DOMAIN = 5    # 每個領域最多處理幾篇

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
    # 微生物 / 微生態
    "microbiology", "microbiome", "microbial", "microbiota", "gut microbiota", "metagenomic", "metagenomics",
    "probiotic", "probiotics", "antibiotic resistance", "AMR", "bacteria", "bacterial", "fungi", "fungus", "mycobiome",
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

FLEX_TITLE_PATTERN = re.compile(r"^##\s+(.+)", flags=re.MULTILINE)


def extract_flex_title(markdown_block: str, fallback: str) -> str:
    match = FLEX_TITLE_PATTERN.search(markdown_block or "")
    if match:
        return match.group(1).strip()
    return fallback.strip()

# ====== 領域定義 ======
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
    "microbe": [
        "microbiology", "microbiome", "microbial", "microbiota", "gut microbiota",
        "metagenomic", "metagenomics", "probiotic", "probiotics", "antibiotic resistance",
        "amr", "bacteria", "bacterial", "fungi", "fungus", "mycobiome"
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
DOMAIN_NAME = {
    "signal": "生理訊號 / 醫療裝置",
    "extracellular": "外泌體 / 精準醫療",
    "neuro": "神經科學 / 心理學",
    "ai": "AI / 數據分析",
    "microbe": "微生物 / 微生態",
    "industry": "產業趨勢 / 法規",
    "basicbio": "生科基礎研究",
    "other": "其他"
}

def classify_domain(text: str) -> str:
    t = text.lower()
    for domain, kws in DOMAIN_MAP.items():
        if any(k.lower() in t for k in kws):
            return domain
    return "other"

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

# ===== 分領域收集 =====
domain_articles: dict[str, list[dict]] = {d: [] for d in DOMAIN_MAP}
domain_articles["other"] = []

for idx, url in enumerate(urls, 1):
    try:
        print(f"\n📡 [{idx}/{total_sources}] 掃描來源：{url}")
        today_articles = fetch_today_from_rss(url)
        if not today_articles:
            print(f"⚠️ 今日無新文章：{url}")
            continue

        print(f"📰 發現 {len(today_articles)} 篇新文章")
        for i, article in enumerate(today_articles, 1):
            try:
                if "text" not in article:
                    article["text"] = article.get("summary", "")

                ok, hits = article_match(article)
                if not ok:
                    skipped_by_keyword += 1
                    print(f"  ⏭️ 關鍵字未命中：{article.get('title','(無標題)')}")
                    continue

                fulltext = " ".join([
                    article.get("title",""),
                    article.get("summary",""),
                    article.get("text","")
                ])
                domain = classify_domain(fulltext)
                domain_articles.setdefault(domain, []).append(article)
                print(f"  ✅ 收錄文章：{article['title']} → {domain}")
                success_count += 1

            except Exception as article_err:
                print(f"  ❌ 文章處理失敗：{article.get('title','(無標題)')} → {article_err}")
                fail_count += 1

        success_sources += 1

    except Exception as source_err:
        print(f"❌ 來源處理失敗：{url} → {source_err}")
        fail_count += 1

# ===== 按領域輸出 Markdown =====
flex_records: list[dict[str, str]] = []
seen_flex_urls: set[str] = set()
with open(md_filename, "w", encoding="utf-8") as f:
    for domain, articles in domain_articles.items():
        if not articles:
            continue
        selected = articles[:MAX_PER_DOMAIN]
        f.write(f"# {DOMAIN_NAME.get(domain, domain)}-------\n\n")
        for article in selected:
            try:
                summary_and_opinion = generate_news_summary_and_opinion(article)
                report = format_report(article, summary_and_opinion)
                f.write(report + "\n\n" + "-" * 88 + "\n\n")
                print(f"🖋️ 產生 {domain} 文章報告：{article.get('title','(無標題)')}")

                url = article.get("url") or article.get("link") or ""
                original_title = (article.get("title") or "").strip() or "(無標題)"
                flex_title = extract_flex_title(report, original_title)
                if url and url not in seen_flex_urls:
                    entry = {
                        "title": flex_title,
                        "url": url,
                        "domain": DOMAIN_NAME.get(domain, domain),
                    }
                    image_url = (article.get("image_url") or "").strip()
                    if image_url:
                        entry["image_url"] = image_url
                    flex_records.append(entry)
                    seen_flex_urls.add(url)
            except Exception as e:
                print(f"⚠️ 產生 {domain} 文章失敗：{article.get('title','(無標題)')} → {e}")
                continue

# ===== 儲存 Flex 資料 =====
flex_json_path = Path("flex_articles.json")
flex_txt_path = Path("flex_urls.txt")
if flex_records:
    flex_json_path.write_text(
        json.dumps(flex_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with open(flex_txt_path, "w", encoding="utf-8") as flex_txt:
        for item in flex_records:
            flex_txt.write(
                "\t".join(
                    [
                        item.get("domain", ""),
                        item.get("title", ""),
                        item.get("url", ""),
                        item.get("image_url", ""),
                    ]
                )
                + "\n"
            )
    print(f"💾 已更新 {flex_json_path.name} 與 {flex_txt_path.name}")
else:
    flex_json_path.unlink(missing_ok=True)
    flex_txt_path.unlink(missing_ok=True)
    print("ℹ️ 今日無 Flex 資料可供儲存")

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

