"""First-run installation never overwrites an existing learner database."""
import os
import shutil
from .config import CORPUS, USER_DATA, DATABASE
from .source_jobs import source_lock
from .prepared_content import manifest


def initialize_user_data():
    if not CORPUS:
        raise RuntimeError('A prepared corpus is required')
    current = manifest()
    with source_lock('initialize-user-data'):
        marker = USER_DATA / 'installation.json'
        if DATABASE.is_file():
            if not marker.exists():
                from .db import json_text
                marker.write_text(json_text({'format': 'shas-install-1', 'pages': current['page_count']}))
            return
        if marker.exists():
            raise FileNotFoundError('The saved-work database is missing; restore a backup before starting')
        temporary = USER_DATA / 'catalogue-install.part'
        try:
            shutil.copyfile(CORPUS / 'catalogue.sqlite3', temporary)
            with temporary.open('rb') as source:
                os.fsync(source.fileno())
            temporary.replace(DATABASE)
            from .db import json_text
            marker.write_text(json_text({'format': 'shas-install-1', 'pages': current['page_count']}))
        finally:
            temporary.unlink(missing_ok=True)
