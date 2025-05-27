from flask import Flask, request, abort
from dotenv import load_dotenv
from app.crawler.crawler import get_product_price
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    FollowEvent
)
import os
import re
import json
import openai
import openai
from urllib.parse import quote

# ✅ 載入 .env 檔案
load_dotenv()

app = Flask(__name__)

# ✅ 初始化 LINE 驗證
configuration = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
line_handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

# ✅ 初始化 OpenAI API
openai.api_key = os.getenv("OPENAI_API_KEY")

if not os.getenv("LINE_CHANNEL_SECRET") or not os.getenv("LINE_CHANNEL_ACCESS_TOKEN") or not os.getenv("OPENAI_API_KEY"):
    print("❌ 環境變數未正確設置")
    print("請確認 LINE_CHANNEL_SECRET、LINE_CHANNEL_ACCESS_TOKEN 和 OPENAI_API_KEY 是否存在")
    exit(1)

# 用戶狀態管理
user_states = {}

# 定義常用容量選項
STORAGE_OPTIONS = ["64GB", "128GB", "256GB", "512GB", "1TB"]

# GPT 調用函數
def call_gpt_with_web_search(prompt):
    try:
        client = openai
        response = client.responses.create(
            model="gpt-4.1",
            tools=[{"type": "web_search_preview"}],
            input=prompt
        )
        return response.output_text
    except Exception as e:
        app.logger.error(f"GPT API 錯誤: {str(e)}")
        return f"無法連接到 GPT 服務: {str(e)}"

# 比較兩個裝置
# 比較兩個裝置
def compare_devices(device1, device2):
    prompt = f"""請比較以下兩款手機的規格（必須包含裝置名稱、處理器、記憶體、儲存空間、螢幕、前後鏡頭、電池與重量）：
    1. {device1}
    2. {device2}
    
    請在最後列出兩款機型的優劣勢分析與適合的人群，並以適合LINE訊息的方式輸出（需有易讀性）。
    請確保每個內容都需要查詢過確保回答的正確性。"""

    try:
        client = openai
        response = client.responses.create(
            model="gpt-4.1",
            tools=[{"type": "web_search_preview"}],
            input=prompt
        )
        return response.output_text
    except Exception as e:
        return f"查詢發生錯誤：{str(e)}"

# 獲取裝置價格
def get_device_price(device_name):
    price_info = get_product_price(device_name)
    if price_info and "status" in price_info and price_info["status"] == "success":
        data = price_info["data"]
        result = f"📱 {data.get('brand', '未知品牌')} {data.get('model', '未知型號')}\n\n"
        
        for spec_price in data.get('specs_prices', []):
            result += f"📋 規格: {spec_price.get('spec', '規格不詳')}\n"
            result += f"💰 發售價格: {spec_price.get('original_price', '資訊不足')}\n"
            result += f"💰 目前最低價格: {spec_price.get('price', '資訊不足')}\n\n"
        
        result += f"🔗 資料來源: SOGI手機王 ({data.get('url', 'https://www.sogi.com.tw/')})\n"
        return result
    else:
        return "💰 價格資訊: 無法獲取價格資訊，請直接訪問 SOGI手機王 (https://www.sogi.com.tw/)"

#裝置資訊查詢
def get_device_info(device_query):
    prompt = f"""請提供關於 {device_query} 的台灣版本詳細資訊，包括：\n 1. 主要規格（僅限台灣版）\n 2. 最新價格範圍（台灣市場）\n 3. 優缺點分析\n 4. 適合的使用場景\n 5. 市場評價（台灣用戶）\n \n 請確保回覆為純文字，且不包含任何外部連結。"""
    return call_gpt_with_web_search(prompt)

# 換機建議
def get_upgrade_recommendation(current_phone, upgrade_cycle, requirements, budget):
    prompt = f"""請根據以下資訊，推薦1-3款在台灣上市的手機：\n - 目前使用的手機：{current_phone}\n - 換機週期：{upgrade_cycle}\n - 特定需求：{requirements}\n - 預算：{budget}\n \n 請提供以下資訊：\n 1. 推薦的1-3款手機型號\n 2. 每款手機的優缺點\n 3. 這些手機適合用戶的需求\n 4. 價格範圍（以台幣顯示）\n \n 請確保回覆為純文字，且不包含任何外部連結。"""
    response = client.responses.create(
        model="gpt-4.1",
        tools=[{"type": "web_search_preview"}],
        input=prompt
    )
    
    return response.output_text

# 顯示幫助信息
def show_help():
    return """📝 使用說明：

1️⃣ 裝置價格查詢
   格式：直接輸入裝置名稱
   例如：iPhone 15 Pro

2️⃣ 裝置資訊查詢
   格式：直接輸入裝置名稱
   例如：Samsung Galaxy S24 Ultra

3️⃣ 裝置比較
   格式：裝置1 vs 裝置2
   例如：iPhone 15 Pro vs Samsung S24 Ultra

4️⃣ 換機建議
   將引導您提供：
   - 目前使用的手機
   - 換機週期
   - 特定需求
   - 預算

5️⃣ 查看說明
   顯示此幫助訊息

請輸入數字 1-5 選擇功能"""

