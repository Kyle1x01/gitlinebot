from flask import Flask, request, abort
from dotenv import load_dotenv
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
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
import openai
import os
import sqlite3
import json
import re
from datetime import datetime, timedelta
from langdetect import detect, DetectorFactory
import logging
import requests
from typing import Dict, List, Optional, Tuple

# 設定語言偵測的隨機種子，確保結果一致性
DetectorFactory.seed = 0

# 載入環境變數
load_dotenv()

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# LINE Bot 設定
line_bot_api = MessagingApi(
    ApiClient(
        Configuration(
            access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
        )
    )
)
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# OpenAI 設定
from openai import OpenAI
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# 全域變數
user_conversations = {}
product_database = {}

# 資料庫初始化
def init_database():
    """初始化 SQLite 資料庫"""
    try:
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        
        # 創建購物車表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cart (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                product TEXT NOT NULL,
                quantity INTEGER DEFAULT 1,
                price REAL,
                added_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 創建產品資料表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT,
                specifications TEXT,
                pchome_price REAL,
                momo_price REAL,
                shopee_price REAL,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 創建用戶偏好表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id TEXT PRIMARY KEY,
                preferred_language TEXT DEFAULT 'zh-tw',
                budget_range TEXT,
                preferred_brands TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("資料庫初始化完成")
    except Exception as e:
        logger.error(f"資料庫初始化失敗: {e}")

# 對話記憶功能
def get_conversation_history(user_id: str, max_messages: int = 6) -> List[Dict]:
    """獲取用戶對話歷史，限制最大訊息數量避免token超限"""
    if user_id not in user_conversations:
        user_conversations[user_id] = []
    return user_conversations[user_id][-max_messages:]

def add_to_conversation(user_id: str, role: str, content: str):
    """新增對話到歷史記錄"""
    if user_id not in user_conversations:
        user_conversations[user_id] = []
    
    user_conversations[user_id].append({
        'role': role,
        'content': content,
        'timestamp': datetime.now().isoformat()
    })
    
    # 限制對話歷史長度
    if len(user_conversations[user_id]) > 20:
        user_conversations[user_id] = user_conversations[user_id][-20:]

def clear_old_conversations():
    """清理舊對話記錄"""
    cutoff_time = datetime.now() - timedelta(hours=24)
    
    for user_id in list(user_conversations.keys()):
        user_conversations[user_id] = [
            msg for msg in user_conversations[user_id]
            if datetime.fromisoformat(msg.get('timestamp', '1970-01-01')) > cutoff_time
        ]
        
        if not user_conversations[user_id]:
            del user_conversations[user_id]



# 修正後的功能：產品價格查詢（新增二手價格，保持原有 OpenAI 設定）
def get_device_price(device_name: str, user_id: str = None) -> str:
    """查詢設備價格資訊，包含新品和二手價格"""
    conversation_history = []
    if user_id:
        history = get_conversation_history(user_id, 4)
        conversation_history = [{"role": msg["role"], "content": msg["content"]} for msg in history]
    
    system_message = {
        "role": "system",
        "content": (
            "你是專業的3C產品價格查詢助理。預設以繁體中文回答，語氣專業且親切。"
            "請提供準確的價格資訊，包含："
            "1. 新品價格：不同通路的價格比較（PChome、Momo 購物網、蝦皮商城、Yahoo奇摩購物、神腦線上、順發3C、燦坤、原價屋）"
            "2. 二手價格：參考各大二手交易平台（如蝦皮拍賣、露天拍賣、Facebook Marketplace、旋轉拍賣、Yahoo拍賣等）的行情價格"
            "3. 二手價格應包含不同成色的價格區間（如：全新未拆、近全新、良好、普通等）"
            "回答格式請使用條列式，清楚區分新品價格和二手價格。"
            "請控制回答在1000字以內，不要使用表情符號或外部連結。"
            "產品必須是在台灣主要線上通路有販售的商品"
            "請以適合line訊息的方式輸出（需有易讀性）"
        )
    }
    
    try:
        messages = [system_message] + conversation_history + [
            {"role": "user", "content": f"請查詢 {device_name} 的價格資訊，包含新品和二手價格"}
        ]
        
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            max_tokens=1500,
            temperature=0.5
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"價格查詢失敗: {e}")
        return "抱歉，目前無法查詢價格資訊，請稍後再試。如需協助，請提供更具體的產品型號。"
        
    except Exception as e:
        logger.error(f"價格查詢失敗: {e}")
        return "抱歉，目前無法查詢價格資訊，請稍後再試。如需協助，請提供更具體的產品型號。"

