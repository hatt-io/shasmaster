import json
import math
import unicodedata
from .db import json_text
from .text import normalize


class CorrectionConflict(ValueError):
    pass


def number(value):
    value=float(value)
    if not math.isfinite(value):raise ValueError('Invalid coordinate')
    return value


def apply_correction(conn,page_id,base_revision,kind,item,correction_id,created_at=None,replay=False):
    from .page_geometry import load_geometry
    previous=conn.execute('SELECT * FROM correction WHERE id=?',(correction_id,)).fetchone()
    if previous:
        same_source=False
        if replay:
            old=conn.execute('SELECT source_sha FROM page_revision WHERE id=?',(previous['base_revision'],)).fetchone()
            new=conn.execute('SELECT source_sha FROM page_revision WHERE id=?',(base_revision,)).fetchone()
            same_source=old and new and old[0]==new[0]
        if (previous['page_id'],previous['kind'],previous['payload_json'])!=(page_id,kind,json_text(item)) or previous['base_revision']!=base_revision and not same_source:
            raise CorrectionConflict('Correction identifier reused with different content')
        if not replay:
            if kind=='boundaries':return {'anchors':{r['old_id']:r['new_id'] for r in conn.execute('SELECT * FROM anchor_mapping WHERE correction_id=?',(correction_id,))}}
            return False
    geometry=load_geometry(page_id,conn,include_artwork=kind!='font')
    if base_revision!=geometry['revision']:raise CorrectionConflict('Source revision changed')
    words={w['id']:w for w in geometry['words']}
    lines={line['id']:line for line in geometry['lines']}
    regions={region['id']:region for region in geometry['regions']}
    if kind=='anchor':
        from .annotations import carry_mapped_annotation
        old=conn.execute('SELECT active FROM occurrence WHERE id=?',(item.get('id'),)).fetchone()
        if not old or old['active']:raise ValueError('Original source anchor is not retired')
        if item.get('target_id') not in words:raise ValueError('Unknown target word')
        if not previous:
            conn.execute('INSERT INTO correction(id,page_id,base_revision,kind,payload_json,created_at) VALUES(?,?,?,?,?,coalesce(?,CURRENT_TIMESTAMP))',
                         (correction_id,page_id,base_revision,kind,json_text(item),created_at))
        conn.execute('INSERT INTO anchor_mapping VALUES(?,?,?,?) ON CONFLICT(correction_id,old_id) DO UPDATE SET new_id=excluded.new_id,status=excluded.status',(correction_id,item['id'],item['target_id'],'explicit'))
        return carry_mapped_annotation(conn,item['id'])
    if kind=='boundaries':
        from .boundaries import apply_boundaries
        already=conn.execute("SELECT 1 FROM occurrence WHERE page_id=? AND page_revision=? AND json_extract(geometry_json,'$.boundary_correction')=? LIMIT 1",(page_id,geometry['revision'],correction_id)).fetchone()
        if previous and already and all(wid not in words for wid in item.get('words',[])):
            return True
        if not previous:
            conn.execute('INSERT INTO correction(id,page_id,base_revision,kind,payload_json,created_at) VALUES(?,?,?,?,?,coalesce(?,CURRENT_TIMESTAMP))',
                         (correction_id,page_id,base_revision,kind,json_text(item),created_at))
        return apply_boundaries(conn,geometry,item,correction_id)
    if kind=='word':
        old=conn.execute('SELECT * FROM occurrence WHERE id=? AND page_id=? AND active=1',(item.get('id'),page_id)).fetchone()
        if not old:raise ValueError('Unknown source word')
        updated=json.loads(old['geometry_json'])
        for key in ('x','r','top','bottom'):updated[key]=number(item.get(key,updated[key]))
        if updated['r']<=updated['x'] or updated['bottom']<=updated['top']:raise ValueError('Invalid word bounds')
        text=item.get('text',old['text'])
        if not isinstance(text,str) or not text or any(char.isspace() for char in text):
            raise ValueError('A source occurrence must contain exactly one word; use Boundaries to split words')
        updated['text']=text;updated['normalized']=normalize(text)
        updated['reading_order']=int(item.get('reading_order',old['reading_order']))
        updated['state']='corrected'
        conn.execute("UPDATE occurrence SET text=?,normalized=?,geometry_json=?,reading_order=?,transcription_state='corrected' WHERE id=?",
                     (updated['text'],updated['normalized'],json_text(updated),updated['reading_order'],old['id']))
    elif kind=='region':
        from .regions import apply_region
        apply_region(conn,geometry,item,correction_id,replay)
    elif kind=='line':
        if item.get('id') not in lines:raise ValueError('Unknown source line')
        updated=dict(lines[item['id']])
        for key in ('x','r','top','bottom','baseline','reading_order'):
            if key in item:updated[key]=number(item[key])
        if updated['r']<=updated['x'] or updated['bottom']<=updated['top']:raise ValueError('Invalid line bounds')
    elif kind=='reading_order':
        ordered=item.get('words',[])
        if len(set(ordered))!=len(ordered) or any(wid not in words for wid in ordered):
            raise ValueError('Invalid reading order')
        for order,wid in enumerate(ordered):
            conn.execute('UPDATE occurrence SET reading_order=? WHERE id=?',(order,wid))
    elif kind=='font':
        fingerprint=item['font_fingerprint'];glyph=int(item['glyph']);text=item['unicode']
        if not isinstance(text,str) or len(text)>16:raise ValueError('Invalid font mapping')
        if not text:
            from .config import CORPUS
            asset=conn.execute('SELECT asset_path FROM page WHERE id=?',(page_id,)).fetchone()
            if CORPUS:
                from .glyph_preview import nonprinting
                empty=nonprinting(fingerprint,glyph)
            else:
                from .font_recovery import nonprinting_glyph
                empty=bool(asset) and nonprinting_glyph(asset['asset_path'],fingerprint,glyph)
            if not empty:raise ValueError('Only a nonprinting glyph can have an empty mapping')
        if not any(g['font']==fingerprint and g['glyph']==glyph for w in geometry['words'] for g in w.get('glyphs',[])):
            raise ValueError('Glyph does not occur on this page')
        affected={r[0] for r in conn.execute('SELECT page_id FROM page_font WHERE font_fingerprint=?',(fingerprint,))}|{page_id}
        for affected_page in affected:
            source=geometry if affected_page==page_id else load_geometry(affected_page,conn,include_artwork=False)
            for word in source['words']:
                if word['state']=='corrected':continue
                glyphs=word.get('glyphs',[])
                if not any(g['font']==fingerprint and g['glyph']==glyph for g in glyphs):continue
                pieces=[text if g['font']==fingerprint and g['glyph']==glyph else g['text'] for g in glyphs]
                if word.get('ocr',{}).get('original_text'):
                    # Retain recovered OCR letters while replacing this mapping.
                    logical=list(reversed(glyphs)) if any('א'<=c<='ת' for c in word['text']) else glyphs
                    cursor=0;pieces=[]
                    for g in logical:
                        length=len(g['text']);piece=word['text'][cursor:cursor+length];cursor+=length
                        pieces.append(text if g['font']==fingerprint and g['glyph']==glyph else piece)
                elif any('א'<=c<='ת' for piece in pieces for c in piece):pieces.reverse()
                updated={k:v for k,v in word.items() if k!='glyphs' or word.get('boundary_correction')}
                updated.update(text=''.join(pieces),state='font-corrected')
                updated['normalized']=normalize(updated['text'])
                conn.execute("UPDATE occurrence SET text=?,normalized=?,geometry_json=?,transcription_state='font-corrected' WHERE id=?",(updated['text'],updated['normalized'],json_text(updated),word['id']))
                if not any(c=='\ufffd' or unicodedata.category(c)=='Co' for c in updated['text']):
                    conn.execute("UPDATE source_issue SET resolved=1 WHERE page_id=? AND kind IN ('ocr-unresolved','ocr-failed') AND json_extract(evidence_json,'$.word')=?",(affected_page,word['id']))
        conn.execute('INSERT INTO font_mapping VALUES(?,?,?,?,1) ON CONFLICT(font_fingerprint,glyph) DO UPDATE SET unicode=excluded.unicode,provenance_json=excluded.provenance_json,revision=revision+1',
                     (fingerprint,glyph,text,json_text({'correction':correction_id})))
        conn.execute("UPDATE source_issue SET resolved=1 WHERE kind='unmapped-glyph' AND json_extract(evidence_json,'$.font')=? AND json_extract(evidence_json,'$.glyph')=?",(fingerprint,glyph))
        for affected_page in affected:
            conn.execute("UPDATE page SET extraction_state='complete' WHERE id=? AND extraction_state='issues' AND NOT EXISTS (SELECT 1 FROM source_issue WHERE page_id=? AND resolved=0)",(affected_page,affected_page))
    else:raise ValueError('Unknown correction type')
    if not previous:
        conn.execute('INSERT INTO correction(id,page_id,base_revision,kind,payload_json,created_at) VALUES(?,?,?,?,?,coalesce(?,CURRENT_TIMESTAMP))',
                     (correction_id,page_id,base_revision,kind,json_text(item),created_at))
    if kind=='word':
        conn.execute('INSERT OR IGNORE INTO anchor_mapping VALUES(?,?,?,?)',(correction_id,item['id'],item['id'],'explicit'))
    return True


