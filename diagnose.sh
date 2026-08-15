#!/bin/zsh
set -euo pipefail

# ==============================================================================
# READ-ONLY DIAGNOSTIC SCRIPT FOR BATTERY BAR (SYSTEM-SAFE)
# This script inspects the installation, signatures, entitlements, and registration
# status of Battery Bar and its Widget Extension without modifying any system state.
# ==============================================================================

echo "=============================================================================="
echo "          BATTERY BAR READ-ONLY DIAGNOSTIC SYSTEM CHECK"
echo "=============================================================================="
echo "Timestamp: $(date)"
echo "macOS Version: $(sw_vers -productVersion) ($(uname -m))"
echo "SIP Status: $(csrutil status 2>/dev/null || echo "Unknown")"
echo "=============================================================================="

# 1. Check Directories and Installation Paths
echo "
[1/5] Checking Installation Files..."
MAIN_APP="/Applications/Battery Bar.app"
HOST_APP="/Applications/BatteryBarNative.app"
WIDGET_ID="io.github.l351i3.batterybar.widgethost.widget"

if [ -d "$MAIN_APP" ]; then
    echo "✓ Main App found at: $MAIN_APP"
    echo "  Version: $(defaults read "$MAIN_APP/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo "Unknown")"
    echo "  Build: $(defaults read "$MAIN_APP/Contents/Info.plist" CFBundleVersion 2>/dev/null || echo "Unknown")"
else
    echo "✗ Main App NOT found at $MAIN_APP"
fi

if [ -d "$HOST_APP" ]; then
    echo "✓ Widget Host App found at: $HOST_APP"
    echo "  Version: $(defaults read "$HOST_APP/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo "Unknown")"
    
    WIDGET_PATH="$HOST_APP/Contents/PlugIns/BatteryBarWidgetExtension.appex"
    if [ -d "$WIDGET_PATH" ]; then
        echo "✓ Widget Extension bundle exists inside host."
    else
        echo "✗ Widget Extension NOT found inside host app plugins directory!"
    fi
else
    echo "✗ Widget Host App NOT found at $HOST_APP"
fi

# 2. Check Signatures and Entitlements
echo "
[2/5] Checking Code Signatures & Entitlements..."

check_signature() {
    local label="$1"
    local path="$2"
    if [ -d "$path" ]; then
        echo "
* $label signature verification:"
        /usr/bin/codesign --verify --deep --strict --verbose=2 "$path" 2>&1 || echo "  -> Signature verification FAILED!"
        
        echo "  Entitlements:"
        /usr/bin/codesign -d --entitlements - "$path" 2>/dev/null | grep -E "com.apple.security.app-sandbox|com.apple.security.application-groups" || echo "  -> No sandbox/group entitlements found or unsigned."
    else
        echo "  - $label not installed; skipping signature check."
    fi
}

check_signature "Main App" "$MAIN_APP"
check_signature "Host App" "$HOST_APP"
if [ -d "$HOST_APP/Contents/PlugIns/BatteryBarWidgetExtension.appex" ]; then
    check_signature "Widget Extension" "$HOST_APP/Contents/PlugIns/BatteryBarWidgetExtension.appex"
fi

# 3. Check LaunchAgent and Login Items
echo "
[3/5] Checking Autostart LaunchAgents & Login Items..."
AGENT_PATH="$HOME/Library/LaunchAgents/io.github.l351i3.batterybar.plist"
if [ -f "$AGENT_PATH" ]; then
    echo "✓ LaunchAgent file exists: $AGENT_PATH"
    echo "  ProgramArguments: $(defaults read "$AGENT_PATH" ProgramArguments 2>/dev/null || echo "Unknown")"
    echo "  RunAtLoad: $(defaults read "$AGENT_PATH" RunAtLoad 2>/dev/null || echo "Unknown")"
    
    # Check if loaded in launchctl
    echo "  Status in launchd:"
    launchctl list | grep "io.github.l351i3.batterybar" || echo "  -> Not active in current launchctl session."
else
    echo "✗ LaunchAgent plist NOT found."
fi

# 4. Check Widget PluginKit Registration
echo "
[4/5] Checking Widget Registration Status..."
if command -v pluginkit &>/dev/null; then
    echo "Querying pluginkit for: $WIDGET_ID"
    PLUGINS=$(/usr/bin/pluginkit -m -A -D -v -i "$WIDGET_ID" 2>&1)
    if [ -n "$PLUGINS" ]; then
        echo "$PLUGINS"
        COUNT=$(echo "$PLUGINS" | grep -c "path=" || echo "0")
        if [ "$COUNT" -gt 1 ]; then
            echo "⚠️ WARNING: Multiple physical copies of the Widget are registered with the same ID!"
            echo "  This usually causes system conflicts and breaks widget updates."
        fi
    else
        echo "✗ Widget NOT registered in PlugInKit database."
    fi
else
    echo "pluginkit command not available."
fi

# 5. Check System Log Warnings
echo "
[5/5] Scanning system logs for related subsystem errors (last 10m)..."
if command -v log &>/dev/null; then
    log show --predicate 'subsystem == "com.apple.chrono" or process == "chronod"' --last 10m 2>/dev/null | grep -Ei "battery|widget|sandboxed|deny" | tail -n 10 || echo "  No chronod/chrono log entries found in the last 10 minutes."
else
    echo "log command not available (requires admin privileges or system support)."
fi

echo "
=============================================================================="
echo "Diagnostic Finished. Please provide this output to the developer if widgets do not load."
echo "=============================================================================="
