#!/bin/zsh
set -euo pipefail

APP_NAME="Battery Bar"
APP_PATH="/Applications/${APP_NAME}.app"

printf '==> Stopping process...
'
pkill -x "$APP_NAME" 2>/dev/null || true

printf '==> Removing Login Item...
'
osascript -e "tell application "System Events" to delete login item "${APP_NAME}"" 2>/dev/null || true

printf '==> Removing Application...
'
rm -rf "$APP_PATH"

printf '==> Cleaning Data and Caches...
'
rm -rf "$HOME/Library/Application Support/Battery Bar"
rm -rf "$HOME/Library/Caches/io.github.l351i3.batterybar"

printf '
========================================
Uninstallation Complete.
========================================
'
