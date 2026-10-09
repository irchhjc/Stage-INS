import uuid
from copy import copy
from pathlib import Path
from time import perf_counter

from flask import current_app
from openpyxl import Workbook, load_workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font, PatternFill
from sqlalchemy import or_


from app.extensions import db
from app.models import DSF, DSFValue, ImportColumn, ImportSession, User
from app.services.value_codec import deserialize_value, display_value


COLORS = {
    "unverified": "FF000000",
    "verified": "FF008000",
    "anomaly": "FFC00000",
    "not_applicable": "FF666666",
}
CORRECTED_FILL = PatternFill(fill_type="solid", fgColor="FFE2F0D9")


def _apply_font_color(cell, color, cache):
    # Reuse complete styles: retain each source font, border and number format.
    key = (tuple(cell._style) if cell.has_style else None, color)
    style = cache.get(key)
    if style is None:
        font = copy(cell.font) if cell.font else Font()
        font.color = color
        cell.font = font
        style = copy(cell._style)
        cache[key] = style
    cell._style = style


def _retain_rows(worksheet, header_row, selected_rows):
    # Move sparse cells once rather than repeatedly shifting the whole sheet.
    row_map = {old: new for new, old in enumerate(sorted(selected_rows), header_row + 1)}
    cells = {}
    for (row, column), cell in worksheet._cells.items():
        target = row if row <= header_row else row_map.get(row)
        if target is not None:
            cell.row = target
            cells[target, column] = cell
    worksheet._cells = cells
    worksheet._current_row = max((r for r, _ in cells), default=0)


def _journal_sheet_name(workbook):
    base = "JOURNAL_CONTROLE"
    if base not in workbook.sheetnames:
        return base
    number = 2
    while f"{base}_{number}" in workbook.sheetnames:
        number += 1
    return f"{base}_{number}"


def _prepare_controlled_workbook(import_session_id, assigned_user_id=None):
    import_session = db.session.get(ImportSession, import_session_id)
    if import_session is None:
        raise ValueError("Session d'import introuvable.")

    completed_dsfs_query = DSF.query.filter(
        DSF.import_session_id == import_session.id,
        DSF.status == "completed",
    )
    if assigned_user_id is not None:
        completed_dsfs_query = completed_dsfs_query.filter(DSF.assigned_to_id == assigned_user_id)
    completed_dsfs = completed_dsfs_query.order_by(DSF.row_index).all()
    if not completed_dsfs:
        raise ValueError("Aucune DSF entièrement contrôlée n'est disponible pour l'export.")

    completed_dsf_ids = [dsf.id for dsf in completed_dsfs]
    selected_rows = {dsf.row_index for dsf in completed_dsfs}
    source = Path(import_session.filepath)
    if not source.exists():
        raise FileNotFoundError("Le classeur original associé à cet import est introuvable.")

    workbook = load_workbook(source, data_only=False, keep_links=True)
    if import_session.sheet_name not in workbook.sheetnames:
        raise ValueError("La feuille source enregistrée n'existe plus dans le classeur original.")
    worksheet = workbook[import_session.sheet_name]

    dsfs_by_id = {dsf.id: dsf for dsf in completed_dsfs}
    columns = {column.id: column for column in ImportColumn.query.filter_by(import_session_id=import_session.id)}
    # Scalar rows and batches avoid constructing/retaining millions of ORM objects.
    values_query = db.session.query(
        DSFValue.dsf_id, DSFValue.import_column_id, DSFValue.variable_name,
        DSFValue.original_value, DSFValue.current_value, DSFValue.status,
        DSFValue.corrected, DSFValue.verified, DSFValue.operator,
        DSFValue.corrected_at, DSFValue.verified_at,
    ).filter(DSFValue.dsf_id.in_(completed_dsf_ids))
    values_query = values_query.join(DSF).join(ImportColumn).order_by(DSF.row_index, ImportColumn.column_index)
    font_cache = {}
    for value in values_query.yield_per(2000):
        dsf = dsfs_by_id[value.dsf_id]
        column = columns[value.import_column_id]
        cell = worksheet.cell(row=dsf.row_index, column=column.column_index)
        if value.corrected:
            cell.value = deserialize_value(value.current_value)
        _apply_font_color(cell, COLORS.get(value.status, COLORS["unverified"]), font_cache)
        if value.corrected and value.status == "verified":
            # Style objects are shared: copy before changing the fill.
            cell._style = copy(cell._style)
            cell.fill = CORRECTED_FILL

    _retain_rows(worksheet, import_session.header_row, selected_rows)

    if assigned_user_id is not None:
        for other_sheet in list(workbook.worksheets):
            if other_sheet is not worksheet:
                workbook.remove(other_sheet)

    journal = workbook.create_sheet(_journal_sheet_name(workbook))
    headers = [
        "NIU",
        "NUMERO DSF",
        "Raison sociale",
        "Année",
        "Fiche",
        "Variable",
        "Colonne Excel",
        "Valeur originale",
        "Nouvelle valeur",
        "Statut",
        "Opérateur",
        "Date",
        "Heure",
    ]
    journal.append(headers)
    header_fill = PatternFill(fill_type="solid", fgColor="FF17365D")
    for cell in journal[1]:
        cell.font = Font(color="FFFFFFFF", bold=True)
        cell.fill = header_fill

    for value in values_query.filter((DSFValue.status != "unverified") | DSFValue.corrected.is_(True)).yield_per(2000):
        dsf = dsfs_by_id[value.dsf_id]
        column = columns[value.import_column_id]
        if value.status == "unverified" and not value.corrected:
            continue
        timestamp = value.corrected_at or value.verified_at
        journal.append(
            [
                dsf.niu,
                dsf.numero_dsf,
                dsf.raison_sociale,
                dsf.annee,
                column.fiche_name,
                value.variable_name,
                column.excel_column_letter,
                display_value(value.original_value),
                display_value(value.current_value),
                "corrigée et vérifiée" if value.corrected and value.verified else value.status,
                value.operator,
                timestamp.date().isoformat() if timestamp else None,
                timestamp.time().replace(microsecond=0).isoformat() if timestamp else None,
            ]
        )
    journal.freeze_panes = "A2"
    journal.auto_filter.ref = journal.dimensions
    widths = [20, 18, 32, 12, 38, 55, 15, 22, 22, 24, 22, 14, 12]
    for index, width in enumerate(widths, start=1):
        journal.column_dimensions[journal.cell(1, index).column_letter].width = width

    return workbook, import_session, len(completed_dsfs)


