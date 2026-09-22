from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func

from app.extensions import db
from app.models import AuditLog, DSF, FicheStatus, ImportSession


LOCAL_TIMEZONE = ZoneInfo("Africa/Douala")
DEFAULT_PERIOD_DAYS = 30
MAX_PERIOD_DAYS = 366
FINAL_FICHE_ACTIONS = {
    "validation fiche",
    "validation fiche avec anomalies",
    "fiche non renseignée",
}
CONTROL_ACTIONS = FINAL_FICHE_ACTIONS | {
    "vérification",
    "correction",
    "annulation validation",
}


def _local_date(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_TIMEZONE).date()


def _parse_date(raw_value, field_name):
    if not raw_value:
        return None
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise ValueError(f"La {field_name} est invalide.") from exc


def resolve_period(date_from_raw=None, date_to_raw=None, today=None):
    today = today or datetime.now(LOCAL_TIMEZONE).date()
    date_to = _parse_date(date_to_raw, "date de fin") or today
    date_from = _parse_date(date_from_raw, "date de début") or (
        date_to - timedelta(days=DEFAULT_PERIOD_DAYS - 1)
    )
    if date_from > date_to:
        raise ValueError("La date de début doit précéder la date de fin.")
    if (date_to - date_from).days + 1 > MAX_PERIOD_DAYS:
        raise ValueError("La période de suivi ne peut pas dépasser 366 jours.")
    return date_from, date_to


def _utc_bounds(date_from, date_to):
    start_local = datetime.combine(date_from, time.min, tzinfo=LOCAL_TIMEZONE)
    end_local = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=LOCAL_TIMEZONE)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _new_daily_row(day):
    return {
        "date": day,
        "label": day.strftime("%d/%m/%Y"),
        "imported": 0,
        "assigned": 0,
        "completed": 0,
        "active_dsf_ids": set(),
        "finalized_fiches": 0,
        "corrections": 0,
    }


def build_admin_performance(date_from_raw=None, date_to_raw=None):
    date_from, date_to = resolve_period(date_from_raw, date_to_raw)
    start_utc, end_utc = _utc_bounds(date_from, date_to)
    daily = {
        date_from + timedelta(days=offset): _new_daily_row(date_from + timedelta(days=offset))
        for offset in range((date_to - date_from).days + 1)
    }

    cohort = DSF.query.join(ImportSession).filter(
        ImportSession.imported_at >= start_utc,
        ImportSession.imported_at < end_utc,
    )
    period_total = cohort.count()
    assigned = cohort.filter(DSF.assigned_to_id.is_not(None)).count()
    in_progress = cohort.filter(DSF.status == "in_progress").count()
    completed = cohort.filter(DSF.status == "completed").count()
    anomalies = cohort.filter(DSF.anomaly_count > 0).count()

    imported_rows = (
        db.session.query(ImportSession.imported_at, func.count(DSF.id))
        .join(DSF)
        .filter(
            ImportSession.imported_at >= start_utc,
            ImportSession.imported_at < end_utc,
        )
        .group_by(ImportSession.imported_at)
        .all()
    )
    for imported_at, count in imported_rows:
        day = _local_date(imported_at)
        if day in daily:
            daily[day]["imported"] += count

    assigned_rows = DSF.query.filter(
        DSF.assigned_at >= start_utc,
        DSF.assigned_at < end_utc,
    ).all()
    for dsf in assigned_rows:
        day = _local_date(dsf.assigned_at)
        if day in daily:
            daily[day]["assigned"] += 1

    completion_rows = (
        db.session.query(DSF.id, func.max(FicheStatus.validated_at))
        .join(FicheStatus, FicheStatus.dsf_id == DSF.id)
        .filter(DSF.status == "completed")
        .group_by(DSF.id)
        .all()
    )
    for _, completed_at in completion_rows:
        day = _local_date(completed_at)
        if day in daily:
            daily[day]["completed"] += 1

    audit_rows = AuditLog.query.filter(
        AuditLog.created_at >= start_utc,
        AuditLog.created_at < end_utc,
        AuditLog.action.in_(CONTROL_ACTIONS),
    ).all()
    for log in audit_rows:
        day = _local_date(log.created_at)
        if day not in daily:
            continue
        daily[day]["active_dsf_ids"].add(log.dsf_id)
        if log.action in FINAL_FICHE_ACTIONS:
            daily[day]["finalized_fiches"] += 1
        if log.action == "correction":
            daily[day]["corrections"] += 1

    daily_rows = []
    max_daily_volume = max(
        (max(row["imported"], row["completed"]) for row in daily.values()),
        default=0,
    )
    for day in sorted(daily, reverse=True):
        row = daily[day]
        row["active_dsfs"] = len(row.pop("active_dsf_ids"))
        row["imported_percent"] = int(round(row["imported"] / max_daily_volume * 100)) if max_daily_volume else 0
        row["completed_percent"] = int(round(row["completed"] / max_daily_volume * 100)) if max_daily_volume else 0
        daily_rows.append(row)

    total_all = DSF.query.count()
    total_completed_all = DSF.query.filter_by(status="completed").count()
    return {
        "date_from": date_from,
        "date_to": date_to,
        "timezone": "Africa/Douala",
        "summary": {
            "total_all": total_all,
            "completed_all": total_completed_all,
            "period_total": period_total,
            "assigned": assigned,
            "unassigned": period_total - assigned,
            "in_progress": in_progress,
            "completed": completed,
            "anomalies": anomalies,
            "completion_rate": int(round(completed / period_total * 100)) if period_total else 0,
        },
        "daily": daily_rows,
    }


