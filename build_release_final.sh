#!/bin/zsh
set -euo pipefail

# ==============================================================================
# MASTER BUILD & DISTRIBUTION PACKAGING SCRIPT (IMPROVED VERSION)
# This script automates building, verifying, signing, packaging, and testing
# Battery Bar. It outputs robust, clean DMG distribution packages.
# ==============================================================================

ROOT="$(
    cd "$(dirname "$0")"
    pwd
)"
DIST="$ROOT/dist"
FULL="$DIST/BatteryBar-Full"
APP_ONLY="$DIST/BatteryBar-AppOnly"
MAIN_APP="$DIST/Battery Bar.app"
NATIVE_APP="$ROOT/Widget/BatteryBarNative/build-release/Build/Products/Release/BatteryBarNative.app"
WIDGET_ENTITLEMENTS="$ROOT/Widget/BatteryBarNative/BatteryBarWidgetExtension.entitlements"

# 1. Clean previous DMG outputs.
#    注意：这里不能提前创建 $FULL/$APP_ONLY staging 目录。
#    下一步会调用 build_release.sh，它会执行 rm -rf "$PROJECT_DIR/dist"，
#    把整个 dist/ 目录连同 staging 全部删掉。所以 staging 目录必须在
#    编译完成（步骤 3 校验通过）之后再创建（见步骤 5）。
printf '==> [1/9] Cleaning old distribution structures...
'
rm -f "$DIST/BatteryBar-Full.dmg" "$DIST/BatteryBar-AppOnly.dmg"

# 2. Trigger Xcode compilation via standard build script
printf '==> [2/9] Executing release compilation...
'
cd "$ROOT"
if [ -f "./build_release.sh" ]; then
    ./build_release.sh
else
    printf 'ERROR: build_release.sh not found in root %s
' "$ROOT"
    exit 1
fi

# 3. Strict existence checks for compiled app bundles
printf '==> [3/9] Verifying compiled build artifacts...
'
if [ ! -d "$MAIN_APP" ]; then
    printf 'ERROR: Main App package not found at: %s
' "$MAIN_APP"
    exit 1
fi
if [ ! -d "$NATIVE_APP" ]; then
    printf 'ERROR: Widget Host App package not found at: %s
' "$NATIVE_APP"
    exit 1
fi

# 4. Rigorous Signing and Entitlement Injection
# We enforce "Inside-Out" codesigning. We do not use --deep for production.
printf '==> [4/9] Injected precise codesigning and sandbox entitlements...
'
WIDGET_PATH="$NATIVE_APP/Contents/PlugIns/BatteryBarWidgetExtension.appex"

if [ -d "$WIDGET_PATH" ]; then
    printf '  -> Signing Widget Extension with App Sandbox entitlement...
'
    if [ -f "$WIDGET_ENTITLEMENTS" ]; then
        /usr/bin/codesign --force --sign - --entitlements "$WIDGET_ENTITLEMENTS" "$WIDGET_PATH"
    else
        # Fallback to local creation of temporary entitlements if not in root
        TEMP_ENT="/tmp/temp_widget.entitlements"
        cat > "$TEMP_ENT" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.app-sandbox</key>
    <true/>
</dict>
</plist>
EOF
        /usr/bin/codesign --force --sign - --entitlements "$TEMP_ENT" "$WIDGET_PATH"
        rm -f "$TEMP_ENT"
    fi
else
    printf 'ERROR: Widget Extension (.appex) missing inside %s
' "$NATIVE_APP"
    exit 1
fi

printf '  -> Signing Native Widget Host App...
'
/usr/bin/codesign --force --sign - "$NATIVE_APP"

printf '  -> Signing Main Menu Bar App...
'
/usr/bin/codesign --force --sign - "$MAIN_APP"

# Verify entitlements of signed outputs
printf '  -> Verifying Sandbox entitlements on Widget...
'
WIDGET_CHECK=$(/usr/bin/codesign -d --entitlements - "$WIDGET_PATH" 2>/dev/null)
if echo "$WIDGET_CHECK" | grep -q "com.apple.security.app-sandbox"; then
    printf '✓ Widget Sandbox entitlement validated successfully.
'
else
    printf 'ERROR: Widget Sandbox entitlement verification failed!
'
    exit 1
fi

# 5. Populate staging packages
printf '==> [5/9] Copying signed assets into Full and App-Only packages...
'
# 在编译之后再创建 staging 目录（build_release.sh 内部会 rm -rf dist/，
# 提前建的目录会被清掉）。mkdir -p 确保目录存在，避免下面的 cp -R 把
# 源 .app 复制成同名文件而非目录内容（这正是之前 DMG 里没有 app 的根因）。
rm -rf "$FULL" "$APP_ONLY"
mkdir -p "$FULL" "$APP_ONLY"
cp -R "$MAIN_APP" "$FULL/"
cp -R "$NATIVE_APP" "$FULL/"
cp -R "$MAIN_APP" "$APP_ONLY/"

