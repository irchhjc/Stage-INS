import os
from datetime import timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _session_lifetime():
    try:
        hours = int(os.environ.get("SESSION_LIFETIME_HOURS", "168"))
    except ValueError:
        hours = 168
    return timedelta(hours=max(1, hours))


def normalize_database_url(database_url):
    """Sélectionne explicitement psycopg 3 pour les URL PostgreSQL de Render."""
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me-before-production")
    _DATABASE_URL = normalize_database_url(
        os.environ.get(
            "DATABASE_URL", f"sqlite:///{(BASE_DIR / 'instance' / 'dsf_control.db').as_posix()}"
        )
    )
    SQLALCHEMY_DATABASE_URI = _DATABASE_URL
    SQLALCHEMY_ENGINE_OPTIONS = (
        {"connect_args": {"timeout": 60, "check_same_thread": False}, "pool_pre_ping": True}
        if _DATABASE_URL.startswith("sqlite")
        else {"pool_pre_ping": True}
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = _session_lifetime()
    SESSION_REFRESH_EACH_REQUEST = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_flag("SESSION_COOKIE_SECURE", _env_flag("RENDER"))
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
    UPLOAD_FOLDER = BASE_DIR / "instance" / "uploads"
    EXPORT_FOLDER = BASE_DIR / "instance" / "exports"
    ALLOWED_EXTENSIONS = {"xlsx"}
    INITIAL_ADMIN_USERNAME = os.environ.get("INITIAL_ADMIN_USERNAME", "irch")
    INITIAL_ADMIN_PASSWORD = os.environ.get("INITIAL_ADMIN_PASSWORD", "15081960irchdefluviaire")


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "test-key"
