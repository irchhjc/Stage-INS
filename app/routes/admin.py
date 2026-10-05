from datetime import datetime, timezone

from sqlalchemy import update, or_
from sqlalchemy.orm import joinedload

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.extensions import db
from app.models import AuditLog, DSF, ImportSession, User
from app.services.admin_dashboard_service import build_admin_performance, build_controller_daily_stats, resolve_period
from app.services.control_quality_service import build_control_quality
from app.services.auth_service import admin_required, login_required, create_user, current_user, normalize_full_name
from app.services.dsf_service import search_dsfs
from app.services.activity_service import activity_groups
from app.services.search_service import Page, rank_matching_ids


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def _controller_progress(controllers):
    rows = []
    for controller in controllers:
        assigned = DSF.query.filter_by(assigned_to_id=controller.id)
        total = assigned.count()
        not_started = assigned.filter_by(status="not_started").count()
        completed = assigned.filter_by(status="completed").count()
        in_progress = assigned.filter_by(status="in_progress").count()
        anomalies = assigned.filter(DSF.anomaly_count > 0).count()
        average = db.session.query(db.func.avg(DSF.progress)).filter(DSF.assigned_to_id == controller.id).scalar()
        rows.append(
            {
                "user": controller,
                "total": total,
                "not_started": not_started,
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
    activity, branches = activity_groups(active_session.id) if active_session else ({}, [])
    branch = request.args.get("branch", "")
    if branch:
        dsfs = [d for d in dsfs if activity.get(d.id, {}).get("key") == branch]
    try:
        performance = build_admin_performance(
            request.args.get("date_from"),
            request.args.get("date_to"),
        )
    except ValueError as exc:
        flash(str(exc), "warning")
        performance = build_admin_performance()
    controller_daily = build_controller_daily_stats(
        performance["date_from"],
        performance["date_to"],
        controllers,
    )
    return render_template(
        "admin/dashboard.html",
        activity=activity, branches=branches, branch=branch,
        account_users=User.query.order_by(User.username).all(),
        controllers=controllers,
        controller_progress=_controller_progress(controllers),
        controller_daily=controller_daily,
        sessions=sessions,
        active_session=active_session,
        dsfs=dsfs,
        term=term,
        selected_status=status,
        performance=performance,
    )


@admin_bp.get("/rigueur")
@admin_required
def control_quality():
    try:
        date_from, date_to = resolve_period(request.args.get("date_from"), request.args.get("date_to"))
    except ValueError as exc:
        flash(str(exc), "warning")
        date_from, date_to = resolve_period()
    controllers = User.query.filter_by(role="controller", is_active=True).order_by(User.username).all()
    return render_template(
        "admin/control_quality.html",
        quality=build_control_quality(date_from, date_to, controllers),
        date_from=date_from,
        date_to=date_to,
    )


@admin_bp.post("/users")
@admin_required
def create_controller():
    try:
        user = create_user(request.form.get("username"), request.form.get("password"), role="controller", full_name=request.form.get("full_name"))
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


@admin_bp.post("/controllers/<int:controller_id>/unassign-not-started")
@admin_required
def unassign_not_started(controller_id):
    controller = db.get_or_404(User, controller_id)
    if controller.role != "controller":
        abort(400)
    operator = current_user().username
    try:
        # The status/owner conditions are checked by the UPDATE itself, not
        # from the potentially stale count displayed in the browser.
        removed_ids = db.session.execute(
            update(DSF)
            .where(DSF.assigned_to_id == controller.id, DSF.status == "not_started")
            .values(assigned_to_id=None, assigned_by_id=None, assigned_at=None)
            .returning(DSF.id)
        ).scalars().all()
        for dsf_id in removed_ids:
            db.session.add(AuditLog(
                dsf_id=dsf_id,
                action="retrait affectation DSF non commencée",
                old_value=controller.username,
                new_value="Non assignée",
                operator=operator,
            ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    if removed_ids:
        flash(
            f"{len(removed_ids)} DSF non commencée(s) retirée(s) à {controller.username}. "
            "Elles peuvent être réaffectées. Les DSF en cours et terminées sont conservées.",
            "success",
        )
    else:
        flash(f"Aucune DSF non commencée à retirer à {controller.username}.", "info")
    return redirect(url_for("admin.dashboard"))


@admin_bp.get("/search")
@login_required
def global_search():
    term = request.args.get("q", "").strip()
    assignment = request.args.get("assignment", "all")
    if assignment not in {"all", "assigned", "unassigned"}:
        assignment = "all"
    if not current_user().is_admin:
        assignment = "assigned"
    activity, branches = activity_groups(assigned_only=not current_user().is_admin)
    branch = request.args.get("branch", "")
    page = max(1, request.args.get("page", 1, type=int))
    per_page = 50
    query = DSF.query.join(ImportSession).outerjoin(User, DSF.assigned_to_id == User.id)
    if branch:
        query = query.filter(DSF.id.in_([i for i, a in activity.items() if a["key"] == branch]))
    if assignment == "assigned":
        query = query.filter(DSF.assigned_to_id.is_not(None))
    elif assignment == "unassigned":
        query = query.filter(DSF.assigned_to_id.is_(None))
    rows = query.with_entities(
        DSF.id, DSF.niu, DSF.numero_dsf, DSF.raison_sociale, DSF.sigle,
        ImportSession.filename, User.username, User.full_name,
    ).order_by(DSF.raison_sociale, DSF.id).all()
    ids = rank_matching_ids(
        [
            (
                row.id, row.niu, row.numero_dsf, row.raison_sociale, row.sigle,
                " ".join(filter(None, (
                    activity.get(row.id, {}).get("label"), row.filename, row.username, row.full_name,
                ))),
            )
            for row in rows
        ],
        term,
    )
    page_ids = ids[(page - 1) * per_page : page * per_page]
    loaded = {
        dsf.id: dsf
        for dsf in DSF.query.options(joinedload(DSF.assignee), joinedload(DSF.import_session))
        .filter(DSF.id.in_(page_ids)).all()
    }
    pagination = Page([loaded[i] for i in page_ids if i in loaded], page, per_page, len(ids))
    return render_template(
        "admin/global_search.html", pagination=pagination,
        term=term, assignment=assignment, activity=activity, branches=branches, branch=branch,
    )


@admin_bp.post("/users/<int:user_id>/full-name")
@admin_required
def update_full_name(user_id):
    user = db.get_or_404(User, user_id)
    try:
        user.full_name = normalize_full_name(request.form.get("full_name"))
        db.session.commit()
        flash(f"Nom complet enregistré pour {user.username}.", "success")
    except ValueError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("admin.dashboard", _anchor="accountNames"))


@admin_bp.post("/import-sessions/<int:import_session_id>/assign-branch")
@admin_required
def assign_branch(import_session_id):
    db.get_or_404(ImportSession, import_session_id)
    assignee = db.session.get(User, request.form.get("user_id", type=int))
    if not assignee or assignee.role != "controller" or not assignee.is_active:
        abort(400)
    branch = request.form.get("branch", "")
    _, groups = activity_groups(import_session_id)
    selected = next((g for g in groups if g["key"] == branch), None)
    if selected is None:
        abort(400)
    administrator = current_user()
    try:
        ids = db.session.execute(update(DSF).where(
            DSF.import_session_id == import_session_id,
            DSF.id.in_(selected["ids"]), DSF.assigned_to_id.is_(None),
        ).values(assigned_to_id=assignee.id, assigned_by_id=administrator.id,
                 assigned_at=datetime.now(timezone.utc)).returning(DSF.id)).scalars().all()
        for dsf_id in ids:
            db.session.add(AuditLog(dsf_id=dsf_id, action="affectation par sous-branche",
                old_value="Non assignée", new_value=assignee.username,
                operator=administrator.username))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    flash(f"{len(ids)} DSF libre(s) affectée(s) à {assignee.display_label} : {selected['label']}.", "success")
    return redirect(url_for("admin.dashboard", session_id=import_session_id, branch=branch))
