"""
Uncle Super App — Django settings
Developed by Uncle Engineer (https://uncle-engineer.com/)
"""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_secret_key() -> str:
    """ใช้ SECRET_KEY จาก env ถ้ามี ไม่งั้นสร้างไฟล์ secret_key.txt ครั้งแรกแล้วใช้ค่าเดิมตลอด
    (สำคัญ: API Key ของผู้ใช้ถูกเข้ารหัสด้วยคีย์นี้ ถ้าคีย์เปลี่ยน API Key เดิมจะถอดรหัสไม่ได้)"""
    env_key = os.environ.get("DJANGO_SECRET_KEY")
    if env_key:
        return env_key
    key_file = BASE_DIR / "secret_key.txt"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    key = secrets.token_urlsafe(50)
    key_file.write_text(key, encoding="utf-8")
    return key


SECRET_KEY = _load_secret_key()
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "chat",
    "imagegen",
    "videogen",
    "analyst",
    "rag",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "videogen.context.video_jobs",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        # worker เบื้องหลัง (Video Generator) เขียน DB พร้อมกับหน้าเว็บ → ใช้ WAL + timeout กัน "database is locked"
        "OPTIONS": {"timeout": 30, "init_command": "PRAGMA journal_mode=WAL;"},
    }
}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "chat:index"
LOGOUT_REDIRECT_URL = "accounts:login"

LANGUAGE_CODE = "th"
TIME_ZONE = "Asia/Bangkok"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # ต่อท้าย ?v=... ให้ CSS/JS เพื่อให้เบราว์เซอร์โหลดไฟล์ใหม่เองหลังอัปเดต
    "staticfiles": {"BACKEND": "config.storage.VersionedStaticFilesStorage"},
}

# ไฟล์ภาพที่ generate และภาพอ้างอิง (เสิร์ฟผ่าน view ที่ตรวจสิทธิ์เจ้าของเท่านั้น)
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "media/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "uncle-super-app",
    }
}

# ---------------------------------------------------------------------------
# OpenRouter
# ---------------------------------------------------------------------------
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_APP_TITLE = "Uncle Super App"
OPENROUTER_APP_URL = "https://uncle-engineer.com/"
OPENROUTER_MODELS_CACHE_SECONDS = 60 * 60  # แคชรายชื่อโมเดล 1 ชั่วโมง
CHAT_HISTORY_LIMIT = 30  # จำนวนข้อความล่าสุดที่ส่งเป็นบริบทให้โมเดล
IMAGE_REF_MAX_BYTES = 8 * 1024 * 1024  # ขนาดสูงสุดต่อภาพอ้างอิง (8 MB)
IMAGE_GENERATE_TIMEOUT = 300  # วินาที — บางโมเดลใช้เวลานาน

# ---------------------------------------------------------------------------
# Video Generator — งานรันเบื้องหลัง (Prompt and Leave)
# ---------------------------------------------------------------------------
VIDEO_WORKER_AUTOSTART = os.environ.get("VIDEO_WORKER_AUTOSTART", "1") == "1"  # เริ่ม worker อัตโนมัติพร้อม runserver
VIDEO_WORKER_TICK = int(os.environ.get("VIDEO_WORKER_TICK", 5))  # วินาที — รอบการทำงานของ worker
VIDEO_POLL_SECONDS = int(os.environ.get("VIDEO_POLL_SECONDS", 20))  # วินาที — ถามสถานะงานจาก OpenRouter ทุกกี่วินาที
VIDEO_MAX_CONCURRENT = 3       # จำนวนฉากที่ส่งไป generate พร้อมกันต่อโปรเจกต์
VIDEO_MAX_SCENES = 24
VIDEO_SUBMIT_RETRIES = 2
FFMPEG_BINARY = os.environ.get("FFMPEG_BINARY", "")  # เว้นว่าง = ใช้ ffmpeg จาก imageio-ffmpeg หรือ PATH

# ---------------------------------------------------------------------------
# Data Analyst / RAG
# ---------------------------------------------------------------------------
DOC_MAX_UPLOAD_MB = 50            # ขนาดไฟล์สูงสุดต่อไฟล์
ANALYST_CONTEXT_CHARS = 60_000    # ข้อความจากเอกสารที่ส่งให้ AI สูงสุดต่อคำถาม (ตัวอักษร)
RAG_DEFAULT_EMBED_MODEL = "baai/bge-m3"                       # รองรับหลายภาษารวมถึงไทย
RAG_FREE_EMBED_MODEL = "nvidia/nemotron-3.5-embed-1b:free"    # สำหรับบัญชี Member
RAG_CHUNK_CHARS = 1000
RAG_CHUNK_OVERLAP = 150
RAG_TOP_K = 6
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# ---------------------------------------------------------------------------
# ประเภทผู้ใช้ (User roles) และสิทธิ์ — ปรับได้ตามต้องการ
#   allow_paid_models : ใช้โมเดลเสียเงินได้หรือไม่ (False = ใช้ได้เฉพาะโมเดลฟรี)
#   daily_message_limit : จำนวนข้อความต่อวัน (None = ไม่จำกัด)
#   can_manage_users : เข้าหน้าจัดการผู้ใช้ได้หรือไม่
# ---------------------------------------------------------------------------
ROLE_PERMISSIONS = {
    "member": {"allow_paid_models": False, "daily_message_limit": 50, "can_manage_users": False},
    "pro": {"allow_paid_models": True, "daily_message_limit": None, "can_manage_users": False},
    "admin": {"allow_paid_models": True, "daily_message_limit": None, "can_manage_users": True},
}
