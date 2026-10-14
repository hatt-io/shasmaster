"""Keep page membership in the coarse index; exact matching uses word records."""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import sqlite3
from .content_codec import read_page


def page_text(path):
    page=read_page(path)
    return page['id'],' '.join(w['text'] for w in page['words']),' '.join(w['normalized'] for w in page['words'])


def build(source,target):
    source=Path(source);target=Path(target)
    with sqlite3.connect(target/'catalogue.sqlite3') as conn,ProcessPoolExecutor(max_workers=8) as workers:
        conn.execute('DROP TABLE retained_page_text')
        conn.execute("CREATE VIRTUAL TABLE retained_page_text USING fts5(page_id UNINDEXED,text,normalized,content='',contentless_delete=1,detail=none,tokenize='unicode61 remove_diacritics 2')")
        ids=dict(conn.execute('SELECT page_id,id FROM retained_page_search_id'))
        for i,(page,text,normalized) in enumerate(workers.map(page_text,sorted((source/'pages').glob('*.shas')),chunksize=8),1):
            conn.execute('INSERT INTO retained_page_text(rowid,page_id,text,normalized) VALUES(?,?,?,?)',(ids[page],page,text,normalized))
            if i%1000==0:print(f'Indexed {i} pages without duplicate position records',flush=True)
        conn.execute("INSERT INTO retained_page_text(retained_page_text) VALUES('optimize')")
        conn.commit();conn.execute('VACUUM')
    print(f'Catalogue: {(target/"catalogue.sqlite3").stat().st_size:,} bytes',flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('source');parser.add_argument('target')
    args=parser.parse_args();build(args.source,args.target)
