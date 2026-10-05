"""Indicateurs de rigueur du contrôle : les contrôleurs vérifient-ils vraiment les DSF ?

Les indicateurs sont des signaux à examiner, jamais une preuve : ils s'appuient
sur le journal d'audit (qui fait quoi, quand) et sur l'origine des vérifications
de cellules (``manual`` = vérifiée une à une, ``fiche_validation`` = validée en
bloc avec la fiche). Aucune donnée n'est modifiée.
"""
from collections import defaultdict
from datetime import datetime
from statistics import median

from sqlalchemy import func

from app.config.fiche_mapping import FICHE_BY_CODE
from app.extensions import db
from app.models import AuditLog, DSF, DSFValue
from app.services.admin_dashboard_service import CONTROL_ACTIONS, LOCAL_TIMEZONE, _utc_bounds

VALIDATION_ACTIONS = {"validation fiche", "validation fiche avec anomalies"}
CELL_ACTIONS = {"vérification", "correction"}

BREAK_SECONDS = 600          # au-delà, l'écart entre deux actions est une pause, pas du travail
BULK_WINDOW_SECONDS = 10     # validations enchaînées sur une même DSF
BULK_MIN_RUN = 3
FAST_SECONDS = 15            # temps médian par fiche jugé trop court
MAX_CELLS_PER_MINUTE = 40    # cadence de vérification manuelle jugée peu réaliste
MIN_VALIDATIONS = 5          # en dessous, pas de jugement
MIN_CELLS = 200
MIN_DSFS_FOR_DETECTION = 10

LOW_COVERAGE = 0.30
HIGH_EMPTY_RATE = 0.40
HIGH_BULK_RATE = 0.50


def _ts(value):
    return value.timestamp() if value.tzinfo else value.replace(tzinfo=None).timestamp()


def _flag_bulk(run):
    if len(run) >= BULK_MIN_RUN:
        for item in run:
            item["bulk"] = True


def _rate(part, whole):
    return part / whole if whole else None


def analyse_events(events):
    """Analyse la chronologie d'un opérateur.

    ``events`` : liste triée de dicts (``action``, ``dsf_id``, ``fiche_code``, ``at`` en secondes).
    Retourne les validations enrichies et les métriques de temps.
    """
    manual_since_validation = defaultdict(int)
    last_on_dsf = {}
    previous_at = None
    active_seconds = 0.0
    manual_events = 0
    corrections = 0
    reopens = 0
    validations = []

    for event in events:
        at, dsf_id, fiche = event["at"], event["dsf_id"], event["fiche_code"]
        if previous_at is not None and 0 < at - previous_at <= BREAK_SECONDS:
            active_seconds += at - previous_at
        previous_at = at
        action = event["action"]
        key = (dsf_id, fiche)
        if action in CELL_ACTIONS:
            manual_since_validation[key] += 1
            manual_events += 1
            if action == "correction":
                corrections += 1
        elif action in VALIDATION_ACTIONS or action == "fiche non renseignée":
            gap = at - last_on_dsf[dsf_id] if dsf_id in last_on_dsf else None
            validations.append(
                {
                    "dsf_id": dsf_id,
                    "fiche_code": fiche,
                    "at": at,
                    "action": action,
                    "manual_before": manual_since_validation.pop(key, 0),
                    "gap": gap if gap is not None and gap <= 1800 else None,
                    "accepted_anomalies": action == "validation fiche avec anomalies",
                    "not_provided": action == "fiche non renseignée",
                    "bulk": False,
                }
            )
        elif action == "annulation validation":
            reopens += 1
            manual_since_validation.pop(key, None)
        last_on_dsf[dsf_id] = at

    # Validations enchaînées : au moins BULK_MIN_RUN fiches de la même DSF en quelques secondes.
    run = []
    for validation in validations:
        if run and validation["dsf_id"] == run[-1]["dsf_id"] and validation["at"] - run[-1]["at"] <= BULK_WINDOW_SECONDS:
            run.append(validation)
        else:
            _flag_bulk(run)
            run = [validation]
    _flag_bulk(run)

    return {
        "validations": validations,
        "active_seconds": active_seconds,
        "manual_events": manual_events,
        "reopens": reopens,
        "corrections": corrections,
    }


