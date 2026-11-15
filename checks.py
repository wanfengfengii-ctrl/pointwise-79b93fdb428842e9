import io
import json
import os
import sys
import tempfile
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
                       (3, [cell('B3', '3', 'A3+1', 2, 'B1:B3')])])]
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
        disk_checks()
        resources()
    elif mode == 'resources':
        resources()
    elif mode == 'demo':
        demo()
    else:
        raise SystemExit('unknown mode')
