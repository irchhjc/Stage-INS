from collections import defaultdict

from sqlalchemy.orm import joinedload

from app.config.validation_rules import BALANCE_RULE, NET_RULE_SUFFIXES
from app.models import DSFValue, ImportColumn
from app.services.value_codec import deserialize_value
from app.services.mapping_service import build_accounting_sections, normalize_label


def _numeric(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(" ", "").replace("\u00a0", "").replace(",", "."))
        except ValueError:
            return None
    return None


def _values_for_dsf(dsf_id):
    return (
        DSFValue.query.options(joinedload(DSFValue.column)).join(ImportColumn)
        .filter(DSFValue.dsf_id == dsf_id)
        .order_by(ImportColumn.column_index)
        .all()
    )


NOTE_3D_TOLERANCE = 0.5
# Lignes de la note 3D : (sous-total, lignes qui le composent) ; le total général somme les sous-totaux.
NOTE_3D_SUBTOTALS = {4: range(0, 4), 10: range(5, 10), 13: range(11, 13)}
NOTE_3D_TOTAL_ROW = 14
NOTE_3D_COLUMN_NAMES = ["brut", "amortissements pratiqués", "valeur comptable nette", "prix de cession", "plus ou moins-value"]


def _numeric_cell(cell):
    return _numeric(deserialize_value(cell["value"].current_value))


def _tables(by_fiche, code):
    sections = build_accounting_sections(by_fiche.get(code, []), code)
    if not sections or sections[0]["layout"] != "model":
        return None
    return sections[0]["tables"]


def _issue(code, fiche_codes, variables, observed, expected, message):
    return {
        "code": code,
        "level": "warning",
        "fiche_codes": fiche_codes,
        "variables": variables,
        "observed": observed,
        "expected": expected,
        "difference": observed - expected,
        "message": message,
    }


def _find_row(tables, prefix):
    key = normalize_label(prefix)
    for table in tables:
        for row in table["rows"]:
            if normalize_label(row["poste"]).startswith(key):
                return row
    return None


def note_3d_issues(by_fiche):
    """Contrôles de la note 3D (plus-values et moins-values de cession). Ne modifie rien."""
    tables = _tables(by_fiche, "NOTE_AMORT")
    if not tables or len(tables) < 2 or len(tables[1]["rows"]) != 15:
        return []
    rows = tables[1]["rows"]
    grid = [[_numeric_cell(cell) for cell in row["cells"]] for row in rows]
    names = [[cell["source_variable"] for cell in row["cells"]] for row in rows]
    issues = []

    def compare(code, row_index, column_index, expected, message, extra=()):
        observed = grid[row_index][column_index]
        if observed is None or expected is None:
            return
        if abs(observed - expected) > NOTE_3D_TOLERANCE:
            issues.append(_issue(code, ["NOTE_AMORT"], [names[row_index][column_index], *extra], observed, expected, message))

    for index, row in enumerate(rows):
        brut, amort, net, prix, plus = grid[index]
        if None not in (brut, amort):
            compare("NOTE_3D_NET", index, 2, brut - amort,
                    f"Note 3D, {row['poste']} : la valeur comptable nette doit être égale au brut moins les amortissements pratiqués.")
        if None not in (prix, net):
            compare("NOTE_3D_PLUS_VALUE", index, 4, prix - net,
                    f"Note 3D, {row['poste']} : la plus ou moins-value doit être égale au prix de cession moins la valeur comptable nette.")

    for subtotal, parts in NOTE_3D_SUBTOTALS.items():
        for column in range(5):
            values = [grid[i][column] for i in parts]
            if None in values:
                continue
            compare("NOTE_3D_SOUS_TOTAL", subtotal, column, sum(values),
                    f"Note 3D, {rows[subtotal]['poste']} : le sous-total ({NOTE_3D_COLUMN_NAMES[column]}) doit être la somme de ses lignes.")
    for column in range(5):
        values = [grid[i][column] for i in NOTE_3D_SUBTOTALS]
        if None not in values:
            compare("NOTE_3D_TOTAL", NOTE_3D_TOTAL_ROW, column, sum(values),
                    f"Note 3D, total général ({NOTE_3D_COLUMN_NAMES[column]}) : doit être la somme des 3 sous-totaux.")

    total = NOTE_3D_TOTAL_ROW
    cross = []
    result_tables = _tables(by_fiche, "COMPTE_RESULTAT")
    produits = valeur_comptable = None
    if result_tables:
        for prefix, target in (("TN Produits des cessions", "produits"), ("RO Valeur comptable des cessions", "valeur")):
            row = _find_row(result_tables, prefix)
            if row:
                number = _numeric_cell(row["cells"][0])
                if target == "produits":
                    produits = (number, row["cells"][0]["source_variable"])
                else:
                    valeur_comptable = (number, row["cells"][0]["source_variable"])
        for column, found, label in (
            (3, produits, "le total des prix de cession doit être égal aux produits des cessions d'immobilisations (TN) du compte de résultat"),
            (2, valeur_comptable, "le total des valeurs comptables nettes doit être égal à la valeur comptable des cessions d'immobilisations (RO) du compte de résultat"),
        ):
            if found and found[0] is not None and grid[total][column] is not None:
                if abs(abs(grid[total][column]) - abs(found[0])) > NOTE_3D_TOLERANCE:
                    issues.append(_issue("NOTE_3D_COMPTE_RESULTAT", ["NOTE_AMORT", "COMPTE_RESULTAT"],
                                         [names[total][column], found[1]], grid[total][column], found[0], f"Note 3D : {label}."))
    for code, table_index, column, column_index, label in (
        ("NOTE_3A", 1, 4, 0, "le total brut doit correspondre aux cessions du total général de la note 3A"),
        ("NOTE_3A", 3, 2, 1, "le total des amortissements pratiqués doit correspondre aux diminutions d'amortissements du total général de la note 3C"),
    ):
        other = _tables(by_fiche, code)
        if not other or len(other) <= table_index or not other[table_index]["rows"]:
            continue
        cell = other[table_index]["rows"][-1]["cells"][column]
        number = _numeric_cell(cell)
        if number is not None and grid[total][column_index] is not None:
            if abs(abs(grid[total][column_index]) - abs(number)) > NOTE_3D_TOLERANCE:
                issues.append(_issue("NOTE_3D_NOTES", ["NOTE_AMORT", code], [names[total][column_index], cell["source_variable"]],
                                     grid[total][column_index], number, f"Note 3D : {label}."))

    answer = deserialize_value(tables[0]["rows"][0]["cells"][0]["value"].current_value)
    if isinstance(answer, str) and normalize_label(answer) in {"non", "n"}:
        for found in (produits, valeur_comptable):
            if found and found[0] not in (None, 0):
                issues.append(_issue("NOTE_3D_INCOMPLETE", ["NOTE_AMORT", "COMPTE_RESULTAT"], [found[1]], found[0], 0.0,
                                     "Note 3D déclarée non renseignée alors que le compte de résultat enregistre des cessions d'immobilisations."))
    return issues


