from .db import read, transaction, digest, json_text, _write_lock
from contextlib import nullcontext
import json

class EditConflict(ValueError):
    pass

def components_for(row):
    row = dict(row)
    value = row.get('components')
    if value is None and row.get('components_json') is not None:
        value = json.loads(row['components_json'])
    if value is None:
        value = [{'id': 'legacy', 'role': 'base', 'text': row.get('text', ''),
                  'direction': row.get('direction', 'auto'), 'char_range': None}]
    return validate_components(value)


def validate_components(value):
    if not isinstance(value, list) or len(value) > 64:
        raise ValueError('Invalid annotation components')
    ids = set()
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not 1 <= len(item['id']) <= 160 or item['id'] in ids:
            raise ValueError('Invalid or duplicate component identifier')
        ids.add(item['id'])
        if item.get('role') not in ('base','prefix','suffix','custom') or item.get('direction', 'auto') not in ('auto','ltr','rtl'):
            raise ValueError('Invalid component role or direction')
        if not isinstance(item.get('text'), str) or len(item['text']) > 20000:
            raise ValueError('Invalid component wording')
        area = item.get('char_range')
        if area is not None and (not isinstance(area, list) or len(area) != 2 or any(type(n) is not int for n in area) or not 0 <= area[0] < area[1]):
            raise ValueError('Invalid component character range')
    if sum(len(c['text']) for c in value) > 20000 or len(json_text(value)) > 250000:
        raise ValueError('Annotation components too large')
    return value


def annotation_record(row):
    result = dict(row)
    result['components'] = components_for(result)
    result.pop('components_json', None)
    return result


def current_for_page(page_id,connection=None):
    with nullcontext(connection) if connection is not None else read() as conn:
        rows=conn.execute('SELECT a.occurrence_id,a.head_revision,r.text,r.direction,r.deleted,r.created_at,r.components_json FROM annotation a JOIN occurrence o ON o.id=a.occurrence_id JOIN annotation_revision r ON r.occurrence_id=a.occurrence_id AND r.revision=a.head_revision WHERE o.page_id=? AND o.active=1',(page_id,)).fetchall()
    return [annotation_record(row) for row in rows]

def write_annotation(occurrence_id,text,direction,base_revision,operation_id,deleted=False,components=None,remember_meaning=False):
    with transaction() as conn:
        already=conn.execute('SELECT 1 FROM operation WHERE id=?',(operation_id,)).fetchone()
        result=write_annotation_tx(conn,occurrence_id,text,direction,base_revision,operation_id,deleted,components,remember_meaning)
        active=conn.execute('SELECT active FROM occurrence WHERE id=?',(occurrence_id,)).fetchone()
        if active and not active['active']:
            carried=carry_mapped_annotation(conn,occurrence_id)
            result=dict(result,mapped_to=carried['target'],mapped_conflict=bool(carried['conflicts']),recovery=bool(carried['unresolved']))
            conn.execute('UPDATE operation SET result_json=? WHERE id=?',(json_text(result),operation_id))
        elif not result['conflict'] and not already:
            resolved=[]
            items=conn.execute("SELECT id,payload_json FROM recovery_item WHERE kind='annotation' AND status='pending' AND reason='Source attachment has conflicting versions'").fetchall()
            for item in items:
                bundle=json.loads(item['payload_json']);origins={r['occurrence_id'] for r in bundle.get('annotations',[])}
                if origins and all(mapped_anchor(conn,old)==occurrence_id for old in origins):
                    conn.execute("UPDATE recovery_item SET status='resolved',resolution_json=? WHERE id=?",(json_text({'occurrence_id':occurrence_id,'operation_id':operation_id}),item['id']))
                    resolved.extend(origins)
            if resolved:
                result=dict(result,resolved_sources=resolved)
                conn.execute('UPDATE operation SET result_json=? WHERE id=?',(json_text(result),operation_id))
        return result


