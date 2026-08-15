#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Battery Bar"
NATIVE_APP_NAME="BatteryBarNative"
APP_PATH="/Applications/${APP_NAME}.app"
NATIVE_PATH="/Applications/${NATIVE_APP_NAME}.app"

printf '==> Stopping running instances...
'
pkill -x "$APP_NAME" 2>/dev/null || true
pkill -x "$NATIVE_APP_NAME" 2>/dev/null || true

printf '==> Installing %s...
' "$APP_NAME"
rm -rf "$APP_PATH"
cp -R "$SCRIPT_DIR/${APP_NAME}.app" "$APP_PATH"
xattr -cr "$APP_PATH" 2>/dev/null || true

printf '==> Installing %s...
' "$NATIVE_APP_NAME"
rm -rf "$NATIVE_PATH"
cp -R "$SCRIPT_DIR/${NATIVE_APP_NAME}.app" "$NATIVE_PATH"
xattr -cr "$NATIVE_PATH" 2>/dev/null || true

printf '==> Registering Widget Plugin...
'
WIDGET_EX="${NATIVE_PATH}/Contents/PlugIns/BatteryBarWidgetExtension.appex"
if [ -d "$WIDGET_EX" ]; then
    /usr/bin/pluginkit -a "$WIDGET_EX" || true
    /usr/bin/pluginkit -e use -i io.github.l351i3.batterybar.widgethost.widget || true
fi

printf '==> Setting up Login Items...
'
osascript -e "tell application "System Events" to delete login item "${APP_NAME}"" 2>/dev/null || true
osascript -e "tell application "System Events" to delete login item "${NATIVE_APP_NAME}"" 2>/dev/null || true
sleep 1
osascript -e "tell application "System Events" to make login item at end with properties {path:"${APP_PATH}", hidden:true}"
osascript -e "tell application "System Events" to make login item at end with properties {path:"${NATIVE_PATH}", hidden:true}"

printf '==> Launching applications...
'
open "$APP_PATH"
open "$NATIVE_PATH"

printf '
========================================
Installation Complete.
Please add the Widget manually:
Right-click Desktop -> Edit Widgets -> Search "Battery Bar".
========================================
'
