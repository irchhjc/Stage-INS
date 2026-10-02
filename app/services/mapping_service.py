import re
import unicodedata
from collections import Counter
from itertools import combinations

from app.config.fiche_layouts import FICHE_LAYOUTS
from app.config.fiche_mapping import FICHE_DEFINITIONS, MEASURE_LABELS


class MappingError(ValueError):
    pass


def normalize_label(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"\s+", " ", text).strip().casefold()
    # Matching only: source headers are stored and exported verbatim.
    return re.sub(r"\s*([()])\s*", r"\1", text)


def build_column_mapping(headers):
    normalized_headers = [normalize_label(header) for header in headers]
    starts = [(0, FICHE_DEFINITIONS[0])]
    cursor = 1
    missing = []

    for definition in FICHE_DEFINITIONS[1:]:
        marker = normalize_label(definition["start"])
        found = next(
            (index for index in range(cursor, len(headers)) if normalized_headers[index].startswith(marker)),
            None,
        )
        if found is None:
            missing.append(definition["name"])
            continue
        starts.append((found, definition))
        cursor = found + 1

    if missing:
        raise MappingError(
            "Structure DSF non reconnue. Repères de fiches absents : " + ", ".join(missing)
        )

    starts.sort(key=lambda item: item[0])
    mapping = []
    start_pointer = 0
    for index, header in enumerate(headers):
        while start_pointer + 1 < len(starts) and index >= starts[start_pointer + 1][0]:
            start_pointer += 1
        definition = starts[start_pointer][1]
        mapping.append(
            {
                "column_index": index + 1,
                "variable_name": "" if header is None else str(header),
                "fiche_code": definition["code"],
                "fiche_name": definition["name"],
            }
        )
    return mapping


def _source_column_index(value, fallback):
    column = getattr(value, "column", None)
    return getattr(column, "column_index", fallback)


def _is_total_label(poste):
    label = normalize_label(poste)
    return label.startswith(("total", "sous-total", "=")) or bool(
        re.match(r"^x[a-z] ", label)
    )


def _column_labels(measures):
    """Libellés d'affichage ; une mesure répétée est numérotée (1), (2)…"""
    labels = [MEASURE_LABELS.get(measure, measure or "Valeur") for measure in measures]
    totals = Counter(labels)
    seen = Counter()
    result = []
    for label in labels:
        seen[label] += 1
        result.append(f"{label} ({seen[label]})" if totals[label] > 1 else label)
    return result


def _row_entry(poste, cells, fallback_order):
    return {
        "poste": poste,
        "cells": cells,
        "source_order": cells[0]["source_order"] if cells else fallback_order,
        "is_question": poste.rstrip().endswith("?"),
        "is_total": _is_total_label(poste),
    }


def _cell_entry(value, fallback):
    return {
        "source_order": _source_column_index(value, fallback),
        "source_variable": value.variable_name,
        "value": value,
    }


def _layout_size(layout, skipped):
    return sum(
        len(table["columns"])
        * sum(1 for row_index, row in enumerate(table["rows"]) if (table_index, row_index) not in skipped)
        for table_index, table in enumerate(layout)
    )


def _matching_skipped_rows(layout, expected):
    """Cherche quelles lignes optionnelles retirer pour obtenir ``expected`` cellules."""
    optional = [
        (table_index, row_index)
        for table_index, table in enumerate(layout)
        for row_index, row in enumerate(table["rows"])
        if row.get("optional")
    ]
    for count in range(len(optional) + 1):
        for skipped in combinations(optional, count):
            if _layout_size(layout, set(skipped)) == expected:
                return set(skipped)
    return None


def _tables_from_layout(layout, values):
    skipped = _matching_skipped_rows(layout, len(values))
    if skipped is None:
        return None
    position = 0
    tables = []
    for table_index, table in enumerate(layout):
        rows = []
        for row_index, row in enumerate(table["rows"]):
            if (table_index, row_index) in skipped:
                continue
            cells = []
            for _ in table["columns"]:
                position += 1
                cells.append(_cell_entry(values[position - 1], position))
            rows.append(_row_entry(row["label"], cells, position))
        tables.append(
            {
                "title": table.get("title"),
                "columns": _column_labels(table["columns"]),
                "is_question": bool(table.get("question")),
                "rows": rows,
            }
        )
    return tables


def _tables_from_source(values):
    """Repli : une ligne par variable, dans l'ordre exact du fichier source."""
    rows = [
        _row_entry(str(value.variable_name or ""), [_cell_entry(value, position)], position)
        for position, value in enumerate(values, start=1)
    ]
    return [{"title": None, "columns": ["Valeur"], "is_question": False, "rows": rows}]


def build_accounting_sections(values, fiche_code=None):
    """Construit les tableaux d'une fiche selon le modèle « fiche en tableau ».

    ``FICHE_LAYOUTS`` décrit, fiche par fiche, les tableaux attendus (postes en
    lignes, mesures en colonnes). Les variables, triées par colonne source, sont
    rattachées dans l'ordre : le résultat reste donc exactement dans l'ordre du
    fichier importé et aucune variable n'est perdue. Si le nombre de variables
    ne correspond à aucune version connue du modèle (fichier source modifié), la
    fiche est affichée en liste simple plutôt que mal alignée.
    """
    values = list(values)
    if not values:
        return []
    tables = None
    layout_name = "source"
    if fiche_code in FICHE_LAYOUTS:
        tables = _tables_from_layout(FICHE_LAYOUTS[fiche_code], values)
        layout_name = "model"
    if tables is None:
        tables = _tables_from_source(values)
        layout_name = "source"
    return [
        {
            "number": 1,
            "title": "Tableaux de la fiche",
            "layout": layout_name,
            "tables": tables,
            "variable_count": len(values),
        }
    ]