# 原有功能：3C產品規格查詢
def get_3c_product_info(product_name: str, user_id: str = None) -> str:
    """查詢3C產品詳細規格資訊"""
    conversation_history = []
    if user_id:
        history = get_conversation_history(user_id, 4)
        conversation_history = [{"role": msg["role"], "content": msg["content"]} for msg in history]
    
    system_message = {
        "role": "system",
        "content": (
            "你是一個專業的3C產品規格資訊助理。預設以繁體中文回答，使用者若有其他語言需求則更換成使用者所需語言，語氣專業且親切。"
            "請提供詳細且準確的產品規格資訊，包括："
            "1. 產品基本資訊（品牌、型號、發布時間）"
            "2. 核心規格（處理器、記憶體、儲存空間等）"
            "3. 特色功能和優缺點分析"
            "4. 適用族群建議"
            "產品產品必須是在台灣主要線上通路（如 PChome、Momo 購物網、蝦皮商城、Yahoo奇摩購物、神腦線上、順發3C、燦坤、原價屋）有販售的商品。"
            "請以適合LINE訊息的方式輸出（需有易讀性）。 請確保每個內容都需要查詢過確保回答的正確性。"
            "回答請控制在1000字以內，不要使用表情符號、外部連結或表格格式。"
        )
    }
    
    try:
        messages = [system_message] + conversation_history + [
            {"role": "user", "content": f"請提供 {product_name} 的詳細規格資訊"}
        ]
        
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            max_tokens=15000,
            temperature=0.5
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"產品資訊查詢失敗: {e}")
        return "抱歉，目前無法取得產品資訊，請稍後再試。建議您：\n1. 確認產品名稱是否正確\n2. 稍後重新查詢\n3. 聯繫客服取得協助"

# 原有功能：產品比較
def compare_devices(device1: str, device2: str, user_id: str = None) -> str:
    """比較兩個設備的功能和規格"""
    conversation_history = []
    if user_id:
        history = get_conversation_history(user_id, 4)
        conversation_history = [{"role": msg["role"], "content": msg["content"]} for msg in history]
    
    system_message = {
        "role": "system",
        "content": (
            "你是專業的3C產品比較專家。請以繁體中文提供詳細的產品比較分析。"
            "比較內容應包含：規格對比、效能差異、價格分析、使用情境建議。"
            "請保持客觀中立，提供實用的購買建議。回答控制在800字以內。"
            "對不同的3c產品做基本規格比較（處理器、RAM、儲存空間、電池、螢幕尺寸/類型、重量）。"
            "額外比較項目（螢幕更新率、作業系統版本、快充支援、相機功能、功率、效能）。"
            "最後提供簡短分析，說明各自適合的使用者類型（拍照、遊戲、預算等）。"
            "請將回覆控制在1000字以內，且不要使用表格、Emoji 或加入外部連結。"
            "請以適合LINE訊息的方式輸出（需有易讀性）。 請確保每個內容都需要查詢過確保回答的正確性。"
            "比較產品必須有在官網或者台灣主要線上通路（如 PChome、Momo 購物網、蝦皮商城、Yahoo奇摩購物、神腦線上、順發3C、燦坤、原價屋）有販售的商品。"
        )
    }
    
    try:
        messages = [system_message] + conversation_history + [
            {"role": "user", "content": f"請比較 {device1} 和 {device2} 的差異"}
        ]
        
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            max_tokens=1500,
            temperature=0.5
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"產品比較失敗: {e}")
        return "抱歉，目前無法進行產品比較，請稍後再試或提供更具體的產品型號。"

