#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:?Usage: bash packaging/build_linux.sh VERSION}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="$ROOT/dist"
APP_DIR="$DIST/AppDir"
DEB_ROOT="$DIST/deb-root"
TEMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TEMP_DIR"' EXIT

if [[ ! -x "$DIST/TxBridge/TxBridge" ]]; then
    echo "Missing PyInstaller output: $DIST/TxBridge/TxBridge" >&2
    exit 1
fi

mkdir -p "$DIST"
rm -rf "$APP_DIR" "$DEB_ROOT"

mkdir -p "$APP_DIR/usr/lib" "$APP_DIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$DIST/TxBridge" "$APP_DIR/usr/lib/txbridge"
install -m 755 "$ROOT/packaging/linux/AppRun" "$APP_DIR/AppRun"
install -m 644 "$ROOT/txbridge/assets/icon.png" "$APP_DIR/txbridge.png"
install -m 644 "$ROOT/txbridge/assets/icon.png" "$APP_DIR/usr/share/icons/hicolor/256x256/apps/txbridge.png"
sed 's/@EXEC@/AppRun/' "$ROOT/packaging/linux/txbridge.desktop.in" > "$APP_DIR/txbridge.desktop"

LINUXDEPLOY_URL="https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage"
LINUXDEPLOY_SHA256="df908b19f1ed1cdafa79508d415aa12d6c56ce4d56d4149aa8c09286718706e5"
APPIMAGE_PLUGIN_URL="https://github.com/linuxdeploy/linuxdeploy-plugin-appimage/releases/download/continuous/linuxdeploy-plugin-appimage-x86_64.AppImage"
APPIMAGE_PLUGIN_SHA256="49d6a17160675a6bd1781699aae6bdf7692d98552e02a3671d2183d10547842e"

curl --fail --location --retry 3 "$LINUXDEPLOY_URL" --output "$TEMP_DIR/linuxdeploy.AppImage"
echo "$LINUXDEPLOY_SHA256  $TEMP_DIR/linuxdeploy.AppImage" | sha256sum --check
curl --fail --location --retry 3 "$APPIMAGE_PLUGIN_URL" --output "$TEMP_DIR/linuxdeploy-plugin-appimage.AppImage"
echo "$APPIMAGE_PLUGIN_SHA256  $TEMP_DIR/linuxdeploy-plugin-appimage.AppImage" | sha256sum --check
chmod +x "$TEMP_DIR/linuxdeploy.AppImage" "$TEMP_DIR/linuxdeploy-plugin-appimage.AppImage"
ln -s "$TEMP_DIR/linuxdeploy-plugin-appimage.AppImage" "$TEMP_DIR/linuxdeploy-plugin-appimage"

mkdir -p "$TEMP_DIR/output"
(
    cd "$TEMP_DIR/output"
    PATH="$TEMP_DIR:$PATH" APPIMAGE_EXTRACT_AND_RUN=1 "$TEMP_DIR/linuxdeploy.AppImage" \
        --appdir "$APP_DIR" \
        --executable "$APP_DIR/usr/lib/txbridge/TxBridge" \
        --desktop-file "$APP_DIR/txbridge.desktop" \
        --icon-file "$APP_DIR/txbridge.png" \
        --output appimage
)

APPIMAGE="$(find "$TEMP_DIR/output" -maxdepth 1 -type f -name '*.AppImage' -print -quit)"
if [[ -z "$APPIMAGE" ]]; then
    echo "linuxdeploy did not produce an AppImage." >&2
    exit 1
fi
mv "$APPIMAGE" "$DIST/TxBridge-$VERSION-x86_64.AppImage"

mkdir -p "$DEB_ROOT/DEBIAN" "$DEB_ROOT/opt/txbridge" "$DEB_ROOT/usr/bin" \
    "$DEB_ROOT/usr/share/applications" "$DEB_ROOT/usr/share/icons/hicolor/256x256/apps"
cp -a "$DIST/TxBridge/." "$DEB_ROOT/opt/txbridge/"
install -m 755 "$ROOT/packaging/linux/debian-launcher" "$DEB_ROOT/usr/bin/txbridge"
install -m 644 "$ROOT/txbridge/assets/icon.png" "$DEB_ROOT/usr/share/icons/hicolor/256x256/apps/txbridge.png"
sed 's/@EXEC@/txbridge/' "$ROOT/packaging/linux/txbridge.desktop.in" > "$DEB_ROOT/usr/share/applications/txbridge.desktop"
sed "s/@VERSION@/$VERSION/" "$ROOT/packaging/linux/control.in" > "$DEB_ROOT/DEBIAN/control"
dpkg-deb --build --root-owner-group "$DEB_ROOT" "$DIST/txbridge_${VERSION}_amd64.deb"
