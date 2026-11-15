import re
from errors import IngestError

CELL = re.compile(r'([A-Z]{1,3})([1-9][0-9]*)\Z')
CELL_REF = re.compile(r'(\$?)([A-Z]{1,3})(\$?)([1-9][0-9]*)')
IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_.]*\Z')
SHEET_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
COLUMN_MAX = 16384
ROW_MAX = 1048576


def column_number(text):
    number = 0
    for char in text:
        number = number * 26 + ord(char) - 64
    return number


def position(address):
    match = CELL.fullmatch(address)
    if not match:
        raise IngestError('BAD_CELL:' + address)
    column = column_number(match[1])
    row = int(match[2])
    if column > COLUMN_MAX or row > ROW_MAX:
        raise IngestError('BAD_CELL:' + address)
    return row, column


def letters(column):
    if not 1 <= column <= COLUMN_MAX:
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


def _escaped_end(text, start, quote):
    """Return the index just past a quoted token; doubled quotes are escapes."""
    index = start + 1
    length = len(text)
    while index < length:
        if text[index] == quote:
            if index + 1 < length and text[index + 1] == quote:
                index += 2
                continue
            return index + 1
        index += 1
    return length


def _number_end(text, start):
    """Consume a numeric literal, including decimals and scientific notation."""
    index = start
    length = len(text)
    while index < length and text[index].isdigit():
        index += 1
    if index < length and text[index] == '.':
        index += 1
        while index < length and text[index].isdigit():
            index += 1
    if index < length and text[index] in 'Ee':
        candidate = index + 1
        if candidate < length and text[candidate] in '+-':
            candidate += 1
        digits = candidate
        while candidate < length and text[candidate].isdigit():
            candidate += 1
        if candidate > digits:
            index = candidate
    return index


def _cell_at(text, index):
    """Match one reference cell at index, requiring a token boundary after it."""
    match = CELL_REF.match(text, index)
    if match is None:
        return None
    end = match.end()
    if end < len(text):
        following = text[end]
        if following.isascii() and (following.isalnum() or following in '_$.'):
            return None
    return match, end


def _shifted(match, row_delta, column_delta):
    column_mark, column_text, row_mark, row_text = match.groups()
    old_row, old_column = position(column_text + row_text)
    column = old_column + (0 if column_mark else column_delta)
    row = old_row + (0 if row_mark else row_delta)
    if not (1 <= column <= COLUMN_MAX and 1 <= row <= ROW_MAX):
        raise IngestError('REFERENCE_OUT_OF_GRID')
    return column_mark + letters(column) + row_mark + str(row)


def _followed_by_paren(text, index):
    length = len(text)
    while index < length and text[index].isspace():
        index += 1
    return index < length and text[index] == '('


