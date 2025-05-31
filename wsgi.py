# wsgi.py - 應用程序入口點

# 初始化資料庫
from app.app import app as application, init_database

# 確保資料庫已初始化
init_database()

# 導入路由
import app.web_routes

if __name__ == "__main__":
    # 本地運行
    import os
    port = int(os.environ.get("PORT", 5000))
    application.run(host='0.0.0.0', port=port, debug=False)