def export_controlled_workbook(import_session_id, assigned_user_id=None, username=None):
    started = perf_counter()
    workbook, import_session, completed_count = _prepare_controlled_workbook(
        import_session_id,
        assigned_user_id=assigned_user_id,
    )
    output_dir = Path(current_app.config["EXPORT_FOLDER"])
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = Path(import_session.filename).stem[:80] or "dsf"
    scope = f"_{username}" if username else ""
    output_path = output_dir / f"{safe_stem}_dsf_controlees{scope}_{uuid.uuid4().hex[:8]}.xlsx"
    try:
        workbook.save(output_path)
    finally:
        workbook.close()
    current_app.logger.info(
        "Export classeur %s : %s DSF, %.2f secondes",
        import_session_id,
        completed_count,
        perf_counter() - started,
    )
    return output_path


def _streaming_header(worksheet, values):
    header_fill = PatternFill(fill_type="solid", fgColor="FF17365D")
    header_font = Font(color="FFFFFFFF", bold=True)
    cells = []
    for value in values:
        cell = WriteOnlyCell(worksheet, value=value)
        cell.font = header_font
        cell.fill = header_fill
        cells.append(cell)
    worksheet.append(cells)


def _completed_schema_groups(completed_by_session):
    groups = {}
    sessions_by_id = {}
    for import_session_id, dsf_count in completed_by_session:
        import_session = db.session.get(ImportSession, import_session_id)
        if import_session is None:
            raise ValueError(f"Import {import_session_id} introuvable.")
        sessions_by_id[import_session_id] = import_session
        headers = tuple(
            variable_name
            for variable_name, in (
                db.session.query(ImportColumn.variable_name)
                .filter(ImportColumn.import_session_id == import_session_id)
                .order_by(ImportColumn.column_index)
                .all()
            )
        )
        if not headers:
            raise ValueError(f"{import_session.filename} : aucune colonne importée.")
        group = groups.setdefault(
            headers,
            {"headers": headers, "session_ids": [], "dsf_count": 0},
        )
        group["session_ids"].append(import_session_id)
        group["dsf_count"] += dsf_count
    return list(groups.values()), sessions_by_id


