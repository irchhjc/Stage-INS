from copy import copy
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from app.extensions import db
from app.models import DSF, DSFValue, ImportColumn
from app.services.export_service import _retain_rows, export_controlled_workbook
from app.services.value_codec import serialize_value


def test_sparse_row_compaction_matches_previous_behavior():
    book=Workbook();sheet=book.active
    for row in (1,2,4,6,8):
        sheet.cell(row,1,f'row-{row}')
        sheet.cell(row,3,f'=A{row}')
    sheet.cell(6,3).font=Font(name='Courier New',italic=True)
    old=book.copy_worksheet(sheet)
    for row in range(old.max_row,2,-1):
        if row not in {4,6}:old.delete_rows(row)
    _retain_rows(sheet,2,{4,6})
    assert sheet.max_row==old.max_row
    for row in old:
        for cell in row:
            actual=sheet.cell(cell.row,cell.column)
            assert actual.value==cell.value
            assert copy(actual.font)==copy(cell.font)


def test_shared_styles_preserve_source_fonts_without_correction_leak(client,imported_session):
    first=DSF.query.order_by(DSF.row_index).first();first.status='completed'
    book=load_workbook(imported_session.filepath)
    sheet=book[imported_session.sheet_name]
    sheet.cell(first.row_index,3).font=Font(name='Courier New',size=17,italic=True)
    book.save(imported_session.filepath);book.close()
    values=DSFValue.query.join(ImportColumn).filter(DSFValue.dsf_id==first.id,ImportColumn.column_index.in_([3,4,5])).order_by(ImportColumn.column_index).all()
    for value in values:value.status='verified';value.verified=True
    values[1].corrected=True;values[1].current_value=serialize_value('CHANGED')
    db.session.commit()
    path=export_controlled_workbook(imported_session.id)
    book=load_workbook(path);sheet=book[imported_session.sheet_name]
    assert sheet.cell(2,3).font.name=='Courier New'
    assert sheet.cell(2,3).font.sz==17 and sheet.cell(2,3).font.i
    assert sheet.cell(2,3).font.color.rgb=='FF008000'
    assert sheet.cell(2,4).value=='CHANGED'
    assert sheet.cell(2,4).fill.fgColor.rgb=='FFE2F0D9'
    assert sheet.cell(2,5).fill.fgColor.rgb!='FFE2F0D9'
    assert book['JOURNAL_CONTROLE'].max_row==4
    book.close()
