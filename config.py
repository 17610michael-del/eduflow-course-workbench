import os
from datetime import timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY must be set in the server environment")
    DATABASE = os.environ.get("DATABASE", str(BASE_DIR / "data" / "app.db"))
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", str(BASE_DIR / "data" / "uploads"))
    SERVER_SUBMISSION_ROOT = os.environ.get(
        "SERVER_SUBMISSION_ROOT", str(BASE_DIR / "data" / "server-files")
    )
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_CHAT_MODEL = os.environ.get("DEEPSEEK_CHAT_MODEL", "deepseek-v4-flash")
    DEEPSEEK_REASONING_MODEL = os.environ.get("DEEPSEEK_REASONING_MODEL", "deepseek-v4-pro")
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    TEACHER_GROUP = os.environ.get("TEACHER_GROUP", "teacher")
    ASSISTANT_GROUP = os.environ.get("ASSISTANT_GROUP", "assistant")
    TEACHERS = {x.strip() for x in os.environ.get("TEACHERS", "").split(",") if x.strip()}
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "1") == "1"
    PERMANENT_SESSION_LIFETIME = 8 * 60 * 60
    # Effectively persistent on a personal device; explicit logout still clears it.
    REMEMBER_COOKIE_DURATION = timedelta(days=3650)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    # Only create this cookie when the user explicitly checks auto-login.
    REMEMBER_COOKIE_REFRESH_EACH_REQUEST = False
    HOST = os.environ.get("HOST", "127.0.0.1")
    PORT = int(os.environ.get("PORT", "5000"))
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
