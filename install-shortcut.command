#!/bin/bash
# Creates the desktop shortcut on macOS. Run once; run again if the project folder moves.
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
if [ ! -x .venv/bin/python ]; then
  PY=""
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      PY="$candidate"; break
    fi
  done
  [ -n "$PY" ] || { echo "Python 3.10 or newer is required."; exit 1; }
  "$PY" -m venv .venv
fi
APP="$HOME/Desktop/Trade Journal.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp assets/icon.icns "$APP/Contents/Resources/icon.icns"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Trade Journal</string>
  <key>CFBundleIdentifier</key><string>local.exs.tradejournal</string>
  <key>CFBundleExecutable</key><string>journal</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSUIElement</key><true/>
</dict></plist>
PLIST
{
  echo '#!/bin/bash'
  echo 'export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"'
  printf 'cd %q || exit 1\n' "$DIR"
  echo 'exec .venv/bin/python launcher.py'
} > "$APP/Contents/MacOS/journal"
chmod +x "$APP/Contents/MacOS/journal"
xattr -cr "$APP" 2>/dev/null || true
codesign --force --deep -s - "$APP" 2>/dev/null || true
touch "$APP"
killall Finder 2>/dev/null || true
echo "Done. Trade Journal is on your Desktop."
