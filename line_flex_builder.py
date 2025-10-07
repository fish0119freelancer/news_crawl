"""Utilities to build (and optionally send) LINE Flex carousel messages."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Iterable, List

import requests


def _default_source_path() -> Path:
    json_path = Path("flex_articles.json")
    if json_path.exists():
        return json_path
    today_str = datetime.today().strftime("%Y%m%d")
    return Path(f"news_report_{today_str}.md")


def _load_lines(md_path: Path) -> list[str]:
    try:
        return md_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise SystemExit(f"[line_flex_builder] Source file not found: {md_path}") from exc


def _extract_articles(lines: Iterable[str]) -> list[dict[str, str]]:
    """Parse markdown lines and collect article title/url/image."""
    articles: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    link_pattern = re.compile(r"\[點我閱讀原文\]\((.*?)\)")
    image_pattern = re.compile(r"!\[.*?\]\((.*?)\)")

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        if line.startswith("## "):
            if current and current.get("title") and current.get("url"):
                articles.append(current)
            title = line[3:].strip()
            # Remove leftover trailing markers like "-------"
            title = re.sub(r"-{2,}$", "", title).strip()
            current = {"title": title}
            continue

        if current is None:
            continue

        if "[點我閱讀原文]" in line:
            match = link_pattern.search(line)
            if match:
                url = match.group(1).strip()
                if url:
                    current["url"] = url
            continue

        if line.startswith("!["):
            match = image_pattern.search(line)
            if match:
                image_url = match.group(1).strip()
                if image_url and image_url.lower() != "none":
                    current["image_url"] = image_url

    if current and current.get("title") and current.get("url"):
        articles.append(current)

    return articles


DEFAULT_DOMAIN_LABEL = "其他"


def _normalize_domain(raw: str | None) -> str:
    domain = (raw or "").strip()
    return domain or DEFAULT_DOMAIN_LABEL


def _load_from_json(path: Path) -> list[dict[str, str]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[line_flex_builder] Invalid JSON in {path}: {exc}") from exc

    if isinstance(raw, dict):
        raw = raw.get("articles") or raw.get("items") or []

    if not isinstance(raw, list):
        raise SystemExit(f"[line_flex_builder] Expected a list in {path}")

    articles: List[dict[str, str]] = []
    for idx, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        if not title or not url:
            continue
        record = {
            "title": title,
            "url": url,
        }
        image_url = (item.get("image_url") or "").strip()
        if image_url:
            record["image_url"] = image_url
        domain = (item.get("domain") or item.get("category") or "").strip()
        if domain:
            record["domain"] = domain
        articles.append(record)
    return articles


def _load_from_tab_file(path: Path) -> list[dict[str, str]]:
    articles: list[dict[str, str]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise SystemExit(f"[line_flex_builder] Source file not found: {path}") from exc

    for raw in lines:
        if not raw.strip():
            continue
        parts = raw.split("\t")
        # Expected layout: domain \t title \t url \t image_url
        if len(parts) < 3:
            continue
        domain = parts[0].strip()
        title = parts[1].strip()
        url = parts[2].strip()
        if not title or not url:
            continue
        record = {"title": title, "url": url}
        if domain:
            record["domain"] = domain
        if len(parts) > 3:
            image_url = parts[3].strip()
            if image_url:
                record["image_url"] = image_url
        articles.append(record)
    return articles


def _load_articles_from_source(source: Path) -> list[dict[str, str]]:
    if source.suffix.lower() == ".json":
        return _load_from_json(source)
    if source.suffix.lower() in {".tsv", ".txt"}:
        return _load_from_tab_file(source)
    lines = _load_lines(source)
    return _extract_articles(lines)


def _truncate(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _group_articles_by_domain(
    articles: list[dict[str, str]], per_domain_limit: int
) -> list[tuple[str, list[dict[str, str]]]]:
    grouped: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
    for article in articles:
        domain = _normalize_domain(article.get("domain"))
        bucket = grouped.setdefault(domain, [])
        if len(bucket) < per_domain_limit:
            bucket.append(article)
    return list(grouped.items())


def _build_domain_bubble(
    domain: str,
    articles: list[dict[str, str]],
    report_url: str | None,
) -> dict:
    body_contents: list[dict[str, object]] = []

    if not articles:
        body_contents.append(
            {
                "type": "text",
                "text": "今天沒有符合條件的文章",
                "wrap": True,
                "size": "sm",
                "color": "#555555",
            }
        )
    else:
        for idx, article in enumerate(articles, 1):
            title = _truncate(article.get("title", "(無標題)"), 80)
            url = article.get("url") or "https://line.me/"
            article_box = {
                "type": "box",
                "layout": "vertical",
                "spacing": "xs",
                "contents": [
                    {
                        "type": "text",
                        "text": f"{idx}. {title}",
                        "wrap": True,
                        "size": "sm",
                        "weight": "bold",
                        "action": {
                            "type": "uri",
                            "uri": url,
                        },
                    },
                    {
                        "type": "button",
                        "style": "link",
                        "height": "sm",
                        "action": {
                            "type": "uri",
                            "label": "閱讀全文",
                            "uri": url,
                        },
                    },
                ],
            }
            if idx > 1:
                article_box["margin"] = "md"
            image_url = article.get("image_url")
            if image_url and idx == 1:
                article_box["contents"].insert(
                    1,
                    {
                        "type": "image",
                        "url": image_url,
                        "size": "full",
                        "aspectRatio": "3:2",
                        "aspectMode": "cover",
                    },
                )
            body_contents.append(article_box)

    footer_contents: list[dict[str, object]] = []
    if report_url:
        footer_contents.append(
            {
                "type": "button",
                "style": "primary",
                "height": "sm",
                "action": {
                    "type": "uri",
                    "label": "查看報告",
                    "uri": report_url,
                },
            }
        )

    bubble: dict[str, object] = {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "lg",
            "contents": [
                {
                    "type": "text",
                    "text": domain,
                    "wrap": True,
                    "weight": "bold",
                    "size": "lg",
                }
            ],
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "contents": body_contents,
        },
    }

    if footer_contents:
        bubble["footer"] = {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": footer_contents,
        }

    return bubble


def build_carousel_message(
    articles: list[dict[str, str]],
    *,
    alt_text: str,
    limit: int = 12,
    report_url: str | None = None,
    per_domain_limit: int = 5,
) -> dict:
    if not articles:
        return {
            "type": "text",
            "text": "今天沒有符合條件的新聞唷！",
        }

    grouped = _group_articles_by_domain(articles, per_domain_limit=per_domain_limit)
    if not grouped:
        return {
            "type": "text",
            "text": "今天沒有符合條件的新聞唷！",
        }

    bubbles = [
        _build_domain_bubble(domain, domain_articles, report_url)
        for domain, domain_articles in grouped[:limit]
    ]
    return {
        "type": "flex",
        "altText": alt_text,
        "contents": {
            "type": "carousel",
            "contents": bubbles,
        },
    }


def _post_line(endpoint: str, payload: dict, channel_token: str) -> None:
    resp = requests.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {channel_token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(payload),
        timeout=10,
    )
    if resp.status_code >= 300:
        raise SystemExit(
            f"[line_flex_builder] LINE API call failed ({resp.status_code}): {resp.text}"
        )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build (and optionally send) a LINE Flex carousel message from markdown."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=_default_source_path(),
        help="Source file generated by the daily pipeline (JSON/TSV/Markdown).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=12,
        help="Maximum number of articles to include (LINE allows up to 12).",
    )
    parser.add_argument(
        "--per-domain-limit",
        type=int,
        default=int(os.getenv("LINE_FLEX_PER_DOMAIN_LIMIT", "5")),
        help="Maximum number of articles to keep per domain bubble.",
    )
    parser.add_argument(
        "--report-url",
        type=str,
        default=os.getenv("LINE_FLEX_REPORT_URL"),
        help="Shared report URL used for the 查看報告 button.",
    )
    parser.add_argument(
        "--alt-text",
        type=str,
        default=None,
        help="Flex message alt text. If omitted a default message will be used.",
    )
    parser.add_argument(
        "--mode",
        choices=("reply", "push"),
        default="reply",
        help="Target LINE API endpoint: reply or push.",
    )
    parser.add_argument(
        "--reply-token",
        type=str,
        default=os.getenv("LINE_REPLY_TOKEN"),
        help="LINE reply token (required for reply mode).",
    )
    parser.add_argument(
        "--to",
        type=str,
        default=os.getenv("LINE_USER_ID"),
        help="LINE user/group id (required for push mode).",
    )
    parser.add_argument(
        "--channel-token",
        type=str,
        default=os.getenv("LINE_TOKEN"),
        help="LINE channel access token. Required when --post is used.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the payload JSON.",
    )
    parser.add_argument(
        "--post",
        action="store_true",
        help="Send the payload directly to LINE Messaging API.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> None:
    args = parse_args(argv)

    articles = _load_articles_from_source(args.source)

    if args.alt_text:
        alt_text = args.alt_text
    else:
        today_str = datetime.today().strftime("%Y/%m/%d")
        alt_text = f"{today_str} 每日醫療新聞共 {len(articles)} 則"

    message = build_carousel_message(
        articles,
        alt_text=alt_text,
        limit=args.limit,
        report_url=args.report_url,
        per_domain_limit=args.per_domain_limit,
    )

    if message.get("type") == "text":
        payload = {
            "messages": [message],
        }
    else:
        payload = {
            "messages": [message],
        }

    if args.mode == "reply":
        if not args.reply_token:
            raise SystemExit(
                "[line_flex_builder] reply mode requires --reply-token or LINE_REPLY_TOKEN env."
            )
        payload["replyToken"] = args.reply_token
        endpoint = "https://api.line.me/v2/bot/message/reply"
    else:
        if not args.to:
            raise SystemExit(
                "[line_flex_builder] push mode requires --to or LINE_USER_ID env."
            )
        payload["to"] = args.to
        endpoint = "https://api.line.me/v2/bot/message/push"

    if args.output:
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.post:
        if not args.channel_token:
            raise SystemExit(
                "[line_flex_builder] --post requires --channel-token or LINE_TOKEN env."
            )
        _post_line(endpoint, payload, args.channel_token)
    else:
        # Print to stdout so workflows can capture it if needed.
        print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
