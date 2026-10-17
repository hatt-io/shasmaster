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
    mapping = json.loads(mapping_json)
    if CORPUS is None:
        from .prepare_fonts import browser_font as convert_font
        content = convert_font(asset_path, fingerprint, mapping_json)
    else:
        key = hashlib.sha256((fingerprint + mapping_json).encode()).hexdigest()
        from .font_store import font_bytes
        try:
            content = font_bytes(key)
        except FileNotFoundError:
            content = None
    if content is not None and not any(gid == 0 for _, gid in mapping):
        return content
    # User font corrections may require another Unicode map. Reuse the prepared
    # glyph outlines, never the PDF, and keep the result in bounded memory.
    from fontTools.ttLib import TTFont
    from fontTools.fontBuilder import FontBuilder
    font = TTFont(BytesIO(content if content is not None else font_bytes(fingerprint,template=True)))
    order = font.getGlyphOrder()
    cmap = {int(cp):order[gid] for cp,gid in mapping if 0 <= gid < len(order)}
    if any(gid == 0 for _, gid in mapping):
        # Browsers treat cmap glyph zero as missing, even when the PDF drew its
        # outline. Alias that exact outline to an ordinary, nonzero glyph so
        # fallback fonts cannot replace it with a differently sized symbol.
        alias = 'sourceGlyphZero'
        metrics = font['hmtx'].metrics[order[0]]
        if 'glyf' in font:
            from copy import deepcopy
            font['glyf'].glyphs[alias] = deepcopy(font['glyf'][order[0]])
        else:
            from fontTools.pens.t2CharStringPen import T2CharStringPen
            cff = font['CFF '].cff
            top = cff[cff.fontNames[0]]
            pen = T2CharStringPen(metrics[0], None)
            top.CharStrings[order[0]].draw(pen)
            strings = top.CharStrings
            strings.charStrings[alias] = len(strings.charStringsIndex)
            strings.charStringsIndex.append(pen.getCharString(private=top.Private, globalSubrs=cff.GlobalSubrs))
            top.charset = order + [alias]
        font.setGlyphOrder(order + [alias])
        font['maxp'].numGlyphs = len(order) + 1
        font['hmtx'].metrics[alias] = metrics
        cmap.update({int(cp):alias for cp,gid in mapping if gid == 0})
    FontBuilder(font=font).setupCharacterMap(cmap)
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
    variants = {}
    for fingerprint, mapping in mappings.items():
        encoded = json.dumps(sorted(mapping.items()), separators=(',',':'))
        key = hashlib.sha256((fingerprint+encoded).encode()).hexdigest()
        fonts.append({'id':key, 'fingerprint':fingerprint, 'mapping':encoded})
        font_requests[key] = (asset_path,fingerprint,encoded)
        font_requests.move_to_end(key)
        while len(font_requests)>512:font_requests.popitem(last=False)
    # A PDF subset can contain several outlines for the same Unicode letter.
    # Keep Unicode selectable, but give each alternate outline its own cmap.
    for word in geometry['words']:
        for glyph in word.get('glyphs', []):
            text = glyph.get('text', '')
            fingerprint = glyph['font']
            if len(text) != 1 or mappings[fingerprint][ord(text)] == glyph['glyph']:
                continue
            variant = (fingerprint, ord(text), glyph['glyph'])
            if variant in variants:
                continue
            mapping = mappings[fingerprint] | {ord(text): glyph['glyph']}
            encoded = json.dumps(sorted(mapping.items()), separators=(',', ':'))
            key = hashlib.sha256((fingerprint + encoded).encode()).hexdigest()
            variants[variant] = key
            fonts.append({'id': key, 'fingerprint': fingerprint, 'mapping': encoded})
            font_requests[key] = (asset_path, fingerprint, encoded)
            font_requests.move_to_end(key)
            while len(font_requests) > 512:
                font_requests.popitem(last=False)
    by_fingerprint = {}
    for font in fonts:
        by_fingerprint.setdefault(font['fingerprint'], font['id'])
    lines = {line['id']:line for line in geometry['lines']}
    for word in geometry['words']:
        line = lines[word['line']]
        glyphs = sorted(word.get('glyphs',[]), key=lambda g:g['x'],
                        reverse=any('א'<=c<='ת' for c in word['text']))
        if ''.join(g.get('text', '') for g in glyphs) != word['text']:
            # Equal-x glyphs keep their extraction order under reverse=True.
            # The retained RTL text instead reverses the full source sequence.
            source_order = list(reversed(sorted(word.get('glyphs', []), key=lambda g:g['x'])))
            if ''.join(g.get('text', '') for g in source_order) == word['text']:
                glyphs = source_order
        word['size'] = line['size']
        word['baseline'] = line['baseline']
        if glyphs:
            word['font'] = by_fingerprint.get(glyphs[0]['font'])
        if ''.join(g.get('text','') for g in glyphs) == word['text']:
            word['source_glyphs'] = [{'text':g['text'], 'x':g.get('origin_x',g['x']),
                'baseline':g['baseline'], 'size':g['size'],
                'font':variants.get((g['font'], ord(g['text']), g['glyph']), by_fingerprint.get(g['font']))
                    if len(g['text']) == 1 else by_fingerprint.get(g['font'])} for g in glyphs]
    geometry['fonts'] = [{'id':f['id'], 'url':f'/api/pages/{geometry["id"]}/fonts/{f["id"]}'} for f in fonts]
    return fonts
