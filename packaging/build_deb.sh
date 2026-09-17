#!/usr/bin/env bash
# Build a .deb from the PyInstaller onefile binary in dist/.
#
#   ./packaging/build_deb.sh [version] [arch]
#
# Expects dist/OpencodeMonitor to exist (build it with):
#   pyinstaller --noconfirm --clean --onefile --name OpencodeMonitor main.py
set -euo pipefail

VERSION="${1:-0.0.0-dev}"
ARCH="${2:-amd64}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$ROOT/dist/OpencodeMonitor"
STAGE="$ROOT/build/deb"

if [ ! -f "$BIN" ]; then
  echo "error: $BIN not found - run PyInstaller first" >&2
  exit 1
fi
if [ ! -f "$ROOT/assets/icon-256.png" ]; then
  echo "error: $ROOT/assets/icon-256.png not found - run tools/make_icons.py" >&2
  exit 1
fi

rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor/256x256/apps" \
         "$STAGE/usr/share/doc/opencode-monitor"

install -m 755 "$BIN" "$STAGE/usr/bin/opencode-monitor"
install -m 644 "$ROOT/packaging/opencode-monitor.desktop" \
    "$STAGE/usr/share/applications/opencode-monitor.desktop"
install -m 644 "$ROOT/assets/icon-256.png" \
    "$STAGE/usr/share/icons/hicolor/256x256/apps/opencode-monitor.png"
install -m 644 "$ROOT/README.md" "$STAGE/usr/share/doc/opencode-monitor/README.md"
[ -f "$ROOT/LICENSE" ] && install -m 644 "$ROOT/LICENSE" \
    "$STAGE/usr/share/doc/opencode-monitor/copyright" || true

INSTALLED_SIZE="$(du -sk "$STAGE" | cut -f1)"

cat > "$STAGE/DEBIAN/control" <<EOF
Package: opencode-monitor
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: libgl1, libegl1, libxkbcommon-x11-0, libxcb-cursor0, libdbus-1-3
Installed-Size: $INSTALLED_SIZE
Maintainer: WilliamMarci <WilliamMarci@users.noreply.github.com>
Homepage: https://github.com/WilliamMarci/OpencodeMonitor
Description: Always-on-top widget showing opencode usage
 A compact desktop widget that shows opencode / OpenCode Go usage as three
 double-ring dials (5 hours, 1 week, 1 month). The outer ring is the usage
 percentage (or remaining), the inner ring is the time until the window
 resets, and the centre shows the percentage as a number.
 .
 It reads usage from the Zen/Go API when an API key is available and falls
 back to aggregating opencode's own local database, so it also works without
 a Go subscription.
EOF

mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/opencode-monitor_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$OUT"
echo "built $OUT"
