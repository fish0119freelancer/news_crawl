# README.md
# 🗞️ News Summary Agent
自動爬取新聞 → 由 GPT 總結與評論 → 產出 Markdown 報告


## ✅ 功能
- 使用 GPT-3.5 生成摘要與分析
- 包含出處、發布時間、主觀觀點
- 支援多個新聞網址輸入，批次處理


## 🚀 使用方法
```bash
pip install openai newspaper3k


# 將欲處理的網址放入 urls.txt
python main.py
```


## 🔜 待辦
- [ ] 加上 LINE Notify / Email 通知
- [ ] 自動排程（crontab）
- [ ] PDF 報告匯出