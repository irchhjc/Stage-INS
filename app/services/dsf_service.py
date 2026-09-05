from datetime import datetime, timezone

from sqlalchemy import func, or_

from app.extensions import db
from app.models import AuditLog, DSF, DSFValue, FicheStatus, ImportColumn
from app.services.value_codec import display_value, parse_user_value, serialize_value, values_equal


FINAL_FICHE_STATUSES = {"verified", "not_provided"}


def utcnow():
    return datetime.now(timezone.utc)


def clean_operator(operator):
    return (operator or "Opérateur").strip()[:120] or "Opérateur"


def recompute_dsf_progress(dsf, commit=False):
    statuses = FicheStatus.query.filter_by(dsf_id=dsf.id).all()
    total = len(statuses)
    completed = sum(status.status in FINAL_FICHE_STATUSES for status in statuses)
    dsf.progress = completed / total if total else 0.0
    if total and completed == total:
        dsf.status = "completed"
    elif all(status.status == "not_started" for status in statuses):
        dsf.status = "not_started"
    else:
        dsf.status = "in_progress"
    manual_anomalies = DSFValue.query.filter_by(dsf_id=dsf.id, status="anomaly").count()
    from app.services.validation_service import run_validation_rules

    dsf.anomaly_count = manual_anomalies + len(run_validation_rules(dsf.id))
    if commit:
        db.session.commit()
    return completed, total


def touch_fiche(dsf_id, fiche_code):
    fiche = FicheStatus.query.filter_by(dsf_id=dsf_id, fiche_code=fiche_code).one()
    has_anomaly = (
        DSFValue.query.join(ImportColumn)
        .filter(
            DSFValue.dsf_id == dsf_id,
            ImportColumn.fiche_code == fiche_code,
            DSFValue.status == "anomaly",
        )
        .first()
        is not None
    )
    fiche.status = "anomaly" if has_anomaly else "in_progress"
    fiche.validated_at = None
    return fiche


def update_value(dsf_value, raw_value, status, operator, comment=None):
    allowed_statuses = {"unverified", "verified", "anomaly", "not_applicable"}
    if status not in allowed_statuses:
        raise ValueError("Statut de cellule invalide.")
    operator = clean_operator(operator)
    old_serialized = dsf_value.current_value
    parsed = parse_user_value(raw_value, dsf_value.original_value, dsf_value.variable_name)
    new_serialized = serialize_value(parsed)
    changed_now = not values_equal(old_serialized, new_serialized)
    corrected = not values_equal(dsf_value.original_value, new_serialized)
    now = utcnow()

    dsf_value.current_value = new_serialized
    dsf_value.corrected = corrected
    dsf_value.status = status
    dsf_value.verified = status == "verified"
    dsf_value.verification_source = "manual" if status != "unverified" else None
    dsf_value.operator = operator
    dsf_value.comment = (comment or "").strip() or None
    dsf_value.verified_at = now if status == "verified" else None
    dsf_value.corrected_at = now if corrected else None

    if changed_now or status != "unverified":
        db.session.add(
            AuditLog(
                dsf_id=dsf_value.dsf_id,
                fiche_code=dsf_value.column.fiche_code,
                variable_name=dsf_value.variable_name,
                column_index=dsf_value.column.column_index,
                old_value=old_serialized,
                new_value=new_serialized,
                action="correction" if corrected else "vérification",
                operator=operator,
            )
        )

    touch_fiche(dsf_value.dsf_id, dsf_value.column.fiche_code)
    recompute_dsf_progress(dsf_value.dsf)
    db.session.commit()
    return changed_now


def validate_fiche(dsf, fiche_code, operator, allow_anomalies=False, anomaly_details=None):
    operator = clean_operator(operator)
    fiche = FicheStatus.query.filter_by(dsf_id=dsf.id, fiche_code=fiche_code).one()
    values = (
        DSFValue.query.join(ImportColumn)
        .filter(DSFValue.dsf_id == dsf.id, ImportColumn.fiche_code == fiche_code)
        .all()
    )
    has_manual_anomalies = any(value.status == "anomaly" for value in values)
    if has_manual_anomalies and not allow_anomalies:
        raise ValueError("La fiche contient encore une anomalie à résoudre.")
    now = utcnow()
    for value in values:
        if value.status == "unverified":
            value.status = "verified"
            value.verified = True
            value.verification_source = "fiche_validation"
            value.verified_at = now
            value.operator = operator
    fiche.status = "verified"
    fiche.validated_at = now
    fiche.operator = operator
    db.session.add(
        AuditLog(
            dsf_id=dsf.id,
            fiche_code=fiche_code,
            action="validation fiche avec anomalies" if allow_anomalies else "validation fiche",
            operator=operator,
            new_value=anomaly_details if allow_anomalies else None,
        )
    )
    recompute_dsf_progress(dsf)
    db.session.commit()