def write_annotation_tx(conn,occurrence_id,text,direction,base_revision,operation_id,deleted=False,components=None,remember_meaning=False):
    payload={'occurrence_id':occurrence_id,'text':text,'direction':direction,'base_revision':base_revision,'deleted':deleted}
    if remember_meaning:payload['remember_meaning']=True
    if components is not None:
        components=validate_components(components)
        if text!='\n'.join(c['text'] for c in components):raise ValueError('Component text does not match annotation')
        payload['components']=components
    fingerprint=digest(payload)
    previous=conn.execute('SELECT * FROM operation WHERE id=?',(operation_id,)).fetchone()
    if previous:
        if previous['payload_sha']!=fingerprint:raise EditConflict('Operation identifier reused with different content')
        return json.loads(previous['result_json'])
    if not conn.execute('SELECT 1 FROM occurrence WHERE id=?',(occurrence_id,)).fetchone():raise KeyError(occurrence_id)
    conn.execute('INSERT OR IGNORE INTO annotation(occurrence_id) VALUES(?)',(occurrence_id,))
    head=conn.execute('SELECT head_revision FROM annotation WHERE occurrence_id=?',(occurrence_id,)).fetchone()[0]
    revision=conn.execute('SELECT coalesce(max(revision),0)+1 FROM annotation_revision WHERE occurrence_id=?',(occurrence_id,)).fetchone()[0]
    conflict=head!=base_revision
    known_parent=base_revision==0 or conn.execute('SELECT 1 FROM annotation_revision WHERE occurrence_id=? AND revision=?',(occurrence_id,base_revision)).fetchone()
    parent_revision=base_revision if known_parent else -1
    conn.execute('INSERT INTO annotation_revision(occurrence_id,revision,parent_revision,text,direction,deleted,conflict,operation_id,components_json) VALUES(?,?,?,?,?,?,?,?,?)',(occurrence_id,revision,parent_revision,text,direction,int(deleted),int(conflict),operation_id,json_text(components) if components is not None else None))
    if not conflict:
        conn.execute('UPDATE annotation SET head_revision=?,modified_at=CURRENT_TIMESTAMP WHERE occurrence_id=?',(revision,occurrence_id))
        if remember_meaning and not deleted:
            from .saved_meanings import remember
            spelling=conn.execute('SELECT text FROM occurrence WHERE id=?',(occurrence_id,)).fetchone()[0]
            remember(conn,spelling,text,direction)
    result={'occurrence_id':occurrence_id,'revision':revision,'head_revision':head if conflict else revision,'text':text,'direction':direction,'deleted':deleted,'conflict':conflict,'operation_id':operation_id}
    result['components']=components_for({'components':components,'text':text,'direction':direction})
    conn.execute('INSERT INTO operation(id,kind,payload_sha,result_json) VALUES(?,?,?,?)',(operation_id,'annotation',fingerprint,json_text(result)))
    return result

def history(occurrence_id):
    with read() as conn:
        return [annotation_record(r) for r in conn.execute('SELECT r.*,a.head_revision FROM annotation_revision r JOIN annotation a ON a.occurrence_id=r.occurrence_id WHERE r.occurrence_id=? ORDER BY r.revision DESC',(occurrence_id,))]

def export_from_connection(conn):
    payload={'format':'shasmaster-work','version':2}
    queries={
        'annotations':'SELECT * FROM annotation_revision ORDER BY occurrence_id,revision',
        'heads':'SELECT * FROM annotation',
        'bookmarks':'SELECT * FROM bookmark',
        'preferences':'SELECT * FROM preference',
        'corrections':'SELECT * FROM correction ORDER BY created_at,rowid',
        'operations':'SELECT * FROM operation WHERE id IN (SELECT operation_id FROM annotation_revision)',
        'anchors':'SELECT id,page_id,page_revision,text,geometry_json FROM occurrence WHERE id IN (SELECT occurrence_id FROM annotation)',
        'pages':'SELECT id,edition,source_sha,source_url FROM page WHERE id IN (SELECT page_id FROM occurrence WHERE id IN (SELECT occurrence_id FROM annotation)) OR id IN (SELECT page_id FROM correction)',
    }
    for key,query in queries.items():payload[key]=[annotation_record(r) if key=='annotations' else dict(r) for r in conn.execute(query)]
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='saved_meaning'").fetchone():
        payload['saved_meanings']=[dict(r) for r in conn.execute('SELECT * FROM saved_meaning ORDER BY spelling,text')]
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='recovery_item'").fetchone():
        payload['recovery']=[dict(r) for r in conn.execute('SELECT * FROM recovery_item')]
    return payload

def export_work():
    with read() as conn:
        conn.execute('BEGIN')
        return export_from_connection(conn)

def retain_recovery(conn,kind,payload,reason,reopen=True):
    key=digest({'kind':kind,'payload':payload})
    conn.execute('INSERT OR IGNORE INTO recovery_item(id,kind,payload_json,reason) VALUES(?,?,?,?)',
                 (key,kind,json_text(payload),reason))
    if reopen:
        conn.execute("UPDATE recovery_item SET status='pending',reason=? WHERE id=?",(reason,key))
    return key


