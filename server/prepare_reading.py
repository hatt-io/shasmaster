"""Retain only the column boundaries used by reading order, not OCR caches."""
import gzip
import json
from pathlib import Path
from .config import DATA
from .db import read, json_text
from .source_context import printed_blocks
from .prepare_content import atomic_write


def prepare_reading(destination):
    destination=Path(destination)
    with read() as conn:
        pages=conn.execute('SELECT p.id,r.geometry_path FROM page p JOIN page_revision r ON r.id=p.active_revision ORDER BY p.sequence').fetchall()
    blocks={}
    for index,page in enumerate(pages):
        with gzip.open(DATA/page['geometry_path'],'rt',encoding='utf-8') as source:
            geometry=json.load(source)
        found=printed_blocks(geometry)
        if found:
            blocks[page['id']]=[{'id':block['id'],'bounds':block['bounds']} for block in found]
        if (index+1)%500==0:print(f'Prepared reading columns: {index+1}/{len(pages)}',flush=True)
    atomic_write(destination/'reading-blocks.json',json_text(blocks).encode())
    print(f'Reading columns prepared for {len(pages)} pages; OCR caches are not required',flush=True)
