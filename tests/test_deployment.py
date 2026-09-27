import pytest

from app import create_app
from config import configured_database_url


def test_healthcheck_confirms_database(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
    assert response.headers["Cache-Control"] == "no-store"


def test_production_rejects_default_secrets():
    class InvalidProductionConfig:
        PRODUCTION = True
        SECRET_KEY = "dev-change-me-before-production"
        INITIAL_ADMIN_PASSWORD = "change-me-before-production"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

    with pytest.raises(RuntimeError, match="Configuration de production invalide"):
        create_app(InvalidProductionConfig)


def test_component_database_settings_encode_password(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_HOST", "db")
    monkeypatch.setenv("POSTGRES_USER", "dsf_app")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret:@value")
    monkeypatch.setenv("POSTGRES_DB", "insdsf")
    url = configured_database_url()
    assert url == "postgresql+psycopg://dsf_app:secret%3A%40value@db:5432/insdsf"
