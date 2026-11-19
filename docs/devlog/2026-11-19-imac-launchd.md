# NEWSCRAWL-IMAC devlog（2026-11-19）

目標：daily.yml 因 Ubuntu 26.04 無 Python 3.9 失敗 → 搬 iMac launchd。

## 嘗試 → 被推翻的假設 → 數字
- 假設「requirements 在 3.12 要修相容」→ 推翻：python3.12.14 venv 直接裝成功（openai 1.108.2 / reportlab 4.4.4 / lxml 6.1.3），main.py 無需改。
- 假設「main.py 沒 DRY_RUN 可直接乾跑」→ 推翻：`OpenAI(api_key=None)` 在 import 時就拋錯。改 summarize_with_llm.py：DRY_RUN=1 不建 client、回罐頭摘要。
- 原 workflow 的 LINE curl 重複兩次（會推兩則）→ run_daily.sh 只送一次，並用 `.line_sent_YYYYMMDD` 防重送。
- 派工 3 次：第 1、2 次 opencode 免費執行者因 brief 內的 repo 絕對路徑（含 hydra-verify 的絕對 python）去 `cd` 外部被自動拒絕，產出 0 檔；改相對路徑＋`{python}` placeholder 後第 3 次成功。
- 乾跑（DRY_RUN=1，真抓 RSS）：31 秒、17/30 來源有文章（其餘「今日無新文章」非錯誤）、收錄 128 篇、PDF 168 KB、0 失敗、log 無 secret、tracked 檔已還原。
- sabotage：無 OPENAI_API_KEY → exit 2 ✅；PY=/usr/bin/false → exit 3 ✅。

## 待決
keychain 目前沒有三個 secret（`security find-generic-password -s news_crawl -a …` 均 no），需 owner 放入（見回報）。
## 未驗證
真實 launchd 觸發、git push（SSH 金鑰是否免密碼）、LINE 實送——等 secrets 與 PM 驗收後。

## 安裝注意（README 未收，Edit 被 guard 擋）
安裝 plist 前先 `mkdir -p ~/Library/Logs/news_crawl`：launchd 開 StandardOutPath 時不會自建目錄。
