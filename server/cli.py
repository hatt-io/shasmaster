import argparse
from pathlib import Path
import subprocess
import sys
from .config import ROOT,HOST,PORT,CORPUS,FRONTEND
from .db import migrate
from .catalogue import initialize_catalogue

def main():
    parser=argparse.ArgumentParser(prog='shasmaster');sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('serve');sub.add_parser('catalogue');sub.add_parser('acquire');sub.add_parser('extract');sub.add_parser('fonts');sub.add_parser('backup');sub.add_parser('setup')
    sub.add_parser('reconnect-local-pages')
    sub.add_parser('initialize-user-data')
    import_work=sub.add_parser('import-user-work')
    import_work.add_argument('database',type=Path)
    prepare=sub.add_parser('prepare-content')
    prepare.add_argument('destination',type=Path)
    reading=sub.add_parser('prepare-reading')
    reading.add_argument('destination',type=Path)
    compact=sub.add_parser('compact-fonts')
    compact.add_argument('destination',type=Path)
    cleanup=sub.add_parser('cleanup-generated')
    cleanup.add_argument('--apply',action='store_true')
    restore = sub.add_parser('restore-backup')
    restore.add_argument('path', type=Path)
    args=parser.parse_args()
    if args.command=='initialize-user-data':
        from .user_install import initialize_user_data
        initialize_user_data()
        return
    migrate(initialize=args.command=='setup')
    if args.command=='catalogue':initialize_catalogue()
    elif args.command=='serve':
        import uvicorn
        if not (FRONTEND/'index.html').exists():
            if CORPUS:raise FileNotFoundError('The installed interface is missing')
            subprocess.run(['npm','run','build'],cwd=ROOT,check=True)
        uvicorn.run('server.api:app',host=HOST,port=PORT)
    elif args.command=='acquire':
        import asyncio
        from .acquire import acquire_pages
        asyncio.run(acquire_pages())
    elif args.command=='extract':
        from .extract import import_available
        import_available(follow=True)
        from .font_recovery import recover_fonts,repair_font_text
        recover_fonts();repair_font_text()
    elif args.command=='fonts':
        from .font_recovery import recover_fonts,repair_font_text
        recover_fonts();repair_font_text()
    elif args.command=='backup':
        from .db import backup
        print(backup('manual'))
    elif args.command=='restore-backup':
        from .db import backup, load_backup
        from .annotations import restore_work
        payload = load_backup(args.path)
        backup('before-restore')
        print(restore_work(payload))
    elif args.command=='import-user-work':
        import json
        from .config import DATABASE
        from .db import read,backup
        from .annotations import export_from_connection,restore_work
        if args.database.resolve()==DATABASE.resolve():raise ValueError('Source and destination must differ')
        with read(args.database) as conn:
            conn.execute('BEGIN')
            payload=export_from_connection(conn)
        backup('before-import')
        print(json.dumps(restore_work(payload),indent=2))
    elif args.command=='compact-fonts':
        from .compact_fonts import compact_fonts
        compact_fonts(args.destination)
    elif args.command=='prepare-reading':
        from .prepare_reading import prepare_reading
        prepare_reading(args.destination)
    elif args.command=='prepare-content':
        from .prepare_content import prepare_content
        prepare_content(args.destination)
    elif args.command=='cleanup-generated':
        import json
        from .storage_cleanup import cleanup_generated
        print(json.dumps(cleanup_generated(apply=args.apply),indent=2))
    elif args.command=='reconnect-local-pages':
        from .retained_pages import restore_catalogue
        restore_catalogue()
    elif args.command=='setup':
        import asyncio
        from .acquire import acquire_pages,acquire_attribution,acquire_ocr
        async def sources():
            results=await asyncio.gather(acquire_pages(),acquire_attribution(),acquire_ocr(),return_exceptions=True)
            failures=[str(result) for result in results if isinstance(result,Exception)]
            if failures:raise RuntimeError('; '.join(failures))
        asyncio.run(sources())
        # Extraction imports the actual post-download OCR files.
        subprocess.run([sys.executable,'-m','server.cli','extract'],cwd=ROOT,check=True)

if __name__=='__main__':main()
