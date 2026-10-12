import io

from openpyxl import Workbook

from app.extensions import db
from app.models import DSF, ImportSession, User
from app.services.auth_service import create_user
from app.services.work_scope_service import available_years, dsf_in_scope, normalize_requested_year, year_key, year_stats
from tests.conftest import build_test_workbook

import pytest


def _import_two_years(client):
    """Deux classeurs : le premier en 2025 (2 DSF), le second réécrit en 2024 (2 DSF)."""
    for name in ("annee_2025.xlsx", "annee_2024.xlsx"):
        client.post("/import/", data={"file": (build_test_workbook(), name)}, content_type="multipart/form-data")
    first, second = ImportSession.query.order_by(ImportSession.id).all()
    DSF.query.filter_by(import_session_id=second.id).update({"annee": "2024"})
    db.session.commit()
    return first, second


def _login(app, name):
    other = app.test_client()
    other.post("/auth/login", data={"username": name, "password": "motdepasse10"})
    return other


def test_year_key_normalises_variants():
    assert year_key("2023") == year_key("2023.0") == year_key("Exercice 2023") == "2023"
    assert year_key(None) == "" and year_key("n/a") == "n/a"


def test_year_stats_and_requested_year_validation(client):
    _import_two_years(client)

    assert available_years() == ["2025", "2024"]
    assert year_stats()[0] == {"year": "2025", "total": 2, "free": 2, "completed": 0}
    assert normalize_requested_year("") is None and normalize_requested_year("all") is None
    assert normalize_requested_year("2024") == "2024"
    with pytest.raises(ValueError):
        normalize_requested_year("1999")


def test_admin_sets_one_controller_and_all_controllers(client):
    _import_two_years(client)
    alice = create_user("alice", "motdepasse10", role="controller")
    bruno = create_user("bruno", "motdepasse10", role="controller")

    assert client.post(f"/admin/users/{alice.id}/work-year", data={"work_year": "2024"}).status_code == 302
    assert db.session.get(User, alice.id).work_year == "2024"
    assert db.session.get(User, bruno.id).work_year is None

    client.post("/admin/controllers/work-year", data={"work_year": "2025"})
    assert {u.work_year for u in User.query.filter_by(role="controller")} == {"2025"}

    client.post(f"/admin/users/{alice.id}/work-year", data={"work_year": "all"})
    assert db.session.get(User, alice.id).work_year is None

    client.post(f"/admin/users/{alice.id}/work-year", data={"work_year": "1999"})
    assert db.session.get(User, alice.id).work_year is None  # année inconnue refusée


def test_controllers_cannot_change_scopes(app, client):
    _import_two_years(client)
    alice = create_user("alice", "motdepasse10", role="controller")

    assert _login(app, "alice").post(f"/admin/users/{alice.id}/work-year", data={"work_year": "2024"}).status_code == 403
    assert _login(app, "alice").post("/admin/controllers/work-year", data={"work_year": "2024"}).status_code == 403


def test_limited_controller_only_sees_and_claims_their_year(app, client):
    first, second = _import_two_years(client)
    alice = create_user("alice", "motdepasse10", role="controller")
    alice.work_year = "2024"
    db.session.commit()
    me = _login(app, "alice")

    html = me.get("/dsfs").get_data(as_text=True)
    assert html.count("<tr data-search=") == 2
    assert "annee_2024.xlsx</small>" in html and "annee_2025.xlsx</small>" not in html
    assert "périmètre de travail" in html and "année 2024" in html
    dashboard = me.get("/").get_data(as_text=True)
    assert "Tous les classeurs importés (1) · 2 DSF" in dashboard and "périmètre" in dashboard

    out_of_scope = DSF.query.filter_by(import_session_id=first.id).first()
    in_scope = DSF.query.filter_by(import_session_id=second.id).first()
    me.post(f"/dsfs/{out_of_scope.id}/claim")
    assert db.session.get(DSF, out_of_scope.id).assigned_to_id is None
    me.post(f"/dsfs/{in_scope.id}/claim")
    assert db.session.get(DSF, in_scope.id).assigned_to_id == alice.id


def test_unlimited_controller_and_admin_see_every_year(app, client):
    _import_two_years(client)
    create_user("alice", "motdepasse10", role="controller")

    assert _login(app, "alice").get("/dsfs").get_data(as_text=True).count("<tr data-search=") == 4
    assert client.get("/dsfs").get_data(as_text=True).count("<tr data-search=") == 4


