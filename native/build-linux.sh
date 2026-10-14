#!/bin/sh
set -eu
test "${1:-}" = Release || { echo 'Explicit Release configuration required' >&2; exit 1; }
cd "$(dirname "$0")/.."
stage="$PWD/.desktop-build/linux-package"
test ! -e "$stage" || { echo 'Linux package staging already exists' >&2; exit 1; }
mkdir -p "$stage/DEBIAN" "$stage/opt/shas-master" "$stage/usr/bin" "$stage/usr/share/applications" "$stage/usr/share/icons/hicolor/scalable/apps" release
cp -a data/prepared "$stage/opt/shas-master/prepared"
cp -a dist "$stage/opt/shas-master/dist"
cp -a "${SHAS_LINUX_BACKEND:-.desktop-build/runtime-linux/shas-backend}" "$stage/opt/shas-master/shas-backend"
cp web/public/icon.svg "$stage/usr/share/icons/hicolor/scalable/apps/shas-master.svg"
cat > "$stage/usr/bin/shas-master" <<'LAUNCH'
#!/bin/sh
export SHAS_CORPUS=/opt/shas-master/prepared
export SHAS_FRONTEND=/opt/shas-master/dist
exec /opt/shas-master/shas-backend/shas-backend --configuration Release --open-browser
LAUNCH
chmod 755 "$stage/usr/bin/shas-master"
cat > "$stage/usr/share/applications/shas-master.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Shas Master
Comment=Read Shas with your own word meanings
Exec=shas-master
Icon=shas-master
Terminal=false
Categories=Education;
DESKTOP
architecture=$(dpkg --print-architecture)
size=$(du -sk "$stage/opt" | cut -f1)
libc=$(getconf GNU_LIBC_VERSION | cut -d' ' -f2)
cat > "$stage/DEBIAN/control" <<CONTROL
Package: shas-master
Version: 0.1.0
Architecture: $architecture
Maintainer: Shas Master
Depends: libc6 (>= $libc), libgcc-s1, xdg-utils
Installed-Size: $size
Description: Offline Shas reader with personal word meanings
 Opens the reader automatically from its application icon.
CONTROL
dpkg-deb --root-owner-group -Zgzip -z1 --build "$stage" "release/Shas-Master-Native-linux-$architecture.deb"
