# fetch_articles.py (RSS 版本 + 封面圖)
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import warnings
from bs4 import XMLParsedAsHTMLWarning
import re

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# 共用 session + retry 機制
session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retries))

RSS_URL = "http://feeds.nature.com/natbiomedeng/rss/current"

def parse_rss_date(date_str: str) -> datetime:
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d"
    ):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"無法解析日期格式：{date_str}")

def extract_image_from_item(item):
    """從 RSS <item> 嘗試抓封面圖 URL"""
    # 1. <media:content>
    media = item.find("media:content")
    if media and media.get("url"):
        return media.get("url")

    # 2. <enclosure>
    enclosure = item.find("enclosure")
    if enclosure and enclosure.get("url") and "image" in (enclosure.get("type") or ""):
        return enclosure.get("url")

    # 3. <image>
    image = item.find("image")
    if image and image.get_text(strip=True):
        return image.get_text(strip=True)

    # 4. <description> 或 <content:encoded> 中的 <img src="...">
    desc = item.find("description")
    content = item.find("content:encoded")
    html_source = ""
    if desc: html_source += desc.get_text()
    if content: html_source += content.get_text()
    if html_source:
        match = re.search(r'<img[^>]+src=["\'](.*?)["\']', html_source)
        if match:
            return match.group(1)

    return None

def fetch_today_from_rss(rss_url=RSS_URL):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; NewsBot/1.0)"}
    resp = session.get(rss_url, headers=headers, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "xml")
    items = soup.find_all("item")
    
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)

    articles = []
    for item in items:
        link = item.find("link").get_text(strip=True) if item.find("link") else None
        title = item.find("title").get_text(strip=True) if item.find("title") else "(無標題)"
        description = item.find("description").get_text(strip=True) if item.find("description") else ""
        pub_date_tag = item.find("pubDate") or item.find("dc:date")
        image_url = extract_image_from_item(item)

        if not link or not pub_date_tag:
            continue

        try:
            pub_dt = parse_rss_date(pub_date_tag.get_text(strip=True))
            if pub_dt.date() in (today, yesterday):
                articles.append({
                    "title": title,
                    "summary": description,
                    "publish_date": pub_dt.isoformat(),
                    "url": link,
                    "image_url": image_url
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
            print(f"連結: {art['url']}")
            print(f"封面圖: {art['image_url']}\n")
