import json

from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import AuditLog, DSF, DSFValue, FicheStatus, ImportColumn
from app.services.dsf_service import (
    mark_fiche_not_provided,
    recompute_dsf_progress,
    reopen_fiche,
    update_value,
    validate_fiche,
)
from app.services.auth_service import accessible_dsf_or_404, can_access_dsf, current_user
from app.services.mapping_service import build_accounting_sections
from app.services.validation_service import run_validation_rules
from app.services.value_codec import display_value, raw_input_value


dsf_bp = Blueprint("dsf", __name__, url_prefix="/dsf")


def _operator(payload=None):
    return current_user().username


def _sidebar(dsf, issues):
    issue_codes = {code for issue in issues for code in issue["fiche_codes"]}
    statuses = FicheStatus.query.filter_by(dsf_id=dsf.id).order_by(FicheStatus.position).all()
    return statuses, issue_codes


def _progress_counts(statuses):
    completed = sum(item.status in {"verified", "not_provided"} for item in statuses)
    return completed, len(statuses)


@dsf_bp.get("/<int:dsf_id>")
def detail(dsf_id):
    dsf = accessible_dsf_or_404(dsf_id)
    issues = run_validation_rules(dsf.id)
    statuses, issue_codes = _sidebar(dsf, issues)
    completed, total = _progress_counts(statuses)
    return render_template(
        "dsf_detail.html",
        dsf=dsf,
        fiche_statuses=statuses,
        issue_codes=issue_codes,
        completed=completed,
        total=total,
        issues=issues,
    )


@dsf_bp.get("/<int:dsf_id>/fiche/<fiche_code>")
def fiche_detail(dsf_id, fiche_code):
    dsf = accessible_dsf_or_404(dsf_id)
    fiche = FicheStatus.query.filter_by(dsf_id=dsf.id, fiche_code=fiche_code).first_or_404()
    values = (
        DSFValue.query.options(joinedload(DSFValue.column)).join(ImportColumn)
        .filter(DSFValue.dsf_id == dsf.id, ImportColumn.fiche_code == fiche_code)
        .order_by(ImportColumn.column_index)
        .all()
    )
    sections = build_accounting_sections(values)
    all_issues = run_validation_rules(dsf.id)
    statuses, issue_codes = _sidebar(dsf, all_issues)
    completed, total = _progress_counts(statuses)
    issues = [issue for issue in all_issues if fiche_code in issue["fiche_codes"]]
    current_index = next(index for index, item in enumerate(statuses) if item.fiche_code == fiche_code)
    previous_fiche = statuses[current_index - 1] if current_index > 0 else None
    next_fiche = statuses[current_index + 1] if current_index + 1 < len(statuses) else None
    return render_template(
        "fiche_detail.html",
        dsf=dsf,
        fiche=fiche,
        fiche_statuses=statuses,
        issue_codes=issue_codes,
        sections=sections,
        completed=completed,
        total=total,
        issues=issues,
        display_value=display_value,
        raw_input_value=raw_input_value,
        previous_fiche=previous_fiche,
        next_fiche=next_fiche,
    )


@dsf_bp.patch("/api/values/<int:value_id>")
def api_update_value(value_id):
    value = db.get_or_404(DSFValue, value_id)
    if not can_access_dsf(value.dsf):
        abort(403)
    payload = request.get_json(silent=True) or {}
    try:
        update_value(
            value,
            payload.get("value", raw_input_value(value.current_value)),
            payload.get("status", value.status),
            _operator(payload),
            payload.get("comment", value.comment),
        )
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 422
    fiche = FicheStatus.query.filter_by(dsf_id=value.dsf_id, fiche_code=value.column.fiche_code).one()
    return jsonify(
        ok=True,
        value_id=value.id,
        display_value=display_value(value.current_value),
        raw_value=raw_input_value(value.current_value),
        status=value.status,
        corrected=value.corrected,
        fiche_status=fiche.status,
        progress=value.dsf.progress_percent,
        anomaly_count=value.dsf.anomaly_count,
    )


