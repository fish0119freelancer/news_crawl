# main.py (RSS 版 + 分段摘要)

from summarize_with_llm import generate_news_summary_and_opinion, llm_batch_summarize
from report_generator import format_report
from fetch_articles import fetch_today_from_rss
from generate_pdf_summary import md_to_pdf

# 讀取網址列表
with open("urls.txt", "r", encoding="utf-8") as f:
    urls = [line.strip() for line in f if line.strip()]

total_sources = len(urls)
total_articles = 0
success_count = 0
fail_count = 0

print(f"🔍 共 {total_sources} 個來源網站，開始掃描今天的新文章...")

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
                print(f"  ⏳ [{i}/{len(today_articles)}] 處理文章：{article['title']}")

                # RSS 抓回來只有 summary，補一個 text 給後續流程用
                if "text" not in article:
                    article["text"] = article.get("summary", "")

                summary_and_opinion = generate_news_summary_and_opinion(article)
                report = format_report(article, summary_and_opinion)

                with open("news_report.md", "a", encoding="utf-8") as f:
                    f.write(report + "\n\n---\n\n")

                print(f"  ✅ 成功：{article['title']}")
                success_count += 1
                total_articles += 1
            except Exception as article_err:
                print(f"  ❌ 文章處理失敗：{article['title']} → {article_err}")
                fail_count += 1

    except Exception as source_err:
        print(f"❌ 來源處理失敗：{url} → {source_err}")
        fail_count += 1

# 總結
print("\n📊 爬蟲完成")
print(f"✔️ 成功處理文章數：{success_count}")
print(f"❌ 失敗文章數：{fail_count}")
print(f"📄 成功來源總數：{total_sources - fail_count}／{total_sources}")


md_to_pdf("news_report.md")

print("✅ PDF 已完成：news_summary.pdf")
