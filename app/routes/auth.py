from datetime import datetime, timezone
from urllib.parse import urlsplit

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from app.extensions import db
from app.models import User


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def _safe_next_url(candidate):
    if not candidate:
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc or not candidate.startswith("/"):
        return None
    return candidate


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if getattr(g, "current_user", None):
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter_by(username=username, is_active=True).first()
        if user and user.check_password(password):
            session.clear()
            session["user_id"] = user.id
            user.last_login_at = datetime.now(timezone.utc)
            db.session.commit()
            flash(f"Bienvenue, {user.username}.", "success")
            return redirect(_safe_next_url(request.form.get("next")) or url_for("main.dashboard"))
        flash("Nom d'utilisateur ou mot de passe incorrect.", "danger")
    return render_template("login.html", next_url=_safe_next_url(request.args.get("next")) or "")


@auth_bp.post("/logout")
def logout():
    session.clear()
    flash("Vous êtes déconnecté.", "success")
    return redirect(url_for("auth.login"))
