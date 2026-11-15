import re
from errors import IngestError

CELL = re.compile(r'([A-Z]{1,3})([1-9][0-9]*)\Z')
REFERENCE = re.compile(r'(\$?)([A-Z]{1,3})(\$?)([1-9][0-9]*)')


def position(address):
    match = CELL.fullmatch(address)
    if not match:
        raise IngestError('BAD_CELL:' + address)
    column = 0
    for char in match[1]:
        column = column * 26 + ord(char) - 64
    row = int(match[2])
    if column > 16384 or row > 1048576:
        raise IngestError('BAD_CELL:' + address)
    return row, column


def letters(column):
    if not 1 <= column <= 16384:
        raise IngestError('REFERENCE_OUT_OF_GRID')
    result = ''
    while column:
        column, digit = divmod(column - 1, 26)
        result = chr(65 + digit) + result
    return result


def rectangle(text):
    ends = text.split(':')
    if len(ends) == 1:
        ends *= 2
    if len(ends) != 2:
        raise IngestError('BAD_SHARED_RANGE')
    a, b = map(position, ends)
    if a[0] > b[0] or a[1] > b[1]:
        raise IngestError('BAD_SHARED_RANGE')
    return a, b


def contains(bounds, coord):
    (r1, c1), (r2, c2) = bounds
    r, c = position(coord)
    return r1 <= r <= r2 and c1 <= c <= c2


def translate(text, anchor, target):
    ar, ac = position(anchor)
    tr, tc = position(target)

    def replace(match):
        ca, column, ra, row = match.groups()
        _, number = position(column + row)
        number += 0 if ca else tc - ac
        shifted = int(row) + (0 if ra else tr - ar)
        if not 1 <= shifted <= 1048576:
            raise IngestError('REFERENCE_OUT_OF_GRID')
        return ca + letters(number) + ra + str(shifted)

    return REFERENCE.sub(replace, text)


class SharedFormulas:
    def __init__(self):
        self.definitions = {}
        self.used = set()

    def resolve(self, cell):
        formula = cell['f']
        if formula is None:
            return None
        if formula['t'] == 'normal':
            return formula['text']
        si = formula['si']
        if not isinstance(si, str) or not si.isascii() or not si.isdecimal():
            raise IngestError('BAD_SHARED_ID')
        si = int(si)
        self.used.add(si)
        if len(self.used) > 4096:
            raise IngestError('TOO_MANY_SHARED_GROUPS')
        text, ref = formula['text'], formula['ref']
        if text:
            if ref is None:
                raise IngestError('MISSING_SHARED_RANGE')
            bounds = rectangle(ref)
            if not contains(bounds, cell['coord']):
                raise IngestError('MASTER_OUTSIDE_RANGE')
            definition = (cell['coord'], text, bounds)
            previous = self.definitions.get(si)
            if previous is not None and previous != definition:
                raise IngestError('CONFLICTING_SHARED_DEFINITION')
            self.definitions[si] = definition
        elif ref is not None:
            raise IngestError('FOLLOWER_HAS_RANGE')
        definition = self.definitions.get(si)
        if definition is None:
            return None
        anchor, text, bounds = definition
        if not contains(bounds, cell['coord']):
            raise IngestError('FOLLOWER_OUTSIDE_RANGE')
        return translate(text, anchor, cell['coord'])

    def finish(self):
        if self.used - self.definitions.keys():
            raise IngestError('MISSING_SHARED_DEFINITION')