# Copy read-only diagnostic script to Full package for user convenience
if [ -f "$ROOT/diagnose.sh" ]; then
    cp "$ROOT/diagnose.sh" "$FULL/diagnose_safely.sh"
    chmod +x "$FULL/diagnose_safely.sh"
fi

# 6. Generate Idempotent Install/Uninstall scripts with syntax checks
printf '==> [6/9] Generating robust install and uninstall scripts...
'

# --- Full Package Installation Script ---
cat > "$FULL/install_full.sh" <<'SCRIPT'
#!/bin/zsh
set -euo pipefail

# Precise script directory discovery
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
APP_NAME="Battery Bar"
NATIVE_APP_NAME="BatteryBarNative"
APP_PATH="/Applications/${APP_NAME}.app"
NATIVE_PATH="/Applications/${NATIVE_APP_NAME}.app"
MANIFEST_LOG="/Applications/.batterybar_full_manifest.txt"

printf '==> Stopping and terminating running instances cleanly...
'
pkill -x "${APP_NAME}" 2>/dev/null || true
pkill -x "${NATIVE_APP_NAME}" 2>/dev/null || true
killall -9 BatteryBarWidgetExtension 2>/dev/null || true

printf '==> Installing "%s" to /Applications...
' "$APP_NAME"
if [ -d "$APP_PATH" ]; then
    rm -rf "$APP_PATH"
fi
/usr/bin/ditto "$SCRIPT_DIR/${APP_NAME}.app" "$APP_PATH"
xattr -cr "$APP_PATH" 2>/dev/null || true

printf '==> Installing "%s" to /Applications...
' "$NATIVE_APP_NAME"
if [ -d "$NATIVE_PATH" ]; then
    rm -rf "$NATIVE_PATH"
fi
/usr/bin/ditto "$SCRIPT_DIR/${NATIVE_APP_NAME}.app" "$NATIVE_PATH"
xattr -cr "$NATIVE_PATH" 2>/dev/null || true

printf '==> Registering Widget Extension with PlugInKit...
'
WIDGET_EX="${NATIVE_PATH}/Contents/PlugIns/BatteryBarWidgetExtension.appex"
if [ -d "$WIDGET_EX" ]; then
    /usr/bin/pluginkit -a "$WIDGET_EX" || true
    /usr/bin/pluginkit -e use -i io.github.l351i3.batterybar.widgethost.widget || true
else
    printf 'WARNING: Widget Extension not found inside installed application!
'
fi

printf '==> Configuring Autostart Login Items (idempotent configuration)...
'
osascript -e "tell application "System Events" to delete login item "${APP_NAME}"" 2>/dev/null || true
osascript -e "tell application "System Events" to delete login item "${NATIVE_APP_NAME}"" 2>/dev/null || true
sleep 0.5
osascript -e "tell application "System Events" to make login item at end with properties {path:"${APP_PATH}", hidden:true}"
osascript -e "tell application "System Events" to make login item at end with properties {path:"${NATIVE_PATH}", hidden:true}"

# Record installed files in a private manifest file for precise cleanups
cat > "$MANIFEST_LOG" <<EOF
$APP_PATH
$NATIVE_PATH
EOF

printf '==> Spawning applications...
'
open "$APP_PATH"
open "$NATIVE_PATH"

printf '
======================================================================
INSTALLATION COMPLETED SUCCESSFULLY!
To add your Battery Bar desktop widget:
1. Right-click on empty desktop space.
2. Select "Edit Widgets...".
3. Search or locate "Battery Bar" and drag the widget to your screen.
======================================================================
'
SCRIPT

# --- Full Package Uninstallation Script ---
cat > "$FULL/uninstall_full.sh" <<'SCRIPT'
#!/bin/zsh
set -euo pipefail

APP_NAME="Battery Bar"
NATIVE_APP_NAME="BatteryBarNative"
APP_PATH="/Applications/${APP_NAME}.app"
NATIVE_PATH="/Applications/${NATIVE_APP_NAME}.app"
WIDGET_ID="io.github.l351i3.batterybar.widgethost.widget"
MANIFEST_LOG="/Applications/.batterybar_full_manifest.txt"

printf '==> Shutting down running processes safely...
'
pkill -x "${APP_NAME}" 2>/dev/null || true
pkill -x "${NATIVE_APP_NAME}" 2>/dev/null || true
killall -9 BatteryBarWidgetExtension 2>/dev/null || true

