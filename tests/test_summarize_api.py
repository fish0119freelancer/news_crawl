"""Anthropic SDK 摘要模組、CostGuard 與 summary_runner 的單元測試（全使用假 client）。"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

# 確保在未啟動 venv 或由外層 python（例如 hydra 測試環境）執行 pytest 時能找到專案依賴
_repo_root = Path(__file__).resolve().parent.parent
for _venv_candidate in ("venv", ".venv", ".venv-linux"):
    for _sp in (_repo_root / _venv_candidate).glob("lib/python*/site-packages"):
        if _sp.is_dir() and str(_sp) not in sys.path:
            sys.path.insert(0, str(_sp))

import anthropic
import httpx2
import pytest

import cost_guard
import summarize_with_llm
from cost_guard import BudgetExceeded
from summarize_with_llm import (
    FatalSummaryError,
    extract_score_from_response,
    generate_news_summary_and_opinion,
    get_anthropic_client,
)
from summary_runner import SummaryStats, exit_code_for, run_summaries


class FakeMessagesAPI:
    """記錄所有呼叫參數並回傳預設或自訂回應的假 messages API。"""

    def __init__(self, handler=None):
        self.calls: list[dict] = []
        self._handler = handler

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._handler is not None:
            return self._handler(kwargs, len(self.calls))
        return make_fake_response(
            "## 繁體中文生醫創新\n\n### 評分\n⭐ 7.5 分\n\n### 摘要\n測試摘要。"
        )


class FakeAnthropicClient:
    def __init__(self, handler=None):
        self.messages = FakeMessagesAPI(handler=handler)


def make_fake_response(
    text: str = "## 預設標題\n\n### 評分\n⭐ 7.5 分\n\n### 摘要\n內文",
    *,
    input_tokens: int = 1000,
    output_tokens: int = 400,
    stop_reason: str = "end_turn",
    content=None,
):
    if content is None:
        content = [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(
        content=content,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
        stop_reason=stop_reason,
    )


def make_httpx_response(status_code: int, headers: dict[str, str] | None = None):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return httpx2.Response(
        status_code=status_code,
        request=req,
        headers=headers or {},
        json={"error": {"type": "api_error", "message": "upstream error"}},
    )


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("SUMMARY_CACHE_DIR", str(cache_dir))
    for var in (
        "DRY_RUN",
        "SUMMARY_BACKEND",
        "SUMMARY_MODEL",
        "MAX_ARTICLES_PER_DAY",
        "DAILY_COST_CAP_USD",
        "SUMMARY_MAX_TOKENS",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(summarize_with_llm, "_anthropic_client", None)
    cost_guard.reset_for_test()


def test_anthropic_success_and_request_params(monkeypatch, tmp_path):
    article = {
        "title": "測試生醫文章",
        "text": "這是生醫內文研究發現...",
        "url": "https://example.com/article-1",
    }
    raw_summary = (
        "## 繁體中文生醫創新\n\n"
        "### 評分\n⭐ 7.5 分\n\n"
        "### 摘要\n研究取得突破進展。\n\n"
        "### 原文連結\n[點擊連結](https://example.com/article-1)"
    )
    fake_client = FakeAnthropicClient(
        handler=lambda kw, n: make_fake_response(raw_summary)
    )
    monkeypatch.setattr(
        summarize_with_llm, "get_anthropic_client", lambda: fake_client
    )

    result = generate_news_summary_and_opinion(article)
    assert result == raw_summary
    assert extract_score_from_response(result) == 7.5
    assert len(fake_client.messages.calls) == 1

    sent = fake_client.messages.calls[0]
    assert "temperature" not in sent
    assert sent["model"] == "claude-haiku-5-5"
    assert sent["max_tokens"] == cost_guard.guard.max_tokens == 3000
    assert sent["output_config"] == {"effort": "low"}

    # 確認成功結果寫入快取
    key_hash = hashlib.sha256(article["url"].encode("utf-8")).hexdigest()
    cache_file = tmp_path / "cache" / f"{key_hash}.json"
    assert cache_file.exists()
    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cached["url"] == article["url"]
    assert cached["summary"] == raw_summary


def test_cache_hit_title_fallback_and_no_cache_on_failure(monkeypatch, tmp_path):
    article_url = {
        "title": "文章 A",
        "text": "內文 A",
        "url": "https://example.com/cached-a",
    }
    article_no_url = {
        "title": "無網址文章標題",
        "text": "僅有標題與內文",
        "url": "",
    }
    article_fail = {
        "title": "失敗文章",
        "text": "將觸發拒絕",
        "url": "https://example.com/fail-no-cache",
    }

    def handler(kw, n):
        prompt = kw["messages"][0]["content"]
        if "失敗文章" in prompt:
            return make_fake_response("refused", stop_reason="refusal")
        return make_fake_response(f"## 摘要 #{n}\n\n### 評分\n⭐ 8.0 分")

    fake_client = FakeAnthropicClient(handler=handler)
    monkeypatch.setattr(
        summarize_with_llm, "get_anthropic_client", lambda: fake_client
    )

    # 同 URL 兩次只呼叫 1 次且不重複計入 guard.calls
    r1 = generate_news_summary_and_opinion(article_url)
    r2 = generate_news_summary_and_opinion(article_url)
    assert r1 == r2
    assert len(fake_client.messages.calls) == 1
    assert cost_guard.guard.calls == 1

    # 無 URL 時以 title hash 當快取 key
    t1 = generate_news_summary_and_opinion(article_no_url)
    t2 = generate_news_summary_and_opinion(article_no_url)
    assert t1 == t2
    assert len(fake_client.messages.calls) == 2
    title_hash = hashlib.sha256("無網址文章標題".encode("utf-8")).hexdigest()
    assert (tmp_path / "cache" / f"{title_hash}.json").exists()

    # 失敗時不寫入快取
    with pytest.raises(RuntimeError):
        generate_news_summary_and_opinion(article_fail)
    fail_hash = hashlib.sha256(article_fail["url"].encode("utf-8")).hexdigest()
    assert not (tmp_path / "cache" / f"{fail_hash}.json").exists()


def test_article_cap_blocks_third_call(monkeypatch, caplog):
    monkeypatch.setenv("MAX_ARTICLES_PER_DAY", "2")
    cost_guard.reset_for_test()

    fake_client = FakeAnthropicClient()
    monkeypatch.setattr(
        summarize_with_llm, "get_anthropic_client", lambda: fake_client
    )

    with caplog.at_level(logging.ERROR):
        generate_news_summary_and_opinion(
            {"title": "A1", "text": "t1", "url": "https://example.com/cap1"}
        )
        generate_news_summary_and_opinion(
            {"title": "A2", "text": "t2", "url": "https://example.com/cap2"}
        )
        with pytest.raises(BudgetExceeded, match="article cap"):
            generate_news_summary_and_opinion(
                {"title": "A3", "text": "t3", "url": "https://example.com/cap3"}
            )

    assert len(fake_client.messages.calls) == 2
    assert "article cap" in caplog.text


def test_cost_cap_blocks_first_call_when_tiny(monkeypatch, caplog):
    monkeypatch.setenv("DAILY_COST_CAP_USD", "0.0001")
    cost_guard.reset_for_test()

    fake_client = FakeAnthropicClient()
    monkeypatch.setattr(
        summarize_with_llm, "get_anthropic_client", lambda: fake_client
    )

    with caplog.at_level(logging.ERROR):
        with pytest.raises(BudgetExceeded, match="cost cap"):
            generate_news_summary_and_opinion(
                {"title": "TinyCap", "text": "body", "url": "https://example.com/tiny"}
            )

    assert len(fake_client.messages.calls) == 0
    assert "cost cap" in caplog.text


def test_cost_cap_stops_after_cumulative_spend(monkeypatch, caplog):
    # max_tokens=1000 -> 最壞 output 成本 0.0005；每篇短 prompt 最壞輸入成本 < 0.0001
    # 每次回應實際紀錄 in=0, out=1000 -> 每次花費 0.0005
    # 設上限 0.0012：第 1 次 (0 + ~0.00055 <= 0.0012) 通過並花 0.0005；
    # 第 2 次 (0.0005 + ~0.00055 <= 0.0012) 通過並花 0.0005（累計 0.0010）；
    # 第 3 次 (0.0010 + ~0.00055 > 0.0012) 被擋下
    monkeypatch.setenv("SUMMARY_MAX_TOKENS", "1000")
    monkeypatch.setenv("DAILY_COST_CAP_USD", "0.0012")
    cost_guard.reset_for_test()

    fake_client = FakeAnthropicClient(
        handler=lambda kw, n: make_fake_response(
            f"## 累計 #{n}\n\n### 評分\n⭐ 7.0 分",
            input_tokens=0,
            output_tokens=1000,
        )
    )
    monkeypatch.setattr(
        summarize_with_llm, "get_anthropic_client", lambda: fake_client
    )

    with caplog.at_level(logging.ERROR):
        generate_news_summary_and_opinion(
            {"title": "C1", "text": "short", "url": "https://example.com/cum1"}
        )
        generate_news_summary_and_opinion(
            {"title": "C2", "text": "short", "url": "https://example.com/cum2"}
        )
        with pytest.raises(BudgetExceeded, match="cost cap"):
            generate_news_summary_and_opinion(
                {"title": "C3", "text": "short", "url": "https://example.com/cum3"}
            )

    assert len(fake_client.messages.calls) == 2
    assert "cost cap" in caplog.text


def test_max_tokens_env_override(monkeypatch):
    monkeypatch.setenv("SUMMARY_MAX_TOKENS", "777")
    cost_guard.reset_for_test()

    fake_client = FakeAnthropicClient()
    monkeypatch.setattr(
        summarize_with_llm, "get_anthropic_client", lambda: fake_client
    )

    generate_news_summary_and_opinion(
        {"title": "MaxTok", "text": "content", "url": "https://example.com/maxtok"}
    )
    assert len(fake_client.messages.calls) == 1
    assert fake_client.messages.calls[0]["max_tokens"] == 777


def test_usage_recording_and_log(monkeypatch, caplog):
    in_tok = 12345
    out_tok = 678
    expected_est = in_tok * 0.10 / 1e6 + out_tok * 0.50 / 1e6

    fake_client = FakeAnthropicClient(
        handler=lambda kw, n: make_fake_response(
            "## 用量記錄\n\n### 評分\n⭐ 8.2 分",
            input_tokens=in_tok,
            output_tokens=out_tok,
        )
    )
    monkeypatch.setattr(
        summarize_with_llm, "get_anthropic_client", lambda: fake_client
    )

    with caplog.at_level(logging.INFO):
        generate_news_summary_and_opinion(
            {"title": "Usage", "text": "body", "url": "https://example.com/usage"}
        )

    assert cost_guard.guard.total_cost_usd == pytest.approx(expected_est)
    assert f"usage in={in_tok} out={out_tok}" in caplog.text
    assert "total_est=$" in caplog.text
    assert "calls=1" in caplog.text
    assert "calls=1" in cost_guard.guard.summary_line()


@pytest.mark.parametrize(
    "response_factory",
    [
        lambda: make_fake_response("截斷內容", stop_reason="max_tokens"),
        lambda: make_fake_response("拒絕內容", stop_reason="refusal"),
        lambda: make_fake_response("", content=[]),
        lambda: make_fake_response(
            "", content=[SimpleNamespace(type="text", text="   ")]
        ),
        lambda: make_fake_response(
            "", content=[SimpleNamespace(type="thinking", thinking="internal")]
        ),
    ],
)
def test_loud_failure_bad_responses(monkeypatch, response_factory):
    fake_client = FakeAnthropicClient(handler=lambda kw, n: response_factory())
    monkeypatch.setattr(
        summarize_with_llm, "get_anthropic_client", lambda: fake_client
    )

    with pytest.raises(RuntimeError):
        generate_news_summary_and_opinion(
            {"title": "BadResp", "text": "x", "url": "https://example.com/bad-resp"}
        )
    # 失敗不應記錄用量
    assert cost_guard.guard.total_cost_usd == 0.0


def test_api_status_error_raises_and_hides_headers(monkeypatch, caplog):
    header_marker = "HDRMARK" + "987654"
    resp = make_httpx_response(500, headers={"x-custom-secret": header_marker})
    err = anthropic.APIStatusError("server failed", response=resp, body=None)

    def raise_err(kw, n):
        raise err

    fake_client = FakeAnthropicClient(handler=raise_err)
    monkeypatch.setattr(
        summarize_with_llm, "get_anthropic_client", lambda: fake_client
    )

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(RuntimeError) as exc_info:
            generate_news_summary_and_opinion(
                {"title": "Err500", "text": "x", "url": "https://example.com/err500"}
            )

    assert not isinstance(exc_info.value, FatalSummaryError)
    assert header_marker not in caplog.text
    assert header_marker not in str(exc_info.value)


def test_api_connection_error_raises_runtime_error(monkeypatch, caplog):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.APIConnectionError(message="network down", request=req)

    def raise_err(kw, n):
        raise err

    fake_client = FakeAnthropicClient(handler=raise_err)
    monkeypatch.setattr(
        summarize_with_llm, "get_anthropic_client", lambda: fake_client
    )

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(RuntimeError) as exc_info:
            generate_news_summary_and_opinion(
                {"title": "ConnErr", "text": "x", "url": "https://example.com/conn"}
            )
    assert "APIConnectionError" in str(exc_info.value)


@pytest.mark.parametrize(
    "exc_cls,status_code",
    [
        (anthropic.AuthenticationError, 401),
        (anthropic.PermissionDeniedError, 403),
    ],
)
def test_auth_and_permission_errors_raise_fatal_and_hide_headers(
    monkeypatch, caplog, exc_cls, status_code
):
    header_marker = "HDRMARK" + "401403"
    resp = make_httpx_response(status_code, headers={"x-debug-token": header_marker})
    err = exc_cls("auth failed", response=resp, body=None)

    def raise_err(kw, n):
        raise err

    fake_client = FakeAnthropicClient(handler=raise_err)
    monkeypatch.setattr(
        summarize_with_llm, "get_anthropic_client", lambda: fake_client
    )

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(FatalSummaryError) as exc_info:
            generate_news_summary_and_opinion(
                {"title": "AuthErr", "text": "x", "url": "https://example.com/auth"}
            )

    assert header_marker not in caplog.text
    assert header_marker not in str(exc_info.value)


def test_missing_anthropic_key_and_import_without_any_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(summarize_with_llm, "_anthropic_client", None)

    # 沒有任何金鑰時重新載入模組不得拋出例外
    importlib.reload(summarize_with_llm)
    assert hasattr(summarize_with_llm, "generate_news_summary_and_opinion")

    with pytest.raises(RuntimeError) as exc_info:
        summarize_with_llm.get_anthropic_client()
    assert "ANTHROPIC_API_KEY not set" in str(exc_info.value)


def test_run_summaries_all_success(monkeypatch):
    domain_articles = {
        "ai": [
            {"title": "AI-1", "text": "t1", "url": "https://example.com/ai1"},
            {"title": "AI-2", "text": "t2", "url": "https://example.com/ai2"},
            {"title": "AI-3-over-limit", "text": "t3", "url": "https://example.com/ai3"},
        ],
        "neuro": [
            {"title": "N-1", "text": "t4", "url": "https://example.com/n1"},
        ],
    }

    scores = {"AI-1": "6.5", "AI-2": "9.0", "N-1": "8.0"}

    def fake_gen(article):
        sc = scores[article["title"]]
        return f"## {article['title']}\n\n### 評分\n⭐ {sc} 分"

    monkeypatch.setattr(
        summarize_with_llm, "generate_news_summary_and_opinion", fake_gen
    )

    processed, stats = run_summaries(domain_articles, max_per_domain=2)
    assert stats.selected_total == 3
    assert stats.summary_ok == 3
    assert stats.summary_fail == 0
    assert stats.summary_skipped == 0
    # 依評分高到低排序
    assert [a["title"] for a in processed["ai"]] == ["AI-2", "AI-1"]
    assert [a["title"] for a in processed["neuro"]] == ["N-1"]


def test_run_summaries_partial_failure_skipped(monkeypatch):
    domain_articles = {
        "ai": [
            {"title": "OK-1", "text": "t1", "url": "https://example.com/p1"},
            {"title": "BAD-2", "text": "t2", "url": "https://example.com/p2"},
            {"title": "OK-3", "text": "t3", "url": "https://example.com/p3"},
        ]
    }

    def fake_gen(article):
        if article["title"] == "BAD-2":
            raise RuntimeError("transient failure")
        return f"## {article['title']}\n\n### 評分\n⭐ 7.0 分"

    monkeypatch.setattr(
        summarize_with_llm, "generate_news_summary_and_opinion", fake_gen
    )

    processed, stats = run_summaries(domain_articles, max_per_domain=5)
    assert stats.selected_total == 3
    assert stats.summary_ok == 2
    assert stats.summary_fail == 1
    assert stats.summary_skipped == 0
    assert [a["title"] for a in processed["ai"]] == ["OK-1", "OK-3"]


def test_run_summaries_budget_exceeded_aborts_and_counts_skipped(monkeypatch, capsys):
    monkeypatch.setenv("MAX_ARTICLES_PER_DAY", "2")
    cost_guard.reset_for_test()

    fake_client = FakeAnthropicClient()
    monkeypatch.setattr(
        summarize_with_llm, "get_anthropic_client", lambda: fake_client
    )

    domain_articles = {
        "ai": [
            {"title": "B1", "text": "t1", "url": "https://example.com/b1"},
            {"title": "B2", "text": "t2", "url": "https://example.com/b2"},
            {"title": "B3", "text": "t3", "url": "https://example.com/b3"},
        ],
        "neuro": [
            {"title": "B4", "text": "t4", "url": "https://example.com/b4"},
            {"title": "B5", "text": "t5", "url": "https://example.com/b5"},
        ],
    }

    processed, stats = run_summaries(domain_articles, max_per_domain=5)
    out = capsys.readouterr().out

    assert len(fake_client.messages.calls) == 2
    assert stats.selected_total == 5
    assert stats.summary_ok == 2
    assert stats.summary_fail == 0
    assert stats.summary_skipped == 3
    assert "neuro" not in processed
    assert "::error::" in out


def test_run_summaries_all_fail_returns_zero_ok(monkeypatch):
    domain_articles = {
        "ai": [
            {"title": "F1", "text": "t1", "url": "https://example.com/f1"},
            {"title": "F2", "text": "t2", "url": "https://example.com/f2"},
        ]
    }

    def fake_gen(article):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        summarize_with_llm, "generate_news_summary_and_opinion", fake_gen
    )

    processed, stats = run_summaries(domain_articles, max_per_domain=5)
    assert stats.selected_total == 2
    assert stats.summary_ok == 0
    assert stats.summary_fail == 2
    assert processed == {}


def test_run_summaries_fatal_error_aborts_immediately(monkeypatch, capsys):
    calls = 0

    def fake_gen(article):
        nonlocal calls
        calls += 1
        raise FatalSummaryError("invalid api key")

    monkeypatch.setattr(
        summarize_with_llm, "generate_news_summary_and_opinion", fake_gen
    )

    domain_articles = {
        "ai": [
            {"title": "X1", "text": "t1", "url": "https://example.com/x1"},
            {"title": "X2", "text": "t2", "url": "https://example.com/x2"},
        ],
        "neuro": [
            {"title": "X3", "text": "t3", "url": "https://example.com/x3"},
        ],
    }

    processed, stats = run_summaries(domain_articles, max_per_domain=5)
    out = capsys.readouterr().out

    assert calls == 1
    assert stats.summary_ok == 0
    assert stats.summary_fail == 1
    assert stats.summary_skipped == 2
    assert "::error::" in out


def test_backend_openai_uses_lazy_getter(monkeypatch):
    monkeypatch.setenv("SUMMARY_BACKEND", "openai")

    mock_openai_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "## OpenAI 摘要\n\n### 評分\n⭐ 8.5 分"
    mock_openai_client.chat.completions.create.return_value.choices = [mock_choice]

    monkeypatch.setattr(
        summarize_with_llm, "get_openai_client", lambda: mock_openai_client
    )
    monkeypatch.setattr(
        summarize_with_llm,
        "get_anthropic_client",
        lambda: (_ for _ in ()).throw(AssertionError("Anthropic should not be called")),
    )

    article = {
        "title": "OpenAI 測試",
        "text": "內文",
        "url": "https://example.com/openai-fallback",
    }
    res = generate_news_summary_and_opinion(article)
    assert "OpenAI 摘要" in res
    assert mock_openai_client.chat.completions.create.called
    assert cost_guard.guard.calls == 0


def test_exit_code_for_cases():
    # (a) 全失敗（selected_total=2、summary_ok=0）→ 1
    stats_all_fail = SummaryStats(selected_total=2, summary_ok=0, summary_fail=2)
    assert exit_code_for(stats_all_fail) == 1

    # (b) 部分失敗 → 0
    stats_partial = SummaryStats(selected_total=2, summary_ok=1, summary_fail=1)
    assert exit_code_for(stats_partial) == 0

    # (c) selected_total=0 → 0
    stats_zero = SummaryStats(selected_total=0, summary_ok=0, summary_fail=0)
    assert exit_code_for(stats_zero) == 0


def test_main_calls_exit_code_for_and_exits():
    # (d) 讀 main.py 原始碼文字，斷言其中有 exit_code_for( 且有 sys.exit(
    main_code = (Path(__file__).resolve().parent.parent / "main.py").read_text(
        encoding="utf-8"
    )
    assert "exit_code_for(" in main_code
    assert "sys.exit(" in main_code