def mark_fiche_not_provided(dsf, fiche_code, operator):
    operator = clean_operator(operator)
    fiche = FicheStatus.query.filter_by(dsf_id=dsf.id, fiche_code=fiche_code).one()
    now = utcnow()
    values = (
        DSFValue.query.join(ImportColumn)
        .filter(DSFValue.dsf_id == dsf.id, ImportColumn.fiche_code == fiche_code)
        .all()
    )
    for value in values:
        value.status = "not_applicable"
        value.verified = False
        value.verification_source = "not_provided"
        value.verified_at = None
        value.operator = operator
    fiche.status = "not_provided"
    fiche.validated_at = now
    fiche.operator = operator
    db.session.add(
        AuditLog(
            dsf_id=dsf.id,
            fiche_code=fiche_code,
            action="fiche non renseignée",
            operator=operator,
        )
    )
    recompute_dsf_progress(dsf)
    db.session.commit()


def reopen_fiche(dsf, fiche_code, operator):
    operator = clean_operator(operator)
    fiche = FicheStatus.query.filter_by(dsf_id=dsf.id, fiche_code=fiche_code).one()
    values = (
        DSFValue.query.join(ImportColumn)
        .filter(DSFValue.dsf_id == dsf.id, ImportColumn.fiche_code == fiche_code)
        .all()
    )
    for value in values:
        if value.verification_source in {"fiche_validation", "not_provided"}:
            value.status = "unverified"
            value.verified = False
            value.verification_source = None
            value.verified_at = None
    fiche.status = "in_progress"
    fiche.validated_at = None
    fiche.operator = operator
    db.session.add(
        AuditLog(dsf_id=dsf.id, fiche_code=fiche_code, action="annulation validation", operator=operator)
    )
    recompute_dsf_progress(dsf)
    db.session.commit()


def dashboard_stats(import_session_id=None, assigned_to_id=None):
    query = DSF.query
    if import_session_id:
        query = query.filter_by(import_session_id=import_session_id)
    if assigned_to_id is not None:
        query = query.filter_by(assigned_to_id=assigned_to_id)
    total = query.count()
    completed = query.filter_by(status="completed").count()
    in_progress = query.filter_by(status="in_progress").count()
    not_started = query.filter_by(status="not_started").count()
    with_anomalies = query.filter(DSF.anomaly_count > 0).count()
    return {
        "total": total,
        "completed": completed,
        "in_progress": in_progress,
        "not_started": not_started,
        "with_anomalies": with_anomalies,
        "overall_progress": int(round((completed / total) * 100)) if total else 0,
    }


def search_dsfs(term, status=None, import_session_id=None, assigned_to_id=None):
    query = DSF.query
    if import_session_id:
        query = query.filter_by(import_session_id=import_session_id)
    if assigned_to_id is not None:
        query = query.filter_by(assigned_to_id=assigned_to_id)
    if status == "anomalies":
        query = query.filter(DSF.anomaly_count > 0)
    elif status in {"not_started", "in_progress", "completed"}:
        query = query.filter_by(status=status)
    if term:
        pattern = f"%{term.strip()}%"
        query = query.filter(
            or_(
                DSF.niu.ilike(pattern),
                DSF.numero_dsf.ilike(pattern),
                DSF.raison_sociale.ilike(pattern),
                DSF.sigle.ilike(pattern),
            )
        )
    return query.order_by(DSF.raison_sociale, DSF.annee.desc()).all()


def fiche_counts(dsf_id):
    rows = (
        db.session.query(FicheStatus.status, func.count(FicheStatus.id))
        .filter(FicheStatus.dsf_id == dsf_id)
        .group_by(FicheStatus.status)
        .all()
    )
    return dict(rows)


def serialized_display(serialized):
    return display_value(serialized)