@dsf_bp.post("/api/<int:dsf_id>/fiches/<fiche_code>/validate")
def api_validate_fiche(dsf_id, fiche_code):
    dsf = accessible_dsf_or_404(dsf_id)
    payload = request.get_json(silent=True) or {}
    automatic_issues = [
        issue
        for issue in run_validation_rules(dsf.id)
        if fiche_code in issue["fiche_codes"]
    ]
    manual_anomaly_count = (
        DSFValue.query.join(ImportColumn)
        .filter(
            DSFValue.dsf_id == dsf.id,
            ImportColumn.fiche_code == fiche_code,
            DSFValue.status == "anomaly",
        )
        .count()
    )
    has_anomalies = bool(automatic_issues or manual_anomaly_count)
    acknowledge = payload.get("acknowledge_anomalies") is True
    if has_anomalies and not acknowledge:
        messages = [issue["message"] for issue in automatic_issues]
        if manual_anomaly_count:
            messages.append(f"{manual_anomaly_count} cellule(s) marquée(s) comme anomalie par l'opérateur.")
        return (
            jsonify(
                ok=False,
                requires_confirmation=True,
                error="Cette fiche contient des anomalies. Examinez-les avant de confirmer la validation.",
                anomaly_count=len(automatic_issues) + manual_anomaly_count,
                issues=messages,
            ),
            409,
        )
    try:
        validate_fiche(
            dsf,
            fiche_code,
            _operator(payload),
            allow_anomalies=acknowledge and has_anomalies,
            anomaly_details=(
                json.dumps(
                    {
                        "automatic_issues": [issue["message"] for issue in automatic_issues],
                        "manual_anomaly_count": manual_anomaly_count,
                    },
                    ensure_ascii=False,
                )
                if acknowledge and has_anomalies
                else None
            ),
        )
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 409
    return jsonify(ok=True, status="verified", progress=dsf.progress_percent, dsf_status=dsf.status)


@dsf_bp.post("/api/<int:dsf_id>/fiches/<fiche_code>/not-provided")
def api_not_provided(dsf_id, fiche_code):
    dsf = accessible_dsf_or_404(dsf_id)
    payload = request.get_json(silent=True) or {}
    mark_fiche_not_provided(dsf, fiche_code, _operator(payload))
    return jsonify(ok=True, status="not_provided", progress=dsf.progress_percent, dsf_status=dsf.status)


@dsf_bp.post("/api/<int:dsf_id>/fiches/<fiche_code>/reopen")
def api_reopen_fiche(dsf_id, fiche_code):
    dsf = accessible_dsf_or_404(dsf_id)
    payload = request.get_json(silent=True) or {}
    reopen_fiche(dsf, fiche_code, _operator(payload))
    return jsonify(ok=True, status="in_progress", progress=dsf.progress_percent, dsf_status=dsf.status)


@dsf_bp.get("/api/<int:dsf_id>/search")
def api_search_variables(dsf_id):
    dsf = accessible_dsf_or_404(dsf_id)
    term = request.args.get("q", "").strip()
    if len(term) < 2:
        return jsonify(ok=True, results=[])
    matches = (
        DSFValue.query.join(ImportColumn)
        .filter(
            DSFValue.dsf_id == dsf.id,
            ImportColumn.variable_name.ilike(f"%{term}%"),
        )
        .order_by(ImportColumn.column_index)
        .limit(50)
        .all()
    )
    return jsonify(
        ok=True,
        results=[
            {
                "value_id": value.id,
                "variable_name": value.variable_name,
                "fiche_name": value.column.fiche_name,
                "url": url_for(
                    "dsf.fiche_detail",
                    dsf_id=dsf.id,
                    fiche_code=value.column.fiche_code,
                    _anchor=f"value-{value.id}",
                ),
            }
            for value in matches
        ],
    )


@dsf_bp.get("/<int:dsf_id>/history")
def dsf_history(dsf_id):
    dsf = accessible_dsf_or_404(dsf_id)
    logs = AuditLog.query.filter_by(dsf_id=dsf.id).order_by(AuditLog.created_at.desc()).all()
    return render_template("history.html", logs=logs, dsf=dsf, serialized_display=display_value)
