from flask import Blueprint, render_template, request

from app.extensions import db
from app.models import AuditLog, DSF, ImportSession
from app.services.auth_service import current_user
from app.services.dsf_service import dashboard_stats, search_dsfs, serialized_display


main_bp = Blueprint("main", __name__)


def _accessible_sessions():
    user = current_user()
    query = ImportSession.query.order_by(ImportSession.imported_at.desc())
    if user.is_admin:
        return query.all()
    return (
        query.join(DSF)
        .filter(DSF.assigned_to_id == user.id)
        .distinct()
        .all()
    )


def _active_session(sessions, requested_session):
    if requested_session:
        return next((item for item in sessions if item.id == requested_session), None) or (sessions[0] if sessions else None)
    return sessions[0] if sessions else None


@main_bp.get("/")
def dashboard():
    user = current_user()
    sessions = _accessible_sessions()
    requested_session = request.args.get("session_id", type=int)
    active_session = _active_session(sessions, requested_session)
    term = request.args.get("q", "")
    status = request.args.get("status", "")
    assigned_to_id = None if user.is_admin else user.id
    dsfs = search_dsfs(term, status, active_session.id if active_session else None, assigned_to_id) if active_session else []
    stats = dashboard_stats(active_session.id if active_session else None, assigned_to_id) if active_session else dashboard_stats(-1, assigned_to_id)
    return render_template(
        "dashboard.html",
        sessions=sessions,
        active_session=active_session,
        dsfs=dsfs,
        stats=stats,
        term=term,
        selected_status=status,
    )


@main_bp.get("/dsfs")
def dsf_list():
    user = current_user()
    sessions = _accessible_sessions()
    requested_session = request.args.get("session_id", type=int)
    active_session = _active_session(sessions, requested_session)
    term = request.args.get("q", "")
    status = request.args.get("status", "")
    assigned_to_id = None if user.is_admin else user.id
    dsfs = search_dsfs(term, status, active_session.id if active_session else None, assigned_to_id) if active_session else []
    return render_template(
        "dsf_list.html",
        sessions=sessions,
        active_session=active_session,
        dsfs=dsfs,
        term=term,
        selected_status=status,
    )


@main_bp.get("/history")
def history():
    query = AuditLog.query.join(DSF)
    if not current_user().is_admin:
        query = query.filter(DSF.assigned_to_id == current_user().id)
    logs = query.order_by(AuditLog.created_at.desc()).limit(1000).all()
    return render_template("history.html", logs=logs, serialized_display=serialized_display)
