"""Reuse retained page files instead of duplicating the entire printed corpus."""
from collections import defaultdict
import gzip
import json

from .config import DATA, CORPUS
from .db import json_text, read, transaction

MAX_CACHED_PAGES = 24


def restore_catalogue():
    paths = defaultdict(list)
    for path in (DATA / 'geometry').glob('*_revision_*.json.gz'):
        paths[path.name.split('_revision_', 1)[0]].append(path)
    with read() as conn:
        pages = [dict(row) for row in conn.execute('SELECT * FROM page ORDER BY sequence')]
    restored = 0
    for page in pages:
        evidence_path = DATA / 'source' / (page['id'] + '.json')
        if not evidence_path.is_file():
            continue
        evidence = json.loads(evidence_path.read_text())
        source_sha = evidence['sha256']
        pdf = DATA / 'pdf' / 'sha256' / (source_sha + '.pdf')
        if not pdf.is_file():
            pdf = DATA / 'pdf' / (page['id'] + '.pdf')
        if not pdf.is_file():
            continue
        for path in sorted(paths[page['id']], key=lambda item: item.stat().st_mtime_ns, reverse=True):
            with gzip.open(path, 'rt', encoding='utf-8') as source:
                geometry = json.load(source)
            vector = DATA / 'vectors' / path.name.replace('.json.gz', '.svg.gz')
            if geometry.get('source_sha') != source_sha or not vector.is_file():
                continue
            words = geometry['words']
            with transaction() as conn:
                conn.execute('INSERT OR IGNORE INTO page_source(page_id,source_sha,asset_path,metadata_json) '
                             'VALUES(?,?,?,?)', (page['id'], source_sha, str(pdf.relative_to(DATA)), json_text(evidence)))
                conn.execute('INSERT OR IGNORE INTO page_revision '
                             '(id,page_id,source_sha,geometry_path,vector_path,extractor_revision,'
                             'rules_revision,runtime_revision,ocr_runtime_revision) VALUES(?,?,?,?,?,?,?,?,?)',
                             (geometry['revision'], page['id'], source_sha, str(path.relative_to(DATA)),
                              str(vector.relative_to(DATA)), geometry['extractor_revision'],
                              geometry.get('extraction_rules'), geometry.get('runtime_revision'),
                              geometry.get('ocr_runtime_revision')))
                conn.execute("UPDATE page SET source_sha=?,asset_path=?,source_metadata=?,physical_page=?,"
                             "width=?,height=?,active_revision=?,acquisition_state='complete',"
                             "extraction_state=?,error=NULL WHERE id=?",
                             (source_sha, str(pdf.relative_to(DATA)), json_text(evidence.get('metadata', {})),
                              evidence.get('metadata', {}).get('page_number'), geometry['width'], geometry['height'],
                              geometry['revision'], 'issues' if geometry.get('issues') else 'complete', page['id']))
                conn.execute('INSERT OR IGNORE INTO retained_page_search_id(page_id) VALUES(?)', (page['id'],))
                search_id = conn.execute('SELECT id FROM retained_page_search_id WHERE page_id=?',
                                         (page['id'],)).fetchone()['id']
                conn.execute('INSERT OR REPLACE INTO retained_page_text(rowid,page_id,text,normalized) VALUES(?,?,?,?)',
                             (search_id, page['id'], ' '.join(word['text'] for word in words),
                              ' '.join(word['normalized'] for word in words)))
                conn.executemany('INSERT OR IGNORE INTO page_font(page_id,font_fingerprint) VALUES(?,?)',
                                 [(page['id'], fingerprint) for fingerprint in geometry.get('fonts', [])])
            restored += 1
            break
        if restored and restored % 100 == 0:
            print(f'Reconnected {restored} retained pages', flush=True)
    print(f'Reconnected {restored}/{len(pages)} pages from local files', flush=True)
    return restored


