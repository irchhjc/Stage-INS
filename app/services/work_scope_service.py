"""Périmètre de travail des contrôleurs : une année donnée ou toutes les années.

Un contrôleur dont ``work_year`` est renseignée ne voit, ne prend en charge et ne
se voit affecter que les DSF de cette année. Les DSF qui lui sont déjà affectées
restent toujours accessibles (« Mes DSF »), pour ne jamais bloquer un travail en cours.
Les administrateurs ne sont jamais limités.
"""
import re
from collections import defaultdict

from sqlalchemy import func

from app.extensions import db
from app.models import DSF

_YEAR = re.compile(r"(?:19|20)\d{2}")


def year_key(value):
    """« 2023 », « 2023.0 » ou « Exercice 2023 » donnent tous « 2023 »."""
    text = str(value or "").strip()
    match = _YEAR.search(text)
    return match.group(0) if match else text


def year_stats():
    """Années présentes dans les DSF importées, de la plus récente à la plus ancienne."""
    stats = defaultdict(lambda: {"total": 0, "free": 0, "completed": 0})
    rows = (
        db.session.query(DSF.annee, DSF.assigned_to_id.is_(None), DSF.status, func.count(DSF.id))
        .group_by(DSF.annee, DSF.assigned_to_id.is_(None), DSF.status)
        .all()
    )
    for annee, is_free, status, count in rows:
        key = year_key(annee)
        if not key:
            continue
        stats[key]["total"] += count
        if is_free:
            stats[key]["free"] += count
        if status == "completed":
            stats[key]["completed"] += count
    return [{"year": year, **values} for year, values in sorted(stats.items(), reverse=True)]


def available_years():
    return [item["year"] for item in year_stats()]


def raw_values_for_year(year):
    """Valeurs brutes de DSF.annee qui correspondent à l'année (pour un filtre SQL)."""
    return [
        raw
        for (raw,) in db.session.query(DSF.annee).distinct().all()
        if raw is not None and year_key(raw) == year
    ]


def scope_values(user):
    """None = aucune restriction ; sinon la liste des valeurs brutes d'année autorisées."""
    if user is None or user.is_admin or not user.work_year:
        return None
    return raw_values_for_year(user.work_year)


def dsf_in_scope(dsf, user):
    if user is None or user.is_admin or not user.work_year:
        return True
    return year_key(dsf.annee) == user.work_year


def scope_label(user):
    return f"année {user.work_year}" if user is not None and user.work_year else "toutes les années"


def normalize_requested_year(raw_value):
    """'' ou 'all' -> None (toutes les années) ; sinon l'année, qui doit exister. Sinon ValueError."""
    value = str(raw_value or "").strip()
    if value in {"", "all"}:
        return None
    if value not in available_years():
        raise ValueError(f"Aucune DSF de l'année « {value} » n'a été importée.")
    return value
