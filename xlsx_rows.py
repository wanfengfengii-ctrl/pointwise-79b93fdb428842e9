import posixpath
import xml.etree.ElementTree as ET
from formulas import position
from errors import IngestError

MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'
N = '{' + MAIN + '}'


def sheet_member(archive, name):
    book = ET.fromstring(archive.read('xl/workbook.xml'))
    links = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
    matches = [s for s in book.findall(N + 'sheets/' + N + 'sheet')
               if s.get('name') == name]
    if len(matches) != 1:
        raise IngestError('SHEET_NOT_FOUND')
    rid = matches[0].get('{' + REL + '}id')
    targets = [r for r in links if r.get('Id') == rid
               and r.get('Type') == REL + '/worksheet'
               and r.get('TargetMode', 'Internal') == 'Internal']
    if len(targets) != 1:
        raise IngestError('BAD_SHEET_RELATIONSHIP')
    target = targets[0].get('Target', '')
    member = posixpath.normpath(target.lstrip('/') if target.startswith('/')
                              else posixpath.join('xl', target))
    if not member.startswith('xl/') or member not in archive.namelist():
        raise IngestError('BAD_SHEET_TARGET')
    return member


def rows(archive, member):
    previous_row = 0
    with archive.open(member) as source:
        stack = []
        for event, element in ET.iterparse(source, events=('start', 'end')):
            if event == 'start':
                stack.append(element)
                continue
            if element.tag == N + 'row':
                number = int(element.get('r', '0'))
                if not previous_row < number <= 1048576:
                    raise IngestError('ROW_ORDER')
                previous_row = number
                result, previous_column = [], 0
                for cell in element.findall(N + 'c'):
                    coord = cell.get('r', '')
                    row, column = position(coord)
                    if row != number or column <= previous_column:
                        raise IngestError('CELL_ORDER')
                    previous_column = column
                    kind = cell.get('t', 'n')
                    if kind not in ('n', 'str', 'b', 'e'):
                        raise IngestError('UNSUPPORTED_CELL_TYPE')
                    fs, vs = cell.findall(N + 'f'), cell.findall(N + 'v')
                    if len(fs) > 1 or len(vs) > 1:
                        raise IngestError('DUPLICATE_CELL_FIELD')
                    formula = None
                    if fs:
                        f = fs[0]
                        t = f.get('t', 'normal')
                        if t not in ('normal', 'shared'):
                            raise IngestError('UNSUPPORTED_FORMULA_TYPE')
                        formula = dict(t=t, si=f.get('si'), ref=f.get('ref'),
                                       text=f.text or '')
                    result.append(dict(coord=coord, type=kind,
                                       cache=vs[0].text if vs else None, f=formula))
                yield result
                if len(stack) > 1:
                    stack[-2].remove(element)
                element.clear()
            stack.pop()
