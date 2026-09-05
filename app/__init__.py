import secrets
from pathlib import Path

from flask import Flask, abort, flash, g, jsonify, redirect, request, send_from_directory, session, url_for

from app.extensions import db
from config import Config


def create_app(config_object=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["EXPORT_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)

    from app.routes.dsf import dsf_bp
    from app.routes.export_excel import export_bp
    from app.routes.import_excel import import_bp
    from app.routes.main import main_bp
    from app.routes.admin import admin_bp
    from app.routes.auth import auth_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(import_bp)
    app.register_blueprint(dsf_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(admin_bp)

    @app.before_request
    def load_and_require_user():
        from app.models import User

        user_id = session.get("user_id")
        g.current_user = db.session.get(User, user_id) if user_id else None
        if g.current_user is not None and not g.current_user.is_active:
            session.clear()
            g.current_user = None
        public_endpoints = {"auth.login", "static", "brand_asset"}
        if request.endpoint in public_endpoints:
            return None
        if g.current_user is None:
            if request.path.startswith("/dsf/api/"):
                return jsonify(ok=False, error="Authentification requise."), 401
            if request.method != "GET":
                flash("Votre session n'est plus active. Reconnectez-vous avant de poursuivre.", "warning")
            return_path = "/admin/" if request.path.startswith("/admin/") else "/"
            return redirect(url_for("auth.login", next=return_path))

    @app.before_request
    def protect_state_changes():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(24)
        if app.testing or request.method not in {"POST", "PATCH", "PUT", "DELETE"}:
            return None
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        if not secrets.compare_digest(supplied or "", session["csrf_token"]):
            return {"ok": False, "error": "Jeton de sécurité invalide. Rechargez la page."}, 400

    @app.context_processor
    def inject_globals():
        logo_folder = Path(app.root_path) / "logos"
        supported_extensions = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}
        logo_labels = {
            "ins_congo": "Institut National de la Statistique du Congo",
            "partenaire1": "Banque mondiale",
            "partenaire2": "HISWACA",
        }
        logo_files = sorted(
            (
                path
                for path in logo_folder.iterdir()
                if path.is_file() and path.suffix.casefold() in supported_extensions
            ),
            key=lambda path: ("ins" not in path.stem.casefold(), path.name.casefold()),
        ) if logo_folder.exists() else []
        logos = [
            {
                "filename": path.name,
                "url": url_for("brand_asset", filename=path.name),
                "alt": logo_labels.get(path.stem.casefold(), path.stem.replace("_", " ").title()),
                "is_primary": "ins" in path.stem.casefold(),
            }
            for path in logo_files
        ]
        return {
            "csrf_token": session.get("csrf_token", ""),
            "current_user": getattr(g, "current_user", None),
            "primary_logo": next((logo for logo in logos if logo["is_primary"]), None),
            "partner_logos": [logo for logo in logos if not logo["is_primary"]],
        }

    @app.get("/brand-assets/<path:filename>")
    def brand_asset(filename):
        logo_folder = Path(app.root_path) / "logos"
        if Path(filename).suffix.casefold() not in {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}:
            abort(404)
        return send_from_directory(logo_folder, filename, conditional=True, max_age=86400)

    with app.app_context():
        db.create_all()
        from app.services.database_service import ensure_initial_admin, upgrade_legacy_schema

        upgrade_legacy_schema()
        ensure_initial_admin(
            app.config["INITIAL_ADMIN_USERNAME"],
            app.config["INITIAL_ADMIN_PASSWORD"],
        )

    return app
