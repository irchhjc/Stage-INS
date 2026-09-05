import re
from functools import wraps

from flask import abort, g, redirect, request, session, url_for

from app.extensions import db
from app.models import DSF, User


USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,50}$")
MIN_PASSWORD_LENGTH = 10


def validate_new_user(username, password):
    username = (username or "").strip()
    if username != username.lower():
        raise ValueError("Le nom d'utilisateur doit être entièrement en minuscules.")
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError(
            "Le nom d'utilisateur doit contenir 3 à 50 caractères : lettres minuscules, chiffres, point, tiret ou soulignement."
        )
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise ValueError("Le mot de passe doit contenir au moins 10 caractères.")
    return username


def create_user(username, password, role="controller"):
    username = validate_new_user(username, password)
    if role not in {"admin", "controller"}:
        raise ValueError("Rôle utilisateur invalide.")
    if User.query.filter_by(username=username).first():
        raise ValueError("Ce nom d'utilisateur existe déjà.")
    user = User(username=username, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def current_user():
    return getattr(g, "current_user", None)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        if not user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def can_access_dsf(dsf, user=None):
    user = user or current_user()
    return bool(user and (user.is_admin or dsf.assigned_to_id == user.id))


def accessible_dsf_or_404(dsf_id):
    dsf = db.get_or_404(DSF, dsf_id)
    if not can_access_dsf(dsf):
        abort(403)
    return dsf