def annotation_bundle(conn,occurrence_id):
    word=conn.execute('SELECT o.*,r.source_sha FROM occurrence o JOIN page_revision r ON r.id=o.page_revision WHERE o.id=?',(occurrence_id,)).fetchone()
    if not word:return None
    rows=[annotation_record(r) for r in conn.execute('SELECT * FROM annotation_revision WHERE occurrence_id=? ORDER BY revision',(occurrence_id,))]
    if not rows:return None
    page=dict(conn.execute('SELECT id,edition,source_sha,source_url FROM page WHERE id=?',(word['page_id'],)).fetchone())
    page['source_sha']=word['source_sha']
    return {'format':'shasmaster-work','version':2,'annotations':rows,
            'heads':[dict(r) for r in conn.execute('SELECT * FROM annotation WHERE occurrence_id=?',(occurrence_id,))],
            'anchors':[{key:word[key] for key in ('id','page_id','page_revision','text','geometry_json')}],
            'pages':[page],
            'operations':[dict(r) for r in conn.execute('SELECT * FROM operation WHERE id IN (SELECT operation_id FROM annotation_revision WHERE occurrence_id=?)',(occurrence_id,))]}


def next_anchor(conn,occurrence_id,inactive):
    mappings=conn.execute('SELECT m.correction_id,m.new_id FROM anchor_mapping m JOIN correction c ON c.id=m.correction_id WHERE m.old_id=? AND (m.new_id IS NULL OR m.new_id!=m.old_id) ORDER BY c.created_at DESC,c.rowid DESC',(occurrence_id,))
    for mapping in mappings:
        if mapping['correction_id'] not in inactive:return mapping['new_id']
    # Imported work may reference an occurrence absent from this installation.
    # Only an explicit recovery choice can supply its replacement.
    choices=conn.execute("""SELECT DISTINCT json_extract(r.resolution_json,'$.occurrence_id') AS target
        FROM recovery_item r WHERE r.kind='annotation' AND r.status='resolved'
        AND EXISTS (SELECT 1 FROM json_each(r.payload_json,'$.annotations') a
                    WHERE json_extract(a.value,'$.occurrence_id')=?)""",(occurrence_id,))
    targets={row['target'] for row in choices if isinstance(row['target'],str) and row['target'] and row['target']!=occurrence_id}
    return next(iter(targets)) if len(targets)==1 else None


def mapped_anchor(conn,occurrence_id):
    from .corrections import inactive_corrections
    inactive=inactive_corrections(conn)
    seen=set();current=occurrence_id
    while current and current not in seen:
        seen.add(current)
        active=conn.execute('SELECT active FROM occurrence WHERE id=?',(current,)).fetchone()
        if active and active['active']:return current
        current=next_anchor(conn,current,inactive)
    return None


def carry_annotation(conn,source_id,target_id):
    bundle=annotation_bundle(conn,source_id)
    if not bundle:return {'restored':0,'unresolved':0,'conflicts':0}
    if not target_id:
        retain_recovery(conn,'annotation',bundle,'Source attachment needs a choice',reopen=True)
        return {'restored':0,'unresolved':1,'conflicts':0}
    copied=json.loads(json_text(bundle));copied.pop('operations',None)
    source_text=conn.execute('SELECT text FROM occurrence WHERE id=?',(source_id,)).fetchone()[0]
    target_text=conn.execute('SELECT text FROM occurrence WHERE id=?',(target_id,)).fetchone()[0]
    for row in copied['annotations']:
        if source_text!=target_text:
            for component in row['components']:
                component['char_range']=None
        row['operation_id']='mapped-'+digest([source_id,target_id,row['operation_id']])
    result=restore_into(conn,copied,{source_id:target_id})
    if result['conflicts']:retain_recovery(conn,'annotation',bundle,'Source attachment has conflicting versions',reopen=True)
    return result


def carry_mapped_annotation(conn,occurrence_id):
    from .corrections import inactive_corrections
    inactive=inactive_corrections(conn)
    current=occurrence_id;seen=set();totals={'restored':0,'unresolved':0,'conflicts':0,'target':None}
    while current and current not in seen:
        seen.add(current)
        word=conn.execute('SELECT active FROM occurrence WHERE id=?',(current,)).fetchone()
        if word and word['active']:totals['target']=current;break
        target=next_anchor(conn,current,inactive)
        result=carry_annotation(conn,current,target)
        for key in ('restored','unresolved','conflicts'):totals[key]+=result[key]
        current=target
    return totals


