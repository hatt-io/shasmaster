"""Frozen Release backend: no downloader, extractor or build-tool startup."""
import argparse
import multiprocessing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--configuration', choices=['Release'], required=True)
    parser.add_argument('--initialize-only', action='store_true')
    parser.add_argument('--open-browser', action='store_true')
    args = parser.parse_args()
    from server.user_install import initialize_user_data
    initialize_user_data()
    from server.db import migrate
    migrate()
    if args.initialize_only:
        return
    from server.config import HOST, PORT, FRONTEND
    if not (FRONTEND / 'index.html').is_file():
        raise FileNotFoundError('Installed interface unavailable')
    import uvicorn
    from server.api import app
    server=uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, workers=1, reload=False))
    if args.open_browser:
        import threading
        import time
        import webbrowser
        def open_reader():
            while not server.started and not server.should_exit:
                time.sleep(.1)
            if server.started:
                webbrowser.open(f'http://127.0.0.1:{PORT}',new=1)
        threading.Thread(target=open_reader,daemon=True).start()
    server.run()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