def score_controller(metrics, team_detection_median):
    """Alertes explicites et score de rigueur sur 100 (None si données insuffisantes)."""
    alerts = []
    if metrics["validations_counted"] < MIN_VALIDATIONS:
        return None, alerts
    penalty = 0.0

    coverage = metrics["manual_coverage"]
    if coverage is not None and metrics["cells_total"] >= MIN_CELLS:
        penalty += (1 - coverage) * 30
        if coverage < LOW_COVERAGE:
            alerts.append(f"Seulement {round(coverage * 100)} % des cellules vérifiées une à une")
    empty = metrics["empty_rate"]
    if empty is not None:
        penalty += empty * 25
        if empty > HIGH_EMPTY_RATE:
            alerts.append(f"{round(empty * 100)} % des fiches validées sans vérifier aucune cellule")
    bulk = metrics["bulk_rate"]
    if bulk is not None:
        penalty += bulk * 15
        if bulk > HIGH_BULK_RATE:
            alerts.append(f"{round(bulk * 100)} % des fiches validées en rafale (« Tout valider »)")
    if metrics["median_seconds"] is not None and metrics["median_seconds"] < FAST_SECONDS:
        penalty += 10
        alerts.append(f"Temps médian de {round(metrics['median_seconds'])} s par fiche")
    if metrics["cells_per_minute"] is not None and metrics["cells_per_minute"] > MAX_CELLS_PER_MINUTE:
        penalty += 10
        alerts.append(f"Cadence de {round(metrics['cells_per_minute'])} cellules/minute, peu réaliste")
    if (
        metrics["dsf_touched"] >= MIN_DSFS_FOR_DETECTION
        and metrics["detections"] == 0
        and team_detection_median
    ):
        penalty += 10
        alerts.append(
            f"Aucune correction ni anomalie sur {metrics['dsf_touched']} DSF alors que l'équipe en détecte"
        )
    return max(0, min(100, round(100 - penalty))), alerts


def _level(score):
    if score is None:
        return "unknown"
    if score >= 75:
        return "good"
    return "warn" if score >= 50 else "bad"


