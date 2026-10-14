"""Replace exported font files and duplicate templates with one bounded store."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import zlib
from contextlib import closing
from .source_jobs import source_lock


def compact_fonts(destination):
    destination=Path(destination).resolve()
    with source_lock('prepare-content',blocking=False):
        manifest=json.loads((destination/'manifest.json').read_text())
        if not manifest.get('complete'):raise ValueError('Finish content preparation first')
        target=destination/'fonts.sqlite3'
        if target.exists():
            print(f'Prepared font store already exists: {target}',flush=True)
            return
        staging=destination/'fonts.sqlite3.part'
        staging.unlink(missing_ok=True)
        previous=sum(p.stat().st_size for folder in ('fonts','font-templates') for p in (destination/folder).glob('*.otf'))
        by_hash={};count=0;templates=0
        try:
            with closing(sqlite3.connect(staging)) as conn:
                conn.execute('PRAGMA max_page_count=262144')
                conn.execute('CREATE TABLE font_blob(sha TEXT PRIMARY KEY,content BLOB NOT NULL) WITHOUT ROWID')
                conn.execute('CREATE TABLE font(id TEXT PRIMARY KEY,sha TEXT NOT NULL REFERENCES font_blob(sha)) WITHOUT ROWID')
                conn.execute('CREATE TABLE template(fingerprint TEXT PRIMARY KEY,font_id TEXT NOT NULL REFERENCES font(id)) WITHOUT ROWID')
                conn.execute('PRAGMA foreign_keys=ON')
                for path in (destination/'fonts').glob('*.otf'):
                    content=path.read_bytes();sha=hashlib.sha256(content).hexdigest()
                    conn.execute('INSERT OR IGNORE INTO font_blob VALUES(?,?)',(sha,zlib.compress(content,9)))
                    conn.execute('INSERT INTO font VALUES(?,?)',(path.stem,sha))
                    by_hash.setdefault(sha,path.stem);count+=1
                for path in (destination/'font-templates').glob('*.otf'):
                    sha=hashlib.sha256(path.read_bytes()).hexdigest()
                    if sha not in by_hash:raise ValueError('Template has no matching reading font')
                    conn.execute('INSERT INTO template VALUES(?,?)',(path.stem,by_hash[sha]));templates+=1
                if not count or not templates:raise ValueError('No prepared fonts found')
                conn.commit()
                if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Font store integrity check failed')
            staging.replace(target)
            # Every removed template matched an actual reading font by its SHA-256.
            for folder in ('fonts','font-templates'):shutil.rmtree(destination/folder)
        finally:
            staging.unlink(missing_ok=True)
        print(f'Prepared font store: {count} font maps, {templates} template references; {previous:,} bytes became {target.stat().st_size:,} bytes',flush=True)
