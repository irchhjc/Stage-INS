from collections import defaultdict

from sqlalchemy.orm import joinedload

from app.config.validation_rules import BALANCE_RULE, NET_RULE_SUFFIXES
from app.models import DSFValue, ImportColumn
from app.services.value_codec import deserialize_value
from app.services.mapping_service import normalize_label


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

    return issues
