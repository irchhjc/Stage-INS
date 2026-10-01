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


def _ordered_raw_cells(raw_cells):
    preferred_order = {
        "N": 0,
        "N-1": 1,
        "À 1 an au plus": 2,
        "Plus de 1 an à 2 ans": 3,
        "Plus de 2 ans": 4,
    }
    measures = [measure for measure, _value in raw_cells]
    if len(measures) == len(set(measures)) and all(
        measure in preferred_order for measure in measures
    ):
        return sorted(raw_cells, key=lambda item: preferred_order[item[0]])
    return raw_cells


def _merge_disjoint_poste_fragments(groups):
    mergeable_measure_sets = {
        frozenset(("N", "N-1")),
        frozenset(("À 1 an au plus", "Plus de 1 an à 2 ans", "Plus de 2 ans")),
        frozenset(
            (
                "N",
                "N-1",
                "À 1 an au plus",
                "Plus de 1 an à 2 ans",
                "Plus de 2 ans",
            )
        ),
    }
    merged_groups = []
    positions = {}
    for group in groups:
        existing_index = positions.get(group["poste_key"])
        if existing_index is not None:
            existing = merged_groups[existing_index]
            existing_measures = {measure for measure, _value in existing["raw_cells"]}
            incoming_measures = {measure for measure, _value in group["raw_cells"]}
            combined_measures = existing_measures | incoming_measures
            if (
                existing_measures.isdisjoint(incoming_measures)
                and frozenset(combined_measures) in mergeable_measure_sets
            ):
                existing["raw_cells"] = _ordered_raw_cells(
                    [*existing["raw_cells"], *group["raw_cells"]]
                )
                continue
        positions[group["poste_key"]] = len(merged_groups)
        group["raw_cells"] = _ordered_raw_cells(group["raw_cells"])
        merged_groups.append(group)
    return merged_groups


def _prepare_group(group):
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
    return {
        "poste": group["poste"],
        "cells": cells,
        "slots": slots,
        "signature": tuple(slot["key"] for slot in slots),
    }


def _stitch_total_fragments(groups):
    prepared = []
    cursor = 0
    while cursor < len(groups):
        group = groups[cursor]
        candidate = _prepare_group(group)
        is_total = "total" in normalize_label(group["poste"])
        expected_signature = prepared[-1]["signature"] if prepared else ()

        if is_total and expected_signature and len(candidate["signature"]) < len(expected_signature):
            combined_raw_cells = list(group["raw_cells"])
            lookahead = cursor + 1
            while lookahead < len(groups):
                combined_raw_cells.extend(groups[lookahead]["raw_cells"])
                combined = _prepare_group(
                    {"poste": group["poste"], "raw_cells": combined_raw_cells}
                )
                if combined["signature"] == expected_signature:
                    candidate = combined
                    cursor = lookahead
                    break
                if len(combined["signature"]) >= len(expected_signature):
                    break
                lookahead += 1

        prepared.append(candidate)
        cursor += 1
    return prepared


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


def _section_title(labels, rows):
    signatures = {
        ("BRUT", "AMORT./DÉPRÉC.", "NET N", "NET N-1"):
            "Valeurs brutes, amortissements et valeurs nettes",
        ("N", "N-1"): "Comparaison des exercices N et N-1",
        ("N",): "Exercice N",
        ("N-1",): "Exercice N-1",
        (
            "Brut à l'ouverture",
            "Acquisitions / apports / créations",
            "Virements entre postes (+)",
            "Réévaluations",
            "Cessions / scissions",
            "Virements entre postes (-)",
            "Brut à la clôture",
        ): "Mouvements des immobilisations brutes",
        (
            "Amortissements cumulés à l'ouverture",
            "Dotations",
            "Diminutions",
            "Amortissements cumulés à la clôture",
        ): "Mouvements des amortissements et dépréciations",
        (
            "Montant brut",
            "Amortissements pratiqués",
            "Valeur comptable",
            "Prix de cession",
            "Plus ou moins-value",
        ): "Cessions d'immobilisations",
        ("À 1 an au plus", "Plus de 1 an à 2 ans", "Plus de 2 ans"):
            "Échéancier par maturité",
        (
            "N",
            "N-1",
            "À 1 an au plus",
            "Plus de 1 an à 2 ans",
            "Plus de 2 ans",
        ): "Valeurs des exercices et échéancier par maturité",
        ("N", "N-1", "N (2)", "N-1 (2)"):
            "Hypothèses comparées N et N-1",
        ("Hommes", "Femmes", "Total"): "Répartition par sexe",
    }
    signature = tuple(labels)
    if signature in signatures:
        return signatures[signature]
    if labels == ["Valeur"]:
        return "Informations générales"
    if rows and all("TOTAL" in row["poste"].upper() for row in rows):
        return f"Totaux - {' / '.join(labels)}"
    return f"Colonnes - {' / '.join(labels)}"


def build_accounting_sections(values, max_rows=None, fiche_code=None):
    groups = []
    current = None
    for value in values:
        poste, measure = split_variable_name(value.variable_name)
        poste_key = re.sub(r"\s*([:;])\s*", r"\1", normalize_label(poste))
        if current is None or current["poste_key"] != poste_key:
            current = {"poste": poste, "poste_key": poste_key, "raw_cells": []}
            groups.append(current)
        current["raw_cells"].append((measure, value))

    if fiche_code != "NOTE_27B":
        groups = _merge_disjoint_poste_fragments(groups)
    prepared_groups = _stitch_total_fragments(groups)

    # Une table ne contient que des lignes ayant exactement la même structure.
    # Cela évite qu'une question isolée ou qu'un total particulier ajoute des
    # colonnes vides à toutes les autres lignes de la fiche.
    sections = []
    data_sections = {}
    for group in prepared_groups:
        is_question = (
            group["signature"] == ("Valeur#1",)
            and group["poste"].rstrip().endswith("?")
        )
        current = None
        if fiche_code == "NOTE_27B" and sections:
            previous = sections[-1]
            if previous["signature"] == group["signature"]:
                current = previous
        elif not is_question:
            current = data_sections.get(group["signature"])
            if current is not None and max_rows is not None and len(current["rows"]) >= max_rows:
                current = None
        elif is_question and sections:
            previous = sections[-1]
            if previous["signature"] == group["signature"] and previous.get("questions_only"):
                current = previous

        if current is None:
            current = {
                "number": len(sections) + 1,
                "signature": group["signature"],
                "slots": group["slots"],
                "rows": [],
                "questions_only": is_question,
            }
            sections.append(current)
            if fiche_code != "NOTE_27B" and not is_question:
                data_sections[group["signature"]] = current
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
        else:
            section["title"] = _section_title(labels, section["rows"])
        section["column_count"] = len(section["slots"])
        section.pop("signature", None)
        section.pop("questions_only", None)
    if fiche_code == "NOTE_27B":
        sections = _complete_note_27b_table(sections)
    return sections

