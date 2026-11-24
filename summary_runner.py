"""將各領域文章的摘要迴圈抽離為可測試的函式。"""

from __future__ import annotations

from dataclasses import dataclass

from cost_guard import BudgetExceeded
import summarize_with_llm
from summarize_with_llm import FatalSummaryError


@dataclass
class SummaryStats:
    """單次每日摘要執行的統計資訊。"""

    selected_total: int = 0
    summary_ok: int = 0
    summary_fail: int = 0
    summary_skipped: int = 0
    abort_reason: str | None = None


def exit_code_for(stats: SummaryStats) -> int:
    """若選取文章大於 0 且成功數為 0 則回傳 1，否則 0。"""
    return 1 if stats.selected_total > 0 and stats.summary_ok == 0 else 0


def run_summaries(
    domain_articles: dict[str, list[dict]],
    max_per_domain: int,
) -> tuple[dict[str, list[dict]], SummaryStats]:
    """對各領域前 max_per_domain 篇文章執行摘要並依評分排序。

    捕捉 BudgetExceeded 與 FatalSummaryError 時會印出 ::error:: 註解並立即中止
    所有領域迴圈；一般 Exception 則略過該篇並繼續。
    """
    stats = SummaryStats()
    selected_by_domain: list[tuple[str, list[dict]]] = []

    for domain, articles in domain_articles.items():
        if not articles:
            continue
        selected = articles[:max_per_domain]
        if selected:
            selected_by_domain.append((domain, selected))
            stats.selected_total += len(selected)

    processed_by_domain: dict[str, list[dict]] = {}
    aborted = False

    for domain, selected in selected_by_domain:
        processed_articles: list[dict] = []
        for article in selected:
            try:
                summary_and_opinion = (
                    summarize_with_llm.generate_news_summary_and_opinion(article)
                )
                score = summarize_with_llm.extract_score_from_response(
                    summary_and_opinion
                )
                article["_score"] = score
                article["_summary"] = summary_and_opinion
                processed_articles.append(article)
                stats.summary_ok += 1
                print(
                    f"🖋️ 產生 {domain} 文章報告："
                    f"{article.get('title', '(無標題)')} ⭐{score}"
                )
            except BudgetExceeded as e:
                aborted = True
                stats.abort_reason = f"BudgetExceeded: {e}"
                print(f"::error::摘要已中止（觸發費用/篇數上限：{e}）")
                break
            except FatalSummaryError as e:
                aborted = True
                stats.summary_fail += 1
                stats.abort_reason = f"FatalSummaryError: {e}"
                print(f"::error::摘要已中止（致命 API 錯誤：{e}）")
                break
            except Exception as e:
                stats.summary_fail += 1
                print(
                    f"⚠️ 產生 {domain} 文章失敗："
                    f"{article.get('title', '(無標題)')} → {e}"
                )
                continue

        if processed_articles:
            processed_articles.sort(
                key=lambda x: x.get("_score", 0), reverse=True
            )
            processed_by_domain[domain] = processed_articles

        if aborted:
            break

    if aborted:
        stats.summary_skipped = (
            stats.selected_total - stats.summary_ok - stats.summary_fail
        )

    return processed_by_domain, stats
