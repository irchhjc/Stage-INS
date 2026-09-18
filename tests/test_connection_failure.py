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
    assert response.json["code"] == "database_unavailable"
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
