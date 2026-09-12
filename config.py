import os
from datetime import timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


class Config:
    COURSE_NAME = os.environ.get("COURSE_NAME", "课程工作台")
    COURSE_SUBTITLE = os.environ.get("COURSE_SUBTITLE", "193 内网服务器")
    COURSE_BADGE = os.environ.get("COURSE_BADGE", "CS")
    COURSE_ONLY_SLUG = os.environ.get("COURSE_ONLY_SLUG", "").strip()
    if COURSE_ONLY_SLUG not in {"", "degree", "bioinformatics", "bio_undergrad"}:
        raise RuntimeError("COURSE_ONLY_SLUG must be degree, bioinformatics or bio_undergrad")
    SECRET_KEY = os.environ.get("SECRET_KEY")
    if not SECRET_KEY:
        raise RuntimeError("SECRET_KEY must be set in the server environment")
    PROJECT_AGENT_TOKEN_SECRET = os.environ.get("PROJECT_AGENT_TOKEN_SECRET") or SECRET_KEY
    DATABASE = os.environ.get("DATABASE", str(BASE_DIR / "data" / "app.db"))
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", str(BASE_DIR / "data" / "uploads"))
    SERVER_SUBMISSION_ROOT = os.environ.get(
        "SERVER_SUBMISSION_ROOT", str(BASE_DIR / "data" / "server-files")
    )
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_CHAT_MODEL = os.environ.get("DEEPSEEK_CHAT_MODEL", "deepseek-v4-flash")
    DEEPSEEK_REASONING_MODEL = os.environ.get("DEEPSEEK_REASONING_MODEL", "deepseek-v4-pro")
    DEEPSEEK_3066_MENU_ENABLED = os.environ.get("DEEPSEEK_3066_MENU_ENABLED", "0") == "1"
    WORKBENCH_WORKSPACE_BASE = os.environ.get("WORKBENCH_WORKSPACE_BASE", "/data")
    HAPI_SERVER_HOST = os.environ.get("HAPI_SERVER_HOST", "10.98.103.193")
    HAPI_PORT_BASE = int(os.environ.get("HAPI_PORT_BASE", "32000"))
    HAPI_PUBLIC_URL_TEMPLATE = os.environ.get("HAPI_PUBLIC_URL_TEMPLATE", "").strip()
    MAX_CONTENT_LENGTH = 20 * 1024 * 1024
    TEACHER_GROUP = os.environ.get("TEACHER_GROUP", "teacher")
    ASSISTANT_GROUP = os.environ.get("ASSISTANT_GROUP", "assistant")
    TEACHERS = {x.strip() for x in os.environ.get("TEACHERS", "").split(",") if x.strip()}
    ASSISTANTS = {x.strip() for x in os.environ.get("ASSISTANTS", "").split(",") if x.strip()}
    BIOINFORMATICS_USERS = {
        x.strip() for x in os.environ.get("BIOINFORMATICS_USERS", "").split(",") if x.strip()
    }
    BIOINFORMATICS_ASSISTANTS = {
        x.strip() for x in os.environ.get("BIOINFORMATICS_ASSISTANTS", "").split(",") if x.strip()
    }
    DEGREE_USERS = {
        x.strip() for x in os.environ.get("DEGREE_USERS", "").split(",") if x.strip()
    }
    BIO_UNDERGRAD_USERS = {
        x.strip() for x in os.environ.get("BIO_UNDERGRAD_USERS", "").split(",") if x.strip()
    }
    BIO_UNDERGRAD_ASSISTANTS = {
        x.strip() for x in os.environ.get("BIO_UNDERGRAD_ASSISTANTS", "").split(",") if x.strip()
    }
    ALLOWED_USERS = {
        x.strip() for x in os.environ.get("ALLOWED_USERS", "").split(",") if x.strip()
    }
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_NAME = os.environ.get("SESSION_COOKIE_NAME", "session")
    # The current 193 deployment is an internal HTTP site. Set this to 1 only
    # after HTTPS is enabled, otherwise browsers discard the login session.
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    PERMANENT_SESSION_LIFETIME = 8 * 60 * 60
    # Effectively persistent on a personal device; explicit logout still clears it.
    REMEMBER_COOKIE_DURATION = timedelta(days=3650)
    REMEMBER_COOKIE_NAME = os.environ.get("REMEMBER_COOKIE_NAME", "remember_token")
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    # Only create this cookie when the user explicitly checks auto-login.
    REMEMBER_COOKIE_REFRESH_EACH_REQUEST = False
    LOGIN_HINT_COOKIE_PREFIX = os.environ.get("LOGIN_HINT_COOKIE_PREFIX", "").strip()
    SEED_DEMO_DATA = os.environ.get("SEED_DEMO_DATA", "0") == "1"
    HOST = os.environ.get("HOST", "127.0.0.1")
    PORT = int(os.environ.get("PORT", "5000"))
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
