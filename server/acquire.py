"""Resumable source acquisition. No passage translations are imported."""
import asyncio
import hashlib
import json
from pathlib import Path
import httpx
from .config import DATA, OCR_MODEL_PATH
from .db import migrate, read, transaction, job_progress, json_text
from .catalogue import initialize_catalogue
from .source_jobs import source_lock
from .source_assets import retain_pdf,retain_catalogue_sources

async def download(client, url, path):
    partial = path.with_suffix(path.suffix+'.part')
    size = partial.stat().st_size if partial.exists() else 0
    headers = {'Range':f'bytes={size}-'} if size else {}
    async with client.stream('GET',url,headers=headers) as response:
        response.raise_for_status()
        append = size and response.status_code == 206
        if append and not response.headers.get('content-range','').startswith(f'bytes {size}-'):
            raise ValueError('Unexpected resume offset')
        with partial.open('ab' if append else 'wb') as handle:
            async for chunk in response.aiter_bytes(256*1024):
                handle.write(chunk)
    partial.replace(path)
    return dict(response.headers)

def sha_file(path):
    h=hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

async def acquire_pages(workers=4):
    with source_lock('printed-corpus',blocking=False):
        await _acquire_pages(workers)


async def _acquire_pages(workers=4):
    migrate(); total=initialize_catalogue()
    retain_catalogue_sources()
    with read() as conn:
        pending=[dict(r) for r in conn.execute("SELECT * FROM page WHERE acquisition_state!='complete' ORDER BY sequence")]
        done=conn.execute("SELECT count(*) FROM page WHERE acquisition_state='complete'").fetchone()[0]
    queue=asyncio.Queue()
    for page in pending:queue.put_nowait(page)
    errors=0
    job_progress('printed-corpus','acquire','running',done,total)
    async with httpx.AsyncClient(follow_redirects=True,timeout=httpx.Timeout(120,connect=30),limits=httpx.Limits(max_connections=workers),headers={'User-Agent':'ShasMaster/0.1 private local study'}) as client:
        async def worker():
            nonlocal done,errors
            while True:
                try:page=queue.get_nowait()
                except asyncio.QueueEmpty:return
                path=DATA/'pdf'/f"{page['id']}.pdf"
                error=None
                for attempt in range(5):
                    try:
                        response=await client.get(page['source_url']+'&format=json');response.raise_for_status(); metadata=response.json()
                        if not metadata.get('success'):raise ValueError(json_text(metadata))
                        with transaction() as conn:
                            conn.execute('UPDATE page SET physical_page=?,source_metadata=?,acquisition_state=? WHERE id=?',(metadata['page_number'],json_text(metadata),'downloading',page['id']))
                        # Previously acquired complete source files are adopted, not downloaded again.
                        if not path.exists() or (metadata.get('file_size') and path.stat().st_size!=int(metadata['file_size'])):
                            headers=await download(client,page['source_url'],path)
                        else:headers={}
                        with path.open('rb') as handle:
                            if handle.read(5)!=b'%PDF-':raise ValueError('Source response is not a PDF')
                        if metadata.get('file_size') and path.stat().st_size!=int(metadata['file_size']):raise ValueError('Incomplete source download')
                        sha=sha_file(path)
                        retained={'url':page['source_url'],'metadata':metadata,'headers':headers,'sha256':sha,'edition':page['edition']}
                        asset=retain_pdf(page|{'asset_path':str(path.relative_to(DATA)),'source_sha':sha},metadata=retained)
                        (DATA/'source'/f"{page['id']}.json").write_text(json_text(retained))
                        with transaction() as conn:
                            conn.execute("UPDATE page SET asset_path=?,source_sha=?,acquisition_state='complete',error=NULL,modified_at=CURRENT_TIMESTAMP WHERE id=?",(asset,sha,page['id']))
                        done+=1;error=None;break
                    except (httpx.HTTPError,OSError,ValueError,KeyError) as exc:
                        error=str(exc)
                        if attempt<4:await asyncio.sleep(min(2**attempt,16))
                if error:
                    errors+=1
                    with transaction() as conn:conn.execute("UPDATE page SET acquisition_state='failed',error=? WHERE id=?",(error,page['id']))
                job_progress('printed-corpus','acquire','running',done,total,failures=errors,last_page=page['id'])
                if done%50==0 or error:print(f'PDFs {done}/{total}; failures {errors}; {page["id"]}',flush=True)
                queue.task_done()
        await asyncio.gather(*(worker() for _ in range(workers)))
    job_progress('printed-corpus','acquire','complete' if done==total else 'incomplete',done,total,failures=errors)
    print(f'PDF acquisition {done}/{total}; failures {errors}',flush=True)
    if done!=total:raise RuntimeError(f'PDF acquisition incomplete: {done}/{total}; rerun acquisition to resume')

async def acquire_attribution():
    async with httpx.AsyncClient(follow_redirects=True,timeout=60) as client:
        for name,url in [('shas-api.html','https://www.shas.org/daf-pdf/api/api-documentation.html'),('hebrewbooks-terms.html','https://web.archive.org/web/20101028043253id_/http://hebrewbooks.org/media/terms.html')]:
            response=await client.get(url);response.raise_for_status();(DATA/'source'/name).write_bytes(response.content)
    (DATA/'source'/'ATTRIBUTION.txt').write_text('Scanned Shas provided courtesy of Shas.org, HebrewBooks.org and Moznaim / הוצאת ח. וגשל. Retain original notices. Private, non-commercial educational use. See shas-api.html and hebrewbooks-terms.html for the retained source terms.\n')

async def acquire_ocr():
    migrate();OCR_MODEL_PATH.mkdir(parents=True,exist_ok=True)
    job_progress('ocr-models','acquire','running',0,2)
    sources=[]
    async with httpx.AsyncClient(follow_redirects=True,timeout=120) as client:
        for language in ('heb','eng'):
            url=f'https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/HEAD/{language}.traineddata'
            path=OCR_MODEL_PATH/(language+'.traineddata')
            if not path.exists():await download(client,url,path)
            sources.append({'language':language,'url':url,'sha256':sha_file(path)})
            job_progress('ocr-models','acquire','running',len(sources),2)
        license_path=OCR_MODEL_PATH/'LICENSE'
        if not license_path.exists():await download(client,f'https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/HEAD/LICENSE',license_path)
    (DATA/'source'/'ocr-source.json').write_text(json_text({'models':sources}))
    job_progress('ocr-models','acquire','complete',2,2)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('kind',choices=['pages','attribution','ocr']);parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    if args.kind=='attribution':asyncio.run(acquire_attribution())
    elif args.kind=='ocr':asyncio.run(acquire_ocr())
    else:asyncio.run(acquire_pages(args.workers))
