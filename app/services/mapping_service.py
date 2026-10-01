import re
import unicodedata
from collections import Counter

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


def split_variable_name(variable_name):
    text = str(variable_name or "").strip()
    match = re.match(r"^(.*)\(([^()]*)\)\s*$", text)
    if not match:
        return text, "Valeur"
    poste = match.group(1).strip()
    measure = match.group(2).strip()
    return poste or text, MEASURE_LABELS.get(measure, measure or "Valeur")


def _source_column_index(value, fallback):
    column = getattr(value, "column", None)
    return getattr(column, "column_index", fallback)


def build_accounting_sections(values, max_rows=None):
    """Construit un tableau unique en conservant l'ordre exact des variables.

    Chaque variable source devient une ligne. Ce format long permet de réunir
    dans une même fiche des familles comptables différentes sans créer de
    cellules artificiellement vides et sans confondre les en-têtes dupliqués.
    ``max_rows`` reste accepté pour compatibilité, mais ne découpe plus la fiche.
    """
    rows = []
    for fallback, value in enumerate(values, start=1):
        poste, measure = split_variable_name(value.variable_name)
        rows.append(
            {
                "source_order": _source_column_index(value, fallback),
                "poste": poste,
                "measure": measure,
                "source_variable": value.variable_name,
                "value": value,
                "is_question": poste.rstrip().endswith("?"),
            }
        )

    cursor = 0
    while cursor < len(rows):
        end = cursor + 1
        poste_key = normalize_label(rows[cursor]["poste"])
        while end < len(rows) and normalize_label(rows[end]["poste"]) == poste_key:
            end += 1

        group = rows[cursor:end]
        measure_totals = Counter(row["measure"] for row in group)
        measure_occurrences = Counter()
        for offset, row in enumerate(group):
            measure_occurrences[row["measure"]] += 1
            row["group_start"] = offset == 0
            row["group_size"] = len(group)
            if measure_totals[row["measure"]] > 1:
                row["measure"] = (
                    f"{row['measure']} ({measure_occurrences[row['measure']]})"
                )
        cursor = end

    return [
        {
            "number": 1,
            "title": "Tableau complet de la fiche",
            "rows": rows,
            "variable_count": len(rows),
        }
    ] if rows else []