# 原有功能：升級推薦
def get_upgrade_recommendation_single(user_input: str, user_id: str = None) -> str:
    """根據用戶需求提供升級推薦"""
    conversation_history = []
    if user_id:
        history = get_conversation_history(user_id, 4)
        conversation_history = [{"role": msg["role"], "content": msg["content"]} for msg in history]
    
    system_message = {
        "role": "system",
        "content": (
            "你是專業的3C產品更換顧問。請根據使用者的需求和預算，推薦3-5款合適的產品。"
            "推薦時請考慮："
            "1. 使用者的具體需求和使用情境"
            "2. 預算範圍和性價比"
            "3. 產品的實際可用性和評價"
            "請提供具體的產品型號、規格重點、價格區間，並說明推薦理由。"
            "產品篩選： 推薦產品必須是在台灣主要線上通路（如 PChome、Momo 購物網、蝦皮商城、Yahoo奇摩購物、神腦線上、順發3C、燦坤、原價屋）有販售的商品。"
            "回答請控制在1000字以內，語氣專業且親切。"
            "請以適合LINE訊息的方式輸出（需有易讀性）。 請確保每個內容都需要查詢過確保回答的正確性。"
            "僅提供文字建議，不要附帶任何外部連結或表情符號。"
            "回覆開頭可簡要說明推薦依據，接著以清單形式列出各項產品建議，確保內容條理清晰便於閱讀。"
        )
    }
    
    try:
        messages = [system_message] + conversation_history + [
            {"role": "user", "content": user_input}
        ]
        
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            max_tokens=1500,
            temperature=0.5
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"升級推薦失敗: {e}")
        return "抱歉，目前無法提供升級推薦，請稍後再試。建議您提供更詳細的需求描述以獲得更精準的推薦。"

# 原有功能：熱門排行榜
def get_popular_ranking(category: str, user_id: str = None) -> str:
    """取得熱門產品排行榜"""
    conversation_history = []
    if user_id:
        history = get_conversation_history(user_id, 4)
        conversation_history = [{"role": msg["role"], "content": msg["content"]} for msg in history]
    
    system_message = {
        "role": "system",
        "content": (
            "你是專業的3C產品市場分析師。請提供指定類別的熱門產品排行榜。"
            "排行榜應包含："
            "1. 前1-10名的熱門產品"
            "2. 產品名稱和排名"
            "3. 每個產品的核心特色"
            "4. 大概的價格區間"
            "5. 適合的使用族群"
            "6. 熱門原因"
            "請基於市場銷量、用戶評價、專業評測等綜合因素排名。"
            "價格請參考台灣市場實際售價。回答控制在1000字以內，不使用emoji或外部連結"
            "請以適合LINE訊息的方式輸出（需有易讀性）"
        )
    }
    
    try:
        messages = [system_message] + conversation_history + [
            {"role": "user", "content": f"請提供 {category} 的熱門排行榜"}
        ]
        
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            max_tokens=1500,
            temperature=0.5
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"排行榜查詢失敗: {e}")
        return "抱歉，目前無法取得排行榜資訊，請稍後再試或指定更具體的產品類別。"

# 原有功能：產品評價彙整
def get_product_reviews(product_name: str, user_id: str = None) -> str:
    """彙整產品評價和使用心得"""
    conversation_history = []
    if user_id:
        history = get_conversation_history(user_id, 4)
        conversation_history = [{"role": msg["role"], "content": msg["content"]} for msg in history]
    
    system_message = {
        "role": "system",
        "content": (
            "你是專業的3C產品評測分析師。請彙整指定產品的評價和使用心得。"
            "評價彙整應包含："
            "1. 整體評分和主要優點"
            "2. 常見的使用問題或缺點"
            "3. 不同使用情境的表現"
            "4. 與競品的比較優勢"
            "5. 購買建議和注意事項"
            "6. 用戶評價趨勢"
            "7. 購買建議"
            "基於PTT、Mobile01等討論區和評測網站資訊。"
            "請綜合專業評測、用戶評價、論壇討論等多方資訊。"
            "保持客觀中立，提供實用的參考資訊。回答控制在1000字以內。"
            "請以適合LINE訊息的方式輸出（需有易讀性）"
        )
    }
    
    try:
        messages = [system_message] + conversation_history + [
            {"role": "user", "content": f"請彙整 {product_name} 的評價和使用心得"}
        ]
        
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            max_tokens=1500,
            temperature=0.5
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"評價彙整失敗: {e}")
        return "抱歉，目前無法取得評價資訊，請稍後再試或提供更具體的產品型號。"

# 語言偵測功能
def detect_language(text: str) -> str:
    """偵測文字語言"""
    try:
        # 移除特殊字符和數字，只保留字母
        clean_text = re.sub(r'[^\w\s]', '', text)
        if len(clean_text.strip()) < 3:
            return 'zh-tw'  # 預設繁體中文
        
        detected = detect(clean_text)
        
        # 語言映射
        language_map = {
            'zh-cn': 'zh-tw',  # 簡體轉繁體
            'zh': 'zh-tw',
            'en': 'en',
            'ja': 'ja',
            'ko': 'ko'
        }
        
        return language_map.get(detected, 'zh-tw')
    except Exception as e:
        logger.warning(f"語言偵測失敗: {e}")
        return 'zh-tw'

