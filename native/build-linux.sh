#!/bin/sh
set -eu
test "${1:-}" = Release || { echo 'Explicit Release configuration required' >&2; exit 1; }
cd "$(dirname "$0")/.."
root="$PWD"
architecture=$(uname -m)
case "$architecture" in x86_64|aarch64) ;; *) echo 'Unsupported AppImage architecture' >&2; exit 1;; esac
stage="$root/.desktop-build/Shas-Master-$architecture.AppDir"
test ! -e "$stage" || { echo 'AppImage staging already exists' >&2; exit 1; }
mkdir -p "$stage/usr/share/shas-master" release
cp -a data/prepared "$stage/usr/share/shas-master/prepared"
cp -a dist "$stage/usr/share/shas-master/dist"
cp -a "${SHAS_LINUX_BACKEND:-.desktop-build/runtime/shas-backend}" "$stage/usr/share/shas-master/shas-backend"
cp -a docs/licenses "$stage/usr/share/shas-master/licenses"
cp LICENSE CREDITS.md docs/INSTALL.md "$stage/usr/share/shas-master/"
cp web/public/icon.svg "$stage/shas-master.svg"
cat > "$stage/AppRun" <<'LAUNCH'
#!/bin/sh
set -eu
appdir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export SHAS_CORPUS="$appdir/usr/share/shas-master/prepared"
export SHAS_FRONTEND="$appdir/usr/share/shas-master/dist"
exec "$appdir/usr/share/shas-master/shas-backend/shas-backend" --configuration Release --open-browser "$@"
LAUNCH
chmod 755 "$stage/AppRun"
cat > "$stage/shas-master.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Shas Master
Comment=Read Shas with your own word meanings
Exec=AppRun
Icon=shas-master
Terminal=false
Categories=Education;
DESKTOP
output="$root/release/Shas-Master-$architecture.AppImage"
ARCH="$architecture" APPIMAGE_EXTRACT_AND_RUN=1 "${SHAS_APPIMAGETOOL:?Set SHAS_APPIMAGETOOL to the official appimagetool executable}" --comp xz --no-appstream "$stage" "$output"
chmod 755 "$output"
size=$(stat -c %s "$output")
echo "AppImage: $size bytes"
test "$size" -le 290000000 || { echo 'AppImage exceeds the 290 MB delivery limit' >&2; exit 1; }
