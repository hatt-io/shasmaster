import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import secrets
import threading
import time
from typing import Annotated, Literal
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .config import DATA, ROOT, PORT, USER_DATA, CORPUS, FRONTEND
from .db import migrate, read, transaction, json_text, backup, load_backup, digest, StorageLimitError
from .catalogue import initialize_catalogue
from .annotations import current_for_page,write_annotation,history,export_work,export_from_connection,restore_work,restore_into,EditConflict
from .corrections import apply_correction,CorrectionConflict,inactive_corrections
from .page_geometry import load_geometry
from .text import normalize
from .source_assets import retain_catalogue_sources
from .retained_pages import ensure_page,ensure_occurrence,search_words

TOKEN=secrets.token_urlsafe(32)
ALLOWED_ORIGINS={f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}','http://127.0.0.1:5173','http://localhost:5173'}

@asynccontextmanager
async def lifespan(app):
    migrate();initialize_catalogue()
    if not CORPUS:
        await asyncio.to_thread(retain_catalogue_sources)
    async def snapshots():
        while True:
            await asyncio.sleep(900)
            await asyncio.to_thread(backup)
    task=asyncio.create_task(snapshots())
    try:yield
    finally:task.cancel()

app=FastAPI(title='Shas Master',lifespan=lifespan,docs_url=None,redoc_url=None)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','[::1]'])

@app.exception_handler(StorageLimitError)
async def storage_limit_error(request:Request,exc:StorageLimitError):
    return JSONResponse({'detail':str(exc)},status_code=507)