def run_validation_rules(dsf_id):
    values = _values_for_dsf(dsf_id)
    issues = []
    by_fiche = defaultdict(list)
    for value in values:
        by_fiche[value.column.fiche_code].append(value)

    active = by_fiche["BILAN_ACTIF"]
    by_name = defaultdict(list)
    for value in active:
        by_name[normalize_label(value.variable_name)].append(value)

    suffixes = {key: normalize_label(value) if isinstance(value, str) else value for key, value in NET_RULE_SUFFIXES.items()}
    for gross_value in active:
        name = normalize_label(gross_value.variable_name)
        if not name.endswith(suffixes["brut"]):
            continue
        base = name[: -len(suffixes["brut"])]
        depreciation_items = by_name.get(base + suffixes["depreciation"], [])
        net_items = by_name.get(base + suffixes["net"], [])
        if len(by_name[name]) != 1 or len(depreciation_items) != 1 or len(net_items) != 1:
            continue
        gross = _numeric(deserialize_value(gross_value.current_value))
        depreciation = _numeric(deserialize_value(depreciation_items[0].current_value))
        observed = _numeric(deserialize_value(net_items[0].current_value))
        if gross is None or depreciation is None or observed is None:
            continue
        expected = gross - depreciation
        difference = observed - expected
        if abs(difference) > suffixes["tolerance"]:
            issues.append(
                {
                    "code": "NET_BRUT_AMORT",
                    "level": "warning",
                    "fiche_codes": ["BILAN_ACTIF"],
                    "variables": [gross_value.variable_name, depreciation_items[0].variable_name, net_items[0].variable_name],
                    "observed": observed,
                    "expected": expected,
                    "difference": difference,
                    "message": f"{base} : NET N ne correspond pas à BRUT - AMORT./DÉPRÉC.",
                }
            )

    actif = next((value for value in active if normalize_label(value.variable_name) == normalize_label(BALANCE_RULE["actif"])), None)
    passif = next(
        (value for value in by_fiche["BILAN_PASSIF"] if normalize_label(value.variable_name) == normalize_label(BALANCE_RULE["passif"])),
        None,
    )
    if actif and passif:
        actif_number = _numeric(deserialize_value(actif.current_value))
        passif_number = _numeric(deserialize_value(passif.current_value))
        if actif_number is not None and passif_number is not None:
            difference = actif_number - passif_number
            if abs(difference) > BALANCE_RULE["tolerance"]:
                issues.append(
                    {
                        "code": BALANCE_RULE["code"],
                        "level": "error",
                        "fiche_codes": ["BILAN_ACTIF", "BILAN_PASSIF"],
                        "variables": [actif.variable_name, passif.variable_name],
                        "observed": actif_number,
                        "expected": passif_number,
                        "difference": difference,
                        "message": "Le total général de l'actif diffère du total général du passif.",
                    }
                )

    issues.extend(note_3d_issues(by_fiche))

    return issues
