import json

from line_flex_builder import (
    _extract_articles,
    _load_articles_from_source,
    build_carousel_message,
)


def test_extract_articles_parses_markdown_snippet():
    lines = [
        "## Sample Article",
        "![Cover](https://example.com/cover.jpg)",
        "Some summary text that is ignored by the parser.",
        "[點我閱讀原文](https://example.com/article)",
    ]

    articles = _extract_articles(lines)

    assert len(articles) == 1
    article = articles[0]
    assert article["title"] == "Sample Article"
    assert article["url"] == "https://example.com/article"
    assert article["image_url"] == "https://example.com/cover.jpg"


def test_build_carousel_message_structure():
    long_title = "This title will be truncated if it exceeds the limit " * 3
    articles = [
        {
            "title": long_title,
            "url": "https://example.com/a",
            "image_url": "https://example.com/a.jpg",
        }
    ]

    message = build_carousel_message(articles, alt_text="ALT", limit=12)

    assert message["type"] == "flex"
    assert message["altText"] == "ALT"
    contents = message["contents"]
    assert contents["type"] == "carousel"
    assert len(contents["contents"]) == 1

    bubble = contents["contents"][0]
    assert bubble["type"] == "bubble"
    body_text = bubble["body"]["contents"][0]["text"]
    assert body_text.startswith("This title will be truncated")
    assert bubble["footer"]["contents"][0]["action"]["uri"] == "https://example.com/a"
    assert bubble["hero"]["url"] == "https://example.com/a.jpg"

    dumped = json.dumps(message, ensure_ascii=False)
    assert '"type": "flex"' in dumped


def test_build_carousel_message_no_articles_returns_text():
    message = build_carousel_message([], alt_text="ALT", limit=12)
    assert message["type"] == "text"
    assert "沒有符合條件" in message["text"] or "沒有符合" in message["text"]


def test_load_articles_from_json(tmp_path):
    data = [
        {"title": "Article A", "url": "https://example.com/a", "image_url": "https://example.com/a.jpg"},
        {"title": "Article B", "url": "https://example.com/b"},
    ]
    json_path = tmp_path / "flex_articles.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    articles = _load_articles_from_source(json_path)

    assert len(articles) == 2
    assert articles[0]["title"] == "Article A"
    assert articles[0]["image_url"] == "https://example.com/a.jpg"
    assert articles[1]["url"] == "https://example.com/b"
