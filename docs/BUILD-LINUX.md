# Build on Linux

Linux users build Shas Master from source. There is no maintained Linux installer or automated Linux testing.

You need Git, Node.js 24 or later, Python 3.12 or later with SQLite 3.43 or later, and a desktop web browser. Install these using your distribution's usual tools.

## Get the code

```sh
git clone https://github.com/hatt-io/shasmaster.git
cd shasmaster
python3 -m venv .venv
.venv/bin/pip install '.[build]'
npm install --include=dev --package-lock=false
```

## Get the reading material

Download [prepared.tar.gz.part-00](https://github.com/hatt-io/shasmaster/releases/download/build-content-compact-2026-10-14/prepared.tar.gz.part-00) into the project folder and rename it `codex-tmp-content.tar.gz`. While the repository is private, you must be signed into a GitHub account with access.

The following command checks the download, unpacks it into `data/prepared`, and removes the archive. Run it once; keep `data/prepared` for later builds.

```sh
SHAS_CONTENT_ARCHIVE="$PWD/codex-tmp-content.tar.gz" \
SHAS_CONTENT_SHA256=4faca8e989d41e5a292a800056371e2dc0190bf45ae280e81e411f586888cadd \
.venv/bin/python desktop/fetch-content.py
```

## Build and open

```sh
npm run build
.venv/bin/python -m PyInstaller --noconfirm --distpath .desktop-build/runtime --workpath .desktop-build/python desktop/backend.spec
SHAS_CORPUS="$PWD/data/prepared" SHAS_FRONTEND="$PWD/dist" \
.desktop-build/runtime/shas-backend/shas-backend --configuration Release --open-browser
```

The reader opens in your browser. Keep the terminal open while studying; press Ctrl+C there to stop it. For later sessions, run only the final command.

Your meanings and bookmarks are stored in `$XDG_DATA_HOME/shas-master`, or `~/.local/share/shas-master` when that variable is unset. They stay separate from the source code and build output. Use Settings → Export before updating.

The application code and reading material have separate [license terms](../CREDITS.md).