def superseded_corrections(conn):
    replaced={}
    for row in conn.execute("SELECT payload_json,resolution_json FROM recovery_item WHERE kind='correction' AND status='resolved'"):
        original=json.loads(row['payload_json']);resolution=json.loads(row['resolution_json'] or '{}')
        target=resolution.get('correction_id')
        if target and target!=original.get('id') and conn.execute('SELECT 1 FROM correction WHERE id=?',(target,)).fetchone():
            replaced[original['id']]=target
    return replaced


def inactive_corrections(conn):
    inactive=set(superseded_corrections(conn))
    for row in conn.execute("SELECT payload_json FROM recovery_item WHERE kind='correction' AND status='pending'"):
        saved=json.loads(row['payload_json'])
        if saved.get('id'):inactive.add(saved['id'])
    return inactive


def resolve_replayed_correction(conn,correction_id,page_id):
    resolution=json_text({'correction_id':correction_id,'page_id':page_id})
    conn.execute("UPDATE recovery_item SET status='resolved',resolution_json=? WHERE kind='correction' AND status='pending' AND json_extract(payload_json,'$.id')=?",(resolution,correction_id))


def replay_source_corrections(conn,page_id,revision):
    from .annotations import retain_recovery
    failed=0
    superseded=superseded_corrections(conn)
    rows=[dict(r) for r in conn.execute("SELECT * FROM correction WHERE page_id=? AND kind!='font' ORDER BY created_at,rowid",(page_id,))]
    for row in rows:
        if row['id'] in superseded:continue
        conn.execute('SAVEPOINT source_correction')
        try:
            # Make this mapping available while replay carries learner work.
            # A failed replay rolls the recovery state back with the correction.
            resolve_replayed_correction(conn,row['id'],page_id)
            apply_correction(conn,page_id,revision,row['kind'],json.loads(row['payload_json']),row['id'],row['created_at'],replay=True)
        except (ValueError,KeyError) as exc:
            conn.execute('ROLLBACK TO source_correction')
            retain_recovery(conn,'correction',row,str(exc),reopen=True)
            conn.execute('INSERT INTO source_issue(page_id,kind,evidence_json) VALUES(?,?,?)',(page_id,'source-correction',json_text({'correction':row['id'],'error':str(exc)})))
            failed+=1
        finally:conn.execute('RELEASE source_correction')
    return failed


