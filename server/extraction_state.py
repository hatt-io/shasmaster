"""Inputs that determine a source extraction, separate from learner work."""
from functools import lru_cache
from importlib.metadata import version
import subprocess
from .config import DATA,OCR_REVISION
from .db import digest


@lru_cache(maxsize=1)
def runtime_revision():
    return digest({package:version(package) for package in ('pymupdf','fonttools','beautifulsoup4')})


@lru_cache(maxsize=1)
def ocr_runtime_revision():
    from .ocr import engine
    try:
        _,provenance=engine()
    except (OSError,RuntimeError,subprocess.SubprocessError) as exc:
        provenance={'models':OCR_REVISION,'unavailable':str(exc)}
    return digest(provenance)


def queue_stale_pages(conn,rules_revision,retry_failures=False):
    runtime=runtime_revision();ocr=ocr_runtime_revision()
    queued=conn.execute('''
        UPDATE page SET extraction_state='pending'
        WHERE acquisition_state='complete'
          AND (? OR extraction_state!='failed')
          AND (extraction_state='failed' OR NOT EXISTS (
              SELECT 1 FROM page_revision r
              WHERE r.id=page.active_revision AND r.source_sha=page.source_sha
                AND r.rules_revision=? AND r.runtime_revision=?
                AND (r.ocr_runtime_revision IS NULL OR r.ocr_runtime_revision=?)
          ))
    ''',(retry_failures,rules_revision,runtime,ocr)).rowcount
    for page in conn.execute("SELECT p.id,p.active_revision,r.geometry_path,r.vector_path FROM page p JOIN page_revision r ON r.id=p.active_revision WHERE p.acquisition_state='complete' AND p.extraction_state IN ('complete','issues')").fetchall():
        if any(not path or not (DATA/path).is_file() for path in (page['geometry_path'],page['vector_path'])):
            queued+=conn.execute("UPDATE page SET extraction_state='pending' WHERE id=? AND active_revision=?",(page['id'],page['active_revision'])).rowcount
    return queued
