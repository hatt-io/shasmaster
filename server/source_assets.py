"""Retain the PDF and acquisition evidence for each source revision."""
import hashlib
import json
from .config import DATA
from .db import read,transaction,json_text,job_progress
from .source_jobs import source_lock


def retain_pdf(record,content=None,metadata=None):
    content=(DATA/record['asset_path']).read_bytes() if content is None else content
    sha=hashlib.sha256(content).hexdigest()
    if sha!=record['source_sha']:
        raise ValueError('Source PDF differs from its retained fingerprint')
    folder=DATA/'pdf'/'sha256';folder.mkdir(exist_ok=True)
    path=folder/(sha+'.pdf')
    with source_lock('pdf:'+sha):
        if not path.exists():
            partial=path.with_suffix('.pdf.part')
            partial.write_bytes(content);partial.replace(path)
    if metadata is None:
        evidence=DATA/'source'/f"{record['id']}.json"
        if evidence.exists():
            saved=json.loads(evidence.read_text())
            if saved.get('sha256')==sha:metadata=saved
        if metadata is None:
            metadata={'url':record['source_url'],'edition':record['edition'],
                      'sha256':sha,'physical_page':record.get('physical_page'),
                      'metadata':json.loads(record.get('source_metadata') or '{}')}
    relative=str(path.relative_to(DATA))
    with transaction() as conn:
        conn.execute('INSERT OR IGNORE INTO page_source(page_id,source_sha,asset_path,metadata_json) VALUES(?,?,?,?)',
                     (record['id'],sha,relative,json_text(metadata)))
        conn.execute('UPDATE page SET asset_path=? WHERE id=? AND source_sha=?',
                     (relative,record['id'],sha))
    return relative


def retain_catalogue_sources():
    with source_lock('source-assets'):
        with read() as conn:
            pages=[dict(row) for row in conn.execute('''
                SELECT p.* FROM page p
                WHERE p.asset_path IS NOT NULL AND p.source_sha IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM page_source s WHERE s.page_id=p.id AND s.source_sha=p.source_sha)
                ORDER BY p.sequence
            ''')]
        if not pages:return
        total=len(pages);completed=0;failures=0
        job_progress('source-assets','retain','running',0,total)
        for page in pages:
            try:
                retain_pdf(page);completed+=1
            except (OSError,ValueError) as exc:
                failures+=1
                with transaction() as conn:
                    conn.execute('INSERT INTO source_issue(page_id,kind,evidence_json) VALUES(?,?,?)',
                                 (page['id'],'source-retention',json_text({'source_sha':page['source_sha'],'error':str(exc)})))
                print(f"Source retention failed: {page['id']}: {exc}",flush=True)
            if (completed+failures)%100==0:
                job_progress('source-assets','retain','running',completed,total,failures=failures,last_page=page['id'])
        job_progress('source-assets','retain','complete' if not failures else 'incomplete',completed,total,failures=failures)
        print(f'Retained source PDFs: {completed}/{total}; failures {failures}',flush=True)
