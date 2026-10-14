"""Prepared, read-only font data shared by reading and source corrections."""
from contextlib import closing
import sqlite3
import zlib
from .config import CORPUS


def font_bytes(identifier, *, template=False):
    if CORPUS is None:
        raise ValueError('Prepared fonts unavailable')
    path=CORPUS/'fonts.sqlite3'
    if not path.is_file():
        # Development export compatibility while preparation is in progress.
        return (CORPUS/('font-templates' if template else 'fonts')/(identifier+'.otf')).read_bytes()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)) as conn:
        if template:
            row=conn.execute('SELECT b.content FROM template t JOIN font f ON f.id=t.font_id JOIN font_blob b ON b.sha=f.sha WHERE t.fingerprint=?',(identifier,)).fetchone()
        else:
            row=conn.execute('SELECT b.content FROM font f JOIN font_blob b ON b.sha=f.sha WHERE f.id=?',(identifier,)).fetchone()
    if row is None:
        raise FileNotFoundError('Prepared font unavailable: '+identifier)
    return zlib.decompress(row[0])
