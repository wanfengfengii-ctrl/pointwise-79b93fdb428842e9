import io
import json
import os
import sys
import tempfile
import zipfile
from errors import IngestError
from importer import extract, ingest
from samples import cell, worksheet, workbook, normal_book, late_book, lexical_book


def read(source):
    sink = io.StringIO()
    count = extract(source, 'Readings', sink)
    records = [json.loads(line) for line in sink.getvalue().splitlines()]
    assert count == len(records)
    return records


def record(coord, cache, formula=None, kind='n'):
    return dict(coord=coord, type=kind, cache=cache, formula=formula)


def normal():
    actual = read(normal_book())
    assert actual == [record('A1', '7'), record('B1', '8', 'A1+1'),
                      record('C1', 'ok', '"ok"', 'str'), record('A2', '9'),
                      record('B2', '10', 'A2+1')]
    print('NORMAL_REGRESSION_OK')


def incident():
    expected = [
        ('late-master', late_book(), [
            record('A1', '100'), record('B1', '103', 'A1+$A1+A$1+$A$1'),
            record('A2', '200'), record('A3', '300'),
            record('B3', '303', 'A3+$A3+A$1+$A$1')]),
        ('lexical-boundaries', lexical_book(), [
            record('F1', '11', 'IF(A1="A1","say ""B2""",\'Q1 log\'!B$2+$C1+SUM(D1:E2)+LOG10(A1)+1E10)'),
            record('G2', '22', 'IF(B2="A1","say ""B2""",\'Q1 log\'!C$2+$C2+SUM(E2:F3)+LOG10(B2)+1E10)')])]
    broken = False
    for name, source, wanted in expected:
        try:
            actual = read(source)
        except IngestError as error:
            actual = {'error': str(error)}
        print(json.dumps(dict(case=name, actual=actual, expected=wanted),
                         ensure_ascii=False, sort_keys=True))
        broken |= actual != wanted
    print('XLSX_SHARED_FORMULA_DIVERGENCE' if broken else 'SHARED_FORMULA_REPAIR_OK')
    return int(broken)


MASTER_21 = 'SUM($A1:B$1)+"A1""B2"+1E10+TRUE+_xlfn.X(A1)+LOG10 (B$1)'
MASTER_22 = "'O''Brien'!A1+'A1 log'!B2+'Q1 log'!A$1+$B2"


def boundary_book():
    return workbook(worksheet([
        (1, [cell('A1', '5'),
             cell('B1', '1', MASTER_21, 21, 'B1:D2'),
             cell('C1', '2', si=21),
             cell('D1', '6', 'B1+1')]),
        (2, [cell('A2', '3', MASTER_22, '022', 'A2:C2'),
             cell('B2', '4', si=21),
             cell('C2', '5', si=22),
             cell('D2', '7', si=21)])]))


def rejects(xml, reason):
    try:
        read(workbook(xml))
    except IngestError as error:
        assert reason in str(error), (reason, str(error))
        return
    raise AssertionError('INVALID_SHARED_GROUP_ACCEPTED:' + reason)