def test_my_dsfs_follows_the_scope_and_says_how_many_are_hidden(app, client):
    first, second = _import_two_years(client)
    alice = create_user("alice", "motdepasse10", role="controller")
    old = DSF.query.filter_by(import_session_id=first.id).first()
    old.assigned_to_id, old.status = alice.id, "in_progress"
    alice.work_year = "2024"
    db.session.commit()
    me = _login(app, "alice")

    html = me.get("/my-dsfs").get_data(as_text=True)
    assert html.count("<tr data-search=") == 0
    assert "1 DSF affectée(s) d'une autre année masquée(s)" in html
    # L'accès direct à une DSF déjà affectée n'est jamais coupé.
    assert me.get(f"/dsf/{old.id}").status_code == 200

    alice.work_year = "2025"
    db.session.commit()
    html = me.get("/my-dsfs").get_data(as_text=True)
    assert html.count("<tr data-search=") == 1 and "masquée" not in html


def test_workbook_selector_only_offers_workbooks_with_dsfs_of_the_scope(app, client):
    first, second = _import_two_years(client)
    alice = create_user("alice", "motdepasse10", role="controller")
    alice.work_year = "2024"
    db.session.commit()
    me = _login(app, "alice")

    html = me.get("/dsfs").get_data(as_text=True)

    assert f'<option value="{second.id}"' in html
    assert f'<option value="{first.id}"' not in html
    assert "Tous les classeurs importés (1)" in html
    # Un identifiant de classeur hors périmètre retombe sur « tous » (donc sur l'année du compte).
    assert me.get(f"/dsfs?session_id={first.id}").get_data(as_text=True).count("<tr data-search=") == 2


def test_team_search_and_branch_filter_are_limited_to_the_scope(app, client):
    first, second = _import_two_years(client)
    alice = create_user("alice", "motdepasse10", role="controller")
    bruno = create_user("bruno", "motdepasse10", role="controller")
    for dsf in DSF.query.all():
        dsf.assigned_to_id = bruno.id
    alice.work_year = "2024"
    db.session.commit()
    me = _login(app, "alice")

    html = me.get("/admin/search").get_data(as_text=True)

    assert "2 DSF trouvée(s)" in html
    assert "annee_2025.xlsx" not in html and "annee_2024.xlsx" in html
    assert _login(app, "bruno").get("/admin/search").get_data(as_text=True).count("DSF trouvée(s)") == 1
    assert "4 DSF trouvée(s)" in _login(app, "bruno").get("/admin/search").get_data(as_text=True)


def test_admin_assignments_respect_the_controller_scope(client):
    first, second = _import_two_years(client)
    alice = create_user("alice", "motdepasse10", role="controller")
    alice.work_year = "2024"
    db.session.commit()
    wrong = DSF.query.filter_by(import_session_id=first.id).first()
    right = DSF.query.filter_by(import_session_id=second.id).first()

    client.post(f"/admin/dsfs/{wrong.id}/assign", data={"user_id": alice.id})
    assert db.session.get(DSF, wrong.id).assigned_to_id is None
    client.post(f"/admin/dsfs/{right.id}/assign", data={"user_id": alice.id})
    assert db.session.get(DSF, right.id).assigned_to_id == alice.id

    # Affectation groupée : seules les DSF libres de l'année du contrôleur sont prises.
    client.post(f"/admin/import-sessions/{first.id}/assign-all", data={"user_id": alice.id})
    assert DSF.query.filter_by(import_session_id=first.id, assigned_to_id=alice.id).count() == 0
    client.post(f"/admin/import-sessions/{second.id}/assign-all", data={"user_id": alice.id})
    assert DSF.query.filter_by(import_session_id=second.id, assigned_to_id=alice.id).count() == 2


def test_admin_page_shows_the_scope_card_with_years(client):
    _import_two_years(client)
    create_user("alice", "motdepasse10", role="controller")

    html = client.get("/admin/").get_data(as_text=True)

    assert "Périmètre de travail des contrôleurs" in html
    assert "2025 · 2 DSF · 2 libres · 0 terminées" in html and "Année 2024" in html


def test_dsf_in_scope_helper(client):
    _import_two_years(client)
    alice = create_user("alice", "motdepasse10", role="controller")
    dsf = DSF.query.first()

    assert dsf_in_scope(dsf, alice)
    alice.work_year = "1999"
    assert not dsf_in_scope(dsf, alice)
    admin = User.query.filter_by(username="irch").one()
    admin.work_year = "1999"
    assert dsf_in_scope(dsf, admin)