def restore_correction(conn,row,import_ids=None):
    from .annotations import retain_recovery
    item=json.loads(row['payload_json'])
    previous=conn.execute('SELECT * FROM correction WHERE id=?',(row['id'],)).fetchone()
    if previous:
        if any(previous[k]!=row[k] for k in ('page_id','base_revision','kind','payload_json')):
            raise CorrectionConflict('Imported correction identifier has different content')
    # A restore must not overwrite a later local correction to the same target.
    superseded=superseded_corrections(conn)
    if row['id'] in superseded:return True
    for local in conn.execute('SELECT id,kind,payload_json FROM correction WHERE page_id=? AND kind=?',(row['page_id'],row['kind'])):
        if local['id'] in (import_ids or set()) or local['id'] in superseded:continue
        other=json.loads(local['payload_json'])
        target=(item.get('id'),item.get('font_fingerprint'),item.get('glyph'))
        overlaps=(row['kind']=='boundaries' and bool(set(item.get('words',[]))&set(other.get('words',[])))) or (row['kind']=='region' and bool(set(item.get('lines',[]))&set(other.get('lines',[]))))
        same_target=any(value is not None for value in target) and target==(other.get('id'),other.get('font_fingerprint'),other.get('glyph'))
        if overlaps or same_target:
            retain_recovery(conn,'correction',row,'Conflicting source correction',reopen=True)
            return False
    conn.execute('SAVEPOINT restored_correction')
    try:
        resolve_replayed_correction(conn,row['id'],row['page_id'])
        apply_correction(conn,row['page_id'],row['base_revision'],row['kind'],item,row['id'],row.get('created_at'),replay=True)
    except (ValueError,KeyError) as exc:
        conn.execute('ROLLBACK TO restored_correction')
        conn.execute('RELEASE restored_correction')
        retain_recovery(conn,'correction',row,str(exc),reopen=True)
        return False
    conn.execute('RELEASE restored_correction')
    return True
