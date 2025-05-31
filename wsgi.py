# wsgi.py - 應用程序入口點

# 初始化資料庫
from app.app import app, init_database

# 確保資料庫已初始化
init_database()

# 導入路由
import app.web_routes

# 提供給 gunicorn 的應用程序實例
application = app

if __name__ == "__main__":
    # 本地運行
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)