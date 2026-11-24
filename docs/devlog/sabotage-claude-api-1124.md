# NEWSCRAWL-CLAUDE 保護機制破壞測試（Sabotage）報告（1124）

## 測試方式與基準

- **測試環境**：建立暫存副本目錄 `sab_tmp/`（含 `cost_guard.py`、`summarize_with_llm.py`、`summary_runner.py`、`main.py`、`fetch_articles.py`、`report_generator.py`、`generate_pdf_summary.py`、`scripts/secret_scan.py` 與 `tests/`），所有破壞修改皆僅在 `sab_tmp/` 副本中進行，原始程式碼未做任何修改，且全程未呼叫任何真實 API。
- **執行指令**：以專案 `venv/bin/python -m pytest tests/test_summarize_api.py tests/test_secret_scan.py -q` 執行測試。
- **未改壞基準（Baseline）**：`30 passed`（0 failed）。

---

## 破壞測試結果總表

| 編號 | 改壞內容一句話 | 基準綠數 | 改壞後 failed 數 | 紅的測試名 | 是否被守住 |
| :--- | :--- | :---: | :---: | :--- | :---: |
| **S1** | 讓 `generate_news_summary_and_opinion` 永遠跳過快取讀取（`if False and os.path.exists(cache_file):`） | 30 | 1 | `tests/test_summarize_api.py::test_cache_hit_title_fallback_and_no_cache_on_failure` | ✅ 已守住 |
| **S2** | 讓摘要呼叫拋出例外時仍在重拋前寫入快取檔案 | 30 | 1 | `tests/test_summarize_api.py::test_cache_hit_title_fallback_and_no_cache_on_failure` | ✅ 已守住 |
| **S3** | 拿掉 `CostGuard.before_call` 的每日篇數上限檢查（`self.calls >= self.max_articles`） | 30 | 2 | `tests/test_summarize_api.py::test_article_cap_blocks_third_call`<br>`tests/test_summarize_api.py::test_run_summaries_budget_exceeded_aborts_and_counts_skipped` | ✅ 已守住 |
| **S4** | 拿掉 `CostGuard.before_call` 的每日費用上限檢查（`self.total_cost_usd + worst_cost > self.daily_cost_cap_usd`） | 30 | 2 | `tests/test_summarize_api.py::test_cost_cap_blocks_first_call_when_tiny`<br>`tests/test_summarize_api.py::test_cost_cap_stops_after_cumulative_spend` | ✅ 已守住 |
| **S5** | 讓 `CostGuard.record` 不累加 `self.total_cost_usd` | 30 | 2 | `tests/test_summarize_api.py::test_cost_cap_stops_after_cumulative_spend`<br>`tests/test_summarize_api.py::test_usage_recording_and_log` | ✅ 已守住 |
| **S6** | 讓 `_call_anthropic` 送出的 `max_tokens` 改為固定寫死的 `999`（忽略 `cost_guard.guard.max_tokens`） | 30 | 2 | `tests/test_summarize_api.py::test_anthropic_success_and_request_params`<br>`tests/test_summarize_api.py::test_max_tokens_env_override` | ✅ 已守住 |
| **S7** | 拿掉 `_call_anthropic` 對 `stop_reason in ("max_tokens", "refusal")` 的失敗判斷 | 30 | 3 | `tests/test_summarize_api.py::test_cache_hit_title_fallback_and_no_cache_on_failure`<br>`tests/test_summarize_api.py::test_loud_failure_bad_responses[<lambda>0]`<br>`tests/test_summarize_api.py::test_loud_failure_bad_responses[<lambda>1]` | ✅ 已守住 |
| **S8** | 拿掉 `_call_anthropic` 對空白回應（`if not text_parts:`）的失敗判斷 | 30 | 3 | `tests/test_summarize_api.py::test_loud_failure_bad_responses[<lambda>2]`<br>`tests/test_summarize_api.py::test_loud_failure_bad_responses[<lambda>3]`<br>`tests/test_summarize_api.py::test_loud_failure_bad_responses[<lambda>4]` | ✅ 已守住 |
| **S9** | 讓 `APIStatusError` 的錯誤 log 多印出 `e.response.headers` | 30 | 1 | `tests/test_summarize_api.py::test_api_status_error_raises_and_hides_headers` | ✅ 已守住 |
| **S10** | 把 `AuthenticationError` 與 `PermissionDeniedError` 改為拋出一般 `RuntimeError`（不轉 `FatalSummaryError`） | 30 | 2 | `tests/test_summarize_api.py::test_auth_and_permission_errors_raise_fatal_and_hide_headers[AuthenticationError-401]`<br>`tests/test_summarize_api.py::test_auth_and_permission_errors_raise_fatal_and_hide_headers[PermissionDeniedError-403]` | ✅ 已守住 |
| **S11** | 讓 `run_summaries` 不單獨攔截 `BudgetExceeded` 而落入一般 `Exception` 吞掉並繼續下一篇 | 30 | 1 | `tests/test_summarize_api.py::test_run_summaries_budget_exceeded_aborts_and_counts_skipped` | ✅ 已守住 |
| **S12a** | 讓 `run_summaries` 在文章摘要失敗時不累加 `stats.summary_fail` | 30 | 3 | `tests/test_summarize_api.py::test_run_summaries_partial_failure_skipped`<br>`tests/test_summarize_api.py::test_run_summaries_all_fail_returns_zero_ok`<br>`tests/test_summarize_api.py::test_run_summaries_fatal_error_aborts_immediately` | ✅ 已守住 |
| **S12b** | 讓 `run_summaries` 在文章摘要成功時不累加 `stats.summary_ok` | 30 | 3 | `tests/test_summarize_api.py::test_run_summaries_all_success`<br>`tests/test_summarize_api.py::test_run_summaries_partial_failure_skipped`<br>`tests/test_summarize_api.py::test_run_summaries_budget_exceeded_aborts_and_counts_skipped` | ✅ 已守住 |
| **S13** | 拿掉 `main.py` 在 `summary_stats.selected_total > 0 and summary_stats.summary_ok == 0` 時的 `sys.exit(1)` | 30 | 0 | （無任何測試變紅） | ❌ **未被守住**（已於補測後守住） |
| **S14a** | 讓 `scripts/secret_scan.py` 的 `anthropic_api_key` 規則不再匹配 Anthropic 前綴格式 | 30 | 1 | `tests/test_secret_scan.py::test_planted_secret_exits_one_without_leaking_value[anthropic-<lambda>-anthropic_api_key]` | ✅ 已守住 |
| **S14b** | 讓 `scripts/secret_scan.py` 在輸出命中結果時多印出命中行原始內容 | 30 | 6 | `tests/test_secret_scan.py::test_planted_secret_exits_one_without_leaking_value[anthropic-<lambda>-anthropic_api_key]`<br>`tests/test_secret_scan.py::test_planted_secret_exits_one_without_leaking_value[openai-<lambda>-openai_api_key]`<br>`tests/test_secret_scan.py::test_planted_secret_exits_one_without_leaking_value[bearer-<lambda>-authorization_bearer]`<br>`tests/test_secret_scan.py::test_planted_secret_exits_one_without_leaking_value[aws-<lambda>-aws_access_key]`<br>`tests/test_secret_scan.py::test_planted_secret_exits_one_without_leaking_value[line_token-<lambda>-line_long_token]`<br>`tests/test_secret_scan.py::test_planted_secret_exits_one_without_leaking_value[env_assign-<lambda>-env_secret_assignment]` | ✅ 已守住 |

