"""Serve the retained printed fonts as browser fonts, without image fragments."""
from functools import lru_cache
from collections import OrderedDict
from io import BytesIO
import hashlib
import json
import pymupdf

from fontTools.fontBuilder import FontBuilder
from fontTools.ttLib import TTFont
from fontTools.cffLib import CFFFontSet
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.t2CharStringPen import T2CharStringPen

from .config import DATA
from .extract import ttf_glyphs
from .extract import cff_glyphs


@lru_cache(maxsize=512)
def glyph_signature(data, extension, glyph):
    from fontTools.pens.recordingPen import DecomposingRecordingPen
    if extension == 'cff':
        cff=CFFFontSet();cff.decompile(BytesIO(data),None);top=cff[cff.fontNames[0]]
        glyph_set=top.CharStrings;name=top.charset[glyph];units=1/top.FontMatrix[0]
    else:
        font=TTFont(BytesIO(data));order=font.getGlyphOrder()
        if 'glyf' in font:
            info=ttf_glyphs(data)
            FontBuilder(font=font).setupHorizontalMetrics({name:(info[i]['advance'] or 0,
                info[i]['bounds'][0] if info[i].get('bounds') else 0) for i,name in enumerate(order)})
        glyph_set=font.getGlyphSet();name=order[glyph];units=font['head'].unitsPerEm
    pen=DecomposingRecordingPen(glyph_set);glyph_set[name].draw(pen)
    return tuple((operation,tuple(None if point is None else tuple(round(value/units,8) for value in point) for point in points)) for operation,points in pen.value)


def resolve_outline_fonts(geometry, asset_path, unresolved, available):
    """Use the PDF's actual drawn outlines when subset names are ambiguous."""
    import re
    import xml.etree.ElementTree as ET
    from fontTools.svgLib.path import parse_path
    from fontTools.pens.transformPen import TransformPen
    with pymupdf.open(DATA/asset_path) as document:
        root=ET.fromstring(document[0].get_svg_image(text_as_path=True))
    paths={node.get('id'):node.get('d','') for node in root.iter() if node.tag.endswith('}path') and node.get('id')}
    uses=[]
    for node in root.iter():
        if not node.tag.endswith('}use'):continue
        reference=node.get('{http://www.w3.org/1999/xlink}href','').lstrip('#')
        transform=re.fullmatch(r'matrix\(([^)]+)\)',node.get('transform',''))
        if not transform or reference not in paths:continue
        values=[float(value) for value in re.split(r'[,\s]+',transform[1].strip())]
        if len(values)==6 and abs(values[1])+abs(values[2])<1e-8:
            uses.append((values[4],values[5],reference))
    groups={}
    for glyph in unresolved:
        x=glyph.get('origin_x',glyph['x']);y=glyph['baseline']
        matches={reference for sx,sy,reference in uses if abs(sx-x)<.001 and abs(sy-y)<.001}
        if len(matches)!=1:raise ValueError(f'Printed font outline is not unique on {geometry["id"]}')
        reference=matches.pop();prefix,number=reference.rsplit('_',1)
        groups.setdefault(prefix,[]).append((glyph,int(number)))
    for prefix, members in groups.items():
        shapes={int(key.rsplit('_',1)[1]):value for key,value in paths.items() if key.startswith(prefix+'_')}
        maximum=max(shapes)
        order=['.notdef']+[f'g{number}' for number in range(1,maximum+1)]
        widths={gid:(glyph['r']-glyph['x'])/glyph['size']*1000 for glyph,gid in members}
        strings={};metrics={}
        for gid,name in enumerate(order):
            width=widths.get(gid,1000)
            pen=T2CharStringPen(width,None)
            if shapes.get(gid):parse_path(shapes[gid],TransformPen(pen,(1000,0,0,1000,0,0)))
            strings[name]=pen.getCharString();metrics[name]=(round(width),0)
        builder=FontBuilder(1000,isTTF=False);builder.setupGlyphOrder(order)
        builder.setupCFF('ShasSourceOutline',{},strings,{})
        builder.setupHorizontalMetrics(metrics);builder.setupHorizontalHeader(ascent=1000,descent=0)
        builder.setupCharacterMap({})
        builder.setupNameTable({'familyName':'ShasSourceOutline','styleName':'Regular','psName':'ShasSourceOutline','fullName':'ShasSourceOutline'})
        builder.setupOS2(sTypoAscender=1000,sTypoDescender=0,usWinAscent=1000,usWinDescent=0);builder.setupPost()
        output=BytesIO();builder.save(output);data=output.getvalue()
        fingerprint=hashlib.sha256(data).hexdigest();available[fingerprint]=('otf',data)
        for glyph,gid in members:
            glyph['source_font']=glyph['font'];glyph['source_glyph']=glyph['glyph']
            glyph['font']=fingerprint;glyph['glyph']=gid


