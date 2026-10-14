"""Lossless prepared page storage, without PDF or extraction dependencies."""
import json
import lzma
import struct

FORMAT = 'shas-page-1'


def encode_page(page):
    # Store numeric columns as binary doubles. This preserves the source values
    # without repeating long decimal strings or field names for every letter.
    words = []
    glyphs = []
    counts = []
    for original in page['words']:
        word = dict(original)
        items = word.pop('glyphs', None)
        counts.append(None if items is None else len(items))
        glyphs.extend(items or [])
        words.append(word)
    fields = sorted({key for glyph in glyphs for key in glyph})
    columns = []
    binary = bytearray()
    for field in fields:
        positions = [index for index, glyph in enumerate(glyphs) if field in glyph]
        values = [glyphs[index][field] for index in positions]
        present = None if len(positions) == len(glyphs) else positions
        if values and all(type(value) is float for value in values):
            offset = len(binary)
            binary.extend(struct.pack('<' + 'd' * len(values), *values))
            columns.append([field, present, 'double', [offset, len(values)]])
        else:
            columns.append([field, present, 'json', values])
    header = json.dumps([FORMAT, dict(page, words=words), counts, len(glyphs), columns],
                        ensure_ascii=False, separators=(',', ':')).encode()
    return lzma.compress(struct.pack('<I', len(header)) + header + binary, preset=0)


def decode_page(content):
    unpacked = lzma.decompress(content)
    header_size = struct.unpack_from('<I', unpacked)[0]
    version, page, counts, glyph_count, columns = json.loads(unpacked[4:4+header_size])
    if version != FORMAT:
        raise ValueError('Unsupported prepared page format')
    binary = memoryview(unpacked)[4+header_size:]
    glyphs = [{} for _ in range(glyph_count)]
    for field, positions, kind, values in columns:
        if kind == 'double':
            offset, count = values
            values = struct.unpack_from('<' + 'd' * count, binary, offset)
        elif kind != 'json':
            raise ValueError('Unsupported prepared column format')
        for index, value in zip(range(glyph_count) if positions is None else positions, values, strict=True):
            glyphs[index][field] = value
    cursor = 0
    for word, count in zip(page['words'], counts, strict=True):
        if count is not None:
            word['glyphs'] = glyphs[cursor:cursor+count]
            cursor += count
    if cursor != glyph_count:
        raise ValueError('Invalid prepared glyph count')
    return page
