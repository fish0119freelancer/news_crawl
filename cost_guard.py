"""每日摘要 API 費用與篇數保護機制（無外部相依）。"""

from __future__ import annotations

import logging
import os

MODEL = os.getenv("SUMMARY_MODEL", "claude-haiku-5-5")
PRICE_IN_PER_MTOK = 0.10
PRICE_OUT_PER_MTOK = 0.50


class BudgetExceeded(RuntimeError):
    """超出每日篇數或費用上限時拋出。"""


class CostGuard:
    """追蹤每日 API 呼叫篇數、token 用量與估算花費，超過上限即阻止呼叫。"""

    def __init__(
        self,
        max_articles: int | None = None,
        daily_cost_cap_usd: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.max_articles = (
            int(os.getenv("MAX_ARTICLES_PER_DAY", "40"))
            if max_articles is None
            else int(max_articles)
        )
        self.daily_cost_cap_usd = (
            float(os.getenv("DAILY_COST_CAP_USD", "0.65"))
            if daily_cost_cap_usd is None
            else float(daily_cost_cap_usd)
        )
        self.max_tokens = (
            int(os.getenv("SUMMARY_MAX_TOKENS", "3000"))
            if max_tokens is None
            else int(max_tokens)
        )
        self.calls: int = 0
        self.total_in_tokens: int = 0
        self.total_out_tokens: int = 0
        self.total_cost_usd: float = 0.0

    def before_call(self, prompt: str) -> None:
        """在呼叫 API 前檢查篇數上限與最壞單次成本估算，通過後呼叫次數 +1。"""
        if self.calls >= self.max_articles:
            logging.error(
                "CostGuard blocked call: article cap reached (%d/%d)",
                self.calls,
                self.max_articles,
            )
            raise BudgetExceeded("article cap")

        est_in_tokens = len(prompt or "") / 2.0
        worst_cost = (
            est_in_tokens * PRICE_IN_PER_MTOK / 1_000_000.0
            + self.max_tokens * PRICE_OUT_PER_MTOK / 1_000_000.0
        )
        if self.total_cost_usd + worst_cost > self.daily_cost_cap_usd:
            logging.error(
                "CostGuard blocked call: cost cap exceeded "
                "(spent=$%.6f + worst=$%.6f > cap=$%.6f)",
                self.total_cost_usd,
                worst_cost,
                self.daily_cost_cap_usd,
            )
            raise BudgetExceeded("cost cap")

        self.calls += 1

    def record(self, usage_in: int, usage_out: int) -> float:
        """記錄實際 token 用量並累加估算費用，寫入一行 info log。"""
        in_tok = int(usage_in or 0)
        out_tok = int(usage_out or 0)
        est = (
            in_tok * PRICE_IN_PER_MTOK / 1_000_000.0
            + out_tok * PRICE_OUT_PER_MTOK / 1_000_000.0
        )
        self.total_in_tokens += in_tok
        self.total_out_tokens += out_tok
        self.total_cost_usd += est
        logging.info(
            "usage in=%d out=%d est=$%.6f total_est=$%.6f calls=%d",
            in_tok,
            out_tok,
            est,
            self.total_cost_usd,
            self.calls,
        )
        return est

    def summary_line(self) -> str:
        """回傳摘要統計字串供 main.py 印出。"""
        return (
            f"💰 API 用量統計：calls={self.calls}, "
            f"in={self.total_in_tokens}, out={self.total_out_tokens}, "
            f"est=${self.total_cost_usd:.6f}"
        )


_guard: CostGuard | None = None


def get_guard() -> CostGuard:
    """Lazy 取得模組單例 CostGuard。"""
    global _guard
    if _guard is None:
        _guard = CostGuard()
    return _guard


def reset_for_test(
    max_articles: int | None = None,
    daily_cost_cap_usd: float | None = None,
    max_tokens: int | None = None,
) -> None:
    """重設單例狀態供測試使用；未傳參數時延遲到下次存取再讀環境變數。"""
    global _guard
    if max_articles is None and daily_cost_cap_usd is None and max_tokens is None:
        _guard = None
    else:
        _guard = CostGuard(
            max_articles=max_articles,
            daily_cost_cap_usd=daily_cost_cap_usd,
            max_tokens=max_tokens,
        )


class _LazyGuardProxy:
    """模組層單例代理，確保 reset_for_test() 後所有引用都能讀取最新環境設定。"""

    def __getattr__(self, name: str):
        return getattr(get_guard(), name)

    def __setattr__(self, name: str, value) -> None:
        setattr(get_guard(), name, value)


guard: CostGuard = _LazyGuardProxy()  # type: ignore[assignment]
