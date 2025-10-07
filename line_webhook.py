import base64
import hmac
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from fetch_articles import fetch_today_from_rss
from line_flex_builder import build_carousel_message

app = FastAPI()

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
CHANNEL_TOKEN = os.getenv("LINE_CHANNEL_TOKEN", "")
MAX_ARTICLES = int(os.getenv("WEBHOOK_MAX_ARTICLES", "10"))

REPLY_ENDPOINT = "https://api.line.me/v2/bot/message/reply"
ARTICLE_CACHE: dict[str, list[dict[str, str]]] = {}


def _load_sources() -> list[str]:
    urls_file = Path(__file__).resolve().parent.parent / "urls.txt"
    if not urls_file.exists():
        return []
    return [
        line.strip()
        for line in urls_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_from_flex_json(limit: int) -> list[dict[str, str]] | None:
    base_dir = Path(__file__).resolve().parent.parent
    json_path = base_dir / "flex_articles.json"
    if not json_path.exists():
        return None
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[line_webhook] Invalid flex_articles.json: {exc}")
        return None

    if isinstance(raw, dict):
        raw = raw.get("articles") or raw.get("items") or []
    if not isinstance(raw, list):
        return None

    articles: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        if not title or not url:
            continue
        record = {"title": title, "url": url}
        image_url = (item.get("image_url") or "").strip()
        if image_url:
            record["image_url"] = image_url
        articles.append(record)
        if len(articles) >= limit:
            break

    return articles if articles else None


def _collect_articles(limit: int) -> list[dict[str, str]]:
    today_key = datetime.utcnow().strftime("%Y%m%d")
    cached = ARTICLE_CACHE.get(today_key)
    if cached:
        return cached[:limit]

    from_cache = _load_from_flex_json(limit)
    if from_cache:
        ARTICLE_CACHE.clear()
        ARTICLE_CACHE[today_key] = from_cache
        return from_cache[:limit]

    sources = _load_sources()
    articles: list[dict[str, str]] = []
    seen_titles: set[str] = set()

    for source in sources:
        if len(articles) >= limit:
            break
        try:
            fetched = fetch_today_from_rss(source)
        except Exception as exc:
            print(f"[line_webhook] Failed fetching {source}: {exc}")
            continue

        for item in fetched:
            title = (item.get("title") or "").strip()
            url = (item.get("url") or item.get("link") or "").strip()
            if not title or not url:
                continue
            key = url or title.lower()
            if key in seen_titles:
                continue
            record = {"title": title, "url": url}
            image_url = (item.get("image_url") or "").strip()
            if image_url:
                record["image_url"] = image_url
            articles.append(record)
            seen_titles.add(key)
            if len(articles) >= limit:
                break

    if articles:
        ARTICLE_CACHE.clear()
        ARTICLE_CACHE[today_key] = articles

    return articles


def _verify_signature(signature: str, body: bytes) -> bool:
    if not CHANNEL_SECRET:
        # Without channel secret we cannot validate; allow for development.
        return True
    if not signature:
        return False
    mac = hmac.new(CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def _reply_line(reply_token: str, messages: list[dict[str, Any]]) -> None:
    if not CHANNEL_TOKEN:
        raise RuntimeError("LINE_CHANNEL_TOKEN is not configured.")
    payload = {"replyToken": reply_token, "messages": messages}
    resp = requests.post(
        REPLY_ENDPOINT,
        headers={
            "Authorization": f"Bearer {CHANNEL_TOKEN}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=10,
    )
    if resp.status_code >= 300:
        raise RuntimeError(
            f"Failed to reply to LINE API ({resp.status_code}): {resp.text}"
        )


def _build_daily_message() -> dict[str, Any]:
    articles = _collect_articles(limit=min(MAX_ARTICLES, 12))
    alt_text = f"每日新聞 {datetime.utcnow().strftime('%Y/%m/%d')}"
    return build_carousel_message(articles, alt_text=alt_text, limit=12)


@app.post("/api/line_webhook")
async def line_webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("x-line-signature", "")
    if not _verify_signature(signature, raw_body):
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    events = payload.get("events", [])
    for event in events:
        if event.get("type") != "message":
            continue
        message = event.get("message") or {}
        if message.get("type") != "text":
            continue
        text = (message.get("text") or "").strip()
        if text != "每日新聞":
            continue
        reply_token = event.get("replyToken")
        if not reply_token:
            continue
        try:
            content = _build_daily_message()
            _reply_line(reply_token, [content])
        except Exception as exc:
            print(f"[line_webhook] Failed to build/send flex message: {exc}")
            fallback = {
                "type": "text",
                "text": "抱歉，取得今日新聞時發生錯誤，請稍後再試。",
            }
            try:
                _reply_line(reply_token, [fallback])
            except Exception as send_err:
                print(f"[line_webhook] Failed sending fallback: {send_err}")
        break

    return JSONResponse({"status": "ok"})
