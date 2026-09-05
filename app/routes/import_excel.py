from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from app.services.excel_service import (
    ExcelImportError,
    copy_local_workbook,
    import_workbook,
    save_uploaded_file,
)
from app.services.auth_service import admin_required


import_bp = Blueprint("import_excel", __name__, url_prefix="/import")


def _is_xlsx(filename):
    return bool(filename) and Path(filename).suffix.casefold() == ".xlsx"


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
            import_session = import_workbook(saved_path, upload.filename)
            flash(
                f"Import terminé : {import_session.row_count} DSF et {import_session.column_count} colonnes.",
                "success",
            )
            return redirect(url_for("main.dashboard", session_id=import_session.id))
        except (ExcelImportError, ValueError) as exc:
            flash(str(exc), "danger")
        except Exception as exc:
            current_app.logger.exception("Échec de l'import")
            flash(f"Échec inattendu de l'import : {exc}", "danger")
        return redirect(url_for("import_excel.import_page"))
    return render_template("import.html", local_workbook=local_workbook if local_workbook.exists() else None)


@import_bp.post("/local")
@admin_required
def import_local():
    local_workbook = Path(current_app.root_path).parent / "dsf.xlsx"
    if not local_workbook.exists():
        flash("Le fichier dsf.xlsx n'existe pas dans le dossier du projet.", "danger")
        return redirect(url_for("import_excel.import_page"))
    try:
        copied = copy_local_workbook(local_workbook)
        import_session = import_workbook(copied, local_workbook.name)
        flash(
            f"Import terminé : {import_session.row_count} DSF et {import_session.column_count} colonnes.",
            "success",
        )
        return redirect(url_for("main.dashboard", session_id=import_session.id))
    except Exception as exc:
        current_app.logger.exception("Échec de l'import local")
        flash(str(exc), "danger")
        return redirect(url_for("import_excel.import_page"))