def build_controller_daily_stats(date_from, date_to, controllers):
    """Per-controller daily activity stats (DSFs touched, fiches closed, corrections)."""
    if not controllers:
        return {"rows": [], "day_labels": [], "max_dsfs_per_day": 0}

    start_utc, end_utc = _utc_bounds(date_from, date_to)
    days_asc = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
    days_desc = list(reversed(days_asc))
    controller_names = [c.username for c in controllers]

    logs = (
        db.session.query(
            AuditLog.operator,
            AuditLog.dsf_id,
            AuditLog.action,
            AuditLog.created_at,
        )
        .filter(
            AuditLog.created_at >= start_utc,
            AuditLog.created_at < end_utc,
            AuditLog.action.in_(CONTROL_ACTIONS),
            AuditLog.operator.in_(controller_names),
        )
        .all()
    )

    controller_by_name = {c.username: c for c in controllers}
    raw = {
        c.id: {day: {"dsfs": set(), "fiches": 0, "corrections": 0} for day in days_asc}
        for c in controllers
    }

    for operator, dsf_id, action, created_at in logs:
        if operator not in controller_by_name:
            continue
        ctrl = controller_by_name[operator]
        day = _local_date(created_at)
        if day not in raw[ctrl.id]:
            continue
        raw[ctrl.id][day]["dsfs"].add(dsf_id)
        if action in FINAL_FICHE_ACTIONS:
            raw[ctrl.id][day]["fiches"] += 1
        if action == "correction":
            raw[ctrl.id][day]["corrections"] += 1

    max_dsfs = max(
        (len(d["dsfs"]) for cd in raw.values() for d in cd.values()),
        default=0,
    )

    def _level(count):
        if count == 0 or max_dsfs == 0:
            return 0
        pct = count / max_dsfs * 100
        if pct <= 25:
            return 1
        if pct <= 50:
            return 2
        if pct <= 75:
            return 3
        return 4

    rows = []
    for ctrl in controllers:
        # heatmap shows newest first; sparkline chart shows oldest first
        day_list_desc = []
        day_list_asc = []
        all_dsfs: set = set()
        total_fiches = 0
        total_corrections = 0

        for day in days_desc:
            d = raw[ctrl.id][day]
            count = len(d["dsfs"])
            all_dsfs.update(d["dsfs"])
            total_fiches += d["fiches"]
            total_corrections += d["corrections"]
            entry = {
                "date": day,
                "label": day.strftime("%d/%m"),
                "dsfs": count,
                "fiches": d["fiches"],
                "corrections": d["corrections"],
                "level": _level(count),
            }
            day_list_desc.append(entry)

        # Build chronological copy (oldest→newest) for sparkline bars
        for day in days_asc:
            d = raw[ctrl.id][day]
            count = len(d["dsfs"])
            day_list_asc.append({
                "date": day,
                "label": day.strftime("%d/%m"),
                "dsfs": count,
                "fiches": d["fiches"],
                "corrections": d["corrections"],
                "level": _level(count),
            })

        rows.append({
            "user": ctrl,
            "days": day_list_desc,
            "days_chrono": day_list_asc,
            "total_dsfs": len(all_dsfs),
            "total_fiches": total_fiches,
            "total_corrections": total_corrections,
        })

    return {
        "rows": rows,
        "day_labels": [{"date": d, "label": d.strftime("%d/%m")} for d in days_desc],
        "max_dsfs_per_day": max_dsfs,
    }
