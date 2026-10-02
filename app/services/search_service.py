"""Recherche de DSF : insensible à la casse, aux accents et aux séparateurs.

Chaque mot saisi doit se retrouver (ET logique) dans le NIU, le numéro de DSF,
la raison sociale, le sigle ou les champs complémentaires fournis. Les
résultats sont classés : identifiant exact, puis début de NIU/numéro/nom, puis
le reste. Le filtrage est fait en Python pour fonctionner à l'identique sur
SQLite et PostgreSQL (pas d'extension « unaccent » à installer sur le VPS).
"""
import re
import unicodedata


def normalize_text(value):
    text = unicodedata.normalize("NFKD", str(value if value is not None else ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().casefold()


def compact_text(value):
    """Forme sans séparateur : « M01-23 456 » et « m0123456 » deviennent identiques."""
    return re.sub(r"[^0-9a-z]", "", normalize_text(value))


def _rank(term_norm, term_compact, niu, numero, name, sigle):
    identifiers = [compact_text(niu), compact_text(numero)]
    if term_compact and term_compact in identifiers:
        return 0
    names = [normalize_text(name), normalize_text(sigle)]
    if term_compact and any(item.startswith(term_compact) for item in identifiers if item):
        return 1
    if term_norm and any(item.startswith(term_norm) for item in names if item):
        return 1
    return 2


def rank_matching_ids(rows, term):
    """``rows`` : (id, niu, numero_dsf, raison_sociale, sigle, texte_complémentaire).

    Retourne les identifiants correspondants, meilleurs résultats d'abord.
    L'ordre d'origine des lignes est conservé à rang égal.
    """
    term_norm = normalize_text(term)
    tokens = term_norm.split(" ") if term_norm else []
    if not tokens:
        return [row[0] for row in rows]
    term_compact = compact_text(term)
    ranked = []
    for position, (dsf_id, niu, numero, name, sigle, extra) in enumerate(rows):
        blob = " ".join(normalize_text(item) for item in (niu, numero, name, sigle, extra))
        ids_compact = compact_text(niu) + " " + compact_text(numero)
        matched = all(
            token in blob or (len(compact_text(token)) >= 2 and compact_text(token) in ids_compact)
            for token in tokens
        )
        if matched:
            ranked.append((_rank(term_norm, term_compact, niu, numero, name, sigle), position, dsf_id))
    ranked.sort()
    return [dsf_id for _, _, dsf_id in ranked]


class Page:
    """Pagination minimale compatible avec les gabarits (items, total, pages…)."""

    def __init__(self, items, page, per_page, total):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = max(1, -(-total // per_page))

    has_prev = property(lambda self: self.page > 1)
    has_next = property(lambda self: self.page < self.pages)
    prev_num = property(lambda self: self.page - 1)
    next_num = property(lambda self: self.page + 1)
