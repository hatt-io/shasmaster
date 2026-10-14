from contextlib import closing, contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import zlib
from .config import DATABASE, DATA, ROOT, USER_DATA

_write_lock = threading.RLock()
_database = ContextVar('shas_database',default=DATABASE)
_progress_database = ContextVar('shas_progress_database',default=None)
MAX_DATABASE_BYTES = 1024 * 1024 * 1024
MAX_BACKUP_BYTES = 256 * 1024 * 1024
PACKED_TEXT_HEADER = b'SHASZ1\0'


def pack_text(value):
    if value is None or isinstance(value, bytes):
        return value
    encoded = value.encode('utf-8')
    packed = PACKED_TEXT_HEADER + zlib.compress(encoded)
    return packed if len(packed) < len(encoded) else value


def unpack_text(value):
    if isinstance(value, bytes):
        if not value.startswith(PACKED_TEXT_HEADER):
            raise ValueError('Unknown compressed dictionary storage format')
        return zlib.decompress(value[len(PACKED_TEXT_HEADER):]).decode('utf-8')
    return value

class StorageLimitError(RuntimeError):
    pass

@contextmanager
def database_scope(path,progress=None):
    database_token=_database.set(Path(path))
    progress_token=_progress_database.set(progress)
    try:yield
    finally:
        _progress_database.reset(progress_token)
        _database.reset(database_token)

def connect(database=None, *, create=False):
    path = Path(database or _database.get()).resolve()
    if not create and not path.is_file():
        raise FileNotFoundError(
            'The app database is missing. Restore saved work or explicitly run setup; '
            'normal app commands will not create an empty replacement.')
    conn = sqlite3.connect(path.as_uri() + ('?mode=rwc' if create else '?mode=rw'),
                           uri=True, timeout=60, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.create_function('shas_pack_text', 1, pack_text, deterministic=True)
        conn.create_function('shas_unpack_text', 1, unpack_text, deterministic=True)
        page_size = conn.execute('PRAGMA page_size').fetchone()[0]
        maximum_pages = MAX_DATABASE_BYTES // page_size
        actual_limit = conn.execute(f'PRAGMA max_page_count={maximum_pages}').fetchone()[0]
        if actual_limit > maximum_pages:
            raise StorageLimitError(
                'Database exceeds the 1 GB storage limit; compact or recover it before writing')
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=60000')
        conn.execute('PRAGMA journal_size_limit=16777216')
        conn.execute('PRAGMA wal_autocheckpoint=256')
        return conn
    except BaseException:
        conn.close()
        raise

@contextmanager
def read(database=None, *, create=False):
    conn = connect(database, create=create)
    try:
        yield conn
    finally:
        conn.close()

@contextmanager
def transaction(database=None):
    with _write_lock:
        conn = connect(database)
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException as exc:
            conn.rollback()
            if getattr(exc, 'sqlite_errorcode', None) == sqlite3.SQLITE_FULL:
                raise StorageLimitError(
                    'The change was not saved: the database reached its storage limit '
                    'or the disk is full.') from exc
            raise
        finally:
            conn.close()

def migrate(*, initialize=False):
    with _write_lock, read(create=initialize) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        for migration in sorted((Path(__file__).parent / 'migrations').glob('*.sql')):
            version = int(migration.name.split('_')[0])
            conn.execute('BEGIN IMMEDIATE')
            try:
                current = conn.execute('PRAGMA user_version').fetchone()[0]
                if version > current:
                    statement = ''
                    for line in migration.read_text().splitlines(keepends=True):
                        statement += line
                        if sqlite3.complete_statement(statement):
                            conn.execute(statement);statement = ''
                    if statement.strip():conn.execute(statement)
                    conn.execute(f'PRAGMA user_version={version}')
                conn.commit()
            except BaseException:
                conn.rollback();raise

def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def digest(value):
    return hashlib.sha256(json_text(value).encode()).hexdigest()

def get_meta(key, default=None):
    with read() as conn:
        row = conn.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
    return row['value'] if row else default

def set_meta(key, value):
    with transaction() as conn:
        conn.execute('INSERT INTO metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))

def job_progress(job_id, kind, state, completed=0, total=None, **detail):
    with transaction(_progress_database.get()) as conn:
        conn.execute('INSERT INTO job(id,kind,state,completed,total,detail_json) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,completed=excluded.completed,total=excluded.total,detail_json=excluded.detail_json,updated_at=CURRENT_TIMESTAMP', (job_id, kind, state, completed, total, json_text(detail)))

def backup(reason='scheduled', *, directory=None):
    """Snapshot learner work, not reproducible dictionary/model/search data."""
    from .annotations import export_from_connection
    directory = Path(directory) if directory is not None else USER_DATA / 'backups'
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path = directory / f'{stamp}-{reason}.work.sqlite3'
    with _write_lock, read() as source:
        source.execute('BEGIN')
        payload = json_text(export_from_connection(source)).encode('utf-8')
        fingerprint = hashlib.sha256(payload).hexdigest()
        snapshots = sorted(directory.glob('*.work.sqlite3'))
        if snapshots:
            previous = load_backup(snapshots[-1])
            if digest(previous) == fingerprint:
                return snapshots[-1]
        packed = zlib.compress(payload)
        used = sum(item.stat().st_size for item in directory.glob('*.sqlite3'))
        # Allow SQLite page/header overhead as well as the new compressed work.
        if used + len(packed) + 65536 > MAX_BACKUP_BYTES:
            raise StorageLimitError('Backup storage is full; existing snapshots were preserved')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix='codex-tmp-backup-',
                                             suffix='.sqlite3', delete=False) as output:
                temporary = Path(output.name)
            destination = sqlite3.connect(temporary)
            try:
                destination.execute('CREATE TABLE work_backup(format TEXT NOT NULL, '
                                    'sha256 TEXT NOT NULL, payload BLOB NOT NULL)')
                destination.execute('INSERT INTO work_backup VALUES(?,?,?)',
                                    ('shasmaster-work-zlib-v1', fingerprint, packed))
                destination.commit()
            finally:
                destination.close()
            with temporary.open('r+b') as output:
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        # Keep pre-restore/manual snapshots separately; never remove them here.
        if reason == 'scheduled':
            for old in sorted(directory.glob('*-scheduled.work.sqlite3'))[:-14]:
                old.unlink()
    return path


def load_backup(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        row = conn.execute('SELECT format,sha256,payload FROM work_backup').fetchone()
    if row is None or row[0] != 'shasmaster-work-zlib-v1':
        raise ValueError('Unsupported work backup')
    payload = zlib.decompress(row[2])
    if hashlib.sha256(payload).hexdigest() != row[1]:
        raise ValueError('Work backup is damaged')
    return json.loads(payload)
