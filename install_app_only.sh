#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Battery Bar"
APP_PATH="/Applications/${APP_NAME}.app"

printf '==> Stopping running instance...
'
pkill -x "$APP_NAME" 2>/dev/null || true

printf '==> Installing %s...
' "$APP_NAME"
rm -rf "$APP_PATH"
cp -R "$SCRIPT_DIR/${APP_NAME}.app" "$APP_PATH"
xattr -cr "$APP_PATH" 2>/dev/null || true

printf '==> Setting up Login Item...
'
osascript -e "tell application "System Events" to delete login item "${APP_NAME}"" 2>/dev/null || true
sleep 1
osascript -e "tell application "System Events" to make login item at end with properties {path:"${APP_PATH}", hidden:true}"

printf '==> Launching application...
'
open "$APP_PATH"

printf '
========================================
Installation Complete.
Note: Widget components are NOT included in this package.
========================================
'
