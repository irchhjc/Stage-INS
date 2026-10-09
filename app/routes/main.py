from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import update

from app.extensions import db
from app.models import AuditLog, DSF, ImportSession
from app.services.auth_service import current_user
from app.services.dsf_service import dashboard_stats, search_dsfs, serialized_display


main_bp = Blueprint("main", __name__)


def _accessible_sessions(owned_active_only=False):
    user = current_user()
    query = ImportSession.query.order_by(ImportSession.imported_at.desc())
    if user.is_admin or not owned_active_only:
        return query.all()
    return (
        query.join(DSF)
        .filter(
            DSF.assigned_to_id == user.id,
            DSF.status.in_(("in_progress", "completed")),
        )
        .distinct()
        .all()
    )


def _scope(sessions, raw_session_id):
    """Classeur(s) affiché(s) : tous les classeurs accessibles par défaut, ou un seul choisi."""
    if raw_session_id and str(raw_session_id).isdigit():
        chosen = next((item for item in sessions if item.id == int(raw_session_id)), None)
        if chosen is not None:
            return chosen, [chosen.id]
    return None, [item.id for item in sessions]


def _scope_context(sessions, active_session):
    return {
        "sessions": sessions,
        "active_session": active_session,
        "all_sessions": bool(sessions) and active_session is None,
        "session_param": active_session.id if active_session else "all",
    }


@main_bp.get("/")
def dashboard():
    user = current_user()
    sessions = _accessible_sessions()
    active_session, session_ids = _scope(sessions, request.args.get("session_id"))
    term = request.args.get("q", "")
    status = request.args.get("status", "")
    dsfs = search_dsfs(term, status, import_session_ids=session_ids) if sessions else []
    # Compteurs et progression : toujours tous les classeurs importés, quel que soit le filtre du tableau.
    stats = dashboard_stats(import_session_ids=[item.id for item in sessions]) if sessions else dashboard_stats(-1)
    selected_stats = dashboard_stats(import_session_ids=session_ids) if active_session is not None else None
    export_completed_count = 0
    if active_session is not None:
        export_completed_count = selected_stats["completed"] if user.is_admin else DSF.query.filter_by(
            import_session_id=active_session.id,
            assigned_to_id=user.id,
            status="completed",
        ).count()
    return render_template(
        "dashboard.html",
        completed_all=DSF.query.filter_by(status="completed").count() if user.is_admin else 0,
        dsfs=dsfs,
        stats=stats,
        selected_stats=selected_stats,
        term=term,
        selected_status=status,
        list_mode="all",
        export_completed_count=export_completed_count,
        **_scope_context(sessions, active_session),
    )


@main_bp.get("/dsfs")
def dsf_list():
    sessions = _accessible_sessions()
    active_session, session_ids = _scope(sessions, request.args.get("session_id"))
    term = request.args.get("q", "")
    status = request.args.get("status", "")
    dsfs = search_dsfs(term, status, import_session_ids=session_ids) if sessions else []
    return render_template(
        "dsf_list.html",
        dsfs=dsfs,
        term=term,
        selected_status=status,
        list_mode="all",
        **_scope_context(sessions, active_session),
    )


@main_bp.get("/my-dsfs")
def my_dsf_list():
    user = current_user()
    if user.is_admin:
        return redirect(url_for("main.dsf_list"))
    sessions = _accessible_sessions(owned_active_only=True)
    active_session, session_ids = _scope(sessions, request.args.get("session_id"))
    term = request.args.get("q", "")
    status = request.args.get("status", "")
    if status not in {"", "in_progress", "completed", "anomalies"}:
        status = ""
    dsfs = search_dsfs(
        term,
        status,
        assigned_to_id=user.id,
        statuses=("in_progress", "completed"),
        import_session_ids=session_ids,
    ) if sessions else []
    return render_template(
        "dsf_list.html",
        dsfs=dsfs,
        term=term,
        selected_status=status,
        list_mode="mine",
        **_scope_context(sessions, active_session),
    )


@main_bp.post("/dsfs/<int:dsf_id>/claim")
def claim_dsf(dsf_id):
    user = current_user()
    if user.is_admin:
        return redirect(url_for("dsf.detail", dsf_id=dsf_id))

    now = datetime.now(timezone.utc)
    claimed_id = db.session.execute(
        update(DSF)
        .where(DSF.id == dsf_id, DSF.assigned_to_id.is_(None))
        .values(
            assigned_to_id=user.id,
            assigned_by_id=user.id,
            assigned_at=now,
        )
        .returning(DSF.id)
    ).scalar_one_or_none()

    if claimed_id is not None:
        db.session.add(
            AuditLog(
                dsf_id=dsf_id,
                action="prise en charge DSF",
                old_value="Non assignée",
                new_value=user.username,
                operator=user.username,
            )
        )
        db.session.commit()
        flash("La DSF vous est maintenant attribuée.", "success")
        return redirect(url_for("dsf.detail", dsf_id=dsf_id))

    db.session.rollback()
    dsf = db.get_or_404(DSF, dsf_id)
    if dsf.assigned_to_id == user.id:
        return redirect(url_for("dsf.detail", dsf_id=dsf.id))
    flash("Cette DSF vient d’être prise en charge par un autre contrôleur.", "warning")
    return redirect(url_for("main.dsf_list", session_id=dsf.import_session_id))


@main_bp.get("/history")
def history():
    query = AuditLog.query.join(DSF)
    if not current_user().is_admin:
        query = query.filter(DSF.assigned_to_id == current_user().id)
    logs = query.order_by(AuditLog.created_at.desc()).limit(1000).all()
    return render_template("history.html", logs=logs, serialized_display=serialized_display)
