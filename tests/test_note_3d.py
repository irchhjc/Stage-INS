from types import SimpleNamespace

from app.services.validation_service import note_3d_issues
from app.services.value_codec import serialize_value
from app.services.mapping_service import build_accounting_sections
from tests.test_fiche_tables import _values_by_fiche


def _by_fiche(overrides=None, answer="Oui", result=(0, 0)):
    """Valeurs de la note 3D cohérentes : une seule ligne AE renseignée, sous-total et total reportés."""
    by_fiche = {code: list(values) for code, values in _values_by_fiche().items()}
    for values in by_fiche.values():
        for value in values:
            value.current_value = serialize_value(None)
    notes = by_fiche["NOTE_AMORT"]
    notes[0].current_value = serialize_value(answer)
    cells = {}
    for position, value in enumerate(notes[1:]):
        cells[(position // 5, position % 5)] = value
    line = [1000, 400, 600, 900, 300]
    for column, number in enumerate(line):
        for row in (0, 4, 14):
            cells[(row, column)].current_value = serialize_value(number)
    for key in list(cells):
        if cells[key].current_value == serialize_value(None):
            cells[key].current_value = serialize_value(0)
    for (row, column), number in (overrides or {}).items():
        cells[(row, column)].current_value = serialize_value(number)
    _set_result(by_fiche, *result)
    return by_fiche


def _set_result(by_fiche, produits, valeur):
    rows = build_accounting_sections(by_fiche["COMPTE_RESULTAT"], "COMPTE_RESULTAT")[0]["tables"]
    for table in rows:
        for row in table["rows"]:
            if row["poste"].startswith("TN Produits des cessions"):
                row["cells"][0]["value"].current_value = serialize_value(produits)
            if row["poste"].startswith("RO Valeur comptable des cessions"):
                row["cells"][0]["value"].current_value = serialize_value(valeur)


def _codes(issues):
    return sorted({issue["code"] for issue in issues})


def test_consistent_note_3d_has_no_internal_issue():
    issues = note_3d_issues(_by_fiche(result=(900, 600)))
    assert [i for i in issues if i["code"] in {"NOTE_3D_NET", "NOTE_3D_PLUS_VALUE", "NOTE_3D_SOUS_TOTAL", "NOTE_3D_TOTAL", "NOTE_3D_COMPTE_RESULTAT"}] == []


def test_wrong_net_value_and_plus_value_are_flagged_per_line():
    issues = note_3d_issues(_by_fiche({(0, 2): 650, (0, 4): 0}, result=(900, 600)))
    assert {"NOTE_3D_NET", "NOTE_3D_PLUS_VALUE"} <= set(_codes(issues))


def test_subtotal_and_total_must_add_up():
    issues = note_3d_issues(_by_fiche({(4, 3): 1, (14, 3): 2}, result=(900, 600)))
    assert {"NOTE_3D_SOUS_TOTAL", "NOTE_3D_TOTAL"} <= set(_codes(issues))


def test_income_statement_must_match_disposal_totals():
    issues = note_3d_issues(_by_fiche(result=(10, 20)))
    assert _codes(issues).count("NOTE_3D_COMPTE_RESULTAT") == 1
    assert len([i for i in issues if i["code"] == "NOTE_3D_COMPTE_RESULTAT"]) == 2


def test_note_answered_no_with_disposals_is_incomplete():
    issues = note_3d_issues(_by_fiche(answer="Non", result=(900, 600)))
    assert "NOTE_3D_INCOMPLETE" in _codes(issues)


def test_existing_fiche_names_are_aligned_with_the_mapping(client, imported_session):
    from app.extensions import db
    from app.models import FicheStatus, ImportColumn
    from app.services.database_service import sync_fiche_names

    FicheStatus.query.filter_by(fiche_code="NOTE_AMORT").update({"fiche_name": "Ancien nom"})
    ImportColumn.query.filter_by(fiche_code="NOTE_AMORT").update({"fiche_name": "Ancien nom"})
    db.session.commit()

    sync_fiche_names()

    expected = "Note 3D — Plus-values et moins-values de cession"
    assert {row.fiche_name for row in FicheStatus.query.filter_by(fiche_code="NOTE_AMORT")} == {expected}
    assert {row.fiche_name for row in ImportColumn.query.filter_by(fiche_code="NOTE_AMORT")} == {expected}
