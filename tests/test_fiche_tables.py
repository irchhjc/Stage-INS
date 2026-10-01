import io
import re
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

from app.config.fiche_mapping import FICHE_DEFINITIONS
from openpyxl import Workbook

from app.models import DSF, DSFValue, ImportColumn, ImportSession
from app.services.mapping_service import build_accounting_sections, build_column_mapping


HEADERS_PATH = Path(__file__).parent / "fixtures" / "dsf_headers_20261001.txt"


def _headers():
    return HEADERS_PATH.read_text(encoding="utf-8-sig").strip().split("\t")


def _values_by_fiche():
    values_by_fiche = defaultdict(list)
    for item in build_column_mapping(_headers()):
        values_by_fiche[item["fiche_code"]].append(
            SimpleNamespace(
                variable_name=item["variable_name"],
                column=SimpleNamespace(column_index=item["column_index"]),
            )
        )
    return values_by_fiche


def test_supplied_variables_map_to_all_fiches_in_source_order():
    headers = _headers()
    mapping = build_column_mapping(headers)

    assert len(headers) == 1776
    assert len(mapping) == len(headers)
    assert [item["variable_name"] for item in mapping] == headers
    assert [item["column_index"] for item in mapping] == list(
        range(1, len(headers) + 1)
    )
    assert list(dict.fromkeys(item["fiche_code"] for item in mapping)) == [
        definition["code"] for definition in FICHE_DEFINITIONS
    ]


def test_each_fiche_uses_one_table_and_keeps_every_source_variable():
    values_by_fiche = _values_by_fiche()
    rendered_headers = []

    for definition in FICHE_DEFINITIONS:
        values = values_by_fiche[definition["code"]]
        sections = build_accounting_sections(values)

        assert len(sections) == 1
        rows = sections[0]["rows"]
        assert sections[0]["variable_count"] == len(values)
        assert [row["source_order"] for row in rows] == [
            value.column.column_index for value in values
        ]
        assert [row["source_variable"] for row in rows] == [
            value.variable_name for value in values
        ]
        rendered_headers.extend(row["source_variable"] for row in rows)

    assert rendered_headers == _headers()


def test_repeated_measures_are_numbered_without_collapsing_variables():
    values = _values_by_fiche()

    identification = build_accounting_sections(values["IDENT"])[0]["rows"]
    city_rows = [row for row in identification if row["poste"] == "Ville"]
    assert [row["measure"] for row in city_rows] == ["Valeur (1)", "Valeur (2)"]

    note_3a = build_accounting_sections(values["NOTE_3A"])[0]["rows"]
    first_poste = [
        row for row in note_3a if row["poste"] == "AD IMMOBILISATION INCORPORELLES"
    ]
    assert len(first_poste) == 7
    assert [row["measure"] for row in first_poste][2:6] == [
        "Virement entre postes (1)",
        "Réévaluation",
        "Cessions et scissions",
        "Virement entre postes (2)",
    ]


def test_rendered_fiche_has_one_table_in_database_column_order(client, imported_session):
    dsf = DSF.query.order_by(DSF.id).first()

    for definition in FICHE_DEFINITIONS:
        fiche_code = definition["code"]
        expected_columns = [
            column.column_index
            for column in ImportColumn.query.filter_by(
                import_session_id=imported_session.id,
                fiche_code=fiche_code,
            ).order_by(ImportColumn.column_index)
        ]
        page = client.get(f"/dsf/{dsf.id}/fiche/{fiche_code}")
        html = page.get_data(as_text=True)

        assert page.status_code == 200
        assert html.count('class="table accounting-table variable-order-table') == 1
        assert [
            int(index)
            for index in re.findall(r'data-column-index="(\d+)"', html)
        ] == expected_columns


def test_supplied_1776_variables_import_and_render_once_in_order(client):
    headers = _headers()
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "DSF"
    worksheet.append(headers)
    values = [None] * len(headers)
    values[:5] = ["DSF-1776", "T-1776", "NIU-1776", "SOCIÉTÉ TEST", "ST"]
    worksheet.append(values)
    stream = io.BytesIO()
    workbook.save(stream)
    workbook.close()
    stream.seek(0)

    imported = client.post(
        "/import/",
        data={"file": (stream, "dsf_1776_variables.xlsx")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert imported.status_code == 302

    import_session = ImportSession.query.order_by(ImportSession.id.desc()).first()
    dsf = DSF.query.filter_by(import_session_id=import_session.id).one()
    assert ImportColumn.query.filter_by(import_session_id=import_session.id).count() == 1776
    assert DSFValue.query.filter_by(dsf_id=dsf.id).count() == 1776

    rendered_order = []
    for definition in FICHE_DEFINITIONS:
        page = client.get(f"/dsf/{dsf.id}/fiche/{definition['code']}")
        html = page.get_data(as_text=True)
        assert page.status_code == 200
        assert html.count('class="table accounting-table variable-order-table') == 1
        rendered_order.extend(
            int(index)
            for index in re.findall(r'data-column-index="(\d+)"', html)
        )

    assert rendered_order == list(range(1, 1777))
