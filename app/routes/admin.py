from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.extensions import db
from app.models import AuditLog, DSF, ImportSession, User
from app.services.admin_dashboard_service import build_admin_performance
from app.services.auth_service import admin_required, create_user, current_user
from app.services.dsf_service import search_dsfs


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _controller_progress(controllers):
    rows = []
    for controller in controllers:
        assigned = DSF.query.filter_by(assigned_to_id=controller.id)
        total = assigned.count()
        completed = assigned.filter_by(status="completed").count()
        in_progress = assigned.filter_by(status="in_progress").count()
        anomalies = assigned.filter(DSF.anomaly_count > 0).count()
        average = db.session.query(db.func.avg(DSF.progress)).filter(DSF.assigned_to_id == controller.id).scalar()
        rows.append(
            {
                "user": controller,
                "total": total,
                "completed": completed,
                "in_progress": in_progress,
                "anomalies": anomalies,
                "progress": int(round((average or 0) * 100)),
                "completion_rate": int(round(completed / total * 100)) if total else 0,
            }
        )
    return rows


@admin_bp.get("/")
@admin_required
def dashboard():
    controllers = User.query.filter_by(role="controller", is_active=True).order_by(User.username).all()
    sessions = ImportSession.query.order_by(ImportSession.imported_at.desc()).all()
    requested_session = request.args.get("session_id", type=int)
    active_session = db.session.get(ImportSession, requested_session) if requested_session else (sessions[0] if sessions else None)
    term = request.args.get("q", "")
    status = request.args.get("status", "")
    dsfs = search_dsfs(term, status, active_session.id if active_session else None) if active_session else []
    try:
        performance = build_admin_performance(
            request.args.get("date_from"),
            request.args.get("date_to"),
        )
    except ValueError as exc:
        flash(str(exc), "warning")
        performance = build_admin_performance()
    return render_template(
        "admin/dashboard.html",
        controllers=controllers,
        controller_progress=_controller_progress(controllers),
        sessions=sessions,
        active_session=active_session,
        dsfs=dsfs,
        term=term,
        selected_status=status,
        performance=performance,
    )


@admin_bp.post("/users")
@admin_required
def create_controller():
    try:
        user = create_user(request.form.get("username"), request.form.get("password"), role="controller")
        flash(f"Le compte {user.username} a été créé.", "success")
    except ValueError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("admin.dashboard"))


@admin_bp.post("/dsfs/<int:dsf_id>/assign")
@admin_required
def assign_dsf(dsf_id):
    dsf = db.get_or_404(DSF, dsf_id)
    if dsf.assigned_to_id is not None:
        flash(
            f"Cette DSF est déjà affectée à {dsf.assignee.username}. Son affectation ne peut plus être modifiée.",
            "warning",
        )
        return redirect(request.referrer or url_for("admin.dashboard", session_id=dsf.import_session_id))
    user_id = request.form.get("user_id", type=int)
    assignee = db.session.get(User, user_id) if user_id else None
    if assignee is None or assignee.role != "controller" or not assignee.is_active:
        flash("Le contrôleur sélectionné est invalide.", "danger")
        return redirect(request.referrer or url_for("admin.dashboard"))

    dsf.assignee = assignee
    dsf.assigned_by = current_user()
    dsf.assigned_at = datetime.now(timezone.utc)
    db.session.add(
        AuditLog(
            dsf_id=dsf.id,
            action="affectation DSF",
            old_value="Non assignée",
            new_value=assignee.username,
            operator=current_user().username,
        )
    )
    db.session.commit()
    flash(f"DSF {dsf.numero_dsf or dsf.niu} assignée à {assignee.username}.", "success")
    return redirect(request.referrer or url_for("admin.dashboard"))


@admin_bp.post("/import-sessions/<int:import_session_id>/assign-all")
@admin_required
def assign_all_dsfs(import_session_id):
    import_session = db.get_or_404(ImportSession, import_session_id)
    user_id = request.form.get("user_id", type=int)
    assignee = db.session.get(User, user_id) if user_id else None
    if assignee is None or assignee.role != "controller" or not assignee.is_active:
        flash("Sélectionnez un contrôleur valide.", "danger")
        return redirect(url_for("admin.dashboard", session_id=import_session.id))

    dsfs = DSF.query.filter_by(import_session_id=import_session.id).order_by(DSF.id).all()
    unassigned = [dsf for dsf in dsfs if dsf.assigned_to_id is None]
    already_assigned = len(dsfs) - len(unassigned)
    now = datetime.now(timezone.utc)
    administrator = current_user()
    for dsf in unassigned:
        dsf.assignee = assignee
        dsf.assigned_by = administrator
        dsf.assigned_at = now
        db.session.add(
            AuditLog(
                dsf_id=dsf.id,
                action="affectation DSF groupée",
                old_value="Non assignée",
                new_value=assignee.username,
                operator=administrator.username,
            )
        )
    db.session.commit()

    if unassigned:
        message = f"{len(unassigned)} DSF affectée(s) à {assignee.username}."
        if already_assigned:
            message += f" {already_assigned} DSF déjà affectée(s) ont été conservées sans modification."
        flash(message, "success")
    else:
        flash("Toutes les DSF de ce classeur étaient déjà affectées. Aucune modification effectuée.", "warning")
    return redirect(url_for("admin.dashboard", session_id=import_session.id))
