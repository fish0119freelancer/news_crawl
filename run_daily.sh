#!/bin/bash
set -u

export TZ="Asia/Taipei"
export PATH="/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin:${PATH:-}"

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT" || exit 1

PY="${PY:-$PROJECT/venv/bin/python}"
TODAY="$(date +%Y%m%d)"

LOG_DIR="${NEWS_LOG_DIR:-$HOME/Library/Logs/news_crawl}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/run_${TODAY}.log"

exec >>"$LOG" 2>&1

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "=== 開始執行每日排程 (${TODAY}) ==="

OPENAI_API_KEY=""
LINE_TOKEN=""
LINE_USER_ID=""
SKIP_LINE=0

if [ "${DRY_RUN:-0}" = "1" ]; then
    export DRY_RUN=1
    log "DRY_RUN 模式已啟用：略過 Keychain 讀取、git pull、複製 docs、git commit/push、LINE 發送"
else
    log "從 Keychain 讀取 secrets..."
    OPENAI_API_KEY="$(security find-generic-password -s news_crawl -a OPENAI_API_KEY -w 2>/dev/null || true)"
    if [ -z "$OPENAI_API_KEY" ]; then
        log "錯誤：缺 OPENAI_API_KEY，無法繼續執行"
        exit 2
    fi
    export OPENAI_API_KEY

    LINE_TOKEN="$(security find-generic-password -s news_crawl -a LINE_TOKEN -w 2>/dev/null || true)"
    LINE_USER_ID="$(security find-generic-password -s news_crawl -a LINE_USER_ID -w 2>/dev/null || true)"
    if [ -z "$LINE_TOKEN" ] || [ -z "$LINE_USER_ID" ]; then
        log "警告：缺 LINE_TOKEN 或 LINE_USER_ID，將略過 LINE 發送"
        SKIP_LINE=1
    fi
fi

log "還原 tracked 檔案 (flex_articles.json flex_urls.txt title.txt)..."
git checkout -- flex_articles.json flex_urls.txt title.txt 2>/dev/null || true

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
if [ "${DRY_RUN:-0}" != "1" ]; then
    if [ "$CURRENT_BRANCH" = "main" ]; then
        log "目前分支為 main，執行 git pull --ff-only origin main..."
        if ! git pull --ff-only origin main; then
            log "警告：git pull --ff-only origin main 失敗，繼續執行後續步驟"
        fi
    else
        log "警告：目前分支為 '${CURRENT_BRANCH}'（非 main），略過 git pull"
    fi
fi

log "執行 main.py..."
if ! "$PY" main.py; then
    log "錯誤：執行 main.py 失敗"
    exit 3
fi
log "main.py 執行成功"

PDF_FILE="news_summary_${TODAY}.pdf"
if [ ! -f "$PDF_FILE" ]; then
    log "錯誤：未找到產出的 PDF 檔案 $PDF_FILE"
    exit 4
fi
log "確認產出 PDF 檔案: $PDF_FILE"

if [ "${DRY_RUN:-0}" = "1" ]; then
    log "DRY_RUN 模式：還原 tracked 檔案 (flex_articles.json flex_urls.txt title.txt) 並退出"
    git checkout -- flex_articles.json flex_urls.txt title.txt 2>/dev/null || true
    log "DRY_RUN 執行成功完成"
    exit 0
fi

log "複製 PDF 至 docs/..."
mkdir -p docs
cp "$PDF_FILE" "docs/$PDF_FILE"
touch docs/.nojekyll

if [ "$CURRENT_BRANCH" = "main" ]; then
    log "目前分支為 main，進行 git add、commit 與 push..."
    git add "docs/$PDF_FILE"
    if git diff --staged --quiet; then
        log "docs/$PDF_FILE 無變更，略過 commit"
    else
        git commit -m "update daily report: ${TODAY}" || log "git commit 無變更或略過"
    fi
    if ! git push origin main; then
        log "警告：git push origin main 失敗，只記 log，繼續執行 LINE 通知"
    fi
else
    log "警告：目前分支為 '${CURRENT_BRANCH}'（非 main），略過 commit 與 push"
fi

if [ "$SKIP_LINE" = "1" ]; then
    log "警告：缺 LINE 憑證，略過 LINE 發送"
    exit 0
fi

SENT_FLAG="$LOG_DIR/.line_sent_${TODAY}"
if [ -f "$SENT_FLAG" ] && [ "${FORCE_LINE:-0}" != "1" ]; then
    log "今日已發送過 LINE 訊息（$SENT_FLAG 存在且 FORCE_LINE!=1），略過發送"
    exit 0
fi

log "組裝 LINE 訊息 payload..."
ORIGIN_URL="$(git remote get-url origin 2>/dev/null || echo "")"
export ORIGIN_URL TODAY LINE_USER_ID

PAYLOAD=$("$PY" -I - <<'PYEOF'
import json
import os
import re

origin_url = os.environ.get("ORIGIN_URL", "").strip()
origin_url = re.sub(r"\.git$", "", origin_url).rstrip("/")
parts = re.split(r"[:/]", origin_url)
if len(parts) >= 2:
    owner = parts[-2]
    repo = parts[-1]
else:
    owner = "fish0119freelancer"
    repo = "news_crawl"

today = os.environ.get("TODAY", "")
pdf_url = f"https://{owner}.github.io/{repo}/news_summary_{today}.pdf"

title_file = "title.txt"
titles = "(無標題)"
if os.path.isfile(title_file):
    try:
        with open(title_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                titles = content
    except Exception:
        titles = "(無標題)"

msg = f"嗨!大家! 這是今天{today}的每日生醫新聞報告 :\n  {titles}\n  {pdf_url}"
line_user_id = os.environ.get("LINE_USER_ID", "")

payload = {
    "to": line_user_id,
    "messages": [
        {
            "type": "text",
            "text": msg
        }
    ]
}

print(json.dumps(payload, ensure_ascii=False))
PYEOF
)

log "發送 LINE 推播訊息..."
HTTP_CODE=$(printf 'header = "Authorization: Bearer %s"\n' "$LINE_TOKEN" | curl -K - -s -o /dev/null -w "%{http_code}" -X POST https://api.line.me/v2/bot/message/push -H "Content-Type: application/json" -d "$PAYLOAD")

if [ "$HTTP_CODE" = "200" ]; then
    log "LINE 訊息發送成功 (HTTP 200)"
    touch "$SENT_FLAG"
else
    log "錯誤：LINE 訊息發送失敗 (HTTP $HTTP_CODE)"
    exit 5
fi

log "=== 每日排程全部順利完成 ==="
exit 0
