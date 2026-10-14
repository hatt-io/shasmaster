"""Lossless prepared page storage, without PDF or extraction dependencies."""
import json
import lzma
import struct
from functools import lru_cache


def encode_page(page):
    from .compact_page import encode
    return encode(page)


@lru_cache(maxsize=1)
def _file_measurements(directory):
    return json.loads(lzma.decompress((directory/'measurements.json.xz').read_bytes()))


def read_page(path):
    content=path.read_bytes()
    return decode_page(content,_file_measurements(path.parent.parent) if content.startswith(b'SHAS3') else None)


def decode_page(content,shared_metrics=None):
    if content.startswith((b'SHAS2',b'SHAS3')):
        from .compact_page import decode
        return decode(content,shared_metrics)
    # Existing prepared releases remain readable during upgrades.
    unpacked = lzma.decompress(content)
    header_size = struct.unpack_from('<I', unpacked)[0]
    version, page, counts, glyph_count, columns = json.loads(unpacked[4:4+header_size])
    if version != 'shas-page-1':
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
