import hashlib
import json
import logging
import os
import re

import cost_guard

# DRY_RUN=1：不呼叫 LLM（不需 key、不花錢），回傳罐頭摘要，用來驗證整條管線
DRY_RUN = os.getenv("DRY_RUN") == "1"

_client = None
_anthropic_client = None


class FatalSummaryError(RuntimeError):
    """認證或權限等致命 API 錯誤，應立即停止後續呼叫。"""


def get_anthropic_client():
    """Lazy getter for Anthropic client; reads key only from ANTHROPIC_API_KEY env var."""
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client
    try:
        api_key = os.environ["ANTHROPIC_API_KEY"]
    except KeyError:
        raise RuntimeError("ANTHROPIC_API_KEY not set") from None
    if not api_key or not api_key.strip():
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    import anthropic

    _anthropic_client = anthropic.Anthropic(
        api_key=api_key,
        max_retries=2,
        timeout=60.0,
    )
    return _anthropic_client


def get_openai_client():
    """Lazy getter for OpenAI client; avoids importing openai or requiring API key on module load."""
    global _client
    if "client" in globals() and globals()["client"] is not None:
        return globals()["client"]
    if _client is not None:
        return _client
    from openai import OpenAI

    _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


get_client = get_openai_client


def __getattr__(name):
    if name == "client":
        return get_openai_client()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def extract_score_from_response(response_text: str) -> float:
    """從 LLM 回應中提取評分（1-10）"""
    # 嘗試匹配 "### 評分" 區塊中的數字
    patterns = [
        r"###\s*評分[：:\s]*(\d+(?:\.\d+)?)",
        r"評分[：:\s]*(\d+(?:\.\d+)?)",
        r"⭐\s*(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, response_text)
        if match:
            score = float(match.group(1))
            return min(max(score, 1.0), 10.0)  # 確保在 1-10 範圍內
    return 5.0  # 預設分數


def build_prompt(article: dict) -> str:
    """建構生醫新聞解讀的 prompt 字串"""
    title = article.get("title", "")
    text = article.get("text", "")
    url = article.get("url", "")
    return f"""
你是一位「生醫跨領域提倡者」，需要幫助讀者快速理解最新生醫/醫工文章。

請針對以下文章資訊，生成一則新聞解讀，並**嚴格遵守格式要求**：

## [繁體中文標題放在這一行，不要換行]

### 評分
請根據以下標準綜合評估，給出 1-10 分（必須有區分度，不要全部給類似的分數）：
- **新穎程度** (1-10)：這個研究方法或發現有多創新？是漸進式改良還是突破性進展？
- **有趣程度** (1-10)：這個研究對一般大眾來說有多吸引人？是否容易引起興趣？
- **實用程度** (1-10)：這個研究多快能應用於實際場景？是純理論還是有臨床/產業價值？

綜合評分計算：(新穎 + 有趣 + 實用) / 3，取一位小數
格式：⭐ X.X 分

### 摘要
（3-5句話總結文章的核心發現與結論，不做過多解釋，保留專有名詞）

### 這篇在說什麼？
（用生活化的比喻或類比，讓完全沒背景的人也能理解這篇研究的意義。例如：「就像是...」）

### 學習路徑
請用「A → B → C → …」的箭頭格式，設計出一條從基礎到進階的知識學習順序。
每個節點應該是可查詢的關鍵詞或學科領域，幫助讀者能自學找到資源。

### 原文連結
[點擊連結]({url})

---
文章標題：{title}
文章內容：{text}
文章網址：{url}
"""


def _call_anthropic(prompt: str, article: dict) -> str:
    """透過官方 Anthropic SDK 呼叫 Claude Haiku 5.5 產生摘要。"""
    # BudgetExceeded 必須原樣往外拋出，不可吞掉
    cost_guard.guard.before_call(prompt)

    import anthropic

    url = article.get("url", "")
    client = get_anthropic_client()
    model = os.getenv("SUMMARY_MODEL", cost_guard.MODEL)
    max_tokens = cost_guard.guard.max_tokens

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        err_type = type(e).__name__
        status_code = getattr(e, "status_code", None)
        err_msg = getattr(e, "message", "")
        logging.error(
            "Anthropic auth/permission error: type=%s status=%s message=%s",
            err_type,
            status_code,
            err_msg,
        )
        raise FatalSummaryError(
            f"summary failed for URL {url}: {err_type}/{status_code}"
        ) from None
    except anthropic.APIStatusError as e:
        err_type = type(e).__name__
        status_code = getattr(e, "status_code", None)
        err_msg = getattr(e, "message", "")
        logging.error(
            "Anthropic API status error: type=%s status=%s message=%s",
            err_type,
            status_code,
            err_msg,
        )
        raise RuntimeError(
            f"summary failed for URL {url}: {err_type}/{status_code}"
        ) from None
    except anthropic.APIConnectionError as e:
        err_type = type(e).__name__
        logging.error("Anthropic API connection error: type=%s", err_type)
        raise RuntimeError(f"summary failed for URL {url}: {err_type}") from None

    stop_reason = getattr(response, "stop_reason", None)
    if stop_reason in ("max_tokens", "refusal"):
        logging.error(
            "Anthropic summary rejected for URL %s: stop_reason=%s",
            url,
            stop_reason,
        )
        raise RuntimeError(
            f"summary failed for URL {url}: stop_reason={stop_reason}"
        )

    blocks = getattr(response, "content", None) or []
    text_parts = [
        block.text
        for block in blocks
        if getattr(block, "type", None) == "text"
        and isinstance(getattr(block, "text", None), str)
        and block.text.strip()
    ]
    if not text_parts:
        logging.error("Anthropic summary empty for URL %s", url)
        raise RuntimeError(f"summary failed for URL {url}: empty text response")

    usage = getattr(response, "usage", None)
    usage_in = getattr(usage, "input_tokens", 0) if usage is not None else 0
    usage_out = getattr(usage, "output_tokens", 0) if usage is not None else 0
    cost_guard.guard.record(usage_in, usage_out)

    return "\n".join(text_parts).strip()


def _call_openai(prompt: str) -> str:
    """呼叫 OpenAI gpt-4o 產生摘要（fallback）"""
    client = get_openai_client()
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
    )
    return res.choices[0].message.content.strip()


