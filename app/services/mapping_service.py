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


def _label_note_27b_sections(sections):
    """Donne aux blocs répétés de la note 27B leur contexte de lecture.

    Les en-têtes source distinguent EFFECTIF et MASSE_SALARIALE, tandis que
    les lignes TOTAL suivantes portent les marqueurs 1, 2 et 1+2. Les noms
    originaux restent attachés aux valeurs ; seuls les titres et en-têtes
    d'affichage sont rendus explicites.
    """
    occurrences = Counter()
    previous_group = None
    gender_labels = ["Hommes", "Femmes", "Total"]

    for section in sections:
        variable_names = [value.variable_name for value in _section_values(section)]
        if any("(EFFECTIF_" in name for name in variable_names):
            kind = "Effectifs"
            occurrences[kind] += 1
            previous_group = (kind, occurrences[kind])
            section["title"] = f"{kind} - groupe {occurrences[kind]}"
        elif any("(MASSE_SALARIALE_" in name for name in variable_names):
            kind = "Masse salariale"
            occurrences[kind] += 1
            previous_group = (kind, occurrences[kind])
            section["title"] = f"{kind} - groupe {occurrences[kind]}"
        elif variable_names and all(normalize_label(name).startswith("total(") for name in variable_names):
            if len(section["slots"]) == 3 and previous_group:
                kind, group_number = previous_group
                section["title"] = f"Total - {kind.lower()} (groupe {group_number})"
                for slot, label in zip(section["slots"], gender_labels):
                    slot["label"] = label
            elif len(section["slots"]) == 9:
                section["title"] = "Totaux - groupe 2 et ensemble (1+2)"
                labels = [
                    "Masse salariale 2 - Hommes",
                    "Masse salariale 2 - Femmes",
                    "Masse salariale 2 - Total",
                    "Effectifs 1+2 - Hommes",
                    "Effectifs 1+2 - Femmes",
                    "Effectifs 1+2 - Total",
                    "Masse salariale 1+2 - Hommes",
                    "Masse salariale 1+2 - Femmes",
                    "Masse salariale 1+2 - Total",
                ]
                for slot, label in zip(section["slots"], labels):
                    slot["label"] = label


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
        _label_note_27b_sections(sections)
    return sections

