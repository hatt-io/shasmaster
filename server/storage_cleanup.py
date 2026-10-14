"""Remove unreferenced extraction files; retain every registered revision."""
from .config import DATA
from .db import read
from .source_jobs import source_lock


def cleanup_generated(*, apply=False):
    with source_lock('printed-extraction', blocking=False), read() as conn:
        # Keep the reference set fixed while removing orphaned files.
        conn.execute('BEGIN IMMEDIATE')
        rows=conn.execute('SELECT geometry_path,vector_path FROM page_revision').fetchall()
        referenced={(DATA/row[key]).resolve() for row in rows
                    for key in ('geometry_path','vector_path') if row[key]}
        if not referenced:raise RuntimeError('No registered source revisions; refusing cleanup')
        missing=[path for path in referenced if not path.is_file()]
        if missing:raise RuntimeError(f'{len(missing)} registered source files are missing; refusing cleanup')
        report={'applied':apply,'retained_revisions':len(rows),'files':0,'bytes':0,'folders':{}}
        for name,suffix in (('geometry','.json.gz'),('vectors','.svg.gz')):
            files=0;size=0
            for path in (DATA/name).iterdir():
                if path.is_symlink() or not path.is_file():continue
                if '_revision_' not in path.name or not path.name.endswith(suffix):continue
                if path.resolve() in referenced:continue
                length=path.stat().st_size
                if apply:path.unlink()
                files+=1;size+=length
            report['folders'][name]={'files':files,'bytes':size}
            report['files']+=files;report['bytes']+=size
        conn.rollback()
        return report