def build_control_quality(date_from, date_to, controllers):
    start_utc, end_utc = _utc_bounds(date_from, date_to)
    controllers = list(controllers)
    names = [controller.username for controller in controllers]
    if not names:
        return {"rows": [], "team": None, "flagged": []}
    controller_ids = [controller.id for controller in controllers]

    logs = (
        db.session.query(
            AuditLog.operator, AuditLog.dsf_id, AuditLog.fiche_code, AuditLog.action, AuditLog.created_at
        )
        .filter(
            AuditLog.created_at >= start_utc,
            AuditLog.created_at < end_utc,
            AuditLog.action.in_(CONTROL_ACTIONS),
            AuditLog.operator.in_(names),
        )
        .order_by(AuditLog.created_at, AuditLog.id)
        .all()
    )
    events_by_operator = defaultdict(list)
    dsfs_by_operator = defaultdict(set)
    for operator, dsf_id, fiche_code, action, created_at in logs:
        events_by_operator[operator].append(
            {"dsf_id": dsf_id, "fiche_code": fiche_code, "action": action, "at": _ts(created_at)}
        )
        dsfs_by_operator[operator].add(dsf_id)

    cells = defaultdict(lambda: {"manual": 0, "fiche_validation": 0})
    cell_rows = (
        db.session.query(DSFValue.operator, DSFValue.verification_source, func.count(DSFValue.id))
        .filter(
            DSFValue.verified_at >= start_utc,
            DSFValue.verified_at < end_utc,
            DSFValue.operator.in_(names),
            DSFValue.verification_source.in_(["manual", "fiche_validation"]),
        )
        .group_by(DSFValue.operator, DSFValue.verification_source)
        .all()
    )
    for operator, source, count in cell_rows:
        cells[operator][source] = count

    open_anomalies = dict(
        db.session.query(DSFValue.operator, func.count(DSFValue.id))
        .filter(DSFValue.status == "anomaly", DSFValue.operator.in_(names))
        .group_by(DSFValue.operator)
        .all()
    )

    completed_ids = {
        row.id
        for row in DSF.query.filter(DSF.status == "completed", DSF.assigned_to_id.in_(controller_ids))
        .with_entities(DSF.id)
        .all()
    }

    # Corrections faites sur la DSF d'un contrôleur par quelqu'un d'autre (relecture).
    username_by_id = {controller.id: controller.username for controller in controllers}
    corrected_by_other = defaultdict(int)
    for assigned_id, operator, count in (
        db.session.query(DSF.assigned_to_id, AuditLog.operator, func.count(AuditLog.id))
        .join(DSF, DSF.id == AuditLog.dsf_id)
        .filter(
            AuditLog.created_at >= start_utc,
            AuditLog.created_at < end_utc,
            AuditLog.action == "correction",
            DSF.assigned_to_id.in_(controller_ids),
        )
        .group_by(DSF.assigned_to_id, AuditLog.operator)
        .all()
    ):
        if operator != username_by_id[assigned_id]:
            corrected_by_other[username_by_id[assigned_id]] += count

    rows, flagged_events = [], []
    for controller in controllers:
        name = controller.username
        analysis = analyse_events(events_by_operator.get(name, []))
        validations = analysis["validations"]
        counted = [item for item in validations if not item["not_provided"]]
        manual_cells = cells[name]["manual"]
        auto_cells = cells[name]["fiche_validation"]
        gaps = [item["gap"] for item in counted if item["gap"] is not None]
        active_minutes = analysis["active_seconds"] / 60
        dsf_touched = len(dsfs_by_operator.get(name, ()))
        accepted = sum(1 for item in counted if item["accepted_anomalies"])
        completed_dsfs = len({item["dsf_id"] for item in validations} & completed_ids)
        rows.append(
            {
                "user": controller,
                "dsf_touched": dsf_touched,
                "dsf_completed": completed_dsfs,
                "fiches_validated": len(counted),
                "fiches_not_provided": len(validations) - len(counted),
                "validations_counted": len(counted),
                "cells_manual": manual_cells,
                "cells_auto": auto_cells,
                "cells_total": manual_cells + auto_cells,
                "manual_coverage": _rate(manual_cells, manual_cells + auto_cells),
                "empty_rate": _rate(sum(1 for item in counted if item["manual_before"] == 0), len(counted)),
                "bulk_rate": _rate(sum(1 for item in counted if item["bulk"]), len(counted)),
                "median_seconds": median(gaps) if gaps else None,
                "active_minutes": round(active_minutes),
                "minutes_per_dsf": round(active_minutes / completed_dsfs, 1) if completed_dsfs else None,
                "cells_per_minute": analysis["manual_events"] / active_minutes if active_minutes >= 5 else None,
                "corrections": analysis["corrections"],
                "accepted_anomalies": accepted,
                "detections": analysis["corrections"] + accepted,
                "detection_per_100": (analysis["corrections"] + accepted) / dsf_touched * 100 if dsf_touched else None,
                "reopens": analysis["reopens"],
                "corrected_by_other": corrected_by_other.get(name, 0),
                "open_anomalies": open_anomalies.get(name, 0),
            }
        )
        for item in counted:
            reasons = []
            if item["manual_before"] == 0:
                reasons.append("aucune cellule vérifiée")
            if item["bulk"]:
                reasons.append("validée en rafale")
            if item["gap"] is not None and item["gap"] < FAST_SECONDS:
                reasons.append(f"{round(item['gap'])} s après l'action précédente")
            if reasons:
                flagged_events.append({**item, "controller": controller, "reasons": reasons})

    detection_values = [
        row["detection_per_100"] for row in rows if row["dsf_touched"] >= MIN_DSFS_FOR_DETECTION
    ]
    team_detection_median = median(detection_values) if detection_values else None
    for row in rows:
        row["score"], row["alerts"] = score_controller(row, team_detection_median)
        if row["score"] is not None and row["corrected_by_other"]:
            row["alerts"].append(f"{row['corrected_by_other']} correction(s) faite(s) par un autre sur ses DSF")
        row["level"] = _level(row["score"])

    scored = [row["score"] for row in rows if row["score"] is not None]
    total_cells = sum(row["cells_total"] for row in rows)
    team = {
        "average_score": round(sum(scored) / len(scored)) if scored else None,
        "to_review": sum(1 for row in rows if row["level"] in {"warn", "bad"}),
        "manual_coverage": sum(row["cells_manual"] for row in rows) / total_cells if total_cells else None,
        "detection_median": team_detection_median,
        "validations": sum(row["validations_counted"] for row in rows),
        "flagged": len(flagged_events),
    }

    flagged_events.sort(key=lambda item: item["at"], reverse=True)
    top = flagged_events[:150]
    dsf_ids = {item["dsf_id"] for item in top}
    dsf_by_id = {dsf.id: dsf for dsf in DSF.query.filter(DSF.id.in_(dsf_ids)).all()} if dsf_ids else {}
    flagged = [
        {
            **item,
            "dsf": dsf_by_id[item["dsf_id"]],
            "when": datetime.fromtimestamp(item["at"], LOCAL_TIMEZONE).strftime("%d/%m/%Y %H:%M"),
            "fiche_name": FICHE_BY_CODE.get(item["fiche_code"], {}).get("name", item["fiche_code"]),
        }
        for item in top
        if item["dsf_id"] in dsf_by_id
    ]
    rows.sort(key=lambda row: (row["score"] is None, row["score"] if row["score"] is not None else 0))
    return {"rows": rows, "team": team, "flagged": flagged}