# 購物車功能
def add_to_cart(user_id: str, product_name: str, quantity: int = 1) -> bool:
    """新增商品至購物車"""
    try:
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        
        # 檢查是否已存在
        cursor.execute('SELECT id, quantity FROM cart WHERE user_id = ? AND product = ?', 
                      (user_id, product_name))
        existing = cursor.fetchone()
        
        if existing:
            # 更新數量
            new_quantity = existing[1] + quantity
            cursor.execute('UPDATE cart SET quantity = ? WHERE id = ?', 
                          (new_quantity, existing[0]))
        else:
            # 新增商品
            cursor.execute('INSERT INTO cart (user_id, product, quantity) VALUES (?, ?, ?)', 
                          (user_id, product_name, quantity))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"新增至購物車失敗: {e}")
        return False

def get_cart_items(user_id: str) -> List[Dict]:
    """取得購物車商品"""
    try:
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT product, quantity, added_time FROM cart WHERE user_id = ?', 
                      (user_id,))
        items = cursor.fetchall()
        conn.close()
        
        return [{
            'product': item[0],
            'quantity': item[1],
            'added_time': item[2]
        } for item in items]
    except Exception as e:
        logger.error(f"取得購物車失敗: {e}")
        return []

def remove_from_cart(user_id: str, product_name: str) -> bool:
    """從購物車移除商品"""
    try:
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM cart WHERE user_id = ? AND product = ?', 
                      (user_id, product_name))
        
        affected_rows = cursor.rowcount
        conn.commit()
        conn.close()
        
        return affected_rows > 0
    except Exception as e:
        logger.error(f"從購物車移除失敗: {e}")
        return False

# 意圖識別和回應處理
def detect_intent_and_respond(user_input: str, user_id: str) -> str:
    """智能識別用戶意圖並提供對應回應"""
    user_input_lower = user_input.lower()
    
    # 價格查詢意圖
    if any(keyword in user_input_lower for keyword in ['價格', '多少錢', 'price', '售價', '報價']):
        product_name = extract_product_name(user_input)
        if product_name:
            return get_device_price(product_name, user_id)
    
    # 產品比較意圖
    elif any(keyword in user_input_lower for keyword in ['比較', 'vs', '對比', 'compare', '差別', '差異']):
        products = extract_comparison_products(user_input)
        if len(products) >= 2:
            return compare_devices(products[0], products[1], user_id)
    
    # 推薦意圖
    elif any(keyword in user_input_lower for keyword in ['推薦', '建議', 'recommend', '選擇', '買什麼']):
        return get_upgrade_recommendation_single(user_input, user_id)
    
    # 排行榜意圖
    elif any(keyword in user_input_lower for keyword in ['排行榜', '排名', 'ranking', '熱門', '暢銷']):
        category = extract_product_category(user_input)
        return get_popular_ranking(category or '3C產品', user_id)
    
    # 評價意圖
    elif any(keyword in user_input_lower for keyword in ['評價', '評測', 'review', '心得', '使用感想']):
        product_name = extract_product_name(user_input)
        if product_name:
            return get_product_reviews(product_name, user_id)
    
    # 規格查詢意圖
    elif any(keyword in user_input_lower for keyword in ['規格', '參數', 'spec', '配置', '詳細資訊']):
        product_name = extract_product_name(user_input)
        if product_name:
            return get_3c_product_info(product_name, user_id)
    
    # 如果沒有明確意圖，使用通用3C產品查詢
    product_name = extract_product_name(user_input)
    if product_name:
        return get_3c_product_info(product_name, user_id)
    
    # 使用GPT處理其他對話
    return handle_follow_up_question(user_input, user_id)

# 輔助函數：提取產品名稱
def extract_product_name(text: str) -> str:
    """從文字中提取產品名稱"""
    # 移除常見的查詢詞彙
    remove_words = ['價格', '多少錢', '規格', '評價', '推薦', '比較', '怎麼樣', '好不好', 
                   'price', 'spec', 'review', 'recommend', 'compare']
    
    cleaned_text = text
    for word in remove_words:
        cleaned_text = cleaned_text.replace(word, '')
    
    # 清理多餘空格
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
    
    return cleaned_text

