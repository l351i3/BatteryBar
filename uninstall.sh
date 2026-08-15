#!/bin/bash

set -euo pipefail

APP_NAME="Battery Bar"
NATIVE_APP_NAME="BatteryBarNative"

PYTHON_APP="/Applications/${APP_NAME}.app"
NATIVE_APP="/Applications/${NATIVE_APP_NAME}.app"

SUPPORT_DIR="$HOME/Library/Application Support/Battery Bar"
WIDGET_CONTAINER="$HOME/Library/Containers/io.github.l351i3.batterybar.widgethost.widget"
HOST_CONTAINER="$HOME/Library/Containers/io.github.l351i3.batterybar.widgethost"
OLD_CONTAINER="$HOME/Library/Containers/io.github.l351i3.BatteryBarNative.BatteryBarWidget"

log() {
    printf '==> %s\n' "$1"
}

removed=0

log "停止运行中的进程"

pkill -f "$PYTHON_APP/Contents/MacOS/BatteryBar" 2>/dev/null && {
    echo "  已终止 Battery Bar"
    removed=1
} || true

pkill -f "$NATIVE_APP/Contents/MacOS/BatteryBarNative" 2>/dev/null && {
    echo "  已终止 BatteryBarNative"
    removed=1
} || true

sleep 2

log "移除开机自启项"

osascript -e 'tell application "System Events" to delete login item "Battery Bar"' 2>/dev/null && {
    echo "  已移除 Battery Bar 开机自启"
    removed=1
} || true

osascript -e 'tell application "System Events" to delete login item "BatteryBarNative"' 2>/dev/null && {
    echo "  已移除 BatteryBarNative 开机自启"
    removed=1
} || true

log "移除应用程序"

if [ -d "$PYTHON_APP" ]; then
    rm -rf "$PYTHON_APP"
    echo "  已删除 $PYTHON_APP"
    removed=1
fi

if [ -d "$NATIVE_APP" ]; then
    rm -rf "$NATIVE_APP"
    echo "  已删除 $NATIVE_APP"
    removed=1
fi

log "移除应用数据"

if [ -d "$SUPPORT_DIR" ]; then
    rm -rf "$SUPPORT_DIR"
    echo "  已删除 $SUPPORT_DIR"
    removed=1
fi

if [ -d "$WIDGET_CONTAINER" ]; then
    rm -rf "$WIDGET_CONTAINER"
    echo "  已删除 $WIDGET_CONTAINER"
    removed=1
fi

if [ -d "$HOST_CONTAINER" ]; then
    rm -rf "$HOST_CONTAINER"
    echo "  已删除 $HOST_CONTAINER"
    removed=1
fi

if [ -d "$OLD_CONTAINER" ]; then
    rm -rf "$OLD_CONTAINER"
    echo "  已删除 $OLD_CONTAINER"
    removed=1
fi

log "刷新 Widget 缓存"

killall BatteryBarWidgetExtension 2>/dev/null || true
killall WidgetKit 2>/dev/null || true

echo
if [ "$removed" -eq 1 ]; then
    printf '卸载完成。\n'
else
    printf '未找到 Battery Bar 相关文件，可能已卸载。\n'
fi

printf '\n请手动移除桌面 Widget：右键桌面 Widget → 移除小组件。\n'