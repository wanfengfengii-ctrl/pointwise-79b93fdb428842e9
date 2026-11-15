import io
import zipfile
import xml.etree.ElementTree as ET
from xlsx_rows import MAIN, REL, PKG, N


def cell(coord, cache=None, formula=None, si=None, ref=None, kind='n'):
    c = ET.Element(N + 'c', r=coord, t=kind)
    if formula is not None or si is not None:
        attrs = {} if si is None else {'t': 'shared', 'si': str(si)}
        if ref is not None:
            attrs['ref'] = ref
        ET.SubElement(c, N + 'f', attrs).text = formula
    if cache is not None:
        ET.SubElement(c, N + 'v').text = cache
    return c


def worksheet(row_list):
    root = ET.Element(N + 'worksheet')
    data = ET.SubElement(root, N + 'sheetData')
    for number, cells in row_list:
        row = ET.SubElement(data, N + 'row', r=str(number))
        row.extend(cells)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def workbook(xml):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/data.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels', '<Relationships xmlns="' + PKG + '">'
            '<Relationship Id="book" Type="' + REL + '/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        book = ET.Element(N + 'workbook')
        sheets = ET.SubElement(book, N + 'sheets')
        ET.SubElement(sheets, N + 'sheet', {'name': 'Readings', 'sheetId': '1',
                                           '{' + REL + '}id': 'data'})
        z.writestr('xl/workbook.xml', ET.tostring(book))
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="' + PKG + '">'
            '<Relationship Id="data" Type="' + REL + '/worksheet" Target="worksheets/data.xml"/></Relationships>')
        z.writestr('xl/worksheets/data.xml', xml)
    stream.seek(0)
    return stream


def normal_book():
    return workbook(worksheet([
        (1, [cell('A1', '7'),
             cell('B1', '8', 'A1+1', 0, 'B1:B2'),
             cell('C1', 'ok', '"ok"', kind='str')]),
        (2, [cell('A2', '9'), cell('B2', '10', si=0)])]))


def late_book():
    return workbook(worksheet([
        (1, [cell('A1', '100'), cell('B1', '103', si=7)]),
        (2, [cell('A2', '200')]),
        (3, [cell('A3', '300'),
             cell('B3', '303', 'A3+$A3+A$1+$A$1', 7, 'B1:B3')])]))


def lexical_book():
    formula = 'IF(A1="A1","say ""B2""",\'Q1 log\'!B$2+$C1+SUM(D1:E2)+LOG10(A1)+1E10)'
    return workbook(worksheet([
        (1, [cell('F1', '11', formula, 4, 'F1:G2')]),
        (2, [cell('G2', '22', si=4)])]))
