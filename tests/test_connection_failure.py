import pytest
from sqlalchemy.exc import OperationalError, TimeoutError as PoolTimeoutError
from app.extensions import db


@pytest.mark.parametrize("path", ["/static/js/app.js", "/static/vendor/bootstrap/bootstrap.bundle.min.js", "/brand-assets/missing.png"])
def test_assets_do_not_query_database(client, monkeypatch, path):
    def fail(*args, **kwargs):
        raise AssertionError("Static files must not query the database")
    monkeypatch.setattr(db.session, "get", fail)
    response = client.get(path)
    assert response.status_code == (404 if "missing" in path else 200)


@pytest.mark.parametrize("error", [OperationalError(None, None, Exception("secret detail")), PoolTimeoutError("secret detail")])
def test_database_failure_returns_503_and_keeps_session(client, monkeypatch, error):
    original = db.session.get
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(db.session, "get", fail)
    response = client.post("/dsf/api/1/fiches/NOTE_14/validate")
    assert response.status_code == 503
    assert response.json["code"] == ("database_pool_busy" if isinstance(error, PoolTimeoutError) else "database_unavailable")
    assert response.json["ok"] is False
    assert b"secret detail" not in response.data
    with client.session_transaction() as session:
        assert session.get("user_id")
    response = client.get("/")
    assert response.status_code == 503
    assert response.headers["Cache-Control"] == "no-store"
    assert b"secret detail" not in response.data
    monkeypatch.setattr(db.session, "get", original)
    assert client.get("/").status_code == 200


def test_initial_read_recovers_once(client, monkeypatch):
    original = db.session.get
    calls = []
    def interrupted(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OperationalError(None, None, Exception("closed"), connection_invalidated=True)
        return original(*args, **kwargs)
    monkeypatch.setattr(db.session, "get", interrupted)
    assert client.get("/").status_code == 200
    assert len(calls) == 2


def test_reconnect_is_bounded(client, monkeypatch):
    calls = []
    def interrupted(*args, **kwargs):
        calls.append(1)
        raise OperationalError(None, None, Exception("closed"), connection_invalidated=True)
    monkeypatch.setattr(db.session, "get", interrupted)
    assert client.get("/").status_code == 503
    assert len(calls) == 2


def test_windows_denial_is_not_retried(client, monkeypatch):
    calls = []
    def denied(*args, **kwargs):
        calls.append(1)
        raise OperationalError(None, None, Exception("Permission denied 10013"), connection_invalidated=True)
    monkeypatch.setattr(db.session, "get", denied)
    response = client.post("/dsf/api/1/fiches/NOTE_14/validate")
    assert response.status_code == 503
    assert response.json["code"] == "database_access_denied"
    assert len(calls) == 1


def test_write_is_never_replayed(app):
    calls = []
    @app.post("/dsf/api/test-write-failure")
    def write_failure():
        calls.append(1)
        raise OperationalError(None, None, Exception("closed during write"), connection_invalidated=True)
    client = app.test_client()
    from app.models import User
    user = User.query.filter_by(role="admin").first()
    with client.session_transaction() as session:
        session["user_id"] = user.id
    response = client.post("/dsf/api/test-write-failure")
    assert response.status_code == 503
    assert len(calls) == 1


def test_pool_settings_are_bounded(monkeypatch):
    from config import postgres_engine_options
    monkeypatch.setenv("DB_POOL_SIZE", "8")
    options = postgres_engine_options()
    assert options["pool_size"] == 8
    assert options["max_overflow"] == 0
    assert options["pool_pre_ping"]
    monkeypatch.setenv("DB_POOL_SIZE", "0")
    with pytest.raises(ValueError):
        postgres_engine_options()
