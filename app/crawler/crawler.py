import re
import json
import time
import random
import requests
from bs4 import BeautifulSoup
from difflib import SequenceMatcher

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def load_product_url_map():
    try:
        with open('crawler/c-url-producturl.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"載入商品URL對照表失敗: {str(e)}")
        return []

def string_similarity(a, b):
    """計算兩個字符串的相似度"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def normalize_product_name(name):
    """標準化產品名稱，移除特殊字符並轉換為小寫"""
    return re.sub(r'[^\w\s-]', '', name).strip().lower()

def get_product_price(product_name):
    """根據產品名稱獲取價格信息"""
    # 驗證用戶輸入
    if not product_name or not isinstance(product_name, str):
        return {
            "status": "error",
            "message": "請輸入有效的商品名稱"
        }
    
    # 清理和標準化用戶輸入
    cleaned_input = normalize_product_name(product_name)
    if not cleaned_input:
        return {
            "status": "error",
            "message": "請輸入有效的商品名稱，不要只包含特殊字元"
        }
    
    # 載入商品URL對照表
    product_url_map = load_product_url_map()
    
    # 分解搜索詞
    search_terms = cleaned_input.split()
    
    # 搜索最匹配的產品
    best_matches = []
    for item in product_url_map:
        item_tag = normalize_product_name(item['tag'])
        # 確保所有搜索詞都在標籤中
        if all(term in item_tag for term in search_terms):
            # 計算完整字符串的相似度
            similarity = string_similarity(cleaned_input, item_tag)
            if similarity > 0.5:  # 降低相似度閾值，但要求所有關鍵詞匹配
                best_matches.append((item, similarity))
    
    # 按相似度排序
    best_matches.sort(key=lambda x: x[1], reverse=True)
    
    if not best_matches:
        return {
            "status": "error",
            "message": f"找不到商品 '{product_name}' 的相關資訊，請確認型號是否正確"
        }
    
    # 取得最佳匹配的URL並爬取價格
    best_match = best_matches[0][0]
    url = best_match['url']
    
    try:
        time.sleep(random.uniform(1, 2))
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 獲取所有價格區塊
        price_blocks = soup.find_all('a', class_='d-block btn-price rounded border p-2')
        specs_prices = []
        
        for block in price_blocks:
            # 獲取規格
            spec_div = block.find('div')
            spec = spec_div.text.strip() if spec_div else "規格不詳"
            
            # 獲取最低價格
            price_div = block.find('div', class_='lead text-primary font-weight-bold m-0')
            price = price_div.text.strip() if price_div else "資訊不足"
            
            # 獲取原廠價格
            original_div = block.find('small', class_='d-block text-muted')
            original_price = original_div.text.strip().replace('原廠售價：', '') if original_div else "資訊不足"
            
            specs_prices.append({
                "spec": spec,
                "price": price,
                "original_price": original_price
            })
        
        # 提取品牌和型號
        brand_model = best_match['tag'].split('-')
        brand = brand_model[0] if len(brand_model) > 0 else ''
        model = brand_model[1] if len(brand_model) > 1 else ''
        
        return {
            "status": "success",
            "data": {
                "brand": brand,
                "model": model,
                "specs_prices": specs_prices,
                "url": url,
                "similar_products": [
                    {"tag": m[0]['tag'], "similarity": m[1]} 
                    for m in best_matches[1:4]  # 返回前3個相似產品
                ]
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"獲取價格信息失敗: {str(e)}"
        }