def translate(text, anchor, target):
    """Shift relative references from anchor to target, leaving all else verbatim.

    The scan is lexical: quoted strings, quoted sheet names, function names and
    numeric literals are copied untouched, so coordinate-shaped text inside them
    is never rewritten.
    """
    if anchor == target:
        return text
    anchor_row, anchor_column = position(anchor)
    target_row, target_column = position(target)
    row_delta = target_row - anchor_row
    column_delta = target_column - anchor_column
    pieces = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == '"':
            end = _escaped_end(text, index, '"')
            pieces.append(text[index:end])
            index = end
        elif char == "'":
            end = _escaped_end(text, index, "'")
            pieces.append(text[index:end])
            index = end
            if index < length and text[index] == '!':
                pieces.append('!')
                index += 1
                found = _cell_at(text, index)
                if found is not None:
                    match, index = found
                    pieces.append(_shifted(match, row_delta, column_delta))
        elif char == '$':
            found = _cell_at(text, index)
            if found is None:
                pieces.append(char)
                index += 1
            else:
                match, index = found
                pieces.append(_shifted(match, row_delta, column_delta))
        elif char.isascii() and (char.isalpha() or char == '_'):
            end = index + 1
            while (end < length and text[end].isascii()
                   and (text[end].isalnum() or text[end] == '_')):
                end += 1
            # Dotted function names (e.g. _xlfn.X) are single tokens; keeping
            # the suffix attached prevents its tail from being shifted.
            if end < length and text[end] == '.':
                while end < length and text[end] == '.':
                    following = end + 1
                    while (following < length and text[following].isascii()
                           and (text[following].isalnum()
                                or text[following] == '_')):
                        following += 1
                    if following == end + 1:
                        break
                    end = following
            token = text[index:end]
            if end < length and text[end] == '!' and SHEET_NAME.fullmatch(token):
                pieces.append(token)
                pieces.append('!')
                index = end + 1
                found = _cell_at(text, index)
                if found is not None:
                    match, index = found
                    pieces.append(_shifted(match, row_delta, column_delta))
                continue
            if IDENTIFIER.fullmatch(token) and _followed_by_paren(text, end):
                pieces.append(token)
                index = end
                continue
            # The scan consumes identifier characters only up to '$' or '.',
            # so re-match from the token start to catch anchored references
            # such as A$1 while leaving dotted names like B2.C3 alone.
            found = _cell_at(text, index)
            if found is not None:
                match, index = found
                pieces.append(_shifted(match, row_delta, column_delta))
            else:
                pieces.append(token)
                index = end
        elif char.isascii() and char.isdigit():
            end = _number_end(text, index)
            pieces.append(text[index:end])
            index = end
        else:
            pieces.append(char)
            index += 1
    return ''.join(pieces)


class SharedFormulas:
    def __init__(self):
        self.definitions = {}
        self.used = set()

    @staticmethod
    def _shared_id(si):
        if not isinstance(si, str) or not si.isascii() or not si.isdecimal():
            raise IngestError('BAD_SHARED_ID')
        return int(si)

    def register(self, cell):
        """First pass: record master definitions; no follower is resolved yet."""
        formula = cell['f']
        if formula is None or formula['t'] != 'shared':
            return
        si = self._shared_id(formula['si'])
        text, ref = formula['text'], formula['ref']
        if not text:
            if ref is not None:
                raise IngestError('FOLLOWER_HAS_RANGE')
            return
        if ref is None:
            raise IngestError('MISSING_SHARED_RANGE')
        bounds = rectangle(ref)
        if not contains(bounds, cell['coord']):
            raise IngestError('MASTER_OUTSIDE_RANGE')
        definition = (cell['coord'], text, bounds)
        previous = self.definitions.get(si)
        if previous is not None:
            # Any second master for a group is rejected; identical
            # text/range at another coordinate is a duplicate, else a conflict.
            if previous[1] == text and previous[2] == bounds:
                raise IngestError('DUPLICATE_SHARED_DEFINITION')
            raise IngestError('CONFLICTING_SHARED_DEFINITION')
        if len(self.definitions) >= 4096:
            raise IngestError('TOO_MANY_SHARED_GROUPS')
        self.definitions[si] = definition

    def resolve(self, cell):
        """Second pass: translate against the complete definition table."""
        formula = cell['f']
        if formula is None:
            return None
        if formula['t'] == 'normal':
            return formula['text']
        si = self._shared_id(formula['si'])
        self.used.add(si)
        if len(self.used) > 4096:
            raise IngestError('TOO_MANY_SHARED_GROUPS')
        definition = self.definitions.get(si)
        if definition is None:
            raise IngestError('MISSING_SHARED_DEFINITION')
        anchor, text, bounds = definition
        if not contains(bounds, cell['coord']):
            raise IngestError('FOLLOWER_OUTSIDE_RANGE')
        return translate(text, anchor, cell['coord'])

    def finish(self):
        if self.used - self.definitions.keys():
            raise IngestError('MISSING_SHARED_DEFINITION')
