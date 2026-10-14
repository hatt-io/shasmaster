"""Read-only prepared corpus access, independent of the learner's database."""
import json
from functools import lru_cache
from .config import CORPUS
from .content_codec import decode_page


def page_geometry(page_id):
    if CORPUS is None:
        raise RuntimeError('No prepared corpus configured')
    # Page identifiers come from the catalogue, but also reject path traversal.
    if not page_id or any(char not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for char in page_id):
        raise KeyError(page_id)
    path = CORPUS / 'pages' / (page_id + '.shas')
    if not path.is_file():
        raise KeyError(page_id)
    return decode_page(path.read_bytes())


def manifest():
    if CORPUS is None:
        raise RuntimeError('No prepared corpus configured')
    result = json.loads((CORPUS / 'manifest.json').read_text())
    if result.get('format') != 'shas-corpus-1' or not result.get('complete'):
        raise ValueError('Prepared corpus is incomplete or unsupported')
    return result


@lru_cache(maxsize=1)
def _reading_blocks():
    if CORPUS is None:
        return {}
    return json.loads((CORPUS / 'reading-blocks.json').read_text())


def reading_blocks(page_id):
    return _reading_blocks().get(page_id, [])
