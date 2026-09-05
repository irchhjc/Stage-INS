from pathlib import Path
from threading import Lock

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import OperationalError

from app.extensions import db
from app.services.excel_service import (
    ExcelImportError,
    copy_local_workbook,
    import_workbook,
    save_uploaded_file,
)
from app.services.auth_service import admin_required


import_bp = Blueprint("import_excel", __name__, url_prefix="/import")
import_lock = Lock()


def _is_xlsx(filename):
    return bool(filename) and Path(filename).suffix.casefold() == ".xlsx"


def _import_safely(filepath, filename):
    if not import_lock.acquire(blocking=False):
        raise RuntimeError("Un autre import est déjà en cours. Attendez sa fin avant de recommencer.")
    try:
        return import_workbook(filepath, filename)
    finally:
        import_lock.release()


def _handle_import_failure(exc, context):
    db.session.rollback()
    current_app.logger.exception(context)
    if isinstance(exc, OperationalError) and "database is locked" in str(exc).lower():
        flash(
            "La base est momentanément occupée. Attendez quelques secondes puis relancez l'import. "
            "Si l'erreur persiste sur Render, vérifiez que Gunicorn utilise un seul worker et un seul thread.",
            "warning",
        )
    else:
        flash(f"Échec inattendu de l'import : {exc}", "danger")


def _cleanup_failed_copy(filepath):
    if not filepath:
        return
    path = Path(filepath)
    try:
        path.unlink(missing_ok=True)
        path.parent.rmdir()
    except OSError:
        current_app.logger.warning("Impossible de supprimer la copie d'import échouée : %s", path)


@import_bp.route("/", methods=["GET", "POST"])
@admin_required
def import_page():
    local_workbook = Path(current_app.root_path).parent / "dsf.xlsx"
    if request.method == "POST":
        upload = request.files.get("file")
        if not upload or not upload.filename:
            flash("Sélectionnez un fichier .xlsx.", "danger")
            return redirect(url_for("import_excel.import_page"))
        if not _is_xlsx(upload.filename):
            flash("Seuls les fichiers .xlsx sont acceptés.", "danger")
            return redirect(url_for("import_excel.import_page"))
        saved_path = None
        try:
            saved_path = save_uploaded_file(upload)
            import_session = _import_safely(saved_path, upload.filename)
            flash(
                f"Import terminé : {import_session.row_count} DSF et {import_session.column_count} colonnes.",
                "success",
            )
            return redirect(url_for("main.dashboard", session_id=import_session.id))
        except (ExcelImportError, ValueError) as exc:
            db.session.rollback()
            _cleanup_failed_copy(saved_path)
            flash(str(exc), "danger")
        except Exception as exc:
            _cleanup_failed_copy(saved_path)
            _handle_import_failure(exc, "Échec de l'import")
        return redirect(url_for("import_excel.import_page"))
    return render_template("import.html", local_workbook=local_workbook if local_workbook.exists() else None)


@import_bp.post("/local")
@admin_required
def import_local():
    local_workbook = Path(current_app.root_path).parent / "dsf.xlsx"
    if not local_workbook.exists():
        flash("Le fichier dsf.xlsx n'existe pas dans le dossier du projet.", "danger")
        return redirect(url_for("import_excel.import_page"))
    copied = None
    try:
        copied = copy_local_workbook(local_workbook)
        import_session = _import_safely(copied, local_workbook.name)
        flash(
            f"Import terminé : {import_session.row_count} DSF et {import_session.column_count} colonnes.",
            "success",
        )
        return redirect(url_for("main.dashboard", session_id=import_session.id))
    except Exception as exc:
        _cleanup_failed_copy(copied)
        _handle_import_failure(exc, "Échec de l'import local")
        return redirect(url_for("import_excel.import_page"))