# 輔助函數：提取比較產品
def extract_comparison_products(text: str) -> List[str]:
    """從文字中提取要比較的產品"""
    # 尋找 vs, 和, 與 等分隔符
    separators = ['vs', 'VS', '和', '與', '對比', '比較']
    
    for sep in separators:
        if sep in text:
            parts = text.split(sep)
            if len(parts) >= 2:
                product1 = extract_product_name(parts[0])
                product2 = extract_product_name(parts[1])
                return [product1, product2]
    
    return []

# 輔助函數：提取產品類別
def extract_product_category(text: str) -> str:
    """從文字中提取產品類別"""
    categories = {
        '手機': ['手機', 'phone', '智慧型手機'],
        '筆電': ['筆電', '筆記型電腦', 'laptop', 'notebook'],
        '平板': ['平板', 'tablet', 'ipad'],
        '耳機': ['耳機', 'headphone', '藍牙耳機'],
        '相機': ['相機', 'camera', '攝影機'],
        '電腦': ['電腦', 'computer', 'pc', '桌機']
    }
    
    text_lower = text.lower()
    for category, keywords in categories.items():
        if any(keyword in text_lower for keyword in keywords):
            return category
    
    return '3C產品'

# 追加提問處理
def handle_follow_up_question(user_input: str, user_id: str) -> str:
    """處理追加提問"""
    history = get_conversation_history(user_id, 6)
    
    system_message = {
        "role": "system",
        "content": (
            "你是專業的3C產品助理。請根據對話歷史回答用戶的追加提問。"
            "請以繁體中文回答，語氣專業且親切。"
            "如果問題與3C產品無關，請禮貌地引導用戶回到3C產品相關話題。"
            "回答請控制在800字以內。"
        )
    }
    
    try:
        messages = [system_message]
        
        # 加入對話歷史
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})
        
        messages.append({"role": "user", "content": user_input})
        
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=messages,
            max_tokens=800,
            temperature=0.5
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"追加提問處理失敗: {e}")
        return "抱歉，我無法理解您的問題。請嘗試詢問3C產品相關的問題，例如產品規格、價格比較或購買建議。"