# ✅ 設定 Webhook 路由
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    app.logger.info(f"Request body: {body}")
    
    try:
        line_handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.warning("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)
    
    return 'OK', 200

# 🟢 新增一個根路由，避免 404 Not Found 問題
@app.route("/", methods=['GET'])
def health_check():
    return "LINE Bot is running!", 200

# ✅ 設定測試路由
@app.route("/test", methods=['GET'])
def test_gpt():
    try:
        response = call_gpt_with_web_search("請提供最新的iPhone系列型號和特點")
        return response, 200
    except Exception as e:
        return f"Error: {str(e)}", 500

# ✅ 處理加入好友事件
@line_handler.add(FollowEvent)
def handle_follow(event):
    welcome_text = """🎉 歡迎使用3吸裝置比較助手手！

請選擇您需要的功能：
1️⃣ 裝置價格查詢
2️⃣ 裝置資訊查詢
3️⃣ 裝置比較
4️⃣ 換機建議
5️⃣ 查看說明

請輸入數字 1-5 選擇功能"""

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=welcome_text)]
            )
        )

# ✅ 設定訊息處理
@line_handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    try:
        user_input = event.message.text.strip()
        user_id = event.source.user_id

        # 如果用戶不在任何狀態中，顯示功能選單
        if user_id not in user_states:
            if user_input.lower() in ["1", "2", "3", "4", "5"]:
                # 處理功能選擇
                if user_input == "1":
                    reply_text = "請輸入您想查詢價格的裝置名稱\n例如：iPhone 15 Pro"
                    user_states[user_id] = {"flow": "price", "step": "waiting_input"}
                elif user_input == "2":
                    reply_text = "請輸入您想查詢的裝置名稱\n例如：Samsung Galaxy S24 Ultra"
                    user_states[user_id] = {"flow": "info", "step": "waiting_input"}
                elif user_input == "3":
                    reply_text = "請使用格式：裝置1 vs 裝置2\n例如：iPhone 15 Pro vs Samsung S24 Ultra"
                    user_states[user_id] = {"flow": "compare", "step": "waiting_input"}
                elif user_input == "4":
                    user_states[user_id] = {"flow": "upgrade", "step": "current_phone"}
                    reply_text = "請告訴我您目前使用的手機型號？"
                elif user_input == "5":
                    reply_text = show_help()
            else:
                reply_text = """🎉  歡迎使用3吸裝置比較助手手！

請選擇您需要的功能：
1️⃣ 裝置價格查詢
2️⃣ 裝置資訊查詢
3️⃣ 裝置比較
4️⃣ 換機建議
5️⃣ 查看說明

請輸入數字 1-5 選擇功能"""
        else:
            # 處理各功能的具體邏輯
            state = user_states[user_id]
            if state["flow"] == "price" and state["step"] == "waiting_input":
                reply_text = get_device_price(user_input)
                del user_states[user_id]
            elif state["flow"] == "info" and state["step"] == "waiting_input":
                reply_text = get_device_info(user_input)
                del user_states[user_id]
            elif state["flow"] == "compare" and state["step"] == "waiting_input":
                if "vs" not in user_input:
                    reply_text = "格式錯誤，請使用：裝置1 vs 裝置2"
                else:
                    devices = user_input.split("vs")
                    reply_text = compare_devices(devices[0].strip(), devices[1].strip())
                    del user_states[user_id]
            elif state["flow"] == "upgrade":
                if state["step"] == "current_phone":
                    state["current_phone"] = user_input
                    state["step"] = "upgrade_cycle"
                    reply_text = "您大約多久換一次手機？（例如：2年、3年等）"
                elif state["step"] == "upgrade_cycle":
                    state["upgrade_cycle"] = user_input
                    state["step"] = "requirements"
                    reply_text = "您有什麼特定需求？（例如：拍照、遊戲、續航等）"
                elif state["step"] == "requirements":
                    state["requirements"] = user_input
                    state["step"] = "budget"
                    reply_text = "您的預算是多少？"
                elif state["step"] == "budget":
                    reply_text = get_upgrade_recommendation(
                        state["current_phone"],
                        state["upgrade_cycle"],
                        state["requirements"],
                        user_input
                    )
                    del user_states[user_id]
            elif state["flow"] == "repair":
                if state["step"] == "device_model":
                    state["device_model"] = user_input
                    state["step"] = "damaged_part"
                    reply_text = "請告訴我損壞的部件是什麼？（例如：螢幕、電池、相機等）"
                elif state["step"] == "damaged_part":
                    reply_text = evaluate_repair_value(state["device_model"], user_input)
                    del user_states[user_id]
            elif state["flow"] == "storage_query" and state["step"] == "waiting_for_storage":
                reply_text = get_device_info(
                    f"{state['brand']}-{state['model']}-{user_input}"
                )
                del user_states[user_id]

        # 發送回覆
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )

    except Exception as e:
        app.logger.error(f"錯誤：{str(e)}")
        error_message = "抱歉，系統暫時無法處理您的請求。\n請稍後再試，或嘗試其他關鍵字搜尋。"
        
        try:
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=error_message)]
                    )
                )
        except Exception as reply_error:
            app.logger.error(f"回覆錯誤訊息失敗：{str(reply_error)}")

# 預先載入商品資料
try:
    from crawler.crawler import load_product_url_map
    print("✅ 正在載入商品資料...")
    product_list = load_product_url_map()
    print(f"✅ 已載入 {len(product_list)} 筆商品資料")
except Exception as e:
    print(f"❌ 載入商品資料失敗：{str(e)}")

# 🟢 主程式啟動 - 適用於本地開發和 Vercel 部署
if __name__ == "__main__":
    print("✅ 啟動 LINE Bot 服務...")
    app.run(host='0.0.0.0', port=5000, debug=True)


def main_menu():
    while True:
        user_input = input("請輸入指令（輸入 'Q' 退出）：")
        if user_input.upper() == 'Q':
            print("歡迎使用，再見！")
            break
        # 顯示功能選單
        print(show_help())

main_menu()