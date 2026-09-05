from flask import Blueprint, current_app, flash, redirect, request, send_file, url_for

from app.services.export_service import export_controlled_workbook
from app.services.auth_service import current_user


export_bp = Blueprint("export_excel", __name__, url_prefix="/export")


@export_bp.post("/<int:import_session_id>")
def export_workbook(import_session_id):
    try:
        user = current_user()
        path = export_controlled_workbook(
            import_session_id,
            assigned_user_id=None if user.is_admin else user.id,
            username=None if user.is_admin else user.username,
        )
        return send_file(path, as_attachment=True, download_name=path.name)
    except Exception as exc:
        current_app.logger.exception("Échec de l'export")
        flash(f"Export impossible : {exc}", "danger")
        return redirect(request.referrer or url_for("main.dashboard"))
