"""Development-only export of prepared pages and browser fonts."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from .config import DATA, CORPUS
from .content_codec import encode_page
from .db import read, database_scope, migrate, transaction, json_text
from .reader_fonts import attach_fonts
from .prepare_fonts import browser_font, resolve_font_sources
from .source_jobs import source_lock


def atomic_write(path, content):
    staging = path.with_name(path.name + '.part')
    try:
        staging.write_bytes(content)
        staging.replace(path)
    finally:
        staging.unlink(missing_ok=True)


def prepare_content(destination):
    if CORPUS:
        raise RuntimeError('Content preparation belongs in the development environment')
    destination = Path(destination).resolve()
    if destination == DATA or DATA in destination.parents and destination.name in ('pdf', 'geometry', 'vectors'):
        raise ValueError('Use a separate prepared-content directory')
    if (destination/'fonts.sqlite3').exists():
        raise ValueError('Prepared releases are immutable; use a new destination for changed content')
    with source_lock('prepare-content', blocking=False):
        _prepare(destination)
    from .prepare_reading import prepare_reading
    from .compact_fonts import compact_fonts
    prepare_reading(destination)
    compact_fonts(destination)


def _prepare(destination):
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('pages', 'fonts', 'font-templates'):
        (destination / name).mkdir(exist_ok=True)
    manifest_path = destination / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
        'format': 'shas-corpus-1', 'complete': False, 'pages': {}}
    if manifest['format'] != 'shas-corpus-1':
        raise ValueError('Incompatible content export directory')
    manifest['complete'] = False
    atomic_write(manifest_path, json_text(manifest).encode())
    with read() as source:
        pages = [dict(row) for row in source.execute('SELECT * FROM page ORDER BY sequence')]
        revisions = {row['id']: dict(row) for row in source.execute('SELECT * FROM page_revision')}
        tractates = [dict(row) for row in source.execute('SELECT * FROM tractate ORDER BY sequence')]
        # A publisher's package never includes a learner's font corrections.
        mappings = [dict(row) for row in source.execute('SELECT * FROM font_mapping')
                    if not json.loads(row['provenance_json']).get('correction')]
    if any(page['active_revision'] not in revisions for page in pages):
        raise ValueError('Every catalogued page needs prepared source text before export')
    seed = destination / 'catalogue.sqlite3'
    with database_scope(seed):
        migrate(initialize=not seed.exists())
        with transaction() as conn:
            for row in tractates:
                insert_row(conn, 'tractate', row)
            for row in mappings:
                insert_row(conn, 'font_mapping', row)
    total_bytes = 0
    by_mapping = {(row['font_fingerprint'], row['glyph']): row['unicode'] for row in mappings}
    for index, page in enumerate(pages):
        if shutil.disk_usage(destination).free < 2 * 1024**3:
            raise RuntimeError('Content preparation stopped to preserve 2 GB of free space')
        revision = revisions[page['active_revision']]
        saved = manifest['pages'].get(page['id'])
        path = destination / 'pages' / (page['id'] + '.shas')
        if saved and saved['revision'] == revision['id'] and path.is_file():
            total_bytes += path.stat().st_size
            continue
        with gzip.open(DATA / revision['geometry_path'], 'rt', encoding='utf-8') as source:
            geometry = json.load(source)
        # Fonts must be prepared for the same baseline mapping used by the reader.
        for word in geometry['words']:
            for glyph in word.get('glyphs', []):
                if (glyph['font'], glyph['glyph']) in by_mapping:
                    glyph['text'] = by_mapping[glyph['font'], glyph['glyph']]
        resolve_font_sources(geometry, page['asset_path'])
        font_descriptors = attach_fonts(geometry, page['asset_path'])
        for descriptor in font_descriptors:
            font_path = destination / 'fonts' / (descriptor['id'] + '.otf')
            template = destination / 'font-templates' / (descriptor['fingerprint'] + '.otf')
            if not font_path.exists():
                atomic_write(font_path, browser_font(page['asset_path'], descriptor['fingerprint'], descriptor['mapping']))
            if not template.exists():
                atomic_write(template, font_path.read_bytes())
        # Rendering fields are derived from retained glyphs at load time. Do not
        # store a second per-letter copy produced by attach_fonts.
        for word in geometry['words']:
            word.pop('source_glyphs', None)
        geometry.pop('pdf', None)
        packed = encode_page(geometry)
        atomic_write(path, packed)
        total_bytes += len(packed)
        with database_scope(seed), transaction() as conn:
            conn.execute('PRAGMA defer_foreign_keys=ON')
            clean_page = dict(page, asset_path='', error=None)
            insert_row(conn, 'page', clean_page)
            clean_revision = dict(revision, geometry_path='pages/' + path.name, vector_path=None)
            insert_row(conn, 'page_revision', clean_revision)
            insert_row(conn, 'page_source', {'page_id': page['id'], 'source_sha': revision['source_sha'],
                       'asset_path': '', 'metadata_json': '{}'})
            conn.executemany('INSERT OR IGNORE INTO page_font(page_id,font_fingerprint) VALUES(?,?)',
                             [(page['id'], font['fingerprint']) for font in font_descriptors])
            conn.execute('INSERT OR IGNORE INTO retained_page_search_id(page_id) VALUES(?)', (page['id'],))
            search_id = conn.execute('SELECT id FROM retained_page_search_id WHERE page_id=?', (page['id'],)).fetchone()[0]
            words = geometry['words']
            conn.execute('INSERT OR REPLACE INTO retained_page_text(rowid,page_id,text,normalized) VALUES(?,?,?,?)',
                         (search_id, page['id'], ' '.join(word['text'] for word in words),
                          ' '.join(word['normalized'] for word in words)))
        manifest['pages'][page['id']] = {'revision': revision['id'], 'sha256': hashlib.sha256(packed).hexdigest()}
        if (index + 1) % 25 == 0:
            atomic_write(manifest_path, json_text(manifest).encode())
            print(f'Prepared {index+1}/{len(pages)} pages; page content {total_bytes/1024**2:.1f} MiB', flush=True)
    attribution = DATA / 'source' / 'ATTRIBUTION.txt'
    if attribution.is_file():
        atomic_write(destination / 'ATTRIBUTION.txt', attribution.read_bytes())
    with sqlite3.connect(seed) as conn:
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        conn.execute('PRAGMA journal_mode=DELETE')
    manifest['complete'] = True
    manifest['page_count'] = len(pages)
    atomic_write(manifest_path, json_text(manifest).encode())
    print(f'Prepared corpus complete: {len(pages)} pages in {destination}', flush=True)


def insert_row(conn, table, row):
    columns = ','.join(row)
    conn.execute(f'INSERT OR IGNORE INTO {table}({columns}) VALUES({",".join("?" for _ in row)})', tuple(row.values()))
