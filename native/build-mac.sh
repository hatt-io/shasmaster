#!/bin/sh
set -eu
test "${1:-}" = Release || { echo 'Explicit Release configuration required' >&2; exit 1; }
: "${SHAS_SIGN_IDENTITY:?A Developer ID signing identity is required}"
cd "$(dirname "$0")/.."
app="$PWD/out/native-mac/Shas Master.app"
test ! -e "$app" || { echo 'Native app output already exists; preserve or remove it before rebuilding' >&2; exit 1; }
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources" .cache/swift-release release
swiftc -O -whole-module-optimization -target arm64-apple-macosx13.0 -module-cache-path "$PWD/.cache/swift-release" -framework AppKit -framework WebKit native/MacApp.swift -o "$app/Contents/MacOS/ShasMaster"
cp -cR data/prepared "$app/Contents/Resources/prepared"
cp -cR dist "$app/Contents/Resources/dist"
cp -cR .desktop-build/runtime/shas-backend "$app/Contents/Resources/shas-backend"
cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Shas Master</string>
<key>CFBundleDisplayName</key><string>Shas Master</string>
<key>CFBundleIdentifier</key><string>app.shasmaster.reader.native</string>
<key>CFBundleExecutable</key><string>ShasMaster</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.1.0</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>13.0</string>
<key>NSHighResolutionCapable</key><true/>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/><key>NSAllowsArbitraryLoadsInWebContent</key><true/></dict>
</dict></plist>
PLIST
codesign --force --options runtime --timestamp --sign "$SHAS_SIGN_IDENTITY" "$app"
ln -s /Applications out/native-mac/Applications
hdiutil create -volname 'Shas Master' -srcfolder out/native-mac -ov -format UDZO release/Shas-Master-Native-macOS-arm64.dmg
codesign --force --timestamp --sign "$SHAS_SIGN_IDENTITY" release/Shas-Master-Native-macOS-arm64.dmg
test "$(stat -f %z release/Shas-Master-Native-macOS-arm64.dmg)" -le 290000000 || { echo 'Installer exceeds the 290 MB delivery limit' >&2; exit 1; }
