"""Draw correction previews from prepared font outlines, without source PDFs."""
from functools import lru_cache
from html import escape
from io import BytesIO
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from .config import CORPUS


@lru_cache(maxsize=64)
def font_template(fingerprint):
    if len(fingerprint) != 64 or any(char not in '0123456789abcdef' for char in fingerprint):
        raise ValueError('Invalid prepared font identifier')
    if CORPUS is None:
        raise ValueError('Prepared fonts unavailable')
    from .font_store import font_bytes
    return TTFont(BytesIO(font_bytes(fingerprint,template=True)), lazy=False)


def outline(fingerprint, glyph):
    font = font_template(fingerprint)
    order = font.getGlyphOrder()
    if not 0 <= glyph < len(order):
        raise ValueError('Unknown font glyph')
    glyph_set = font.getGlyphSet()
    pen = SVGPathPen(glyph_set)
    glyph_set[order[glyph]].draw(pen)
    return pen.getCommands(), font['head'].unitsPerEm


def nonprinting(fingerprint, glyph):
    path, _ = outline(fingerprint, glyph)
    return not path


def preview(geometry, bounds):
    left, top, right, bottom = bounds
    left -= .6;top -= .6;right += .6;bottom += .6
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{left} {top} {right-left} {bottom-top}" width="{(right-left)*6}" height="{(bottom-top)*6}">',
             f'<rect x="{left}" y="{top}" width="{right-left}" height="{bottom-top}" fill="white"/>']
    for word in geometry['words']:
        if word['r'] < left or word['x'] > right or word['bottom'] < top or word['top'] > bottom:
            continue
        for glyph in word.get('glyphs', []):
            path, units = outline(glyph['font'], glyph['glyph'])
            scale = glyph['size'] / units
            x = glyph.get('origin_x', glyph['x'])
            parts.append(f'<path d="{escape(path, quote=True)}" transform="translate({x} {glyph["baseline"]}) scale({scale} {-scale})"/>')
    parts.append('</svg>')
    return ''.join(parts).encode()