def restore_work(payload):
    # Retained pages may not be materialized in the bounded reader cache yet.
    from .retained_pages import ensure_page
    page_ids = {row['page_id'] for key in ('anchors', 'corrections', 'bookmarks')
                for row in payload.get(key, []) if row.get('page_id')}
    with _write_lock:
        for page_id in page_ids:
            ensure_page(page_id, protected_pages=page_ids)
        with transaction() as conn:
            result=restore_into(conn,payload,select_heads=True)
            # Corrections can retire the source word before its revisions are imported.
            # Transfer those revisions only after the whole import has been stored.
            for occurrence_id in dict.fromkeys(row['occurrence_id'] for row in payload.get('annotations',[])):
                word=conn.execute('SELECT active FROM occurrence WHERE id=?',(occurrence_id,)).fetchone()
                if word and not word['active'] and mapped_anchor(conn,occurrence_id):
                    carried=carry_mapped_annotation(conn,occurrence_id)
                    for key in ('restored','unresolved','conflicts'):result[key]+=carried[key]
            return result


def restore_recovery(conn,items,restored_corrections,failed_corrections):
    pending=[]
    for row in items:
        saved=json.loads(row['payload_json'])
        key=retain_recovery(conn,row['kind'],saved,row['reason'],reopen=False)
        current=conn.execute('SELECT status FROM recovery_item WHERE id=?',(key,)).fetchone()
        if current['status']=='resolved':continue
        if row['kind']=='correction' and saved.get('id') in restored_corrections:
            resolution={'correction_id':saved['id'],'page_id':saved['page_id']}
            conn.execute("UPDATE recovery_item SET status='resolved',resolution_json=? WHERE id=?",(json_text(resolution),key))
            continue
        if row.get('status')!='resolved' or not row.get('resolution_json'):continue
        resolution=json.loads(row['resolution_json'])
        if row['kind']=='correction' and resolution.get('correction_id') in failed_corrections:continue
        pending.append((key,row['kind'],resolution))
    # Recovery choices can point through other imported recovery choices.
    # Cycles and missing destinations remain pending with their original work.
    while pending:
        unresolved=[]
        for key,kind,resolution in pending:
            if kind=='correction' and resolution.get('correction_id'):
                resolved=conn.execute('SELECT 1 FROM correction WHERE id=?',(resolution['correction_id'],)).fetchone()
            else:resolved=mapped_anchor(conn,resolution.get('occurrence_id'))
            if resolved:
                conn.execute("UPDATE recovery_item SET status='resolved',resolution_json=? WHERE id=?",(json_text(resolution),key))
            else:unresolved.append((key,kind,resolution))
        if len(unresolved)==len(pending):break
        pending=unresolved


