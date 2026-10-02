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


def _source_orders(section):
    return [
        cell["source_order"]
        for table in section["tables"]
        for row in table["rows"]
        for cell in row["cells"]
    ]


def test_every_fiche_follows_the_model_and_keeps_every_variable_in_order():
    values_by_fiche = _values_by_fiche()
    rendered_orders = []

    for definition in FICHE_DEFINITIONS:
        values = values_by_fiche[definition["code"]]
        sections = build_accounting_sections(values, definition["code"])

        assert len(sections) == 1
        assert sections[0]["layout"] == "model", definition["code"]
        assert sections[0]["variable_count"] == len(values)
        assert _source_orders(sections[0]) == [
            value.column.column_index for value in values
        ]
        rendered_orders.extend(_source_orders(sections[0]))

    assert rendered_orders == list(range(1, len(_headers()) + 1))


def test_model_matches_both_source_versions_with_and_without_optional_rows():
    values = _values_by_fiche()

    identification = build_accounting_sections(values["IDENT"], "IDENT")[0]
    labels = [row["poste"] for row in identification["tables"][0]["rows"]]
    assert len(labels) == 28
    assert "Cle" not in labels

    with_key = values["IDENT"][:3] + [
        SimpleNamespace(variable_name="Cle", column=SimpleNamespace(column_index=0))
    ] + values["IDENT"][3:]
    with_key_section = build_accounting_sections(with_key, "IDENT")[0]
    assert with_key_section["layout"] == "model"
    assert "Cle" in [row["poste"] for row in with_key_section["tables"][0]["rows"]]

    note_3a = build_accounting_sections(values["NOTE_3A"], "NOTE_3A")[0]
    assert [table["title"] for table in note_3a["tables"] if table["title"]] == ["Note 3C"]


def test_balance_sheet_assets_is_one_postes_by_measures_table():
    values = _values_by_fiche()

    section = build_accounting_sections(values["BILAN_ACTIF"], "BILAN_ACTIF")[0]
    assert len(section["tables"]) == 1
    table = section["tables"][0]
    assert table["columns"] == ["BRUT", "AMORT./DÉPRÉC.", "NET N", "NET N-1"]
    assert len(table["rows"]) == 29
    assert table["rows"][0]["poste"] == "IMMOBILISATIONS INCORPORELLES"
    assert all(len(row["cells"]) == 4 for row in table["rows"])
    assert [row["poste"] for row in table["rows"] if row["is_total"]][:2] == [
        "TOTAL ACTIF IMMOBILISE",
        "TOTAL ACTIF CIRCULANT",
    ]


def test_notes_split_into_question_row_and_tables_with_their_own_columns():
    values = _values_by_fiche()

    note_4 = build_accounting_sections(values["NOTE_4"], "NOTE_4")[0]["tables"]
    assert [table["is_question"] for table in note_4] == [True, False]
    assert note_4[1]["columns"] == [
        "N",
        "N-1",
        "À un an au plus",
        "De plus d'un an à deux ans",
        "À plus de deux ans",
    ]

    note_16b = build_accounting_sections(values["NOTE_16B"], "NOTE_16B")[0]["tables"]
    assert [len(table["columns"]) for table in note_16b] == [1, 2, 4, 2]

    note_27b = build_accounting_sections(values["NOTE_27B"], "NOTE_27B")[0]["tables"]
    assert note_27b[1]["columns"] == ["Hommes", "Femmes", "Total"]
    assert len(note_27b[1]["rows"]) == 22


def test_repeated_measures_are_numbered_without_collapsing_variables():
    values = _values_by_fiche()

    note_3a = build_accounting_sections(values["NOTE_3A"], "NOTE_3A")[0]["tables"]
    assert note_3a[1]["columns"] == [
        "Montant brut à l'ouverture",
        "Acquisitions, apports et créations",
        "Virement entre postes (1)",
        "Réévaluation",
        "Cessions et scissions",
        "Virement entre postes (2)",
        "Montant brut à la clôture",
    ]
    assert all(len(row["cells"]) == 7 for row in note_3a[1]["rows"])


def test_unknown_source_structure_falls_back_to_ordered_list():
    values = _values_by_fiche()["NOTE_6"][:-1]

    section = build_accounting_sections(values, "NOTE_6")[0]

    assert section["layout"] == "source"
    assert len(section["tables"]) == 1
    assert section["tables"][0]["columns"] == ["Valeur"]
    assert _source_orders(section) == [value.column.column_index for value in values]
    assert [row["poste"] for row in section["tables"][0]["rows"]] == [
        value.variable_name for value in values
    ]


def test_rendered_fiche_keeps_database_column_order(client, imported_session):
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
        assert "version connue du modèle" not in html
        rendered_order.extend(
            int(index)
            for index in re.findall(r'data-column-index="(\d+)"', html)
        )

    assert rendered_order == list(range(1, 1777))

    page = client.get(f"/dsf/{dsf.id}/fiche/BILAN_ACTIF")
    html = page.get_data(as_text=True)
    assert re.findall(r'<th class="measure-column" scope="col">([^<]+)</th>', html) == [
        "BRUT",
        "AMORT./DÉPRÉC.",
        "NET N",
        "NET N-1",
    ]
    assert html.count("<tbody>") == 1
