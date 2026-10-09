from app.models import DSF, ImportSession
from tests.conftest import build_test_workbook


def _import(client, name):
    response = client.post(
        "/import/",
        data={"file": (build_test_workbook(), name)},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302


def test_lists_default_to_every_imported_workbook(client):
    _import(client, "premier.xlsx")
    _import(client, "second.xlsx")
    first, second = ImportSession.query.order_by(ImportSession.id).all()

    for url in ("/", "/dsfs"):
        html = client.get(url).get_data(as_text=True)
        assert 'value="all" selected' in html
        assert "premier.xlsx" in html and "second.xlsx" in html
        assert html.count("<tr data-search=") == 4

    one = client.get(f"/dsfs?session_id={first.id}").get_data(as_text=True)
    assert html and one.count("<tr data-search=") == 2
    assert "second.xlsx</small>" not in one
    assert f'value="{first.id}" selected' in one
    assert "session_id=" + str(first.id) + "&status=" in one


def test_status_links_keep_the_all_workbooks_scope_and_filter_works(client):
    _import(client, "premier.xlsx")
    _import(client, "second.xlsx")
    DSF.query.filter(DSF.id == DSF.query.first().id).update({"status": "completed"})
    from app.extensions import db
    db.session.commit()

    html = client.get("/dsfs?session_id=all&status=completed").get_data(as_text=True)

    assert "session_id=all&status=" in html
    assert html.count("<tr data-search=") == 1


def test_unknown_session_id_falls_back_to_all(client):
    _import(client, "premier.xlsx")

    html = client.get("/dsfs?session_id=999").get_data(as_text=True)

    assert 'value="all" selected' in html
    assert html.count("<tr data-search=") == 2


def test_dashboard_stats_cover_all_workbooks(client):
    _import(client, "premier.xlsx")
    _import(client, "second.xlsx")

    html = client.get("/").get_data(as_text=True)

    assert "Tous les classeurs importés (2) · 4 DSF" in html


def test_dashboard_cards_and_progress_stay_global_when_a_workbook_is_selected(client):
    from app.extensions import db

    _import(client, "premier.xlsx")
    _import(client, "second.xlsx")
    first, second = ImportSession.query.order_by(ImportSession.id).all()
    DSF.query.filter(DSF.import_session_id == first.id, DSF.row_index == 2).update({"status": "completed"})
    db.session.commit()

    html = client.get(f"/?session_id={first.id}").get_data(as_text=True)

    assert "Tous les classeurs importés (2) · 4 DSF" in html
    assert "1 / 4 — 25 %" in html
    assert "Classeur sélectionné (premier.xlsx) : 1 / 2 — 50 %" in html
