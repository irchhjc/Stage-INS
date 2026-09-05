import re
import unicodedata
from collections import Counter

from app.config.fiche_mapping import FICHE_DEFINITIONS, MEASURE_LABELS


class MappingError(ValueError):
    pass


def normalize_label(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip().casefold()


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


def build_accounting_sections(values, max_rows=30):
    groups = []
    current = None
    for value in values:
        poste, measure = split_variable_name(value.variable_name)
        if current is None or current["poste"] != poste:
            current = {"poste": poste, "raw_cells": []}
            groups.append(current)
        current["raw_cells"].append((measure, value))

    sections = []
    for section_number, start in enumerate(range(0, len(groups), max_rows), start=1):
        chunk = groups[start : start + max_rows]
        slot_order = []
        slot_labels = {}
        prepared_rows = []
        for group in chunk:
            counts = Counter()
            cells = {}
            for measure, value in group["raw_cells"]:
                counts[measure] += 1
                slot = f"{measure}#{counts[measure]}"
                if slot not in slot_order:
                    slot_order.append(slot)
                    slot_labels[slot] = measure if counts[measure] == 1 else f"{measure} ({counts[measure]})"
                cells[slot] = value
            prepared_rows.append({"poste": group["poste"], "cells": cells})
        sections.append(
            {
                "number": section_number,
                "title": "Tableau comptable" if len(groups) <= max_rows else f"Section {section_number}",
                "slots": [{"key": slot, "label": slot_labels[slot]} for slot in slot_order],
                "rows": prepared_rows,
            }
        )
    return sections

