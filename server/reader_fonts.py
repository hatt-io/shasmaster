"""Use prebuilt browser fonts; source conversion is development-only."""
from functools import lru_cache
from collections import OrderedDict
from io import BytesIO
import hashlib
import json
from .config import CORPUS

font_requests = OrderedDict()

@lru_cache(maxsize=256)
def browser_font(asset_path, fingerprint, mapping_json):
    if CORPUS is None:
        from .prepare_fonts import browser_font as convert_font
        return convert_font(asset_path, fingerprint, mapping_json)
    key = hashlib.sha256((fingerprint + mapping_json).encode()).hexdigest()
    from .font_store import font_bytes
    try:
        return font_bytes(key)
    except FileNotFoundError:
        pass
    # User font corrections may require another Unicode map. Reuse the prepared
    # glyph outlines, never the PDF, and keep the result in bounded memory.
    from fontTools.ttLib import TTFont
    from fontTools.fontBuilder import FontBuilder
    font = TTFont(BytesIO(font_bytes(fingerprint,template=True)))
    order = font.getGlyphOrder()
    FontBuilder(font=font).setupCharacterMap({int(cp):order[gid] for cp,gid in json.loads(mapping_json) if 0 <= gid < len(order)})
    output = BytesIO()
    font.save(output);font.close()
    return output.getvalue()


def attach_fonts(geometry, asset_path):
    """Keep original Unicode text, type size, baseline and font per glyph."""
    mappings = {}
    for word in geometry['words']:
        for glyph in word.get('glyphs', []):
            text = glyph.get('text','')
            if len(text) == 1:
                mappings.setdefault(glyph['font'], {}).setdefault(ord(text), glyph['glyph'])
    fonts = []
    for fingerprint, mapping in mappings.items():
        encoded = json.dumps(sorted(mapping.items()), separators=(',',':'))
        key = hashlib.sha256((fingerprint+encoded).encode()).hexdigest()
        fonts.append({'id':key, 'fingerprint':fingerprint, 'mapping':encoded})
        font_requests[key] = (asset_path,fingerprint,encoded)
        font_requests.move_to_end(key)
        while len(font_requests)>512:font_requests.popitem(last=False)
    by_fingerprint = {font['fingerprint']:font['id'] for font in fonts}
    lines = {line['id']:line for line in geometry['lines']}
    for word in geometry['words']:
        line = lines[word['line']]
        glyphs = sorted(word.get('glyphs',[]), key=lambda g:g['x'],
                        reverse=any('א'<=c<='ת' for c in word['text']))
        word['size'] = line['size']
        word['baseline'] = line['baseline']
        if glyphs:
            word['font'] = by_fingerprint.get(glyphs[0]['font'])
        if ''.join(g.get('text','') for g in glyphs) == word['text']:
            word['source_glyphs'] = [{'text':g['text'], 'x':g.get('origin_x',g['x']),
                'baseline':g['baseline'], 'size':g['size'],
                'font':by_fingerprint.get(g['font'])} for g in glyphs]
    geometry['fonts'] = [{'id':f['id'], 'url':f'/api/pages/{geometry["id"]}/fonts/{f["id"]}'} for f in fonts]
    return fonts