def boundaries():
    actual = read(boundary_book())
    assert actual == [
        record('A1', '5'),
        record('B1', '1', MASTER_21),
        record('C1', '2', 'SUM($A1:C$1)+"A1""B2"+1E10+TRUE+_xlfn.X(B1)+LOG10 (C$1)'),
        record('D1', '6', 'B1+1'),
        record('A2', '3', MASTER_22),
        record('B2', '4', 'SUM($A2:B$1)+"A1""B2"+1E10+TRUE+_xlfn.X(A2)+LOG10 (B$1)'),
        record('C2', '5', "'O''Brien'!C1+'A1 log'!D2+'Q1 log'!C$1+$B2"),
        record('D2', '7', 'SUM($A2:D$1)+"A1""B2"+1E10+TRUE+_xlfn.X(C2)+LOG10 (D$1)')]
    assert read(workbook(worksheet([
        (1, [cell('A1', '1', 'B2+C$3', 1, 'A1')])]))) == [record('A1', '1', 'B2+C$3')]
    # A formula without a cached value still emits its cell.
    assert read(workbook(worksheet([
        (1, [cell('B1', None, 'A1', 11, 'B1:B2')]),
        (2, [cell('B2', None, si=11)])]))) == [
            record('B1', None, 'A1'), record('B2', None, 'A2')]
    # si identity is numeric: "0007" in a follower matches master si=7.
    assert read(workbook(worksheet([
        (1, [cell('B1', '1', 'A1', 7, 'B1:B2')]),
        (2, [cell('B2', '2', si='0007')])]))) == [
            record('B1', '1', 'A1'), record('B2', '2', 'A2')]
    rejects(worksheet([(1, [cell('B1', '1', si=8)])]), 'MISSING_SHARED_DEFINITION')
    rejects(worksheet([(1, [cell('B1', '1', 'A1', 2, 'B1:B3')]),
                       (3, [cell('B3', '3', 'A3+1', 2, 'B1:B3')])]),
            'CONFLICTING_SHARED_DEFINITION')
    rejects(worksheet([(1, [cell('B1', '1', 'A1', 2, 'B1:B3')]),
                       (2, [cell('B2', '2', 'A1', 2, 'B1:B3')])]),
            'DUPLICATE_SHARED_DEFINITION')
    rejects(worksheet([(1, [cell('B1', '1', si=9)]),
                       (3, [cell('B3', '3', 'A3', 9, 'B2:B3')])]),
            'FOLLOWER_OUTSIDE_RANGE')
    rejects(worksheet([(1, [cell('A1', '1', 'B2', 5, 'A1:XFD2')]),
                       (2, [cell('XFD2', '2', si=5)])]),
            'REFERENCE_OUT_OF_GRID')
    rejects(worksheet([(3, [cell('A3', '2', si=6),
                            cell('C3', '1', 'B1', 6, 'A3:C3')])]),
            'REFERENCE_OUT_OF_GRID')
    rejects(worksheet([(2, [cell('B2', '1', 'A1', 3, 'B3:B1')])]),
            'BAD_SHARED_RANGE')
    rejects(worksheet([(2, [cell('B2', '1', 'A1', 3, 'A1:B1')])]),
            'MASTER_OUTSIDE_RANGE')
    rejects(worksheet([(1, [cell('B1', '1', 'A1', 3)])]), 'MISSING_SHARED_RANGE')
    rejects(worksheet([(1, [cell('B1', '1', 'A1', 3, 'B1:B2')]),
                       (2, [cell('B2', '2', None, 3, 'B1:B2')])]),
            'FOLLOWER_HAS_RANGE')
    rejects(worksheet([(1, [cell('B1', '1', 'A1', 'x', 'B1')])]), 'BAD_SHARED_ID')
    print('BOUNDARY_REGRESSION_OK')


class _LimitedReader:
    """Wrap a ZIP member so positive-size reads never exceed a fixed chunk."""

    def __init__(self, stream, chunk):
        self._stream = stream
        self._chunk = chunk

    def read(self, size=-1):
        if size is None or size < 0:
            return self._stream.read()
        return self._stream.read(min(size, self._chunk))

    def close(self):
        self._stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def chunked():
    original = zipfile.ZipFile.open
    limit = [4096]

    def opening(archive, name, mode='r', *args, **kwargs):
        return _LimitedReader(original(archive, name, mode, *args, **kwargs),
                              limit[0])

    books = [normal_book(), late_book(), lexical_book(), boundary_book()]
    try:
        reference = []
        for book in books:
            book.seek(0)
            reference.append(read(book))
        zipfile.ZipFile.open = opening
        for size in (1, 13, 4096, 16384, 200000):
            limit[0] = size
            for book, wanted in zip(books, reference):
                book.seek(0)
                assert read(book) == wanted, 'CHUNK_DEPENDENT_RESULT:%d' % size
    finally:
        zipfile.ZipFile.open = original
    print('ZIP_CHUNK_INVARIANCE_OK')


