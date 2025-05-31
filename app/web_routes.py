from flask import jsonify, request
from app import app, add_to_cart, get_cart_items, remove_from_cart
import logging

logger = logging.getLogger(__name__)

@app.route('/cart/<user_id>', methods=['GET'])
def get_cart(user_id):
    """取得購物車 API"""
    try:
        items = get_cart_items(user_id)
        return jsonify({
            'success': True,
            'items': items,
            'count': len(items)
        })
    except Exception as e:
        logger.error(f"取得購物車失敗: {e}")
        return jsonify({
            'success': False,
            'error': '取得購物車失敗'
        }), 500

@app.route('/add-to-cart', methods=['POST'])
def add_to_cart_api():
    """新增至購物車 API"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        product_name = data.get('product_name')
        quantity = data.get('quantity', 1)
        
        if not user_id or not product_name:
            return jsonify({
                'success': False,
                'error': '缺少必要參數'
            }), 400
        
        success = add_to_cart(user_id, product_name, quantity)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'已將 {product_name} 加入購物車'
            })
        else:
            return jsonify({
                'success': False,
                'error': '新增至購物車失敗'
            }), 500
            
    except Exception as e:
        logger.error(f"新增至購物車 API 失敗: {e}")
        return jsonify({
            'success': False,
            'error': '伺服器錯誤'
        }), 500

@app.route('/remove-from-cart', methods=['POST'])
def remove_from_cart_api():
    """從購物車移除 API"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        product_name = data.get('product_name')
        
        if not user_id or not product_name:
            return jsonify({
                'success': False,
                'error': '缺少必要參數'
            }), 400
        
        success = remove_from_cart(user_id, product_name)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'已從購物車移除 {product_name}'
            })
        else:
            return jsonify({
                'success': False,
                'error': '商品不在購物車中'
            }), 404
            
    except Exception as e:
        logger.error(f"移除購物車 API 失敗: {e}")
        return jsonify({
            'success': False,
            'error': '伺服器錯誤'
        }), 500