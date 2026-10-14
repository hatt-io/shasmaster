import os
from pathlib import Path

root = Path(SPECPATH).parent
a = Analysis([str(root / 'desktop' / 'backend.py')], pathex=[str(root)],
    datas=[(str(root / 'server' / 'migrations'), 'server/migrations')],
    hiddenimports=['uvicorn.logging', 'uvicorn.loops.asyncio', 'uvicorn.protocols.http.h11_impl',
                   'uvicorn.protocols.websockets.websockets_impl', 'uvicorn.lifespan.on'],
    excludes=['torch', 'transformers', 'pymupdf', 'fitz', 'pymongo', 'bs4',
              'server.extract', 'server.prepare_content', 'server.prepare_fonts',
              'server.font_recovery', 'server.artwork', 'server.ocr', 'server.acquire',
              'server.render', 'tkinter', 'matplotlib', 'numpy', 'PIL'],
    optimize=2)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='shas-backend',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True, codesign_identity=os.environ.get('SHAS_SIGN_IDENTITY'),
    entitlements_file=str(root / 'desktop' / 'backend-entitlements.plist'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='shas-backend')
