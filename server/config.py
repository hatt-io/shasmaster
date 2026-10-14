from pathlib import Path
import os
import sys
from .model_files import model_fingerprint

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('SHAS_DATA', str(ROOT / 'data'))).resolve()
CORPUS = Path(os.environ['SHAS_CORPUS']).resolve() if os.environ.get('SHAS_CORPUS') else None

def default_user_directory():
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'Shas Master'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Shas Master'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local' / 'share'))) / 'shas-master'

USER_DATA = Path(os.environ.get('SHAS_USER_DATA', str(default_user_directory() if CORPUS else DATA))).resolve()
DATABASE = USER_DATA / 'shasmaster.sqlite3'
FRONTEND = Path(os.environ.get('SHAS_FRONTEND', str(ROOT / 'dist'))).resolve()
HOST = '127.0.0.1'
PORT = int(os.environ.get('SHAS_PORT', '9473'))
EDITION = 'hebrewbooks-moznaim-vagshal-shasorg-2026-09-23'
OCR_MODEL_PATH = DATA / 'models' / 'tesseract' / 'current'
OCR_REVISION = model_fingerprint(OCR_MODEL_PATH)
if not CORPUS:
    for directory in ('pdf', 'source', 'geometry', 'vectors', 'models', 'catalogue', 'ocr'):
        (DATA / directory).mkdir(parents=True, exist_ok=True)
USER_DATA.mkdir(parents=True, exist_ok=True)
(USER_DATA / 'backups').mkdir(exist_ok=True)
