#!/bin/bash

set -euo pipefail

PROJECT_DIR="$(
    cd "$(dirname "$0")"
    pwd
)"
cd "$PROJECT_DIR"

APP_NAME="Battery Bar"
NATIVE_APP_NAME="BatteryBarNative"
VERSION="2.1.2"

PYTHON_APP_PATH="$PROJECT_DIR/dist/${APP_NAME}.app"
NATIVE_PROJECT="$PROJECT_DIR/Widget/BatteryBarNative"
NATIVE_BUILD_DIR="$NATIVE_PROJECT/build-release"
NATIVE_APP_PATH="$NATIVE_BUILD_DIR/Build/Products/Release/BatteryBarNative.app"

VENV_DIR="$PROJECT_DIR/.venv-build"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"

DMG_PATH="$PROJECT_DIR/dist/BatteryBar-${VERSION}.dmg"
DMG_STAGING="$PROJECT_DIR/dist/dmg-staging"

log() {
    printf '
==> %s
' "$1"
}

fail() {
    printf '
错误：%s
' "$1" >&2
    exit 1
}

command -v "$PYTHON_BIN" >/dev/null 2>&1     || fail "找不到 Python：$PYTHON_BIN"

command -v /usr/bin/codesign >/dev/null 2>&1     || fail "找不到 codesign"

command -v /usr/bin/plutil >/dev/null 2>&1     || fail "找不到 plutil"

command -v /usr/bin/hdiutil >/dev/null 2>&1     || fail "找不到 hdiutil"

command -v /usr/bin/xcodebuild >/dev/null 2>&1     || fail "找不到 xcodebuild"

log "检查 Python 版本"

"$PYTHON_BIN" - <<'PYV'
import sys

if sys.version_info < (3, 9):
    raise SystemExit(
        "Battery Bar 要求 Python 3.9 或更高版本"
    )

print(sys.version)
PYV

log "创建隔离构建环境"

if [ ! -x "$VENV_DIR/bin/python" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

log "安装固定依赖"

"$VENV_DIR/bin/python"     -m pip install     --disable-pip-version-check     -r requirements.txt

log "运行语法检查"

"$VENV_DIR/bin/python" -m py_compile     app.py     aggregator.py     bluetooth_provider.py     classifier.py     hidpp_provider.py     models.py     provider_registry.py     snapshot_store.py     system_provider.py     widget_snapshot_sync.py

log "运行全部单元测试"

"$VENV_DIR/bin/python"     -m unittest discover     -s tests     -p 'test_*.py'     -v

log "清理旧构建产物"

rm -rf     "$PROJECT_DIR/build"     "$PROJECT_DIR/dist"     "$NATIVE_BUILD_DIR"

log "使用 PyInstaller 构建主应用"

"$VENV_DIR/bin/python"     -m PyInstaller     --noconfirm     --clean     BatteryBar.spec

[ -d "$PYTHON_APP_PATH" ]     || fail "没有生成 ${APP_NAME}.app"

PLIST_PATH="$PYTHON_APP_PATH/Contents/Info.plist"

[ -f "$PLIST_PATH" ]     || fail "主应用缺少 Info.plist"

log "验证主应用元数据"

/usr/bin/plutil -lint "$PLIST_PATH"

/usr/bin/plutil -replace     CFBundleDisplayName     -string "$APP_NAME"     "$PLIST_PATH"

/usr/bin/plutil -replace     CFBundleName     -string "BatteryBar"     "$PLIST_PATH"

/usr/bin/plutil -replace     CFBundleIdentifier     -string     "io.github.l351i3.batterybar"     "$PLIST_PATH"

/usr/bin/plutil -replace     CFBundleShortVersionString     -string "$VERSION"     "$PLIST_PATH"

/usr/bin/plutil -replace     CFBundleVersion     -string "$VERSION"     "$PLIST_PATH"

/usr/bin/plutil -replace     LSUIElement     -bool YES     "$PLIST_PATH"

/usr/bin/plutil -replace     NSBluetoothAlwaysUsageDescription     -string     "Battery Bar 需要访问蓝牙，以读取已连接外设公开的电量信息。"     "$PLIST_PATH"

/usr/bin/plutil -replace     NSBluetoothPeripheralUsageDescription     -string     "Battery Bar 需要访问蓝牙，以读取已连接外设公开的电量信息。"     "$PLIST_PATH"

/usr/bin/plutil -lint "$PLIST_PATH"

log "执行主应用 ad-hoc 签名"

/usr/bin/codesign     --force     --deep     --sign -     "$PYTHON_APP_PATH"

/usr/bin/codesign     --verify     --deep     --strict     --verbose=2     "$PYTHON_APP_PATH"

log "使用 Xcode 构建原生宿主"

xcodebuild     -project "$NATIVE_PROJECT/BatteryBarNative.xcodeproj"     -scheme BatteryBarNative     -configuration Release     -destination 'platform=macOS'     -derivedDataPath "$NATIVE_BUILD_DIR"     CODE_SIGN_STYLE=Manual     CODE_SIGN_IDENTITY=-     DEVELOPMENT_TEAM=     INFOPLIST_KEY_LSUIElement=YES     clean build

[ -d "$NATIVE_APP_PATH" ]     || fail "没有生成 ${NATIVE_APP_NAME}.app"

log "执行原生宿主 ad-hoc 签名"

WIDGET_PATH="$NATIVE_APP_PATH/Contents/PlugIns/BatteryBarWidgetExtension.appex"
/usr/bin/codesign     --force     --sign -     --entitlements "$NATIVE_PROJECT/BatteryBarWidgetExtension.entitlements"     "$WIDGET_PATH"
/usr/bin/codesign     --force     --sign -     "$NATIVE_APP_PATH"

/usr/bin/codesign     --verify     --deep     --strict     --verbose=2     "$NATIVE_APP_PATH"

log "创建 DMG 发布包"

rm -rf "$DMG_STAGING"
mkdir -p "$DMG_STAGING"

cp -R "$PYTHON_APP_PATH" "$DMG_STAGING/"

cp -R "$NATIVE_APP_PATH" "$DMG_STAGING/"

ln -s /Applications "$DMG_STAGING/Applications"

rm -f "$DMG_PATH"

/usr/bin/hdiutil create     -volname "Battery Bar $VERSION"     -srcfolder "$DMG_STAGING"     -ov     -format UDZO     "$DMG_PATH"

rm -rf "$DMG_STAGING"

[ -f "$DMG_PATH" ]     || fail "没有生成 DMG"

printf '
构建成功：%s
' "$DMG_PATH"
