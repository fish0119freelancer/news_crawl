# news_crawl macOS launchd 排程設定

本目錄包含 macOS `launchd` 的排程設定檔 `com.fish.news-crawl.plist`，設定每日早上 09:00（台北時間）自動執行 `run_daily.sh`。

## 前置作業：設定 Keychain Secrets
`run_daily.sh` 從 macOS Keychain 讀取憑證，請先透過以下指令存入：
```bash
security add-generic-password -s news_crawl -a OPENAI_API_KEY -w "<YOUR_OPENAI_API_KEY>" -U
security add-generic-password -s news_crawl -a LINE_TOKEN -w "<YOUR_LINE_TOKEN>" -U
security add-generic-password -s news_crawl -a LINE_USER_ID -w "<YOUR_LINE_USER_ID>" -U
```

## 安裝與載入

1. 複製 plist 到使用者 LaunchAgents 目錄：
```bash
cp launchd/com.fish.news-crawl.plist ~/Library/LaunchAgents/
```

2. 載入並啟用服務：
```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.fish.news-crawl.plist
```

3. 立即手動測試執行（kickstart）：
```bash
launchctl kickstart -k gui/$(id -u)/com.fish.news-crawl
```

4. 檢查狀態與 Log：
```bash
launchctl print gui/$(id -u)/com.fish.news-crawl
cat ~/Library/Logs/news_crawl/run_$(date +%Y%m%d).log
cat ~/Library/Logs/news_crawl/launchd.out.log
cat ~/Library/Logs/news_crawl/launchd.err.log
```

5. 卸載服務（若需更新或停止）：
```bash
launchctl bootout gui/$(id -u)/com.fish.news-crawl
```