def disk_checks():
    with tempfile.TemporaryDirectory() as directory:
        source = os.path.join(directory, 'source.xlsx')
        target = os.path.join(directory, 'rows.jsonl')
        keep = os.path.join(directory, 'unrelated')
        with open(keep, 'w') as f:
            f.write('untouched')
        invalids = [
            worksheet([(1, [cell('B1', '1', si=8)])]),
            worksheet([(1, [cell('B1', '1', si=8)]),
                       (3, [cell('B3', '3', 'A3', 8, 'B2:B3')])]),
            worksheet([(1, [cell('B1', '1', 'A1', 2, 'B1:B3')]),
                       (3, [cell('B3', '3', 'A3+1', 2, 'B1:B3')])]),
            worksheet([(1, [cell('B1', '1', 'A1', 2, 'B1:B3')]),
                       (3, [cell('B3', '3', 'A1', 2, 'B1:B3')])]),
            worksheet([(1, [cell('A1', '1', 'B1', 5, 'A1:XFD2')]),
                       (2, [cell('XFD2', '2', si=5)])]),
            # Deep failure: thousands of valid rows are staged before the
            # follower at the end shifts a reference off the grid.
            worksheet([(r, [cell('B%d' % r, str(r))]) for r in range(1, 2001)]
                      + [(2001, [cell('C2001', '1', 'A1048576', 6, 'C2001:C2002')]),
                         (2002, [cell('C2002', '2', si=6)])])]
        for xml in invalids:
            with open(source, 'wb') as f:
                f.write(workbook(xml).getvalue())
            with open(target, 'w') as f:
                f.write('previous-result')
            try:
                ingest(source, 'Readings', target)
            except IngestError:
                pass
            else:
                raise AssertionError('INVALID_SHARED_GROUP_ACCEPTED')
            with open(target) as f:
                assert f.read() == 'previous-result', 'PARTIAL_PUBLICATION'
            assert sorted(os.listdir(directory)) == ['rows.jsonl', 'source.xlsx', 'unrelated']
        with open(source, 'wb') as f:
            f.write(late_book().getvalue())
        assert ingest(source, 'Readings', target) == 5
        with open(target) as f:
            assert [json.loads(line) for line in f] == read(late_book())
        with open(keep) as f:
            assert f.read() == 'untouched'
    print('PUBLICATION_REGRESSION_OK')


def resources():
    import tracemalloc
    import zipfile
    from xlsx_rows import MAIN
    measurements = []
    with tempfile.TemporaryDirectory() as directory:
        for size in (20000, 100000):
            source = os.path.join(directory, 'large.xlsx')
            target = os.path.join(directory, 'large.jsonl')
            with zipfile.ZipFile(workbook(worksheet([]))) as template:
                with zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED) as z:
                    for member in template.namelist():
                        if member != 'xl/worksheets/data.xml':
                            z.writestr(member, template.read(member))
                    with z.open('xl/worksheets/data.xml', 'w') as xml:
                        xml.write(('<worksheet xmlns="' + MAIN + '"><sheetData>').encode())
                        for r in range(1, size + 1):
                            f = ('<f t="shared" si="0" ref="B1:B%d">A%d+$A$1</f>' % (size, r)
                                 if r == size else '<f t="shared" si="0"/>')
                            xml.write(('<row r="%d"><c r="B%d">%s<v>%d</v></c></row>'
                                       % (r, r, f, r)).encode())
                        xml.write(b'</sheetData></worksheet>')
            tracemalloc.start()
            assert ingest(source, 'Readings', target) == size
            peak = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
            with open(target) as output:
                count = 0
                for count, line in enumerate(output, 1):
                    assert json.loads(line) == record('B' + str(count), str(count),
                                                     'A' + str(count) + '+$A$1')
                assert count == size
            assert sorted(os.listdir(directory)) == ['large.jsonl', 'large.xlsx']
            measurements.append(dict(rows=size, peak_bytes=peak))
    assert measurements[1]['peak_bytes'] <= measurements[0]['peak_bytes'] * 1.5 + 65536, \
        'MEMORY_GROWS_WITH_ROW_COUNT'
    print(json.dumps({'disk_resource_measurements': measurements}, sort_keys=True))


def demo():
    for label, source in [('late-master', late_book()), ('quoted-references', lexical_book())]:
        print(json.dumps({'sample': label, 'cells': read(source)}, ensure_ascii=False))


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'verify'
    if mode == 'normal':
        normal()
    elif mode == 'incident':
        raise SystemExit(incident())
    elif mode == 'verify':
        normal()
        if incident():
            raise SystemExit(1)
        boundaries()
        chunked()
        disk_checks()
        resources()
    elif mode == 'boundaries':
        boundaries()
    elif mode == 'chunked':
        chunked()
    elif mode == 'resources':
        resources()
    elif mode == 'demo':
        demo()
    else:
        raise SystemExit('unknown mode')