def ensure_page(page_id, *, protected_pages=()):
    with read() as conn:
        row = conn.execute('SELECT r.id,r.geometry_path FROM page p JOIN page_revision r '
                           'ON r.id=p.active_revision WHERE p.id=?', (page_id,)).fetchone()
        if row is None:
            return
        exists = conn.execute('SELECT 1 FROM occurrence WHERE page_id=? AND page_revision=? AND active=1 LIMIT 1',
                              (page_id, row['id'])).fetchone()
        if exists:
            return
        retained = dict(row)
    if CORPUS:
        from .prepared_content import page_geometry
        geometry=page_geometry(page_id)
    else:
        with gzip.open(DATA / retained['geometry_path'], 'rt', encoding='utf-8') as source:
            geometry = json.load(source)
    with transaction() as conn:
        if conn.execute('SELECT 1 FROM occurrence WHERE page_id=? AND active=1 LIMIT 1', (page_id,)).fetchone():
            return
        for region in geometry['regions']:
            conn.execute('INSERT OR IGNORE INTO region VALUES(?,?,?,?,?)',
                         (region['id'], retained['id'], region['kind'], json_text(region['bounds']), region['reading_order']))
        for word in geometry['words']:
            compact = {key: value for key, value in word.items() if key != 'glyphs'}
            conn.execute('INSERT OR IGNORE INTO occurrence '
                         '(id,page_id,page_revision,region_id,line_id,text,normalized,geometry_json,reading_order,transcription_state) '
                         'VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (word['id'], page_id, retained['id'], word['region'], word['line'], word['text'],
                          word['normalized'], json_text(compact), word['reading_order'], word['state']))
        conn.execute('INSERT OR REPLACE INTO retained_page_cache(page_id) VALUES(?)', (page_id,))
        # Only untouched, reproducible page details may be discarded. Saved
        # annotations, corrections, bookmarks and anchor mappings protect a page.
        expendable = conn.execute('''SELECT c.page_id FROM retained_page_cache c
            WHERE c.page_id<>?
            AND NOT EXISTS(SELECT 1 FROM correction WHERE page_id=c.page_id)
            AND NOT EXISTS(SELECT 1 FROM bookmark WHERE page_id=c.page_id)
            AND NOT EXISTS(SELECT 1 FROM occurrence o JOIN annotation a ON a.occurrence_id=o.id WHERE o.page_id=c.page_id)
            AND NOT EXISTS(SELECT 1 FROM occurrence o JOIN anchor_mapping m ON m.old_id=o.id OR m.new_id=o.id WHERE o.page_id=c.page_id)
            ORDER BY c.accessed_at,c.page_id''', (page_id,)).fetchall()
        count = conn.execute('SELECT count(*) FROM retained_page_cache').fetchone()[0]
        expendable = [old for old in expendable if old['page_id'] not in protected_pages]
        for old in expendable[:max(0, count - MAX_CACHED_PAGES)]:
            conn.execute('DELETE FROM occurrence WHERE page_id=?', (old['page_id'],))
            conn.execute('DELETE FROM retained_page_cache WHERE page_id=?', (old['page_id'],))


def ensure_occurrence(occurrence_id):
    if occurrence_id:
        ensure_page(occurrence_id.split(':', 1)[0])


def search_words(query, limit, offset):
    # The small page index covers unopened pages too. Materialize only pages
    # needed for the requested result window, then use the original word search.
    with read() as conn:
        pages = [row['id'] for row in conn.execute('''SELECT p.id FROM page p WHERE p.id IN (
            SELECT m.page_id FROM retained_page_text f JOIN retained_page_search_id m ON m.id=f.rowid
            WHERE retained_page_text MATCH ?
            UNION SELECT page_id FROM printed_text WHERE printed_text MATCH ?)
            ORDER BY p.sequence''', (query, query))]
    result = []
    for page_id in pages:
        ensure_page(page_id)
        with read() as conn:
            rows = conn.execute('''SELECT f.occurrence_id,f.page_id,o.text,p.tractate,p.daf,p.amud
                FROM printed_text f JOIN occurrence o ON o.id=f.occurrence_id
                JOIN page p ON p.id=f.page_id
                WHERE printed_text MATCH ? AND f.page_id=? ORDER BY o.reading_order''', (query, page_id)).fetchall()
        for row in rows:
            if offset:
                offset -= 1
            else:
                result.append(dict(row))
                if len(result) == limit:
                    return result
    return result
