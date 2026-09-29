import re
from functools import wraps

from flask import abort, g, redirect, request, session, url_for
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import DSF, User


USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,50}$")
MIN_PASSWORD_LENGTH = 10


def normalize_username(username):
    username = (username or "").strip()
    if username != username.lower():
        raise ValueError("Le nom d'utilisateur doit être entièrement en minuscules.")
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError(
            "Le nom d'utilisateur doit contenir 3 à 50 caractères : lettres minuscules, chiffres, point, tiret ou soulignement."
        )
    return username


def validate_password(password):
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise ValueError("Le mot de passe doit contenir au moins 10 caractères.")


def validate_new_user(username, password):
    username = normalize_username(username)
    validate_password(password)
    return username


def normalize_full_name(value):
    name = " ".join((value or "").split())
    if len(name) > 150:
        raise ValueError("Le nom complet ne doit pas dépasser 150 caractères.")
    return name or None


def create_user(username, password, role="controller", full_name=None):
    username = validate_new_user(username, password)
    if role not in {"admin", "controller"}:
        raise ValueError("Rôle utilisateur invalide.")
    if User.query.filter_by(username=username).first():
        raise ValueError("Ce nom d'utilisateur existe déjà.")
    user = User(username=username, role=role, full_name=normalize_full_name(full_name))
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def update_controller_account(user, username, full_name=None, new_password=None):
    if user.role != "controller":
        raise ValueError("Seuls les comptes contrôleurs peuvent être modifiés ici.")

    normalized_username = normalize_username(username)
    normalized_full_name = normalize_full_name(full_name)
    password = new_password or ""
    if password:
        validate_password(password)
    duplicate = User.query.filter(
        User.username == normalized_username,
        User.id != user.id,
    ).first()
    if duplicate:
        raise ValueError("Ce nom d'utilisateur existe déjà.")

    user.username = normalized_username
    user.full_name = normalized_full_name
    if password:
        user.set_password(password)
    try:
        db.session.commit()
    except IntegrityError as exc:
        db.session.rollback()
        raise ValueError("Ce nom d'utilisateur existe déjà.") from exc
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