# 單篇文章處理
def generate_news_summary_and_opinion(article: dict) -> str:
    is_dry_run = (os.getenv("DRY_RUN") == "1") if "DRY_RUN" in os.environ else DRY_RUN
    if is_dry_run:
        return (
            f"## [DRY RUN] {article.get('title', '(無標題)')}\n\n"
            "### 評分\n⭐ 5.0 分\n\n### 摘要\n（乾跑，未呼叫 LLM）\n\n"
            "### 這篇在說什麼？\n（乾跑）\n\n### 學習路徑\nA → B → C\n\n"
            f"### 原文連結\n[點擊連結]({article.get('url', '')})\n"
        )

    cache_dir = os.getenv("SUMMARY_CACHE_DIR", ".cache/summaries")
    url = (article.get("url") or "").strip()
    key_source = url if url else (article.get("title") or "").strip()
    cache_key = hashlib.sha256(key_source.encode("utf-8")).hexdigest()
    cache_file = os.path.join(cache_dir, f"{cache_key}.json")

    # 快取檢查（命中不呼叫 guard、不計篇數）
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                if isinstance(cached_data, dict) and "summary" in cached_data:
                    return cached_data["summary"]
        except Exception as e:
            logging.warning("Failed to read cache file %s: %s", cache_file, e)

    # 產生摘要
    prompt = build_prompt(article)
    backend = os.getenv("SUMMARY_BACKEND", "anthropic").lower()

    if backend == "openai":
        summary = _call_openai(prompt)
    else:
        summary = _call_anthropic(prompt, article)

    # 寫入快取（僅成功時）
    try:
        os.makedirs(cache_dir, exist_ok=True)
        cache_content = {
            "url": article.get("url", ""),
            "summary": summary,
        }
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache_content, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning("Failed to write cache file %s: %s", cache_file, e)

    return summary


# 批次處理：避免爆 token
def llm_batch_summarize(paragraphs, batch_size=1):
    """
    將多篇文章逐一摘要 → 合併成總結
    每日流程不使用；若啟用需改用 Anthropic
    paragraphs: list[str] 或 list[dict]
    """
    summaries = []
    client = get_openai_client()

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
            temperature=0.4,
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
        temperature=0.4,
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
