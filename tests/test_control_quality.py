from datetime import datetime, timedelta

from app.extensions import db
from app.models import AuditLog, DSF, DSFValue
from app.services.admin_dashboard_service import LOCAL_TIMEZONE
from app.services.auth_service import create_user
from app.services.control_quality_service import (
    analyse_events,
    build_control_quality,
    score_controller,
)


def _event(at, action, dsf_id=1, fiche="IDENT"):
    return {"at": at, "action": action, "dsf_id": dsf_id, "fiche_code": fiche}


def test_validation_without_any_cell_check_is_flagged_empty():
    result = analyse_events(
        [
            _event(0, "vérification", fiche="A"),
            _event(20, "validation fiche", fiche="A"),
            _event(60, "validation fiche", fiche="B"),
        ]
    )
    checked, empty = result["validations"]
    assert checked["manual_before"] == 1
    assert empty["manual_before"] == 0
    assert result["manual_events"] == 1


def test_three_validations_within_ten_seconds_are_a_bulk_run():
    events = [_event(100 + i * 3, "validation fiche", fiche=f"F{i}") for i in range(3)]
    events.append(_event(400, "validation fiche", fiche="F9"))

    validations = analyse_events(events)["validations"]

    assert [item["bulk"] for item in validations] == [True, True, True, False]


def test_breaks_do_not_count_as_active_time_and_reopens_are_counted():
    result = analyse_events(
        [
            _event(0, "vérification"),
            _event(120, "correction"),
            _event(5000, "vérification"),
            _event(5060, "annulation validation"),
        ]
    )
    assert result["active_seconds"] == 120 + 60
    assert result["corrections"] == 1
    assert result["reopens"] == 1


def _metrics(**overrides):
    base = {
        "validations_counted": 20, "manual_coverage": 0.9, "cells_total": 1000, "empty_rate": 0.0,
        "bulk_rate": 0.0, "median_seconds": 90, "cells_per_minute": 10, "dsf_touched": 12,
        "detections": 5,
    }
    base.update(overrides)
    return base


def test_score_is_none_without_enough_validations_and_high_when_rigorous():
    assert score_controller(_metrics(validations_counted=3), 4.0) == (None, [])
    score, alerts = score_controller(_metrics(), 4.0)
    assert score >= 90 and alerts == []


def test_rubber_stamping_gets_a_low_score_with_explicit_alerts():
    score, alerts = score_controller(
        _metrics(manual_coverage=0.05, empty_rate=0.9, bulk_rate=0.8, median_seconds=4,
                 cells_per_minute=120, detections=0),
        4.0,
    )
    assert score < 30
    assert len(alerts) == 6


def test_build_control_quality_end_to_end(client, imported_session):
    dsfs = DSF.query.order_by(DSF.id).all()
    rigorous = create_user("rigoureux", "motdepasse10", role="controller")
    hasty = create_user("presse", "motdepasse10", role="controller")
    now = datetime.now(LOCAL_TIMEZONE).replace(hour=10, minute=0, second=0, microsecond=0)

    def log(dsf, operator, action, seconds, fiche="IDENT"):
        db.session.add(AuditLog(dsf_id=dsf.id, fiche_code=fiche, action=action, operator=operator,
                                created_at=now + timedelta(seconds=seconds)))

    for index in range(6):
        fiche = f"F{index}"
        log(dsfs[0], "rigoureux", "vérification", index * 120, fiche)
        log(dsfs[0], "rigoureux", "vérification", index * 120 + 30, fiche)
        log(dsfs[0], "rigoureux", "validation fiche", index * 120 + 60, fiche)
    for index in range(6):
        log(dsfs[1], "presse", "validation fiche", 1000 + index * 2, f"F{index}")
    db.session.commit()

    quality = build_control_quality(now.date(), now.date(), [rigorous, hasty])
    by_name = {row["user"].username: row for row in quality["rows"]}

    assert by_name["rigoureux"]["empty_rate"] == 0
    assert by_name["rigoureux"]["level"] == "good"
    assert by_name["presse"]["empty_rate"] == 1
    assert by_name["presse"]["bulk_rate"] == 1
    assert by_name["presse"]["level"] in {"warn", "bad"}
    assert quality["rows"][0]["user"].username == "presse"
    assert quality["team"]["to_review"] == 1
    assert quality["flagged"] and all(item["controller"].username == "presse" for item in quality["flagged"])


def test_quality_page_is_admin_only_and_renders(client, imported_session):
    create_user("alice", "motdepasse10", role="controller")

    page = client.get("/admin/rigueur")

    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Rigueur du contrôle" in html and "Comment lire ces indicateurs" in html
    assert "Rigueur du contrôle" in client.get("/admin/").get_data(as_text=True)
