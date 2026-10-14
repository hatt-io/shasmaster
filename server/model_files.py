"""Identify the local model files actually used; never prescribe a release."""
import hashlib
import json
from pathlib import Path
from importlib.metadata import distributions


def installed_versions():
    """Observe installed releases, including transitive dependencies."""
    return dict(sorted((item.metadata['Name'].lower(), item.version) for item in distributions()
                       if item.metadata.get('Name')))


def model_fingerprint(directory):
    directory = Path(directory)
    records = []
    if directory.is_dir():
        for path in sorted(directory.rglob('*')):
            if not path.is_file() or '.cache' in path.relative_to(directory).parts:
                continue
            if path.suffix not in ('.json', '.safetensors', '.bin', '.pt', '.onnx', '.traineddata', '.txt', '.model', '.py'):
                continue
            with path.open('rb') as stream:
                records.append([str(path.relative_to(directory)), hashlib.file_digest(stream, 'sha256').hexdigest()])
    return hashlib.sha256(json.dumps(records, separators=(',', ':')).encode()).hexdigest() if records else 'not-downloaded'
