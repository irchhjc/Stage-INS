"""Suivi de progression du contrôle, année par année.

Pour chaque année de DSF : volumes par statut, taux d'achèvement, avancement moyen,
anomalies, affectations, rythme récent et date de fin estimée, et répartition
par contrôleur. Lecture seule.
"""
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.extensions import db
from app.models import DSF, FicheStatus, User
from app.services.admin_dashboard_service import LOCAL_TIMEZONE
from app.services.work_scope_service import year_key

PACE_WINDOW_DAYS = 14
RECENT_DAYS = 7
NOT_SET_LABEL = "Non renseignée"


def _aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _percent(part, whole):
    return int(round(part / whole * 100)) if whole else 0


def build_year_progress(only_year=None, with_controllers=True, now=None):
    """Retourne ``{"years": [...], "totals": {...}}``.

    ``only_year`` limite le calcul à une année (périmètre d'un contrôleur limité).
    """
    now = _aware(now or datetime.now(timezone.utc))
    dsf_rows = db.session.query(
        DSF.id, DSF.annee, DSF.status, DSF.progress, DSF.anomaly_count, DSF.assigned_to_id
    ).all()
    completed_at = {
        dsf_id: _aware(last_at)
        for dsf_id, last_at in db.session.query(FicheStatus.dsf_id, func.max(FicheStatus.validated_at))
        .join(DSF, DSF.id == FicheStatus.dsf_id)
        .filter(DSF.status == "completed")
        .group_by(FicheStatus.dsf_id)
        .all()
        if last_at is not None
    }

    years = defaultdict(
        lambda: {
            "total": 0, "not_started": 0, "in_progress": 0, "completed": 0, "anomalies": 0,
            "assigned": 0, "progress_sum": 0.0, "completed_recent": 0, "completed_pace_window": 0,
            "controllers": defaultdict(lambda: {"assigned": 0, "completed": 0, "in_progress": 0}),
        }
    )
    recent_start = now - timedelta(days=RECENT_DAYS)
    pace_start = now - timedelta(days=PACE_WINDOW_DAYS)
    for dsf_id, annee, status, progress, anomaly_count, assigned_to_id in dsf_rows:
        key = year_key(annee)
        if only_year is not None and key != only_year:
            continue
        item = years[key]
        item["total"] += 1
        item[status if status in {"not_started", "in_progress", "completed"} else "in_progress"] += 1
        item["progress_sum"] += progress or 0.0
        item["anomalies"] += 1 if (anomaly_count or 0) > 0 else 0
        if assigned_to_id is not None:
            item["assigned"] += 1
            owner = item["controllers"][assigned_to_id]
            owner["assigned"] += 1
            if status == "completed":
                owner["completed"] += 1
            elif status == "in_progress":
                owner["in_progress"] += 1
        if status == "completed" and dsf_id in completed_at:
            if completed_at[dsf_id] >= recent_start:
                item["completed_recent"] += 1
            if completed_at[dsf_id] >= pace_start:
                item["completed_pace_window"] += 1

    names = {}
    if with_controllers:
        names = {user.id: user.display_label for user in User.query.all()}
    today = now.astimezone(LOCAL_TIMEZONE).date()

    result = []
    for key in sorted(years, key=lambda value: (value != "", value), reverse=True):
        item = years[key]
        total, completed = item["total"], item["completed"]
        remaining = total - completed
        pace = item["completed_pace_window"] / PACE_WINDOW_DAYS
        eta_days = math.ceil(remaining / pace) if pace > 0 and remaining > 0 else None
        entry = {
            "year": key or NOT_SET_LABEL,
            "year_key": key,
            "total": total,
            "not_started": item["not_started"],
            "in_progress": item["in_progress"],
            "completed": completed,
            "remaining": remaining,
            "completion_rate": _percent(completed, total),
            "average_progress": _percent(item["progress_sum"], total),
            "with_anomalies": item["anomalies"],
            "assigned": item["assigned"],
            "free": total - item["assigned"],
            "completed_recent": item["completed_recent"],
            "pace_per_day": round(pace, 1),
            "eta_days": eta_days,
            "eta_date": today + timedelta(days=eta_days) if eta_days is not None else None,
            "finished": total > 0 and remaining == 0,
        }
        if with_controllers:
            entry["controllers"] = sorted(
                (
                    {
                        "name": names.get(user_id, f"Compte {user_id}"),
                        "assigned": data["assigned"],
                        "completed": data["completed"],
                        "in_progress": data["in_progress"],
                        "rate": _percent(data["completed"], data["assigned"]),
                    }
                    for user_id, data in item["controllers"].items()
                ),
                key=lambda row: (-row["completed"], row["name"].casefold()),
            )
        result.append(entry)

    totals = {
        "total": sum(row["total"] for row in result),
        "completed": sum(row["completed"] for row in result),
        "years": len(result),
    }
    totals["completion_rate"] = _percent(totals["completed"], totals["total"])
    return {"years": result, "totals": totals}
