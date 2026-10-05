from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import AuditLog, DSF, User
from app.services.admin_dashboard_service import LOCAL_TIMEZONE, build_controller_daily_stats
from app.services.auth_service import create_user


def _log(dsf, operator, action, moment):
    db.session.add(AuditLog(dsf_id=dsf.id, action=action, operator=operator, created_at=moment))


def test_total_row_counts_dsfs_per_day_across_controllers(client, imported_session):
    first, second = DSF.query.order_by(DSF.id).all()
    alice = create_user("alice", "motdepasse10", role="controller")
    bruno = create_user("bruno", "motdepasse10", role="controller")
    today = datetime.now(LOCAL_TIMEZONE).replace(hour=10, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)

    _log(first, "alice", "vérification", today)
    _log(first, "alice", "validation fiche", today)
    _log(second, "bruno", "correction", today)
    _log(second, "bruno", "vérification", yesterday)
    db.session.commit()

    stats = build_controller_daily_stats(yesterday.date(), today.date(), [alice, bruno])
    totals = stats["totals"]
    by_day = {item["date"]: item for item in totals["days"]}

    assert by_day[today.date()]["dsfs"] == 2
    assert by_day[today.date()]["controllers"] == 2
    assert by_day[today.date()]["fiches"] == 1
    assert by_day[today.date()]["corrections"] == 1
    assert by_day[yesterday.date()]["dsfs"] == 1
    assert [item["date"] for item in totals["days"]] == [d["date"] for d in stats["day_labels"]]
    assert totals["total_dsfs"] == 2
    assert totals["total_fiches"] == 1


def test_admin_page_shows_the_total_row(client, imported_session):
    create_user("alice", "motdepasse10", role="controller")

    html = client.get("/admin/").get_data(as_text=True)

    assert "Total par jour" in html
