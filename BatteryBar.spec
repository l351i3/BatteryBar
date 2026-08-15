# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


project_root = Path(SPECPATH)
icon_path = (
    project_root
    / "resources"
    / "AppIcon.icns"
)

app_icon = (
    str(icon_path)
    if icon_path.is_file()
    else None
)

hidden_imports = [
    "AppKit",
    "CoreBluetooth",
    "Foundation",
    "PyObjCTools",
    "PyObjCTools.AppHelper",
    "dispatch",
    "objc",
    "rumps",
]

analysis = Analysis(
    ["app.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (
            str(
                project_root / "resources"
            ),
            "resources",
        ),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tests",
        "tkinter",
        "unittest",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="BatteryBar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BatteryBar",
)

application = BUNDLE(
    collection,
    name="Battery Bar.app",
    icon=app_icon,
    bundle_identifier=(
        "io.github.l351i3.batterybar"
    ),
    info_plist={
        "CFBundleDisplayName": "Battery Bar",
        "CFBundleName": "BatteryBar",
        "CFBundleShortVersionString": "2.1.2",
        "CFBundleVersion": "2.1.2",
        "NSHumanReadableCopyright": (
            "Copyright © 2026 l351i3. "
            "All rights reserved."
        ),
        "LSUIElement": True,
        "NSBluetoothAlwaysUsageDescription": (
            "Battery Bar 需要访问蓝牙，"
            "以读取已连接外设公开的电量信息。"
        ),
        "NSBluetoothPeripheralUsageDescription": (
            "Battery Bar 需要访问蓝牙，"
            "以读取已连接外设公开的电量信息。"
        ),
        "NSHighResolutionCapable": True,
    },
)
