"""Source-word partitioning. Printed artwork and source records are retained."""
import json
from .db import digest,json_text
from .text import normalize


def boundary_words(geometry,item,correction_id):
    from .corrections import number,CorrectionConflict
    words={w['id']:w for w in geometry['words']}
    ids=item.get('words',[])
    if not ids or not isinstance(ids,list) or len(set(ids))!=len(ids):raise ValueError('Invalid source words')
    if item.get('id') not in ids:raise ValueError('Selected word is missing')
    if any(wid not in words for wid in ids):raise CorrectionConflict('Source words changed; reopen the correction')
    originals=sorted((words[wid] for wid in ids),key=lambda w:-w['x'])
    line=originals[0]['line'];region=originals[0]['region']
    if any(w['line']!=line or w['region']!=region for w in originals):raise ValueError('Word boundaries must stay within one source line')
    x=min(w['x'] for w in originals);r=max(w['r'] for w in originals)
    if any(w['line']==line and w['id'] not in ids and w['x']<r and w['r']>x for w in words.values()):raise ValueError('Source words must be adjacent')
    cuts=sorted(number(value) for value in item.get('cuts',[]))
    if len(set(cuts))!=len(cuts) or any(not x<cut<r for cut in cuts):raise ValueError('Invalid word boundary')
    texts=item.get('texts',[])
    if len(texts)!=len(cuts)+1 or any(not isinstance(text,str) or not text.strip() or any(c.isspace() for c in text.strip()) for text in texts):raise ValueError('Each boundary needs one source word')
    edges=[x,*cuts,r];intervals=list(reversed(list(zip(edges,edges[1:]))));result=[]
    glyphs=[dict(g,source_word=w['id'],source_glyph=index) for w in originals for index,g in enumerate(w.get('glyphs',[]))]
    for index,(left,right) in enumerate(intervals):
        assigned=[]
        for glyph in glyphs:
            center=(glyph.get('ink_x',glyph['x'])+glyph.get('ink_r',glyph['r']))/2
            if left<=center and (center<right or right==r and center<=right):assigned.append(glyph)
        assigned.sort(key=lambda g:g['x'])
        wid=geometry['id']+':word:'+digest(['boundary',correction_id,index])[:24]
        text=texts[index].strip()
        result.append({'id':wid,'line':line,'region':region,'x':left,'r':right,
                       'top':min(w['top'] for w in originals),'bottom':max(w['bottom'] for w in originals),
                       'text':text,'normalized':normalize(text),'reading_order':min(w['reading_order'] for w in originals)+index,
                       'state':'corrected','glyphs':assigned,'boundary_correction':correction_id,
                       'source_words':[w['id'] for w in originals]})
    anchors=item.get('anchors',{})
    if any(key not in ids for key in anchors):raise ValueError('Unknown annotation anchor')
    mapping={}
    for old in ids:
        target=anchors.get(old,0 if len(result)==1 else None)
        if target is not None and (type(target) is not int or not 0<=target<len(result)):raise ValueError('Invalid annotation attachment')
        mapping[old]=result[target]['id'] if target is not None else None
    return originals,result,mapping


def apply_boundaries(conn,geometry,item,correction_id):
    from .annotations import carry_mapped_annotation,retain_recovery
    originals,created,mapping=boundary_words(geometry,item,correction_id)
    for old in originals:conn.execute('UPDATE occurrence SET active=0 WHERE id=?',(old['id'],))
    for word in created:
        saved=conn.execute('SELECT geometry_json FROM occurrence WHERE id=?',(word['id'],)).fetchone()
        if saved:
            # Re-import reactivates the same corrected anchor and its later edits.
            previous=json.loads(saved['geometry_json'])
            word.update({key:previous[key] for key in ('text','normalized','x','r','top','bottom')})
        conn.execute('INSERT INTO occurrence(id,page_id,page_revision,region_id,line_id,text,normalized,geometry_json,reading_order,transcription_state,active) VALUES(?,?,?,?,?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET page_revision=excluded.page_revision,region_id=excluded.region_id,line_id=excluded.line_id,text=excluded.text,normalized=excluded.normalized,geometry_json=excluded.geometry_json,reading_order=excluded.reading_order,transcription_state=excluded.transcription_state,active=1',
                     (word['id'],geometry['id'],geometry['revision'],word['region'],word['line'],word['text'],word['normalized'],json_text(word),word['reading_order'],word['state']))
    # Keep a single explicit order after replacing one interval with new words.
    line_order={line['id']:line['reading_order'] for line in geometry['lines']}
    from .corrections import inactive_corrections
    inactive=inactive_corrections(conn)
    explicit=any(row['id'] not in inactive for row in conn.execute("SELECT id FROM correction WHERE page_id=? AND kind='reading_order'",(geometry['id'],)))
    first_line={region['id']:min((line['reading_order'] for line in geometry['lines'] if line['region']==region['id']),default=0) for region in geometry['regions']}
    region_order={r['id']:index for index,r in enumerate(sorted(geometry['regions'],key=lambda r:(r['reading_order'],first_line[r['id']],r['id'])))}
    ordered=sorted(geometry['words'],key=(lambda w:w['reading_order']) if explicit else (lambda w:(region_order[w['region']],line_order[w['line']],-w['x'])))
    replacement=[];inserted=False
    for word in ordered:
        if word['id'] in mapping:
            if not inserted:replacement.extend(created);inserted=True
        else:replacement.append(word)
    for index,word in enumerate(replacement):
        conn.execute('UPDATE occurrence SET reading_order=? WHERE id=?',(index,word['id']))
    totals={'unresolved':0,'conflicts':[],'words':[w['id'] for w in created],'anchors':mapping}
    for old,target in mapping.items():
        conn.execute('INSERT INTO anchor_mapping VALUES(?,?,?,?) ON CONFLICT(correction_id,old_id) DO UPDATE SET new_id=excluded.new_id,status=excluded.status',
                     (correction_id,old,target,'explicit' if target else 'unresolved'))
        carried=carry_mapped_annotation(conn,old)
        totals['unresolved']+=carried['unresolved']
        if carried['conflicts'] and target:totals['conflicts'].append(target)
        bookmark=conn.execute('SELECT * FROM bookmark WHERE occurrence_id=?',(old,)).fetchone()
        if bookmark:
            if target:conn.execute('UPDATE bookmark SET occurrence_id=? WHERE page_id=?',(target,bookmark['page_id']))
            else:retain_recovery(conn,'bookmark',dict(bookmark),'Bookmark attachment needs a choice');totals['unresolved']+=1
    return totals
