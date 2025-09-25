from openai import OpenAI
import os

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
# 單篇文章處理
def generate_news_summary_and_opinion(article):
    prompt = f"""
你是一位「生醫跨領域提倡者」，需要幫助讀者快速理解最新生醫/醫工文章。

請針對以下文章資訊，生成一則新聞解讀，並嚴格包含五個部分，格式如下：
# 標題
(須將原文標題轉為繁體中文)

## 摘要
(以原來文章內容的方式做翻譯，適當分段，並保留專有名詞)

## 導讀
（以初學者角度，淺白解釋，但保留專有名詞，並在括號內補充簡單定義）

## 學習路徑
請用「A → B → C → …」的箭頭格式，設計出一條從基礎到進階的知識學習順序。
每個節點應該是可查詢的關鍵詞或學科領域，幫助讀者能自學找到資源。

## 原文連結
[點擊這裡閱讀原文]({article.get('url', '')})

---
文章標題：{article['title']}
文章內容：{article['text']}
文章網址：{article.get('url', '')}
"""

    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4
    )
    return res.choices[0].message.content.strip()


# 批次處理：避免爆 token
def llm_batch_summarize(paragraphs, batch_size=1):
    """
    將多篇文章逐一摘要 → 合併成總結
    paragraphs: list[str] 或 list[dict]
    """
    summaries = []

    for i, para in enumerate(paragraphs, 1):
        # 如果傳進來是 dict，取 text
        text = para["text"] if isinstance(para, dict) else para
        text = text[:4000]  # 安全切斷，避免單篇過長

        prompt = f"""
你是一位「生醫跨領域提倡者」，請幫我濃縮以下文章重點，輸出 1 段「精簡摘要」即可：
{text}
"""
        res = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4
        )
        summary = res.choices[0].message.content.strip()
        summaries.append(summary)

    # 最後合併所有摘要，再產出總結
    combined = "\n\n".join(summaries)
    final_prompt = f"""
以下是多篇生醫文章的精簡摘要，請整合成一份「每日生醫新聞報告」，
並維持 Markdown 格式，為每篇文章生成：

1. 標題  
2. 摘要  
3. 導讀（淺白解讀）  
4. 學習路徑（知識地圖）  
5. 原文連結  

以下是多篇摘要：
{combined}
"""

    res = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": final_prompt}],
        temperature=0.4
    )

    return res.choices[0].message.content.strip()

if __name__ == "__main__":
    from generate_pdf_summary import extract_references_from_md, generate_pdf

    # 讀取清理後的文章
    cleaned_paragraphs, references = extract_references_from_md("news_report.md")

    # 避免一次爆掉，改成分批處理
    # print(f"🔍 共 {len(cleaned_paragraphs)} 篇文章，開始分批摘要...")
    # final_summary = llm_batch_summarize(cleaned_paragraphs)

    # 輸出 PDF
    generate_pdf(cleaned_paragraphs, references)
    print("✅ PDF 已完成：news_summary.pdf")
