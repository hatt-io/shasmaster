"""Load retained page text and apply user corrections without extraction imports."""
from collections import defaultdict
from contextlib import nullcontext
import gzip
import json
from .config import DATA, CORPUS
from .db import read

def load_geometry(page_id,connection=None,include_artwork=True):
    from .corrections import inactive_corrections
    with nullcontext(connection) if connection is not None else read() as conn:
        if connection is None:conn.execute('BEGIN')
        row=conn.execute('SELECT r.* FROM page p JOIN page_revision r ON r.id=p.active_revision WHERE p.id=?',(page_id,)).fetchone()
        if not row:raise KeyError(page_id)
        if CORPUS:
            from .prepared_content import page_geometry
            geometry=page_geometry(page_id)
        elif include_artwork:
            from .artwork import source_fragments
            geometry,_=source_fragments(row['geometry_path'],row['vector_path'])
        else:
            # Font/text operations need retained glyphs, not regenerated ink
            # fragments. Keep the same active-word and correction overlays.
            with gzip.open(DATA/row['geometry_path'],'rt',encoding='utf-8') as source:
                geometry=json.load(source)
        geometry['pdf']=f'/api/pages/{page_id}/pdf?revision={row["id"]}'
        active={r['id']:json.loads(r['geometry_json'])|{'reading_order':r['reading_order']} for r in conn.execute('SELECT id,geometry_json,reading_order FROM occurrence WHERE page_id=? AND page_revision=? AND active=1',(page_id,geometry['revision']))}
        mappings={(r['font_fingerprint'],r['glyph']):r['unicode'] for r in conn.execute('SELECT * FROM font_mapping')}
        regions={r['id']:dict(r) for r in conn.execute('SELECT * FROM region WHERE page_revision=?',(geometry['revision'],))}
        inactive=inactive_corrections(conn)
        corrections=[dict(r) for r in conn.execute('SELECT id,kind,payload_json FROM correction WHERE page_id=? ORDER BY created_at,rowid',(page_id,)) if r['id'] not in inactive]
    originals={word['id']:word for word in geometry['words']}
    # An unopened retained page still supplies its original geometry to optional
    # adjacent-page context. It need not acquire thousands of database rows.
    geometry['words']=([originals.get(wid,{})|saved for wid,saved in active.items()]
                       if active else list(originals.values()))
    for word in geometry['words']:
        for glyph in word.get('glyphs',[]):
            if (glyph['font'],glyph['glyph']) in mappings:
                glyph['text']=mappings[glyph['font'],glyph['glyph']];glyph['mapping']='correction';glyph['unresolved']=False
    artwork_regions={line['region'] for line in geometry['lines'] if line.get('source')=='artwork'}
    retained_regions=[region for region in geometry['regions'] if region['id'] in artwork_regions and region['id'] not in regions]
    used_regions={word['region'] for word in geometry['words']}|artwork_regions
    if regions:
        geometry['regions']=[{'id':rid,'kind':saved['kind'],'bounds':json.loads(saved['bounds_json']),'reading_order':saved['reading_order']} for rid,saved in regions.items() if rid in used_regions]+retained_regions
    line_map={line['id']:line for line in geometry['lines']}
    words_by_line=defaultdict(list)
    line_regions={}
    for word in geometry['words']:
        words_by_line[word['line']].append(word['id']);line_regions[word['line']]=word['region']
    for line in geometry['lines']:
        line['words']=words_by_line[line['id']]
        line['region']=line_regions.get(line['id'],line['region'])
    for correction in corrections:
        payload=json.loads(correction['payload_json'])
        if correction['kind']=='line' and payload.get('id') in line_map:
            line=line_map[payload['id']]
            for key in ('x','r','top','bottom','baseline','reading_order'):
                if key in payload:line[key]=float(payload[key])
    return geometry
