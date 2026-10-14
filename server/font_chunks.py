"""Share identical byte sequences across source fonts without changing any font."""
import hashlib
import struct
import zlib
from contextlib import contextmanager,closing

GEAR=tuple(int.from_bytes(hashlib.sha256(bytes([i])).digest()[:4],'little') for i in range(256))


def rolling_chunks(content):
    start=0;rolling=0
    for index,value in enumerate(content,1):
        rolling=((rolling<<1)+GEAR[value])&0xffffffff
        length=index-start
        if length>=64 and ((rolling&255)==0 or length>=1024):
            yield content[start:index];start=index;rolling=0
    if start<len(content):yield content[start:]


def chunks(content):
    from io import BytesIO
    from fontTools.cffLib import CFFFontSet
    boundaries={0,len(content)};tables={}
    count=struct.unpack_from('>H',content,4)[0]
    for i in range(count):
        tag,checksum,offset,length=struct.unpack_from('>4sIII',content,12+i*16)
        tables[tag]=(offset,length);boundaries.update((offset,offset+length))
    if b'CFF ' in tables:
        offset,length=tables[b'CFF '];cff=CFFFontSet();cff.decompile(BytesIO(content[offset:offset+length]),None)
        for name in cff.fontNames:
            index=cff[name].CharStrings.charStringsIndex
            boundaries.update(offset+index.offsetBase+pos for pos in index.offsets)
    elif b'glyf' in tables and b'loca' in tables:
        head=tables[b'head'][0];kind=struct.unpack_from('>h',content,head+50)[0]
        offset,length=tables[b'loca'];size=2 if kind==0 else 4
        positions=struct.unpack_from('>'+('H' if kind==0 else 'I')*(length//size),content,offset)
        boundaries.update(tables[b'glyf'][0]+pos*(2 if kind==0 else 1) for pos in positions)
    ordered=sorted(boundaries)
    if ordered[0]!=0 or ordered[-1]!=len(content):raise ValueError('Invalid font boundaries')
    for left,right in zip(ordered,ordered[1:]):yield from rolling_chunks(content[left:right])


def restore(conn,content):
    ids=struct.unpack('<'+'I'*(len(content)//4),content)
    found={}
    for start in range(0,len(ids),400):
        part=ids[start:start+400]
        found.update(conn.execute('SELECT id,content FROM chunk WHERE id IN ('+','.join('?' for _ in part)+')',part))
    return b''.join(zlib.decompress(found[i]) for i in ids)


@contextmanager
def font_sources(source):
    import sqlite3
    if source.is_file():
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro&immutable=1',uri=True)) as conn:
            yield ((sha,zlib.decompress(packed)) for sha,packed in conn.execute('SELECT sha,content FROM font_blob')),conn.execute('SELECT id,sha FROM font'),conn.execute('SELECT fingerprint,font_id FROM template')
    else:
        maps=[];by_hash={}
        def blobs():
            for path in sorted((source/'fonts').glob('*.otf')):
                content=path.read_bytes();sha=hashlib.sha256(content).hexdigest();maps.append((path.stem,sha))
                if sha not in by_hash:
                    by_hash[sha]=path.stem;yield sha,content
        def templates():
            for path in sorted((source/'font-templates').glob('*.otf')):
                sha=hashlib.sha256(path.read_bytes()).hexdigest()
                yield path.stem,by_hash[sha]
        yield blobs(),maps,templates()


def build(source,target):
    import sqlite3
    from contextlib import closing
    from pathlib import Path
    source=Path(source).resolve();target=Path(target).resolve()
    if target.exists():raise FileExistsError(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    staging=target.with_suffix('.part')
    if staging.exists():raise FileExistsError(staging)
    known={};next_id=0
    try:
        with font_sources(source) as (blobs,maps,templates),closing(sqlite3.connect(staging)) as dst:
            dst.execute('PRAGMA max_page_count=65536')
            dst.execute('PRAGMA user_version=2')
            dst.execute('CREATE TABLE chunk(id INTEGER PRIMARY KEY,content BLOB NOT NULL)')
            dst.execute('CREATE TABLE font_blob(sha BLOB PRIMARY KEY,content BLOB NOT NULL) WITHOUT ROWID')
            dst.execute('CREATE TABLE font(id BLOB PRIMARY KEY,sha BLOB NOT NULL) WITHOUT ROWID')
            dst.execute('CREATE TABLE template(fingerprint BLOB PRIMARY KEY,font_id BLOB NOT NULL) WITHOUT ROWID')
            for index,(sha,content) in enumerate(blobs,1):
                refs=[]
                for part in chunks(content):
                    key=hashlib.sha256(part).digest()
                    if key not in known:
                        next_id+=1;known[key]=next_id
                        dst.execute('INSERT INTO chunk VALUES(?,?)',(next_id,zlib.compress(part,9)))
                    refs.append(known[key])
                dst.execute('INSERT INTO font_blob VALUES(?,?)',(bytes.fromhex(sha),struct.pack('<'+'I'*len(refs),*refs)))
                if index%10000==0:
                    dst.commit();print(f'Shared {index} fonts; {len(known)} unique pieces; {staging.stat().st_size:,} bytes',flush=True)
            for table,rows in (('font',maps),('template',templates)):
                dst.executemany('INSERT INTO '+table+' VALUES(?,?)',[(bytes.fromhex(a),bytes.fromhex(b)) for a,b in rows])
            dst.commit()
        staging.replace(target)
    finally:staging.unlink(missing_ok=True)
    print(f'Shared font store: {target.stat().st_size:,} bytes',flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('source');parser.add_argument('target')
    args=parser.parse_args();build(args.source,args.target)