def resolve_font_sources(geometry, asset_path):
    """Resolve PDF standard fonts and ambiguous subsets by source positions."""
    available = embedded_fonts(asset_path)
    missing = {g['font'] for w in geometry['words'] for g in w.get('glyphs', [])
               if not available.get(g['font'], ('', b''))[1]}
    if not missing:
        return
    with pymupdf.open(DATA / asset_path) as document:
        page = document[0]
        by_name = {}
        for record in page.get_fonts(full=True):
            _, extension, _, data = document.extract_font(record[0])
            if not data:
                data = pymupdf.Font(fontname=record[3]).buffer
                extension = 'otf' if data[:4] == b'OTTO' else 'ttf' if data[:4] in (b'\0\1\0\0', b'ttcf') else 'cff'
            fingerprint = hashlib.sha256(data).hexdigest()
            available[fingerprint] = (extension, data)
            for name in {record[3], record[3].split('+')[-1]}:
                by_name.setdefault(name, set()).add(fingerprint)
        positions = {}
        diagnostics = {}
        for span in page.get_texttrace():
            if span['type'] == 3:
                continue
            candidates = by_name.get(span['font'], set()) or by_name.get(span['font'].split('+')[-1], set())
            for _, gid, origin, box in span['chars']:
                matches = []
                for fingerprint in candidates:
                    extension, data = available[fingerprint]
                    metrics = (cff_glyphs(data) if extension == 'cff' else ttf_glyphs(data)).get(gid)
                    if metrics and metrics.get('advance') is not None:
                        difference = abs(metrics['advance'] / metrics['units'] * span['size'] - (box[2] - box[0]))
                        matches.append((difference, fingerprint))
                matches.sort()
                if len(candidates) == 1:
                    selected = next(iter(candidates))
                elif matches and matches[0][0] < .001 and (len(matches) == 1 or matches[1][0] - matches[0][0] > .001):
                    selected = matches[0][1]
                else:
                    tied=[fingerprint for difference,fingerprint in matches if difference < .001]
                    signatures={glyph_signature(available[fingerprint][1],available[fingerprint][0],gid) for fingerprint in tied}
                    if tied and len(signatures)==1:
                        # Identical outlines in overlapping subsets are the same
                        # printed glyph; either subset preserves its appearance.
                        selected=tied[0]
                    else:
                        diagnostics[(round(origin[0],5),round(origin[1],5),gid)]={
                            'font':span['font'],'candidate_count':len(candidates),'width_differences':[round(item[0],6) for item in matches],
                            'outline_variants':len(signatures)}
                        continue
                positions[(round(origin[0], 5), round(origin[1], 5), gid)] = selected
    unresolved=[]
    for word in geometry['words']:
        for glyph in word.get('glyphs', []):
            if glyph['font'] not in missing:
                continue
            key = (round(glyph.get('origin_x', glyph['x']), 5), round(glyph['baseline'], 5), glyph['glyph'])
            if key not in positions:
                unresolved.append(glyph)
            else:
                glyph['font'] = positions[key]
    if unresolved:resolve_outline_fonts(geometry,asset_path,unresolved,available)

@lru_cache(maxsize=4)
def embedded_fonts(asset_path):
    with pymupdf.open(DATA / asset_path) as document:
        result = {}
        for record in document[0].get_fonts(full=True):
            _, extension, _, data = document.extract_font(record[0])
            result[hashlib.sha256(data).hexdigest()] = (extension,data)
        return result

@lru_cache(maxsize=256)
def browser_font(asset_path, fingerprint, mapping_json):
    extension, data = embedded_fonts(asset_path).get(fingerprint, ('',b''))
    if not data:
        raise ValueError(f'Original font unavailable: {asset_path}; {fingerprint}')
    mapping = json.loads(mapping_json)
    if extension == 'cff':
        cff = CFFFontSet()
        cff.decompile(BytesIO(data), None)
        top = cff[cff.fontNames[0]]
        units = round(1 / top.FontMatrix[0])
        order = top.charset
        builder = FontBuilder(units, isTTF=False)
        builder.setupGlyphOrder(order)
        metrics, strings = {}, {}
        for name in order:
            original = top.CharStrings[name]
            bounds = BoundsPen(top.CharStrings)
            original.draw(bounds)
            width = original.width
            pen = T2CharStringPen(width, top.CharStrings)
            original.draw(pen)
            strings[name] = pen.getCharString()
            metrics[name] = (width, bounds.bounds[0] if bounds.bounds else 0)
        builder.setupCFF('ShasSource', {}, strings, {})
        builder.setupHorizontalMetrics(metrics)
        builder.setupHorizontalHeader(ascent=units, descent=0)
        builder.setupNameTable({'familyName':'ShasSource','styleName':'Regular',
                               'psName':'ShasSource','fullName':'ShasSource'})
        builder.setupPost()
    elif extension in ('ttf', 'otf'):
        font = TTFont(BytesIO(data))
        units = font['head'].unitsPerEm
        order = font.getGlyphOrder()
        builder = FontBuilder(font=font)
        # PDF subsets may omit trailing bearings; restore the metrics table
        # from the retained advances and original outline bounds.
        if 'glyf' in font:
            info = ttf_glyphs(data)
            builder.setupHorizontalMetrics({name:(info[i]['advance'] or 0,
                info[i]['bounds'][0] if info[i].get('bounds') else 0)
                for i,name in enumerate(order)})
        for tag in ('GSUB','GPOS','kern'):
            if tag in font:del font[tag]
    else:
        raise ValueError('Unsupported original font: '+extension)
    cmap = {int(cp):order[gid] for cp,gid in mapping if 0 <= gid < len(order)}
    builder.setupCharacterMap(cmap)
    builder.setupOS2(sTypoAscender=units, sTypoDescender=0,
                     usWinAscent=units, usWinDescent=0)
    output = BytesIO()
    builder.save(output)
    return output.getvalue()
