"""基础配置。"""

from pathlib import Path

# 获取当前项目根目录  .resolve()取绝对路径  .parent取父目录
BASE_DIR = Path(__file__).resolve().parent

APP_NAME = "OCR 识别检查系统"
SESSION_SECRET = "dev-secret-key"  # 签名密钥
APP_PASSWORD = "admin123"
APP_HOST = "127.0.0.1"
APP_PORT = 18000

DATABASE_URL = "mysql+pymysql://root:123456@127.0.0.1:3306/ocr_system?charset=utf8mb4"

MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 最大上传50MB文件
UPLOAD_DIR = BASE_DIR / "uploads"
RESULT_DIR = BASE_DIR / "parsed_results"
LOG_DIR = BASE_DIR / "logs"
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
