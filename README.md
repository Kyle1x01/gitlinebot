# LINE Bot 3C 助手

這是一個基於 LINE Messaging API 和 OpenAI API 的 LINE Bot 應用，提供 3C 產品諮詢、價格查詢和購物車功能。

## 功能特點

- 3C 產品諮詢和推薦
- 產品價格查詢
- 產品資訊查詢
- 產品比較
- 購物車功能

## 技術架構

- Flask: Web 框架
- LINE Messaging API: 處理 LINE 訊息
- OpenAI API: 自然語言處理
- SQLite: 資料儲存

## 部署指南 (Render)

1. 在 Render 上創建一個新的 Web Service
2. 連接到您的 GitHub 儲存庫
3. 設定以下參數：
   - Name: 您的應用名稱
   - Environment: Python 3
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn wsgi:application`
4. 添加以下環境變數：
   - LINE_CHANNEL_SECRET: 您的 LINE Channel Secret
   - LINE_CHANNEL_ACCESS_TOKEN: 您的 LINE Channel Access Token
   - OPENAI_API_KEY: 您的 OpenAI API Key
5. 點擊「Create Web Service」

## 本地開發

1. 克隆儲存庫
2. 安裝依賴：`pip install -r requirements.txt`
3. 創建 `.env` 文件並添加必要的環境變數
4. 運行應用：`python app/app.py`

## 環境變數

- LINE_CHANNEL_SECRET: LINE Channel Secret
- LINE_CHANNEL_ACCESS_TOKEN: LINE Channel Access Token
- OPENAI_API_KEY: OpenAI API Key

## 授權

MIT License