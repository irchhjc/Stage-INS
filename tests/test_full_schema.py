import io
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

from openpyxl import Workbook, load_workbook

from app.config.fiche_mapping import FICHE_DEFINITIONS
from app.extensions import db
from app.models import DSF, DSFValue, ImportColumn, ImportSession
from app.services.mapping_service import build_accounting_sections, build_column_mapping, normalize_label
from app.services.schema_service import (
    FULL_DSF_COLUMN_COUNT,
    FULL_DSF_SCHEMA_CODE,
    identify_schema,
)


HEADERS_PATH = Path(__file__).parent / "fixtures" / "new_dsf_headers_20260925.txt"


def _reference_headers():
    return HEADERS_PATH.read_text(encoding="utf-8-sig").strip().split("\t")


def _reference_values_by_fiche():
    values_by_fiche = defaultdict(list)
    for item in build_column_mapping(_reference_headers()):
        values_by_fiche[item["fiche_code"]].append(
            SimpleNamespace(variable_name=item["variable_name"])
        )
    return values_by_fiche


def test_bilan_actif_uses_one_complete_four_measure_table():
    sections = build_accounting_sections(_reference_values_by_fiche()["BILAN_ACTIF"])

    assert len(sections) == 1
    assert sections[0]["column_count"] == 4
    assert [slot["label"] for slot in sections[0]["slots"]] == [
        "BRUT",
        "AMORT./DÉPRÉC.",
        "NET N",
        "NET N-1",
    ]
    assert len(sections[0]["rows"]) == 29
    assert all(len(row["cells"]) == 4 for row in sections[0]["rows"])


def test_every_full_schema_table_contains_only_real_cells():
    for values in _reference_values_by_fiche().values():
        for section in build_accounting_sections(values):
            expected_slots = {slot["key"] for slot in section["slots"]}
            assert expected_slots
            assert all(set(row["cells"]) == expected_slots for row in section["rows"])


def _reference_workbook(headers):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "DSF complète"
    worksheet.append(headers)

    values = [None] * len(headers)
    identity_values = {
        "numero de la dsf": "DSF-COMPLETE-001",
        "numero_t": "T-COMPLETE-001",
        "niu": "NIU-COMPLETE-001",
        "raison sociale": "ENTREPRISE SCHEMA COMPLET",
        "sigle usuel": "ESC",
        "annee": 2026,
    }
    for index, header in enumerate(headers):
        normalized = normalize_label(header)
        if normalized in identity_values:
            values[index] = identity_values[normalized]
    worksheet.append(values)

    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    output.seek(0)
    return output


def test_full_1777_column_schema_is_recognized_imported_and_exported(client):
    headers = _reference_headers()
    profile = identify_schema(headers)

    assert len(headers) == FULL_DSF_COLUMN_COUNT
    assert profile["recognized"] is True
    assert profile["code"] == FULL_DSF_SCHEMA_CODE

    response = client.post(
        "/import/",
        data={"file": (_reference_workbook(headers), "dsf_complete_1777.xlsx")},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Schéma DSF complet — 1 777 colonnes reconnu" in html

    import_session = ImportSession.query.one()
    stored_columns = ImportColumn.query.order_by(ImportColumn.column_index).all()
    dsf = DSF.query.one()

    assert import_session.column_count == FULL_DSF_COLUMN_COUNT
    assert [column.variable_name for column in stored_columns] == headers
    assert [column.column_index for column in stored_columns] == list(
        range(1, FULL_DSF_COLUMN_COUNT + 1)
    )
    assert {column.fiche_code for column in stored_columns} == {
        definition["code"] for definition in FICHE_DEFINITIONS
    }
    assert DSFValue.query.filter_by(dsf_id=dsf.id).count() == FULL_DSF_COLUMN_COUNT
    assert dsf.numero_dsf == "DSF-COMPLETE-001"
    assert dsf.numero_dsf_t == "T-COMPLETE-001"
    assert dsf.niu == "NIU-COMPLETE-001"
    assert dsf.raison_sociale == "ENTREPRISE SCHEMA COMPLET"
    assert dsf.sigle == "ESC"
    assert dsf.annee == "2026"

    duplicate_header = next(name for name, count in Counter(headers).items() if count > 1)
    expected_positions = [index for index, name in enumerate(headers, start=1) if name == duplicate_header]
    stored_positions = [
        column.column_index for column in stored_columns if column.variable_name == duplicate_header
    ]
    assert stored_positions == expected_positions

    dsf.status = "completed"
    db.session.commit()
    exported = client.post(f"/export/{import_session.id}")
    assert exported.status_code == 200
    exported_workbook = load_workbook(io.BytesIO(exported.data), read_only=True, data_only=False)
    try:
        exported_headers = [
            cell.value
            for cell in next(
                exported_workbook[import_session.sheet_name].iter_rows(
                    min_row=import_session.header_row,
                    max_row=import_session.header_row,
                    max_col=FULL_DSF_COLUMN_COUNT,
                )
            )
        ]
        assert exported_headers == headers
    finally:
        exported_workbook.close()
