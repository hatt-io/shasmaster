"""Repack immutable prepared content in parallel, preserving every source value."""
from concurrent.futures import ProcessPoolExecutor
from collections import deque
from pathlib import Path
import hashlib
import json
import lzma
import shutil
import sqlite3
from .content_codec import read_page
from .compact_page import encode,decode,share


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def prepare_page(path):
    page=read_page(path)
    return path.name,encode(page,compress=False),canonical_digest(page)


def finish_page(target,name,raw,metrics,before):
    packed=b'SHAS3'+lzma.compress(raw,preset=6)
    after=canonical_digest(decode(packed,metrics))
    path=target/'pages'/name;staging=path.with_suffix('.part')
    staging.write_bytes(packed);staging.replace(path)
    return name,len(packed),hashlib.sha256(packed).hexdigest(),before,after


def repack(source,target):
    source=Path(source).resolve();target=Path(target).resolve()
    if source==target:raise ValueError('Repack into a separate destination')
    if (target/'manifest.json').exists() and json.loads((target/'manifest.json').read_text()).get('complete'):
        raise FileExistsError('Do not replace a complete corpus')
    if shutil.disk_usage(source).free<2*1024**3:raise RuntimeError('Preserve 2 GiB free space')
    target.mkdir(parents=True,exist_ok=True);(target/'pages').mkdir(exist_ok=True)
    manifest=json.loads((source/'manifest.json').read_text());manifest['complete']=False
    (target/'manifest.json').write_text(json.dumps(manifest,separators=(',',':')))
    values=[];indices={};pending=deque();total=0;completed=0;paths=sorted((source/'pages').glob('*.shas'))
    before_path=Path('codex-tmp-pages-before.txt');after_path=Path('codex-tmp-pages-after.txt')
    with before_path.open('w') as before,after_path.open('w') as after,ProcessPoolExecutor(max_workers=8) as readers,ProcessPoolExecutor(max_workers=8) as writers:
        def collect(future):
            nonlocal total,completed
            name,size,sha,old,new=future.result();total+=size;completed+=1
            manifest['pages'][Path(name).stem]['sha256']=sha
            before.write(name+' '+old+'\n');after.write(name+' '+new+'\n')
            if completed%500==0:print(f'Converted {completed}/{len(paths)} pages: {total:,} bytes; {len(values)} shared measurements',flush=True)
        for name,raw,digest in readers.map(prepare_page,paths,chunksize=4):
            shared,metrics=share(raw,values,indices,defer=True)
            pending.append(writers.submit(finish_page,target,name,shared,metrics,digest))
            if len(pending)>=16:collect(pending.popleft())
        while pending:collect(pending.popleft())
    (target/'measurements.json.xz').write_bytes(lzma.compress(json.dumps(values,ensure_ascii=False,separators=(',',':')).encode(),preset=6))
    for name in ('catalogue.sqlite3','ATTRIBUTION.txt','reading-blocks.json'):shutil.copyfile(source/name,target/name)
    with sqlite3.connect(target/'catalogue.sqlite3') as conn:
        if conn.execute('PRAGMA user_version').fetchone()[0]<27:
            conn.executescript(Path(__file__).with_name('migrations').joinpath('027_compact_page_font.sql').read_text())
            conn.execute('PRAGMA user_version=27');conn.commit();conn.execute('VACUUM')
    if not (target/'fonts.sqlite3').exists():
        with sqlite3.connect((source/'fonts.sqlite3').as_uri()+'?mode=ro',uri=True) as conn:
            shared_fonts=conn.execute('PRAGMA user_version').fetchone()[0]==2
        if shared_fonts:shutil.copyfile(source/'fonts.sqlite3',target/'fonts.sqlite3')
        else:
            from .font_chunks import build
            build(source/'fonts.sqlite3',target/'fonts.sqlite3')
    from .compact_search import build as compact_search
    compact_search(source,target)
    manifest['complete']=True;manifest['storage']='lossless-shared-v3'
    (target/'manifest.json').write_text(json.dumps(manifest,separators=(',',':')))
    print(f'All pages: {total:,} bytes; shared measurements: {(target/"measurements.json.xz").stat().st_size:,} bytes. Compare {before_path} and {after_path} before activation.',flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('source');parser.add_argument('target')
    args=parser.parse_args();repack(args.source,args.target)
