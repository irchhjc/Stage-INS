from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import DSF, FicheStatus, ImportSession
from app.services.auth_service import create_user
from app.services.year_progress_service import build_year_progress
from tests.test_work_scope import _import_two_years, _login


def _complete(dsf, operator, moment):
    statuses = FicheStatus.query.filter_by(dsf_id=dsf.id).order_by(FicheStatus.position).all()
    for index, status in enumerate(statuses):
        status.status = "verified"
        status.operator = operator
        status.validated_at = moment - timedelta(minutes=len(statuses) - index)
    dsf.status, dsf.progress = "completed", 1.0


def _scenario(client):
    """2025 : 1 terminée (il y a 2 j, par alice) + 1 en cours ; 2024 : 1 terminée (il y a 20 j) + 1 non commencée."""
    first, second = _import_two_years(client)
    alice = create_user("alice", "motdepasse10", role="controller")
    now = datetime.now(timezone.utc)
    done_2025, running_2025 = DSF.query.filter_by(import_session_id=first.id).order_by(DSF.id).all()
    done_2024, idle_2024 = DSF.query.filter_by(import_session_id=second.id).order_by(DSF.id).all()
    _complete(done_2025, "alice", now - timedelta(days=2))
    done_2025.assigned_to_id = alice.id
    running_2025.status, running_2025.progress, running_2025.assigned_to_id = "in_progress", 0.5, alice.id
    running_2025.anomaly_count = 3
    _complete(done_2024, "alice", now - timedelta(days=20))
    db.session.commit()
    return alice, now


def test_year_progress_counts_status_rates_and_assignments(client):
    _scenario(client)

    data = build_year_progress()
    by_year = {row["year"]: row for row in data["years"]}

    assert [row["year"] for row in data["years"]] == ["2025", "2024"]
    y2025, y2024 = by_year["2025"], by_year["2024"]
    assert (y2025["total"], y2025["completed"], y2025["in_progress"], y2025["not_started"]) == (2, 1, 1, 0)
    assert (y2025["completion_rate"], y2025["average_progress"]) == (50, 75)
    assert (y2025["with_anomalies"], y2025["assigned"], y2025["free"]) == (1, 2, 0)
    assert (y2024["total"], y2024["completed"], y2024["not_started"]) == (2, 1, 1)
    assert (y2024["assigned"], y2024["free"]) == (0, 2)
    assert data["totals"] == {"total": 4, "completed": 2, "years": 2, "completion_rate": 50}


def test_pace_and_estimated_end_use_the_last_14_days(client):
    _, now = _scenario(client)

    data = build_year_progress(now=now)
    y2025 = next(row for row in data["years"] if row["year"] == "2025")
    y2024 = next(row for row in data["years"] if row["year"] == "2024")

    assert y2025["completed_recent"] == 1 and y2025["pace_per_day"] == 0.1
    assert y2025["remaining"] == 1 and y2025["eta_days"] == 14  # 1 DSF restante à 1/14 par jour
    assert y2025["eta_date"] is not None
    # 2024 : la seule terminée date de 20 jours -> hors fenêtre -> rythme nul, pas de date estimée.
    assert y2024["pace_per_day"] == 0 and y2024["eta_days"] is None and y2024["eta_date"] is None


def test_fully_completed_year_is_flagged_finished(client):
    first, second = _import_two_years(client)
    now = datetime.now(timezone.utc)
    for dsf in DSF.query.filter_by(import_session_id=first.id):
        _complete(dsf, "irch", now)
    db.session.commit()

    row = next(r for r in build_year_progress()["years"] if r["year"] == "2025")

    assert row["finished"] and row["completion_rate"] == 100 and row["eta_days"] is None


def test_breakdown_by_controller_and_year_without_value(client):
    alice, _ = _scenario(client)
    DSF.query.filter(DSF.id == DSF.query.order_by(DSF.id.desc()).first().id).update({"annee": None})
    db.session.commit()

    data = build_year_progress()
    by_year = {row["year"]: row for row in data["years"]}

    assert data["years"][-1]["year"] == "Non renseignée"  # toujours en dernier
    assert by_year["2025"]["controllers"] == [
        {"name": "alice", "assigned": 2, "completed": 1, "in_progress": 1, "rate": 50}
    ]
    assert "controllers" not in build_year_progress(with_controllers=False)["years"][0]


def test_only_year_limits_the_computation(client):
    _scenario(client)

    data = build_year_progress(only_year="2024")

    assert [row["year"] for row in data["years"]] == ["2024"] and data["totals"]["total"] == 2


def test_admin_overview_shows_the_year_progress_with_details(client):
    _scenario(client)

    html = client.get("/admin/").get_data(as_text=True)

    assert "Progression du contrôle par année" in html
    assert "Répartition par contrôleur" in html and "Fin estimée" in html
    assert "2025" in html and "2024" in html


def test_dashboard_shows_year_progress_and_limited_controllers_only_see_their_year(app, client):
    alice, _ = _scenario(client)

    admin_html = client.get("/").get_data(as_text=True)
    assert "Progression du contrôle par année" in admin_html and "Répartition par contrôleur" not in admin_html

    alice.work_year = "2024"
    db.session.commit()
    html = _login(app, "alice").get("/").get_data(as_text=True)
    section = html.split("Progression du contrôle par année")[1].split("</section>")[0]
    assert "2024" in section and "2025" not in section
