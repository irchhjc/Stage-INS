from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import AuditLog, DSF, FicheStatus, User
from app.services.admin_dashboard_service import LOCAL_TIMEZONE, build_controller_daily_stats
from app.services.auth_service import create_user


def _complete(dsf, operator, moment):
    """Marque la DSF terminée : toutes ses fiches validées, la dernière à ``moment``."""
    statuses = FicheStatus.query.filter_by(dsf_id=dsf.id).order_by(FicheStatus.position).all()
    for index, status in enumerate(statuses):
        status.status = "verified"
        status.operator = operator
        status.validated_at = (moment - timedelta(minutes=len(statuses) - index)).astimezone(timezone.utc)
    statuses[-1].validated_at = moment.astimezone(timezone.utc)
    dsf.status = "completed"


def test_daily_table_counts_completed_dsfs_per_person_including_admin(client, imported_session):
    first, second = DSF.query.order_by(DSF.id).all()
    alice = create_user("alice", "motdepasse10", role="controller")
    admin = User.query.filter_by(username="irch").one()
    today = datetime.now(LOCAL_TIMEZONE).replace(hour=10, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)

    _complete(first, "alice", today)
    _complete(second, "irch", yesterday)
    db.session.commit()

    stats = build_controller_daily_stats(yesterday.date(), today.date(), [alice, admin])
    rows = {row["user"].username: row for row in stats["rows"]}
    by_day = {item["date"]: item for item in stats["totals"]["days"]}

    assert rows["alice"]["total_dsfs"] == 1
    assert rows["irch"]["total_dsfs"] == 1
    assert {day["date"]: day["dsfs"] for day in rows["alice"]["days"]}[today.date()] == 1
    assert {day["date"]: day["dsfs"] for day in rows["irch"]["days"]}[yesterday.date()] == 1
    assert by_day[today.date()]["dsfs"] == 1
    assert by_day[yesterday.date()]["dsfs"] == 1
    assert stats["totals"]["total_dsfs"] == 2


def test_active_but_unfinished_or_reopened_dsfs_are_not_counted(client, imported_session):
    first, second = DSF.query.order_by(DSF.id).all()
    alice = create_user("alice", "motdepasse10", role="controller")
    today = datetime.now(LOCAL_TIMEZONE).replace(hour=10, minute=0, second=0, microsecond=0)

    db.session.add(AuditLog(dsf_id=first.id, action="vérification", operator="alice", created_at=today))
    _complete(second, "alice", today)
    second.status = "in_progress"  # rouverte depuis
    db.session.commit()

    stats = build_controller_daily_stats(today.date(), today.date(), [alice])

    assert stats["rows"][0]["total_dsfs"] == 0
    assert stats["totals"]["total_dsfs"] == 0


def test_admin_page_lists_admin_row_and_total_row(client, imported_session):
    create_user("alice", "motdepasse10", role="controller")

    html = client.get("/admin/").get_data(as_text=True)

    assert "Total par jour" in html
    assert "DSF terminées par contrôleur" in html
    assert 'title="Administrateur">admin</span>' in html


def test_completed_dsf_validated_by_unknown_account_is_reported_as_unattributed(client, imported_session):
    first = DSF.query.order_by(DSF.id).first()
    alice = create_user("alice", "motdepasse10", role="controller")
    today = datetime.now(LOCAL_TIMEZONE).replace(hour=10, minute=0, second=0, microsecond=0)
    _complete(first, "ancien_compte", today)
    db.session.commit()

    stats = build_controller_daily_stats(today.date(), today.date(), [alice])

    assert stats["totals"]["total_dsfs"] == 0
    assert stats["totals"]["unattributed"] == 1
