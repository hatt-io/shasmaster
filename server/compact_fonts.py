"""Store repeated font outlines once, retaining byte-identical browser fonts."""
import json
from pathlib import Path
import shutil
from .source_jobs import source_lock
from .font_chunks import build


def compact_fonts(destination):
    destination=Path(destination).resolve()
    with source_lock('prepare-content',blocking=False):
        manifest=json.loads((destination/'manifest.json').read_text())
        if not manifest.get('complete'):raise ValueError('Finish content preparation first')
        target=destination/'fonts.sqlite3'
        if target.exists():
            print(f'Prepared font store already exists: {target}',flush=True)
            return
        build(destination,target)
        for folder in ('fonts','font-templates'):shutil.rmtree(destination/folder)
