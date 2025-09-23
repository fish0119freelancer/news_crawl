# fetch_articles.py (RSS 版本)
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import warnings
from bs4 import XMLParsedAsHTMLWarning

# 關閉 XML parser 警告
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# 共用 session + retry 機制
session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))

# RSS feed URL (Nature Biomedical Engineering)
RSS_URL = "http://feeds.nature.com/natbiomedeng/rss/current"

# 解析 RSS pubDate
def parse_rss_date(date_str: str) -> datetime:
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d"  # 有些 <dc:date> 可能只有日期
    ):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"無法解析日期格式：{date_str}")

# 從 RSS 抓取「當天」文章
from datetime import timedelta

def fetch_today_from_rss(rss_url=RSS_URL):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}
    resp = session.get(rss_url, headers=headers, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "xml")
    items = soup.find_all("item")
    
    # 改用當地時間（台北），並允許昨天+今天
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)

    articles = []
    for item in items:
        link = item.find("link").get_text(strip=True) if item.find("link") else None
        title = item.find("title").get_text(strip=True) if item.find("title") else "(無標題)"
        description = item.find("description").get_text(strip=True) if item.find("description") else ""
        pub_date_tag = item.find("pubDate") or item.find("dc:date")

        if not link or not pub_date_tag:
            continue

        try:
            pub_dt = parse_rss_date(pub_date_tag.get_text(strip=True))
            # 允許昨天或今天
            if pub_dt.date() in (today, yesterday):
                articles.append({
                    "title": title,
                    "summary": description,
                    "publish_date": pub_dt.isoformat(),
                    "url": link
                })
        except Exception:
            continue

    return articles


if __name__ == "__main__":
    results = fetch_today_from_rss()
    if not results:
        print("今天沒有找到新文章")
    else:
        for art in results:
            print(f"📌 {art['title']} ({art['publish_date']})")
            print(f"摘要: {art['summary']}")
            print(f"連結: {art['url']}\n")
