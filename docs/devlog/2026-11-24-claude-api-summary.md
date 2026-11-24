# NEWSCRAWL-CLAUDE API devlog（2026-11-24）

目標：新聞摘要從 OpenAI / `claude -p` 遷移至官方 Claude API（Anthropic SDK），並加入完整的每日費用防護與安全機制。

## 嘗試 → 被推翻的假設 → 前後數字

### 1. 11/23 方案回顧與被推翻的假設
- **前次方案（`claude -p`）**：分支 `feat/claude-p-summary`（commit `ba12f25`、`df4ce8a`），嘗試透過本機已登入的 Claude CLI（`claude -p`）執行摘要。
  - **實測數據**：每篇摘要耗時約 47 秒，`total_cost` 約 0.055 美元（API 等值），每日 35 篇循序執行約需 27 分鐘。
  - **被推翻的假設**：「CI 環境可以直接跑 `claude -p`」。事實上 GitHub Actions runner 並沒有 Claude 登入憑證與 session，無法執行 CLI 工具。
  - **決策**：在決策項目 D212 中，owner 評估方案 A（iMac launchd 凌晨跑）與方案 B（GitHub Actions + 官方 API），最終選定方案 B（改走 GitHub Actions 搭配 Claude API）。

### 2. 現況核對
- 檢查最近三次 Daily News Report 產出，皆順利成功且 PDF / 摘要正常產出。
- **結論**：目前線上運作版本穩定無問題，本次改動為架構平順升級與費用優化。

### 3. 新做法：官方 Anthropic SDK 與 Haiku 5.5
- **SDK 與模型**：採用官方 `anthropic` SDK 2.8.0，搭配 `claude-haiku-5-5`。
  - **定價**：輸入每百萬 token US$0.10、輸出每百萬 token US$0.50（定價來源：官方 models overview，2026-11-24）。
  - **參數配置**：設定 `effort=low`；明確不傳 `temperature` 參數（Haiku 5.5 拒絕任何非預設值）。
  - **重試處理**：不自寫重試迴圈，直接使用 SDK 內建之 `max_retries=2` 處理暫態網路異常。

### 4. 費用保護機制與成本估算
- **三道嚴格 Guard（CostGuard）**：
  1. 預設每日最多處理 40 篇（`MAX_ARTICLES=40`）。
  2. 每日費用上限預設 US$0.65（`DAILY_COST_CAP_USD=0.65`）。
  3. 單篇請求設定 `max_tokens=3000`。
- **保護語意**：超過任一上限即中止後續文章摘要並發出 GitHub Actions `::error::` 標註；已完成之摘要照常產出 PDF；僅在所有文章皆失敗（`summary_ok == 0` 且 `selected_total > 0`）時以 exit code 1 中止流程。
- **每日費用實際估算**：以每日 35 篇估算，每篇約 2K 輸入 tokens + 1K 輸出 tokens ≈ US$0.0007，35 篇合計約 US$0.03／天（此為保守靜態估算，非實測；實際上線首次 run 需觀察日誌輸出之 usage 行進行校正）。

### 5. 其他 OpenAI 用法清單
- 檢視全專案 OpenAI 依賴：`llm_batch_summarize` 中的兩處 `gpt-3.5-turbo` 僅存在於 `__main__` 測試區塊且已被註解，每日排程流程並不會呼叫，故維持原樣未動。
- 保留 OpenAI 作為 fallback：透過環境變數 `SUMMARY_BACKEND=openai` 支援回退模式（預設關閉，且 client 改為 lazy 延遲載入以避免無 key 時 import 失敗）。

### 6. 已知問題（非本卡引入）
- `tests/test_line_flex_builder.py::test_build_carousel_message_structure` 在 `main` 分支上原先即存在錯誤（`KeyError: 'text'`）。
- 產出之 PDF 評分區目前會直接顯示未轉換之 Markdown 粗體語法 `**bold**`。

### 7. 執行過程紀錄
- route 執行者在探索環境時曾於 `venv/` 內寫入一個 `.pyc` 暫存檔，被 dispatcher 評判為範圍違規（屬無害暫存）。
- task brief 描述曾因含有「金鑰名稱後接等號或冒號」的敏感字串組合被 secret guard 攔截，後續修正為描述式寫法以符合安全規則。

### 8. 測試與驗證結果
- **單元測試**：新增相關測試後共 `32 passed`（0 failed）。
- **Sabotage 破壞測試**：針對 S1~S14 共 14 類安全與費用保護機制進行破壞測試，全部精準轉紅（詳見 `docs/devlog/sabotage-claude-api-1124.md`）。
- **Secret 掃描**：執行 `scripts/secret_scan.py` 檢查所有程式碼、devlog 與卡片，達成 `0 命中`（無任何機敏金鑰洩漏）。