---

## 未被守住項目說明

- **S13（`main.py` 全失敗 `summary_ok == 0` 時 `sys.exit(1)`）**：
  - **現象**：將 `main.py` 第 238 行的 `sys.exit(1)` 移除後執行測試，結果仍為 `30 passed`（0 failed），**未被守住**（已於補測後守住）。
  - **原因**：目前單元測試（`tests/test_summarize_api.py`）僅直接測試 `summary_runner.run_summaries` 在全部失敗時回傳 `stats.summary_ok == 0` 與 `stats.summary_fail == 2`（由 `test_run_summaries_all_fail_returns_zero_ok` 驗證），但 `main.py` 頂層屬於直接執行的模組腳本（import 時即會讀 `urls.txt`、連網抓 RSS 與產出 PDF），尚未將該 `sys.exit(1)` 檢查抽離為獨立函式或以子行程測試覆蓋 `main.py` 腳本入口。依任務指示如實標記為「未被守住」，不修改原始檔亦不自行補測試。

## S13 補測

後續已將全失敗退出邏輯抽離為 `summary_runner.exit_code_for`，並於 `main.py` 呼叫 `exit_code = exit_code_for(summary_stats)`，同時在 `tests/test_summarize_api.py` 新增 `test_exit_code_for_cases` 與 `test_main_calls_exit_code_for_and_exits`，將基準提升為 `32 passed`。

針對 S13 進行拆解補測（於暫存副本 `sab_tmp/` 執行）：
- **未改壞基準（Baseline）**：`32 passed`（0 failed）。
- **S13a（`summary_runner.exit_code_for` 全失敗回傳改為 0）**：
  - 改壞內容：將全失敗時回傳 1 改成回傳 0。
  - 測試結果：`1 failed, 31 passed`。
  - 紅的測試名：`tests/test_summarize_api.py::test_exit_code_for_cases`
  - 是否被守住：✅ **已守住**
- **S13b（`main.py` 裡的 `exit_code_for(summary_stats)` 改成常數 0）**：
  - 改壞內容：將 `exit_code = exit_code_for(summary_stats)` 改為 `exit_code = 0`。
  - 測試結果：`1 failed, 31 passed`。
  - 紅的測試名：`tests/test_summarize_api.py::test_main_calls_exit_code_for_and_exits`
  - 是否被守住：✅ **已守住**

結論：S13 退出機制經抽離為純函式與原始碼語意檢驗後，已由單元測試完整守住。

## 清理狀態

- 已刪除暫存副本目錄 `sab_tmp/` 與 `.pytest_cache/`，原始工作目錄保持乾淨。
