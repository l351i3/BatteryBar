#!/bin/zsh
set -euo pipefail

APP_NAME="Battery Bar"
NATIVE_APP_NAME="BatteryBarNative"
APP_PATH="/Applications/${APP_NAME}.app"
NATIVE_PATH="/Applications/${NATIVE_APP_NAME}.app"
BUNDLE_ID="io.github.l351i3.batterybar"
WIDGET_ID="io.github.l351i3.batterybar.widgethost.widget"

printf '==> Stopping processes...
'
pkill -x "$APP_NAME" 2>/dev/null || true
pkill -x "$NATIVE_APP_NAME" 2>/dev/null || true
killall -9 BatteryBarWidgetExtension 2>/dev/null || true

printf '==> Removing Login Items...
'
osascript -e 'tell application "System Events" to delete login item "Battery Bar"' 2>/dev/null || true
osascript -e 'tell application "System Events" to delete login item "BatteryBarNative"' 2>/dev/null || true

printf '==> Unregistering Plugin...
'
/usr/bin/pluginkit -r "$NATIVE_PATH/Contents/PlugIns/BatteryBarWidgetExtension.appex" 2>/dev/null || true
/usr/bin/pluginkit -e ignore -i "$WIDGET_ID" 2>/dev/null || true

printf '==> Removing Applications...
'
rm -rf "$APP_PATH"
rm -rf "$NATIVE_PATH"

printf '==> Cleaning Data and Caches...
'
rm -rf "$HOME/Library/Application Support/Battery Bar"
rm -rf "$HOME/Library/Caches/io.github.l351i3.batterybar"
rm -rf "$HOME/Library/Containers/io.github.l351i3.batterybar.widgethost"
rm -rf "$HOME/Library/Containers/io.github.l351i3.batterybar.widgethost.widget"
rm -rf "$HOME/Library/Group Containers/group.io.github.l351i3.batterybar"
rm -rf "$HOME/Library/Caches/com.apple.chronod" # Force refresh widget cache

printf '==> Resetting Plugin Database (Optional Deep Clean)...
'
/usr/bin/pluginkit -e ignore -i "$WIDGET_ID" 2>/dev/null || true

printf '
========================================
Uninstallation Complete.
Please restart your Mac to fully clear system caches.
========================================
'