def _stream_schema_sheet(
    workbook,
    title,
    group,
    sessions_by_id,
    users_by_id,
    journal_rows,
):
    worksheet = workbook.create_sheet(title)
    headers = group["headers"]
    _streaming_header(worksheet, headers)
    worksheet.freeze_panes = "A2"

    dsf_rows = (
        db.session.query(
            DSF.id,
            DSF.import_session_id,
            DSF.row_index,
            DSF.niu,
            DSF.numero_dsf,
            DSF.raison_sociale,
            DSF.annee,
            DSF.assigned_to_id,
        )
        .filter(
            DSF.status == "completed",
            DSF.import_session_id.in_(group["session_ids"]),
        )
        .order_by(DSF.import_session_id, DSF.row_index)
        .all()
    )
    metadata_by_id = {row.id: row for row in dsf_rows}

    def append_row(dsf_id, values, counts, output_row):
        worksheet.append(values)
        metadata = metadata_by_id[dsf_id]
        import_session = sessions_by_id[metadata.import_session_id]
        assignee = users_by_id.get(metadata.assigned_to_id)
        journal_rows.append(
            [
                title,
                output_row,
                import_session.filename,
                import_session.sheet_name,
                metadata.niu,
                metadata.numero_dsf,
                metadata.raison_sociale,
                metadata.annee,
                assignee.display_label if assignee else None,
                counts[0],
                counts[1],
                counts[2],
                counts[3],
            ]
        )

    values_query = (
        db.session.query(
            DSFValue.dsf_id,
            ImportColumn.column_index,
            DSFValue.current_value,
            DSFValue.status,
            DSFValue.corrected,
        )
        .join(DSF, DSF.id == DSFValue.dsf_id)
        .join(ImportColumn, ImportColumn.id == DSFValue.import_column_id)
        .filter(
            DSF.status == "completed",
            DSF.import_session_id.in_(group["session_ids"]),
        )
        .order_by(DSF.import_session_id, DSF.row_index, ImportColumn.column_index)
        .yield_per(5000)
    )

    current_dsf_id = None
    row_values = None
    counts = None
    output_row = 2
    exported_count = 0
    anomaly_font = Font(color=COLORS["anomaly"])
    for value in values_query:
        if value.dsf_id != current_dsf_id:
            if current_dsf_id is not None:
                append_row(current_dsf_id, row_values, counts, output_row)
                output_row += 1
                exported_count += 1
            current_dsf_id = value.dsf_id
            row_values = [None] * len(headers)
            counts = [0, 0, 0, 0]

        cell_value = deserialize_value(value.current_value)
        if value.corrected or value.status == "anomaly":
            cell = WriteOnlyCell(worksheet, value=cell_value)
            if value.corrected:
                cell.fill = CORRECTED_FILL
            if value.status == "anomaly":
                cell.font = anomaly_font
            cell_value = cell
        row_values[value.column_index - 1] = cell_value
        counts[0] += value.status == "verified"
        counts[1] += bool(value.corrected)
        counts[2] += value.status == "anomaly"
        counts[3] += value.status == "not_applicable"

    if current_dsf_id is not None:
        append_row(current_dsf_id, row_values, counts, output_row)
        exported_count += 1
    if exported_count != len(dsf_rows):
        raise ValueError(
            f"{title} : {len(dsf_rows)} DSF attendues, {exported_count} exportées."
        )


def export_all_completed_workbooks():
    started = perf_counter()
    completed_by_session = (
        db.session.query(DSF.import_session_id, db.func.count(DSF.id))
        .filter(DSF.status == "completed")
        .group_by(DSF.import_session_id)
        .order_by(DSF.import_session_id)
        .all()
    )
    if not completed_by_session:
        raise ValueError("Aucune DSF entièrement contrôlée n'est disponible pour l'export global.")

    groups, sessions_by_id = _completed_schema_groups(completed_by_session)
    users_by_id = {user.id: user for user in User.query.all()}
    total_dsfs = sum(count for _, count in completed_by_session)
    output_dir = Path(current_app.config["EXPORT_FOLDER"])
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"toutes_dsf_terminees_{uuid.uuid4().hex[:8]}.xlsx"
    workbook = Workbook(write_only=True)
    journal_rows = []
    try:
        for index, group in enumerate(groups, start=1):
            title = "DSF_TERMINEES" if len(groups) == 1 else f"DSF_SCHEMA_{index}"
            _stream_schema_sheet(
                workbook,
                title,
                group,
                sessions_by_id,
                users_by_id,
                journal_rows,
            )

        journal = workbook.create_sheet("JOURNAL_CONTROLE")
        _streaming_header(
            journal,
            [
                "Feuille exportée",
                "Ligne exportée",
                "Classeur source",
                "Feuille source",
                "NIU",
                "NUMERO DSF",
                "Raison sociale",
                "Année",
                "Contrôleur",
                "Cellules vérifiées",
                "Cellules corrigées",
                "Anomalies",
                "Cellules non applicables",
            ],
        )
        for row in journal_rows:
            journal.append(row)
        journal.freeze_panes = "A2"

        corrections = workbook.create_sheet("CORRECTIONS_DETAIL")
        _streaming_header(
            corrections,
            [
                "Classeur source",
                "Feuille source",
                "NIU",
                "NUMERO DSF",
                "Raison sociale",
                "Année",
                "Fiche",
                "Variable",
                "Colonne Excel",
                "Valeur originale",
                "Nouvelle valeur",
                "Statut",
                "Opérateur",
                "Date",
                "Heure",
            ],
        )
        correction_rows = (
            db.session.query(
                DSF.import_session_id,
                DSF.niu,
                DSF.numero_dsf,
                DSF.raison_sociale,
                DSF.annee,
                ImportColumn.fiche_name,
                DSFValue.variable_name,
                ImportColumn.excel_column_letter,
                DSFValue.original_value,
                DSFValue.current_value,
                DSFValue.status,
                DSFValue.operator,
                DSFValue.corrected_at,
                DSFValue.verified_at,
            )
            .join(DSF, DSF.id == DSFValue.dsf_id)
            .join(ImportColumn, ImportColumn.id == DSFValue.import_column_id)
            .filter(
                DSF.status == "completed",
                or_(DSFValue.corrected.is_(True), DSFValue.status == "anomaly"),
            )
            .order_by(DSF.import_session_id, DSF.row_index, ImportColumn.column_index)
            .yield_per(2000)
        )
        for value in correction_rows:
            import_session = sessions_by_id[value.import_session_id]
            timestamp = value.corrected_at or value.verified_at
            corrections.append(
                [
                    import_session.filename,
                    import_session.sheet_name,
                    value.niu,
                    value.numero_dsf,
                    value.raison_sociale,
                    value.annee,
                    value.fiche_name,
                    value.variable_name,
                    value.excel_column_letter,
                    display_value(value.original_value),
                    display_value(value.current_value),
                    value.status,
                    value.operator,
                    timestamp.date().isoformat() if timestamp else None,
                    timestamp.time().replace(microsecond=0).isoformat() if timestamp else None,
                ]
            )
        corrections.freeze_panes = "A2"
        workbook.save(output_path)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        workbook.close()
    current_app.logger.info(
        "Export global : %s source(s), %s schéma(s), %s DSF, %.2f secondes",
        len(completed_by_session),
        len(groups),
        total_dsfs,
        perf_counter() - started,
    )
    return output_path, len(completed_by_session), total_dsfs