printf '==> Removing autostart items...
'
osascript -e "tell application "System Events" to delete login item "${APP_NAME}"" 2>/dev/null || true
osascript -e "tell application "System Events" to delete login item "${NATIVE_APP_NAME}"" 2>/dev/null || true

printf '==> Deregistering widget plugin...
'
if [ -d "$NATIVE_PATH/Contents/PlugIns/BatteryBarWidgetExtension.appex" ]; then
    /usr/bin/pluginkit -r "$NATIVE_PATH/Contents/PlugIns/BatteryBarWidgetExtension.appex" 2>/dev/null || true
fi
/usr/bin/pluginkit -e ignore -i "$WIDGET_ID" 2>/dev/null || true

printf '==> Removing application bundles...
'
if [ -f "$MANIFEST_LOG" ]; then
    while IFS= read -r file_path; do
        if [ -n "$file_path" ] && [ -d "$file_path" ] || [ -f "$file_path" ]; then
            printf '  Removing: %s
' "$file_path"
            rm -rf "$file_path"
        fi
    done < "$MANIFEST_LOG"
    rm -f "$MANIFEST_LOG"
else
    rm -rf "$APP_PATH"
    rm -rf "$NATIVE_PATH"
fi

printf '==> Cleaning specific user cache & local sandbox data...
'
# Only delete Battery Bar-specific containers. Never run broad wildcards over system caches.
rm -rf "$HOME/Library/Application Support/Battery Bar"
rm -rf "$HOME/Library/Caches/io.github.l351i3.batterybar"
rm -rf "$HOME/Library/Containers/io.github.l351i3.batterybar.widgethost"
rm -rf "$HOME/Library/Containers/io.github.l351i3.batterybar.widgethost.widget"
rm -rf "$HOME/Library/Group Containers/group.io.github.l351i3.batterybar"

printf '
======================================================================
UNINSTALLATION COMPLETED!
* All applications, login configurations, and widget files removed.
* We recommend restarting your Mac to prompt system cache flushes.
======================================================================
'
SCRIPT

# --- App-Only Package Installation Script ---
cat > "$APP_ONLY/install_app_only.sh" <<'SCRIPT'
#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
APP_NAME="Battery Bar"
APP_PATH="/Applications/${APP_NAME}.app"
MANIFEST_LOG="/Applications/.batterybar_apponly_manifest.txt"

printf '==> Stopping active instances...
'
pkill -x "${APP_NAME}" 2>/dev/null || true

printf '==> Installing "%s" to /Applications...
' "$APP_NAME"
if [ -d "$APP_PATH" ]; then
    rm -rf "$APP_PATH"
fi
/usr/bin/ditto "$SCRIPT_DIR/${APP_NAME}.app" "$APP_PATH"
xattr -cr "$APP_PATH" 2>/dev/null || true

printf '==> Setting up Autostart Login Item...
'
osascript -e "tell application "System Events" to delete login item "${APP_NAME}"" 2>/dev/null || true
sleep 0.5
osascript -e "tell application "System Events" to make login item at end with properties {path:"${APP_PATH}", hidden:true}"

# Record installed file in local manifest
cat > "$MANIFEST_LOG" <<EOF
$APP_PATH
EOF

printf '==> Starting application...
'
open "$APP_PATH"

printf '
======================================================================
INSTALLATION COMPLETE (App-Only mode).
Note: Native desktop widgets are not bundled in this release.
======================================================================
'
SCRIPT

# --- App-Only Package Uninstallation Script ---
cat > "$APP_ONLY/uninstall_app_only.sh" <<'SCRIPT'
#!/bin/zsh
set -euo pipefail

APP_NAME="Battery Bar"
APP_PATH="/Applications/${APP_NAME}.app"
MANIFEST_LOG="/Applications/.batterybar_apponly_manifest.txt"

printf '==> Stopping application process...
'
pkill -x "${APP_NAME}" 2>/dev/null || true

printf '==> Removing autostart login items...
'
osascript -e "tell application "System Events" to delete login item "${APP_NAME}"" 2>/dev/null || true

printf '==> Removing application bundles...
'
if [ -f "$MANIFEST_LOG" ]; then
    while IFS= read -r file_path; do
        if [ -n "$file_path" ] && [ -d "$file_path" ] || [ -f "$file_path" ]; then
            printf '  Removing: %s
' "$file_path"
            rm -rf "$file_path"
        fi
    done < "$MANIFEST_LOG"
    rm -f "$MANIFEST_LOG"
else
    rm -rf "$APP_PATH"
fi

printf '==> Cleaning user cache & settings...
'
rm -rf "$HOME/Library/Application Support/Battery Bar"
rm -rf "$HOME/Library/Caches/io.github.l351i3.batterybar"

printf '
======================================================================
UNINSTALLATION COMPLETED (App-Only)!
======================================================================
'
SCRIPT