# 指令解析功能
def parse_command(user_input: str, user_id: str, detected_language: str) -> str:
    """解析用戶指令"""
    user_input_lower = user_input.lower().strip()
    
    # 購物車相關指令
    if any(keyword in user_input_lower for keyword in ['新增至購物車', 'add to cart', '加入購物車']):
        # 提取產品名稱
        product_match = re.search(r'(?:新增至購物車|add to cart|加入購物車)\s+(.+)', user_input, re.IGNORECASE)
        if product_match:
            product_name = product_match.group(1).strip()
            if add_to_cart(user_id, product_name):
                return f"✅ 已將 {product_name} 加入您的購物車"
            else:
                return "❌ 新增至購物車失敗，請稍後再試"
        else:
            return "⚠️ 請在指令後提供商品名稱，例如：新增至購物車 iPhone 13"
    
    elif any(keyword in user_input_lower for keyword in ['顯示購物車', 'show cart', '我的購物車']):
        items = get_cart_items(user_id)
        if items:
            cart_text = "🛒 您的購物車：\n"
            for i, item in enumerate(items, 1):
                cart_text += f"{i}. {item['product']} (數量: {item['quantity']})\n"
            return cart_text
        else:
            return "🛒 您的購物車目前是空的"
    
    elif any(keyword in user_input_lower for keyword in ['移除', 'remove', '刪除']):
        # 提取產品名稱
        product_match = re.search(r'(?:移除|remove|刪除)\s+(.+)', user_input, re.IGNORECASE)
        if product_match:
            product_name = product_match.group(1).strip()
            if remove_from_cart(user_id, product_name):
                return f"❌ 已從您的購物車移除 {product_name}"
            else:
                return f"⚠️ 找不到 {product_name} 在您的購物車中，請確認名稱是否正確"
        else:
            return "⚠️ 請指定要移除的商品名稱"
    
    elif any(keyword in user_input_lower for keyword in ['清空購物車', 'clear cart']):
        try:
            conn = sqlite3.connect('bot_data.db')
            cursor = conn.cursor()
            cursor.execute('DELETE FROM cart WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()
            return "🗑️ 已清空您的購物車"
        except Exception as e:
            logger.error(f"清空購物車失敗: {e}")
            return "❌ 清空購物車失敗，請稍後再試"
    
    elif any(keyword in user_input_lower for keyword in ['說明', 'help', '幫助']):
        help_messages = {
            'zh-tw': """🤖 3吸小助手手使用說明：
產品規格查詢:"iPhone 13規格"
產品價格查詢:"iPhone 13價格"
產品比較："iPhone 13 vs Samsung S21"
推薦產品："推薦2萬元手機" / "筆電推薦"
熱門排行："手機排行榜" / "筆電排行榜"
產品評價："iPhone 13評價" / "MacBook評測"

🛒 購物車功能：
新增："新增至購物車 iPhone 13"
查看："顯示我的購物車" / "我的購物車"
移除："移除 iPhone 13"
清空："清空購物車"

❓ 其他指令：
"說明" - 顯示此說明
"清除對話" - 清除對話歷史""",
            'en': """🤖 3C Smart Assistant Help:

💬 Natural Conversation:
• Product Info: "iPhone 13 specs" / "iPhone 13 price"
• Compare: "iPhone 13 vs Samsung S21"
• Recommendations: "recommend phone under $600"
• Rankings: "phone ranking" / "laptop ranking"
• Reviews: "iPhone 13 review"

🛒 Shopping Cart:
• Add: "add to cart iPhone 13"
• View: "show cart" / "my cart"
• Remove: "remove iPhone 13"
• Clear: "clear cart"

🌐 Multi-language Support:
• Auto-detect your language
• Support Traditional Chinese, English, Japanese"""
        }
        return help_messages.get(detected_language, help_messages['zh-tw'])
    
    elif any(keyword in user_input_lower for keyword in ['清除對話', 'clear conversation']):
        if user_id in user_conversations:
            user_conversations[user_id] = []
        return "🗑️ 已清除對話歷史"
    
    # 如果不是特殊指令，返回 None 讓其他函數處理
    return None

# 主要訊息處理函數
def handle_user_message(user_input: str, user_id: str) -> str:
    """處理用戶訊息的主函數"""
    try:
        # 偵測語言
        detected_language = detect_language(user_input)
        
        # 記錄用戶輸入
        add_to_conversation(user_id, 'user', user_input)
        
        # 先嘗試解析特殊指令（購物車、說明等）
        command_response = parse_command(user_input, user_id, detected_language)
        if command_response:
            add_to_conversation(user_id, 'assistant', command_response)
            return command_response
        
        # 使用意圖識別處理一般對話
        response = detect_intent_and_respond(user_input, user_id)
        
        # 記錄助手回應
        add_to_conversation(user_id, 'assistant', response)
        
        return response
        
    except Exception as e:
        logger.error(f"處理用戶訊息失敗: {e}")
        return "抱歉，處理您的請求時發生錯誤，請稍後再試 🙏"

# LINE Bot 路由
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)
    
    return 'OK'

@app.route("/", methods=['GET'])
def health_check():
    return "3C Smart Assistant is running!", 200

# 事件處理器
@handler.add(FollowEvent)
def handle_follow(event):
    welcome_text = """🎉 歡迎使用3C智能助手！

✨ 全新體驗：
• 🤖 智能對話：直接詢問產品資訊
• 🛒 購物車：管理您的心儀商品
• 🌐 多語言：自動偵測語言回應
• 📊 即時資訊：整合多個資料來源

🔍 試試這些功能：
• "iPhone 15價格" - 查詢價格
• "推薦2萬元筆電" - 取得推薦
• "iPhone vs Samsung" - 產品比較
• "手機排行榜" - 熱門排行
• "新增至購物車 MacBook" - 購物車
• "說明" - 查看完整功能

讓我們開始探索3C世界吧！ 🚀"""
    
    line_bot_api.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[TextMessage(text=welcome_text)]
        )
    )

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    try:
        user_input = event.message.text.strip()
        user_id = event.source.user_id
        
        # 清理舊對話
        clear_old_conversations()
        
        # 處理用戶訊息
        response = handle_user_message(user_input, user_id)
        
        # 回覆訊息
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=response)]
            )
        )
        
    except Exception as e:
        logger.error(f"處理訊息失敗: {e}")
        error_message = "抱歉，系統暫時無法處理您的請求，請稍後再試 🙏"
        
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=error_message)]
            )
        )

# 導入 Web 路由
try:
    from web_routes import *
except ImportError:
    logger.warning("Web routes not imported")

if __name__ == "__main__":
    # 初始化資料庫
    init_database()
    
    # 啟動應用
    app.run(host='0.0.0.0', port=5000, debug=True)