@app.middleware('http')
async def local_security(request:Request,call_next):
    origin=request.headers.get('origin')
    if origin and origin not in ALLOWED_ORIGINS:return JSONResponse({'detail':'Origin not allowed'},403)
    if request.method not in ('GET','HEAD','OPTIONS'):
        if not secrets.compare_digest(request.headers.get('x-shas-token',''),TOKEN):return JSONResponse({'detail':'Session expired'},403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control']='private, max-age=31536000, immutable' if '/fonts/' in request.url.path and response.status_code==200 else 'no-store'
    return response

@app.get('/api/session')
def session():return {'token':TOKEN}

@app.get('/api/catalogue')
def catalogue():
    with read() as conn:
        return {'tractates':[dict(r) for r in conn.execute('SELECT * FROM tractate ORDER BY sequence')],'pages':[dict(r) for r in conn.execute('SELECT id,tractate,daf,amud,sequence,width,height,acquisition_state,extraction_state FROM page ORDER BY sequence')]}

@app.get('/api/anchors/{occurrence_id}')
def resolve_anchor(occurrence_id:str):
    ensure_occurrence(occurrence_id)
    from .annotations import mapped_anchor
    with read() as conn:
        conn.execute('BEGIN')
        source=conn.execute('SELECT id,page_id,text FROM occurrence WHERE id=?',(occurrence_id,)).fetchone()
        target=mapped_anchor(conn,occurrence_id)
        if not target:
            if not source:raise HTTPException(404,'Source word unavailable')
            return dict(source)|{'occurrence_id':occurrence_id,'state':'unresolved'}
        word=conn.execute('SELECT id,page_id,text FROM occurrence WHERE id=?',(target,)).fetchone()
        return dict(word)|{'occurrence_id':target,'state':'active' if target==occurrence_id else 'mapped'}

@app.get('/api/jobs')
def jobs():
    with read() as conn:return [dict(r) for r in conn.execute('SELECT * FROM job')]

@app.get('/api/pages/{page_id}')
def page_data(page_id:str):
    ensure_page(page_id)
    with read() as conn:
        conn.execute('BEGIN')
        try:geometry=load_geometry(page_id,conn,include_artwork=False)
        except KeyError:raise HTTPException(409,'Page extraction pending')
        page=conn.execute('SELECT p.*,t.label,t.hebrew FROM page p JOIN tractate t ON t.id=p.tractate WHERE p.id=?',(page_id,)).fetchone()
        inactive=inactive_corrections(conn)
        corrections=[json.loads(r['payload_json'])|{'kind':r['kind'],'id':r['id']} for r in conn.execute('SELECT * FROM correction WHERE page_id=? ORDER BY created_at,rowid',(page_id,)) if r['id'] not in inactive]
        annotations=current_for_page(page_id,conn)
    from .source_context import attach_reading_order
    attach_reading_order(geometry,any(correction['kind']=='reading_order' for correction in corrections))
    from .reader_fonts import attach_fonts
    attach_fonts(geometry, page['asset_path'])
    # Glyph evidence remains stored locally; the reader needs source word and line geometry.
    for word in geometry['words']:
        glyphs=sorted(word.pop('glyphs',[]),key=lambda g:g['x'],reverse=any('א'<=c<='ת' for c in word['text']))
        if ''.join(g.get('text','') for g in glyphs)==word['text']:
            word['character_bounds']=[[g.get('ink_x',g['x']),g.get('ink_r',g['r'])]
                                      for g in glyphs for _ in g.get('text','')]

    return {'page':dict(page),'geometry':geometry,'annotations':annotations,'corrections':corrections}

@app.get('/api/pages/{page_id}/fonts/{font_id}')
def source_font(page_id:str,font_id:str):
    from .reader_fonts import attach_fonts,browser_font,font_requests
    cached=font_requests.get(font_id)
    if cached:
        return Response(browser_font(*cached),media_type='font/otf')
    with read() as conn:
        try:geometry=load_geometry(page_id,conn,include_artwork=False)
        except KeyError:raise HTTPException(404,'Source page unavailable')
        row=conn.execute('''SELECT s.asset_path FROM page_revision r
            JOIN page_source s ON s.page_id=r.page_id AND s.source_sha=r.source_sha
            WHERE r.id=?''',(geometry['revision'],)).fetchone()
    if not row:raise HTTPException(404,'Source unavailable')
    fonts=attach_fonts(geometry,row['asset_path'])
    font=next((item for item in fonts if item['id']==font_id),None)
    if not font:raise HTTPException(404,'Source font unavailable')
    try:content=browser_font(row['asset_path'],font['fingerprint'],font['mapping'])
    except ValueError as exc:raise HTTPException(409,str(exc))
    return Response(content,media_type='font/otf')

@app.get('/api/pages/{page_id}/pdf')
def original_pdf(page_id:str,revision:str|None=None):
    with read() as conn:
        if revision:
            row=conn.execute('''SELECT s.asset_path FROM page_revision r
                JOIN page_source s ON s.page_id=r.page_id AND s.source_sha=r.source_sha
                WHERE r.page_id=? AND r.id=?''',(page_id,revision)).fetchone()
        else:
            row=conn.execute('''SELECT s.asset_path FROM page p
                LEFT JOIN page_revision r ON r.id=p.active_revision
                JOIN page_source s ON s.page_id=p.id AND s.source_sha=COALESCE(r.source_sha,p.source_sha)
                WHERE p.id=?''',(page_id,)).fetchone()
    if not row or not (DATA/row['asset_path']).is_file():raise HTTPException(404,'Source PDF unavailable')
    return FileResponse(DATA/row['asset_path'],media_type='application/pdf')

@app.get('/api/search')
def search(q:str,limit:int=50,offset:int=0):
    q=q.strip()
    if not q:return []
    normalized=normalize(q)
    quoted='text : "'+q.replace('"','""')+'"'
    if normalized and not any(c.isalnum() and not 'א'<=c<='ת' for c in q):
        quoted+=' OR normalized : "'+normalized.replace('"','""')+'"'
    return search_words(quoted,max(1,min(limit,200)),max(0,offset))

class AnnotationWrite(BaseModel):
    text:str=Field(max_length=20000)
    direction:Literal['auto','ltr','rtl']='auto'
    base_revision:int=0
    operation_id:str=Field(min_length=16,max_length=120)
    deleted:bool=False
    components:list[dict]|None=None
    remember_meaning:bool=False

@app.put('/api/annotations/{occurrence_id}')
def annotation(occurrence_id:str,payload:AnnotationWrite):
    ensure_occurrence(occurrence_id)
    try:return write_annotation(occurrence_id,**payload.model_dump())
    except KeyError:raise HTTPException(404,'Unknown word')
    except EditConflict as exc:raise HTTPException(409,str(exc))
    except ValueError as exc:raise HTTPException(422,str(exc))

@app.get('/api/annotations/{occurrence_id}/history')
def annotation_history(occurrence_id:str):return history(occurrence_id)

@app.get('/api/preferences')
def preferences():
    with read() as conn:return {r['key']:json.loads(r['value_json']) for r in conn.execute('SELECT * FROM preference')}

class PreferenceWrite(BaseModel):
    value:object

@app.put('/api/preferences/{key}')
def preference(key:str,payload:PreferenceWrite):
    with transaction() as conn:
        if key=='location' and isinstance(payload.value,dict):
            previous=conn.execute('SELECT value_json FROM preference WHERE key=?',(key,)).fetchone()
            prior=json.loads(previous['value_json']) if previous else {}
            stamp=payload.value.get('updated_at',0);old_stamp=prior.get('updated_at',0) if isinstance(prior,dict) else 0
            if isinstance(stamp,(int,float)) and isinstance(old_stamp,(int,float)) and stamp<old_stamp:return {'saved':False}
        conn.execute('INSERT INTO preference VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json',(key,json_text(payload.value)))
    return {'saved':True}

@app.get('/api/bookmarks')
def bookmarks():
    with read() as conn:return [dict(r) for r in conn.execute('SELECT b.*,p.tractate,p.daf,p.amud FROM bookmark b JOIN page p ON p.id=b.page_id ORDER BY p.sequence')]

class BookmarkWrite(BaseModel):
    occurrence_id:str|None=None
    label:str=''

@app.put('/api/bookmarks/{page_id}')
def bookmark(page_id:str,payload:BookmarkWrite):
    ensure_page(page_id)
    with transaction() as conn:conn.execute('INSERT INTO bookmark(page_id,occurrence_id,label) VALUES(?,?,?) ON CONFLICT(page_id) DO UPDATE SET occurrence_id=excluded.occurrence_id,label=excluded.label',(page_id,payload.occurrence_id,payload.label))
    return {'saved':True}

@app.delete('/api/bookmarks/{page_id}')
def delete_bookmark(page_id:str):
    with transaction() as conn:conn.execute('DELETE FROM bookmark WHERE page_id=?',(page_id,))
    return {'deleted':True}

@app.get('/api/export')
def export():return JSONResponse(export_work(),headers={'Content-Disposition':'attachment; filename="shas-master-work.json"'})

@app.post('/api/restore')
def restore(payload:dict):
    backup('before-restore')
    try:return restore_work(payload)
    except (ValueError,KeyError) as exc:raise HTTPException(400,str(exc))

@app.get('/api/recovery')
def recovery_items():
    with read() as conn:
        items=[]
        for row in conn.execute("SELECT * FROM recovery_item WHERE status='pending' ORDER BY created_at,id"):
            item={k:row[k] for k in ('id','kind','reason','created_at')}|{'payload':json.loads(row['payload_json'])}
            if row['kind']=='correction':
                correction=json.loads(item['payload']['payload_json'])
                ids=[wid for wid in correction.get('words',[]) if isinstance(wid,str)]
                if ids:
                    placeholders=','.join('?' for _ in ids)
                    item['source_words']={word['id']:word['text'] for word in conn.execute(f'SELECT id,text FROM occurrence WHERE id IN ({placeholders})',ids)}
            items.append(item)
        return items

class RecoveryCorrection(BaseModel):
    base_revision:str
    kind:Literal['word','region','line','font','reading_order','boundaries']
    payload:dict

class RecoveryWrite(BaseModel):
    occurrence_id:str|None=None
    correction:RecoveryCorrection|None=None

@app.post('/api/recovery/{item_id}/resolve')
def recover_item(item_id:str,payload:RecoveryWrite):
    try:
        with transaction() as conn:
            row=conn.execute('SELECT * FROM recovery_item WHERE id=?',(item_id,)).fetchone()
            if not row:raise HTTPException(404,'Recovery item not found')
            if row['status']=='resolved':
                resolution=json.loads(row['resolution_json'] or '{}')
                if payload.correction and resolution.get('review_sha')!=digest(payload.model_dump()):
                    raise CorrectionConflict('Recovery item already resolved')
                return {'resolved':True,**resolution}
            saved=json.loads(row['payload_json'])
            resolution={}
            target=conn.execute('SELECT * FROM occurrence WHERE id=? AND active=1',(payload.occurrence_id,)).fetchone() if payload.occurrence_id else None
            if not target:raise HTTPException(400,'Select the source word')
            if row['kind']=='annotation':
                originals={r['occurrence_id'] for r in saved['annotations']}
                if len(originals)!=1:raise ValueError('Recovery requires one source word')
                original=next(iter(originals))
                retired=conn.execute('SELECT active FROM occurrence WHERE id=?',(original,)).fetchone()
                if original!=target['id'] and retired and not retired['active']:
                    from .annotations import carry_mapped_annotation
                    apply_correction(conn,target['page_id'],target['page_revision'],'anchor',{'id':original,'target_id':target['id']},'recovery-anchor-'+digest([item_id,target['id']]))
                    result=restore_into(conn,saved)
                    if result['unresolved']:raise ValueError('Revision history still incomplete')
                    result=carry_mapped_annotation(conn,original)
                elif original!=target['id']:
                    # The original record and provenance remain in the recovery item.
                    for revision in saved['annotations']:
                        revision['operation_id']='recovered-'+digest([item_id,target['id'],revision['operation_id']])
                    saved.pop('operations',None)
                    result=restore_into(conn,saved,{original:target['id']})
                else:result=restore_into(conn,saved)
                if result['unresolved']:raise ValueError('Revision history still incomplete')
            elif row['kind']=='correction':
                review=payload.correction
                if not review or review.kind!=saved['kind']:raise ValueError('Review the source correction before applying it')
                expected={'word':target['id'],'line':target['line_id']}.get(review.kind)
                if expected and review.payload.get('id')!=expected:raise ValueError('Correction target changed')
                if review.kind=='boundaries' and target['id'] not in review.payload.get('words',[]):raise ValueError('Correction target changed')
                fingerprint=digest(payload.model_dump())
                correction_id='recovered-'+digest([item_id,fingerprint])
                result=apply_correction(conn,target['page_id'],review.base_revision,review.kind,review.payload,correction_id)
                if isinstance(result,dict):resolution.update(result)
                resolution.update(review_sha=fingerprint,correction_id=correction_id)
                conn.execute("UPDATE source_issue SET resolved=1 WHERE kind='source-correction' AND json_extract(evidence_json,'$.correction')=?",(saved['id'],))
                conn.execute("UPDATE page SET extraction_state='complete' WHERE id=? AND extraction_state='issues' AND NOT EXISTS (SELECT 1 FROM source_issue WHERE page_id=? AND resolved=0)",(saved['page_id'],saved['page_id']))
            elif row['kind']=='bookmark':
                conn.execute('INSERT INTO bookmark(page_id,occurrence_id,label) VALUES(?,?,?) ON CONFLICT(page_id) DO UPDATE SET occurrence_id=excluded.occurrence_id,label=excluded.label',
                             (target['page_id'],target['id'],saved.get('label','')))
            else:raise ValueError('Unsupported recovery item')
            resolution.update(occurrence_id=target['id'],page_id=target['page_id'])
            conn.execute("UPDATE recovery_item SET status='resolved',resolution_json=? WHERE id=?",(json_text(resolution),item_id))
            return {'resolved':True,**resolution}
    except CorrectionConflict as exc:raise HTTPException(409,str(exc))
    except (KeyError,ValueError) as exc:raise HTTPException(400,str(exc))

@app.get('/api/backups')
def backups():return [{'name':p.name,'size':p.stat().st_size} for p in sorted((USER_DATA/'backups').glob('*.sqlite3'),reverse=True)]

@app.post('/api/backups')
def make_backup():return {'name':backup('manual').name}

@app.get('/api/backups/{name}')
def download_backup(name:str):
    if Path(name).name!=name or not name.endswith('.sqlite3'):raise HTTPException(400,'Invalid backup')
    path=USER_DATA/'backups'/name
    if not path.is_file():raise HTTPException(404,'Backup not found')
    return FileResponse(path,media_type='application/vnd.sqlite3',filename=name)

class SavedMeaning(BaseModel):
    id:str
    text:str
    direction:Literal['auto','ltr','rtl']

class SavedMeanings(BaseModel):
    items:list[SavedMeaning]
    offset:int
    total:int

@app.get('/api/suggestions/{occurrence_id}')
def word_suggestions(occurrence_id:str,
                     offset:Annotated[int,Query(ge=0)]=0,
                     limit:Annotated[int,Query(ge=1,le=100)]=24) -> SavedMeanings:
    from .saved_meanings import suggestions_for_word
    ensure_occurrence(occurrence_id)
    try:return SavedMeanings(**suggestions_for_word(occurrence_id,offset,limit))
    except KeyError:raise HTTPException(404,'Unknown word')

class ForgetMeaning(BaseModel):
    text:str=Field(max_length=20000)

@app.delete('/api/suggestions/{occurrence_id}')
def forget_meaning(occurrence_id:str,payload:ForgetMeaning):
    from .saved_meanings import forget
    ensure_occurrence(occurrence_id)
    try:forget(occurrence_id,payload.text)
    except KeyError:raise HTTPException(404,'Unknown word')
    return {'deleted':True}

class CorrectionWrite(BaseModel):
    id:str
    base_revision:str
    kind:Literal['word','region','line','font','reading_order','boundaries']
    payload:dict

@app.post('/api/pages/{page_id}/corrections')
def correct_source(page_id:str,payload:CorrectionWrite):
    ensure_page(page_id)
    try:
        with transaction() as conn:
            result=apply_correction(conn,page_id,payload.base_revision,payload.kind,payload.payload,payload.id)
    except CorrectionConflict as exc:raise HTTPException(409,str(exc))
    except (KeyError,ValueError) as exc:raise HTTPException(400,str(exc))
    return {'saved':True,'id':payload.id,**(result if isinstance(result,dict) else {})}

def correction_geometry(page_id,revision):
    ensure_page(page_id)
    try:geometry=load_geometry(page_id)
    except KeyError:raise HTTPException(409,'Page extraction pending')
    if revision is not None and geometry['revision']!=revision:
        raise HTTPException(409,'Source revision changed')
    return geometry

@app.get('/api/pages/{page_id}/source')
def source_line(page_id:str,line_id:str,revision:str|None=None):
    geometry=correction_geometry(page_id,revision)
    return [word for word in geometry['words'] if word['line']==line_id]

@app.get('/api/pages/{page_id}/source/{occurrence_id}')
def source_word(page_id:str,occurrence_id:str,revision:str|None=None):
    geometry=correction_geometry(page_id,revision)
    word=next((w for w in geometry['words'] if w['id']==occurrence_id),None)
    if not word:raise HTTPException(404,'Unknown source word')
    return word

@app.get('/api/pages/{page_id}/source/{occurrence_id}/image')
def source_image(page_id:str,occurrence_id:str,glyph:int|None=None,include:str='',revision:str|None=None):
    geometry=correction_geometry(page_id,revision)
    word=next((w for w in geometry['words'] if w['id']==occurrence_id),None)
    if not word:raise HTTPException(404,'Unknown source word')
    if glyph is not None:
        if glyph<0 or glyph>=len(word.get('glyphs',[])):raise HTTPException(404,'Unknown glyph')
        item=word['glyphs'][glyph]
        bounds=[item.get('ink_x',item['x']),item['top'],item.get('ink_r',item['r']),item['bottom']]
    elif include:
        ids=set(include.split(','))|{occurrence_id}
        selected=[item for item in geometry['words'] if item['line']==word['line'] and item['id'] in ids]
        if len(selected)!=len(ids):raise HTTPException(400,'Source words must share a line')
        bounds=[min(w['x'] for w in selected),min(w['top'] for w in selected),max(w['r'] for w in selected),max(w['bottom'] for w in selected)]
    else:bounds=[word['x'],word['top'],word['r'],word['bottom']]
    if CORPUS:
        from .glyph_preview import preview
        return Response(preview(geometry,bounds),media_type='image/svg+xml')
    import pymupdf
    with read() as conn:row=conn.execute('SELECT asset_path FROM page_source WHERE page_id=? AND source_sha=?',(page_id,geometry['source_sha'])).fetchone()
    if not row or not (DATA/row['asset_path']).is_file():raise HTTPException(404,'Source PDF unavailable')
    with pymupdf.open(DATA/row['asset_path']) as doc:
        clip=pymupdf.Rect(bounds)+(-.6,-.6,.6,.6)
        pix=doc[0].get_pixmap(matrix=pymupdf.Matrix(6,6),clip=clip,alpha=False)
        return Response(pix.tobytes('png'),media_type='image/png')

@app.post('/api/backups/{name}/restore')
def restore_backup(name:str):
    import sqlite3
    if Path(name).name!=name or not name.endswith('.sqlite3'):raise HTTPException(400,'Invalid backup')
    path=USER_DATA/'backups'/name
    if not path.is_file():raise HTTPException(404,'Backup not found')
    backup('before-restore')
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='work_backup'").fetchone():
            payload=load_backup(path)
        else:
            conn.execute('BEGIN')
            payload=export_from_connection(conn)
    try:return restore_work(payload)
    except (ValueError,KeyError) as exc:raise HTTPException(400,str(exc))

if FRONTEND.is_dir():
    app.mount('/',StaticFiles(directory=FRONTEND,html=True),name='interface')