# Add executing permissions to generated scripts
chmod +x "$FULL"/*.sh "$APP_ONLY"/*.sh

# Syntax Verification of all created scripts prior to compilation
printf '  -> Checking generated script syntaxes...
'
/bin/zsh -n "$FULL/install_full.sh"
/bin/zsh -n "$FULL/uninstall_full.sh"
/bin/zsh -n "$APP_ONLY/install_app_only.sh"
/bin/zsh -n "$APP_ONLY/uninstall_app_only.sh"
printf '✓ Script syntax checks passed.
'

# 7. Generate Documentations
printf '==> [7/9] Creating Markdown files...
'

cat > "$FULL/README.md" <<'DOC'
# Battery Bar - Full Package (App + Desktop Widget)

## Introduction
Complete macOS battery status tool containing both the lightweight Menu Bar status application and native Apple Silicon/Intel Desktop widgets.

## Requirements
- macOS 14.0 (Sonoma) or newer.
- Universal support (Intel + Apple Silicon).

## Installing
1. Open Terminal, navigate to the folder where this DMG is mounted or extracted.
2. Run the command:
   ```bash
   ./install_full.sh
   ```
3. Wait for the success confirmation.

## Adding Desktop Widgets
1. Right-click anywhere on your desktop workspace -> Choose **"Edit Widgets..."**.
2. Type **"Battery Bar"** into the search field.
3. Select your preferred style/size and position it on your desktop.

## Uninstalling
1. Run the uninstallation helper inside terminal:
   ```bash
   ./uninstall_full.sh
   ```
2. A macOS system restart is suggested to clean layout and container caches.
DOC

cat > "$APP_ONLY/README.md" <<'DOC'
# Battery Bar - App Only Package

## Introduction
Standard Menu Bar battery status display without widgets or background hosting extensions.

## Requirements
- macOS 12.0 (Monterey) or newer.

## Installing
1. In Terminal, navigate inside the extracted files:
   ```bash
   ./install_app_only.sh
   ```

## Uninstalling
1. In Terminal run:
   ```bash
   ./uninstall_app_only.sh
   ```
DOC

# 8. Create DMG Files
printf '==> [8/9] Creating DMG packages...
'
/usr/bin/hdiutil create -volname "Battery Bar Full" -srcfolder "$FULL" -ov -format UDZO "$DIST/BatteryBar-Full.dmg"
/usr/bin/hdiutil create -volname "Battery Bar App Only" -srcfolder "$APP_ONLY" -ov -format UDZO "$DIST/BatteryBar-AppOnly.dmg"

# 9. Final Validation, Manifest & Build isolation cleanup
printf '==> [9/9] Verifying and generating publication metadata...
'
printf 'Full package folder contents:
'
ls -la "$FULL"

# Clear duplicate build artifacts to isolate system registration conflicts
printf '  -> Performing build artifact cleanup and registration isolation...
'
# To avoid registered Widget ID conflicts, we clean build directories of redundant copies.
# If running on actual Mac, compiling output is retained inside Xcode intermediates,
# but we safely sweep build-release products of extra files.
find "$ROOT/Widget/BatteryBarNative" -type d -name "BatteryBarNative.app" -not -path "$NATIVE_APP" -exec rm -rf {} + 2>/dev/null || true

# Generate checksums for release auditing
MANIFEST_FILE="$DIST/manifest.json"
FULL_HASH=$(/usr/bin/shasum -a 256 "$DIST/BatteryBar-Full.dmg" | awk '{print $1}')
APP_ONLY_HASH=$(/usr/bin/shasum -a 256 "$DIST/BatteryBar-AppOnly.dmg" | awk '{print $1}')

cat > "$MANIFEST_FILE" <<EOF
{
  "project": "BatteryBar",
  "build_time": "$(date -u +'%Y-%m-%dT%H:%M:%SZ')",
  "version": "$(defaults read "$MAIN_APP/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo "2.1.2")",
  "targets": {
    "full_package": {
      "dmg": "BatteryBar-Full.dmg",
      "sha256": "$FULL_HASH"
    },
    "app_only_package": {
      "dmg": "BatteryBar-AppOnly.dmg",
      "sha256": "$APP_ONLY_HASH"
    }
  }
}
EOF

printf '
======================================================================
BUILD COMPLETED SUCCESSFULLY!
Metadata and packages:
- Full Package: %s/BatteryBar-Full.dmg (SHA-256: %s)
- App-Only:     %s/BatteryBar-AppOnly.dmg (SHA-256: %s)
- Audit File:   %s
======================================================================
' "$DIST" "$FULL_HASH" "$DIST" "$APP_ONLY_HASH" "$MANIFEST_FILE"