def export_not_started_workbook(import_session_id):
    """Exporte en flux les DSF non commencées d'un classeur (mémoire constante).

    Les valeurs viennent de la base (identiques au fichier importé tant que la DSF
    n'est pas commencée) : le classeur Excel d'origine n'est ni rouvert ni chargé.
    """
    started = perf_counter()
    import_session = db.session.get(ImportSession, import_session_id)
    if import_session is None:
        raise ValueError("Session d'import introuvable.")
    headers = [
        variable_name
        for variable_name, in db.session.query(ImportColumn.variable_name)
        .filter(ImportColumn.import_session_id == import_session_id)
        .order_by(ImportColumn.column_index)
        .all()
    ]
    dsf_ids = [
        dsf_id
        for dsf_id, in db.session.query(DSF.id)
        .filter(DSF.import_session_id == import_session_id, DSF.status == "not_started")
        .order_by(DSF.row_index)
        .all()
    ]
    if not dsf_ids or not headers:
        raise ValueError("Aucune DSF non commencée n'est disponible pour l'export.")

    output_dir = Path(current_app.config["EXPORT_FOLDER"])
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = Path(import_session.filename).stem[:80] or "dsf"
    output_path = output_dir / f"{safe_stem}_dsf_non_commencees_{uuid.uuid4().hex[:8]}.xlsx"

    workbook = Workbook(write_only=True)
    try:
        worksheet = workbook.create_sheet("DSF_NON_COMMENCEES")
        _streaming_header(worksheet, headers)
        worksheet.freeze_panes = "A2"
        values_query = (
            db.session.query(DSFValue.dsf_id, ImportColumn.column_index, DSFValue.original_value)
            .join(DSF, DSF.id == DSFValue.dsf_id)
            .join(ImportColumn, ImportColumn.id == DSFValue.import_column_id)
            .filter(DSF.import_session_id == import_session_id, DSF.status == "not_started")
            .order_by(DSF.row_index, ImportColumn.column_index)
            .yield_per(5000)
        )
        current_dsf_id, row_values, exported = None, None, 0
        for dsf_id, column_index, original in values_query:
            if dsf_id != current_dsf_id:
                if current_dsf_id is not None:
                    worksheet.append(row_values)
                    exported += 1
                current_dsf_id, row_values = dsf_id, [None] * len(headers)
            row_values[column_index - 1] = deserialize_value(original)
        if current_dsf_id is not None:
            worksheet.append(row_values)
            exported += 1
        if exported != len(dsf_ids):
            raise ValueError(f"{len(dsf_ids)} DSF attendues, {exported} exportées.")
        workbook.save(output_path)
    finally:
        workbook.close()
    current_app.logger.info(
        "Export des DSF non commencées du classeur %s : %s DSF, %.2f secondes",
        import_session_id,
        len(dsf_ids),
        perf_counter() - started,
    )
    return output_path