def restore_into(conn,payload,anchor_map=None,select_heads=False):
    from collections import defaultdict
    if payload.get('format')!='shasmaster-work' or payload.get('version') not in (1,2):
        raise ValueError('Unsupported export')
    from .saved_meanings import remember
    for item in payload.get('saved_meanings',[]):
        remember(conn,item.get('spelling'),item.get('text'),item.get('direction','auto'),item.get('created_at'))
    anchor_map=anchor_map or {}
    groups=defaultdict(list)
    for row in payload.get('annotations',[]):
        if not isinstance(row,dict):raise ValueError('Invalid annotation record')
        if not isinstance(row.get('text'),str) or len(row['text'])>20000:
            raise ValueError('Invalid annotation text')
        if row.get('direction') not in ('auto','ltr','rtl'):raise ValueError('Invalid text direction')
        if not isinstance(row.get('revision'),int) or row['revision']<1:
            raise ValueError('Invalid revision')
        if not isinstance(row.get('parent_revision'),int) or row['parent_revision'] < -1:raise ValueError('Invalid parent revision')
        if not isinstance(row.get('operation_id'),str) or not 16<=len(row['operation_id'])<=120:
            raise ValueError('Invalid operation identifier')
        parts=components_for(row)
        if row['text']!='\n'.join(c['text'] for c in parts):raise ValueError('Imported component text does not match annotation')
        if payload.get('version')==2 and 'components' not in row and 'components_json' not in row:raise ValueError('Missing component array')
        groups[row['occurrence_id']].append(row)
    heads={r['occurrence_id']:r for r in payload.get('heads',[])}
    anchors={r['id']:r for r in payload.get('anchors',[])}
    pages={r['id']:r for r in payload.get('pages',[])}
    operations={r['id']:r for r in payload.get('operations',[])}
    operation_ids=[r['operation_id'] for rows in groups.values() for r in rows]
    if len(set(operation_ids))!=len(operation_ids):raise ValueError('Duplicate annotation operation')
    totals={'restored':0,'unresolved':0,'conflicts':0,'corrections':0}
    correction_ids={r['id'] for r in payload.get('corrections',[])}
    restored_corrections=set();failed_corrections=set()
    superseded=set()
    for item in payload.get('recovery',[]):
        if item.get('kind')!='correction' or item.get('status')!='resolved':continue
        original=json.loads(item['payload_json']);resolution=json.loads(item.get('resolution_json') or '{}')
        replacement=resolution.get('correction_id')
        if replacement and replacement!=original.get('id') and replacement in correction_ids:
            superseded.add(original['id'])
    for row in payload.get('corrections',[]):
        if row['id'] in superseded:continue
        from .corrections import restore_correction
        if restore_correction(conn,row,correction_ids):
            totals['corrections']+=1;restored_corrections.add(row['id'])
        else:
            totals['unresolved']+=1;failed_corrections.add(row['id'])
    for original_id,rows in groups.items():
        oid=anchor_map.get(original_id,original_id)
        rows.sort(key=lambda r:r['revision'])
        source={r['revision']:r for r in rows}
        if len(source)!=len(rows):raise ValueError('Duplicate annotation revision')
        if any(r['parent_revision']>=r['revision'] for r in rows):
            raise ValueError('Invalid revision ancestry')
        incoming_head=heads.get(original_id,{}).get('head_revision')
        if incoming_head is None:
            incoming_head=max((r['revision'] for r in rows if not r.get('conflict')),default=0)
        reason=None
        word=conn.execute('SELECT active FROM occurrence WHERE id=?',(oid,)).fetchone()
        archived=word and not word['active'] and mapped_anchor(conn,oid) is not None
        if not word or not word['active'] and not archived:reason='Source word unavailable'
        elif incoming_head and incoming_head not in source:reason='Selected revision unavailable'
        elif any(r['parent_revision']>0 and r['parent_revision'] not in source for r in rows):
            reason='Incomplete revision history'
        if reason:
            saved_anchor=anchors.get(original_id)
            saved_page=pages.get(saved_anchor['page_id']) if saved_anchor else None
            bundle={'format':'shasmaster-work','version':2,'annotations':[annotation_record(row) for row in rows],
                    'heads':[heads[original_id]] if original_id in heads else [],
                    'anchors':[saved_anchor] if saved_anchor else [],
                    'pages':[saved_page] if saved_page else [],
                    'operations':[operations[r['operation_id']] for r in rows if r['operation_id'] in operations]}
            retain_recovery(conn,'annotation',bundle,reason,reopen=False)
            totals['unresolved']+=len(rows)
            continue
        local=conn.execute('SELECT * FROM annotation WHERE occurrence_id=?',(oid,)).fetchone()
        old_head=local['head_revision'] if local else 0
        next_revision=conn.execute('SELECT coalesce(max(revision),0) FROM annotation_revision WHERE occurrence_id=?',(oid,)).fetchone()[0]
        mapped={0:0,-1:-1};existing=set()
        for row in rows:
            previous=conn.execute('SELECT * FROM annotation_revision WHERE operation_id=?',(row['operation_id'],)).fetchone()
            if previous:
                if previous['occurrence_id']!=oid or any(previous[k]!=row[k] for k in ('text','direction','deleted')) or components_for(previous)!=components_for(row):
                    raise EditConflict('Imported operation identifier has different content')
                mapped[row['revision']]=previous['revision'];existing.add(row['revision'])
            else:
                next_revision+=1;mapped[row['revision']]=next_revision
        parents={mapped[r['revision']]:mapped[r['parent_revision']] for r in rows}
        chosen=mapped[incoming_head]
        ancestor=chosen
        while ancestor>0 and ancestor!=old_head:ancestor=parents.get(ancestor,0)
        advance=old_head==0 or ancestor==old_head
        head=chosen if advance else old_head
        conn.execute('INSERT OR IGNORE INTO annotation(occurrence_id) VALUES(?)',(oid,))
        for row in rows:
            old_revision=row['revision'];revision=mapped[old_revision]
            parent=mapped[row['parent_revision']]
            if old_revision in existing:
                saved=conn.execute('SELECT parent_revision FROM annotation_revision WHERE occurrence_id=? AND revision=?',(oid,revision)).fetchone()
                if saved['parent_revision']!=parent:raise EditConflict('Imported revision has different ancestry')
                continue
            conflict=bool(row.get('conflict')) or not advance
            conn.execute('INSERT INTO annotation_revision(occurrence_id,revision,parent_revision,text,direction,deleted,conflict,operation_id,created_at,components_json) VALUES(?,?,?,?,?,?,?,?,coalesce(?,CURRENT_TIMESTAMP),?)',
                         (oid,revision,parent,row['text'],row['direction'],int(bool(row['deleted'])),int(conflict),row['operation_id'],row.get('created_at'),json_text(components_for(row))))
            original_request={'occurrence_id':original_id,'text':row['text'],'direction':row['direction'],
                              'base_revision':row['parent_revision'],'deleted':bool(row['deleted'])}
            if 'components' in row:original_request['components']=row['components']
            fingerprint=operations.get(row['operation_id'],{}).get('payload_sha') or digest(original_request)
            result={'occurrence_id':oid,'revision':revision,'head_revision':head,'text':row['text'],
                    'direction':row['direction'],'deleted':bool(row['deleted']),'conflict':conflict,'operation_id':row['operation_id']}
            result['components']=components_for(row)
            if conn.execute('SELECT 1 FROM operation WHERE id=?',(row['operation_id'],)).fetchone():
                raise EditConflict('Imported operation identifier already belongs to another operation')
            conn.execute('INSERT INTO operation(id,kind,payload_sha,result_json,created_at) VALUES(?,?,?,?,coalesce(?,CURRENT_TIMESTAMP))',
                         (row['operation_id'],'annotation',fingerprint,json_text(result),row.get('created_at')))
            totals['restored']+=1
            if conflict:totals['conflicts']+=1
        if advance:
            modified=heads.get(original_id,{}).get('modified_at')
            conn.execute('UPDATE annotation SET head_revision=?,modified_at=coalesce(?,CURRENT_TIMESTAMP) WHERE occurrence_id=?',(head,modified,oid))
        if select_heads and old_head and chosen and chosen!=head:
            selected=source[incoming_head]
            current=conn.execute('SELECT text,direction,deleted,components_json FROM annotation_revision WHERE occurrence_id=? AND revision=?',(oid,head)).fetchone()
            if any(current[k]!=selected[k] for k in ('text','direction','deleted')) or components_for(current)!=components_for(selected):
                operation_id='restore-'+digest([oid,selected['operation_id'],head])
                write_annotation_tx(conn,oid,selected['text'],selected['direction'],head,operation_id,bool(selected['deleted']),components_for(selected))
                totals['restored']+=1
    restore_recovery(conn,payload.get('recovery',[]),restored_corrections,failed_corrections)
    for row in payload.get('bookmarks',[]):
        oid=anchor_map.get(row.get('occurrence_id'),row.get('occurrence_id'))
        page_id=row['page_id']
        target=mapped_anchor(conn,oid) if oid else None
        if target and target!=oid:
            oid=target
            page_id=conn.execute('SELECT page_id FROM occurrence WHERE id=?',(oid,)).fetchone()['page_id']
        page_exists=conn.execute('SELECT 1 FROM page WHERE id=?',(page_id,)).fetchone()
        word_exists=not oid or conn.execute('SELECT 1 FROM occurrence WHERE id=? AND page_id=? AND active=1',(oid,page_id)).fetchone()
        if not page_exists or not word_exists:
            retain_recovery(conn,'bookmark',row,'Bookmark source unavailable',reopen=False);totals['unresolved']+=1
            continue
        conn.execute('INSERT OR IGNORE INTO bookmark(page_id,occurrence_id,label,created_at) VALUES(?,?,?,coalesce(?,CURRENT_TIMESTAMP))',
                     (page_id,oid,row.get('label',''),row.get('created_at')))
    for row in payload.get('preferences',[]):
        json.loads(row['value_json'])
        conn.execute('INSERT OR IGNORE INTO preference(key,value_json) VALUES(?,?)',(row['key'],row['value_json']))
    return totals
