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

    # Quelques en-têtes du schéma officiel contiennent un suffixe technique
    # supplémentaire, par exemple ``(NET_N) (N)`` ou
    # ``(BRUT) (IMMO_INC_BRUT)``. Le premier suffixe décrit la vraie colonne
    # comptable ; le second ne doit pas créer une nouvelle ligne ou mesure.
    prior_match = re.match(r"^(.*)\(([^()]*)\)\s*$", poste)
    core_measures = {"BRUT", "AMORT/DEPREC", "NET_N", "NET_N-1", "NET_N_1"}
    if prior_match and prior_match.group(2).strip() in core_measures:
        poste = prior_match.group(1).strip()
        measure = prior_match.group(2).strip()
    return poste or text, MEASURE_LABELS.get(measure, measure or "Valeur")


def _section_values(section):
    for row in section["rows"]:
        for slot in section["slots"]:
            value = row["cells"].get(slot["key"])
            if value is not None:
                yield value


def _complete_note_27b_table(sections):
    """Regroupe la note 27B en une seule table à trois colonnes de valeurs.

    La source alterne quatre blocs de données et plusieurs lignes TOTAL dont
    les signatures diffèrent. Leur ordre est conservé, mais chaque bloc est
    transformé en lignes explicites afin d'éviter neuf sous-tableaux.
    """
    expected_slot_counts = [1, 3, 3, 3, 3, 3, 3, 3, 9]
    if len(sections) != len(expected_slot_counts) or [
        len(section["slots"]) for section in sections
    ] != expected_slot_counts:
        return sections

    slots = [
        {"key": "Hommes#1", "label": "Hommes"},
        {"key": "Femmes#1", "label": "Femmes"},
        {"key": "Total#1", "label": "Total"},
    ]
    rows = []

    def append_row(poste, values):
        if len(values) != 3:
            return
        rows.append(
            {
                "poste": poste,
                "cells": {slot["key"]: value for slot, value in zip(slots, values)},
            }
        )

    def append_group(section, group_label):
        for row in section["rows"]:
            values = [row["cells"].get(slot["key"]) for slot in section["slots"]]
            append_row(f"{group_label} - {row['poste']}", values)

    def append_total(section, total_label):
        values = list(_section_values(section))
        append_row(total_label, values)

    append_group(sections[1], "Effectifs - groupe 1")
    append_total(sections[2], "Total - effectifs (groupe 1)")
    append_group(sections[3], "Masse salariale - groupe 1")
    append_total(sections[4], "Total - masse salariale (groupe 1)")
    append_group(sections[5], "Effectifs - groupe 2")
    append_total(sections[6], "Total - effectifs (groupe 2)")
    append_group(sections[7], "Masse salariale - groupe 2")

    final_values = list(_section_values(sections[8]))
    append_row("Total - masse salariale (groupe 2)", final_values[0:3])
    append_row("Total - effectifs (1+2)", final_values[3:6])
    append_row("Total - masse salariale (1+2)", final_values[6:9])

    complete_section = {
        "number": 2,
        "title": "Tableau complet - effectifs et masse salariale",
        "slots": slots,
        "rows": rows,
        "column_count": 3,
        "is_question_block": False,
        "is_compact_table": False,
    }
    return [sections[0], complete_section]


def build_accounting_sections(values, max_rows=30, fiche_code=None):
    groups = []
    current = None
    for value in values:
        poste, measure = split_variable_name(value.variable_name)
        if current is None or current["poste"] != poste:
            current = {"poste": poste, "raw_cells": []}
            groups.append(current)
        current["raw_cells"].append((measure, value))

    prepared_groups = []
    for group in groups:
        counts = Counter()
        cells = {}
        slots = []
        for measure, value in group["raw_cells"]:
            counts[measure] += 1
            slot = f"{measure}#{counts[measure]}"
            slots.append(
                {
                    "key": slot,
                    "label": measure if counts[measure] == 1 else f"{measure} ({counts[measure]})",
                }
            )
            cells[slot] = value
        prepared_groups.append(
            {
                "poste": group["poste"],
                "cells": cells,
                "slots": slots,
                "signature": tuple(slot["key"] for slot in slots),
            }
        )

    # Une table ne contient que des lignes ayant exactement la même structure.
    # Cela évite qu'une question isolée ou qu'un total particulier ajoute des
    # colonnes vides à toutes les autres lignes de la fiche.
    sections = []
    for group in prepared_groups:
        current = sections[-1] if sections else None
        if (
            current is None
            or current["signature"] != group["signature"]
            or len(current["rows"]) >= max_rows
        ):
            current = {
                "number": len(sections) + 1,
                "signature": group["signature"],
                "slots": group["slots"],
                "rows": [],
            }
            sections.append(current)
        current["rows"].append({"poste": group["poste"], "cells": group["cells"]})

    for section in sections:
        labels = [slot["label"] for slot in section["slots"]]
        section["is_question_block"] = (
            labels == ["Valeur"]
            and all(row["poste"].rstrip().endswith("?") for row in section["rows"])
        )
        # Les changements de structure du fichier source créent parfois un
        # tableau autonome d'une à trois lignes (TOTAL, SOUS-TOTAL, trace…).
        # Il conserve ses colonnes exactes, mais n'a pas besoin de la hauteur
        # minimale réservée aux grands tableaux de saisie.
        section["is_compact_table"] = (
            not section["is_question_block"] and len(section["rows"]) <= 3
        )
        if section["is_question_block"]:
            section["title"] = (
                "Question de contrôle"
                if len(section["rows"]) == 1
                else "Questions de contrôle"
            )
        elif len(sections) == 1:
            section["title"] = "Tableau comptable"
        elif labels == ["Valeur"]:
            section["title"] = "Informations générales"
        else:
            section["title"] = f"Tableau {section['number']} - {' / '.join(labels)}"
        section["column_count"] = len(section["slots"])
        section.pop("signature", None)
    if fiche_code == "NOTE_27B":
        sections = _complete_note_27b_table(sections)
    return sections

