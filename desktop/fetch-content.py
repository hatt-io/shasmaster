"""Fetch a prepared release archive for a build, never source PDFs."""
import hashlib
import os
from pathlib import Path
import shutil
import tarfile
import urllib.request
from urllib.parse import urlparse

root=Path(__file__).resolve().parent.parent
url=os.environ.get('SHAS_CONTENT_URL','');expected=os.environ['SHAS_CONTENT_SHA256'].lower()
local=os.environ.get('SHAS_CONTENT_ARCHIVE')
if (not local and urlparse(url).scheme!='https') or len(expected)!=64 or any(c not in '0123456789abcdef' for c in expected):
    raise ValueError('A content archive or HTTPS URL and SHA-256 digest are required')
destination=root/'data'/'prepared'
if destination.exists():raise FileExistsError('Prepared content already exists')
archive=Path(local).resolve() if local else root/'codex-tmp-content.tar.gz'
if local and archive != root/'codex-tmp-content.tar.gz':
    raise ValueError('Local build archive must be codex-tmp-content.tar.gz in the project root')
try:
    digest=hashlib.sha256();size=0
    from contextlib import nullcontext
    with (archive.open('rb') if local else urllib.request.urlopen(url,timeout=60)) as response, (nullcontext(None) if local else archive.open('xb')) as output:
        while chunk:=response.read(1024*1024):
            size+=len(chunk)
            if size>5*1024**3 or shutil.disk_usage(root).free<2*1024**3:
                raise ValueError('Prepared content exceeds the build storage limit')
            digest.update(chunk)
            if output is not None:output.write(chunk)
    if digest.hexdigest()!=expected:raise ValueError('Prepared content checksum does not match')
    destination.mkdir(parents=True)
    with tarfile.open(archive,'r:gz') as source:
        members=source.getmembers()
        if any(member.issym() or member.islnk() or member.isdev() for member in members):
            raise ValueError('Prepared content must contain regular files and directories only')
        if sum(member.size for member in members)>6*1024**3:
            raise ValueError('Expanded content exceeds the build storage limit')
        source.extractall(destination,filter='data')
finally:
    archive.unlink(missing_ok=True)
