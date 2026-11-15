import argparse
import json
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from errors import IngestError
from formulas import SharedFormulas
from xlsx_rows import rows, sheet_member


def extract(source, sheet, sink):
    """Internal streaming worker; sink is private until ingest commits.

    The worksheet is read twice on the same open stream: the first pass indexes
    shared-formula masters (a master may appear after its followers), the second
    pass resolves and emits rows in the original order.  Only the shared
    definition table persists between passes; rows are never retained.
    """
    try:
        with zipfile.ZipFile(source) as archive:
            member = sheet_member(archive, sheet)
            registry = SharedFormulas()
            for row in rows(archive, member):
                for cell in row:
                    registry.register(cell)
            count = 0
            for row in rows(archive, member):
                for cell in row:
                    formula = registry.resolve(cell)
                    record = dict(coord=cell['coord'], type=cell['type'],
                                  cache=cell['cache'], formula=formula)
                    sink.write(json.dumps(record, ensure_ascii=False) + '\n')
                    count += 1
            registry.finish()
            return count
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError) as error:
        raise IngestError('INVALID_WORKBOOK:' + str(error)) from error


def ingest(path, sheet, output_path):
    """Publish a complete JSONL file, preserving any previous target on failure."""
    destination = os.path.abspath(os.fspath(output_path))
    parent = os.path.dirname(destination)
    temporary = None
    try:
        with open(path, 'rb') as source:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                             newline='\n', dir=parent,
                                             prefix='.xlsx-ingest-', delete=False) as sink:
                temporary = sink.name
                count = extract(source, sheet, sink)
        os.replace(temporary, destination)
        temporary = None
        return count
    finally:
        if temporary is not None:
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('path')
    parser.add_argument('sheet')
    parser.add_argument('output')
    args = parser.parse_args()
    try:
        count = ingest(args.path, args.sheet, args.output)
    except IngestError as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({'cells': count}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
