# Battery Bar

[English](README_EN.md) | [简体中文](README.md)

A macOS menu bar app that keeps an eye on the battery of every wireless device you own: AirPods, Magic Keyboard / Mouse / Trackpad, Logitech keyboards and mice (Unifying / Bolt receivers), and any standard BLE device.

![macOS](https://img.shields.io/badge/macOS-14%2B%20(Sonoma)-arm64) ![Arch](https://img.shields.io/badge/arch-Apple%20Silicon%20only-red) ![Python](https://img.shields.io/badge/Python-3.9%2B-blue) ![Tests](https://img.shields.io/badge/tests-113%20passed-brightgreen) ![License](https://img.shields.io/badge/license-MIT-green)

> **Note:** the app UI is currently Chinese-only. See [Known Limitations](#known-limitations).

## Features

### 📊 All-device battery monitoring

| Data source | Devices covered | Notes |
|-------------|-----------------|-------|
| system_profiler + pmset | AirPods, Magic accessories, paired Bluetooth devices | Includes charging state (the only reliable source on macOS) |
| BLE GATT (CoreBluetooth) | Standard Battery Service (0x180F) devices | e.g. third-party BLE accessories like DJI Mic |
| Logitech HID++ 2.0 | Unifying / Bolt receiver keyboards & mice | Dynamic feature addressing, slots 1–6, multi-device |

- **AirPods three-component display**: left ear / right ear / charging case shown separately
- **Charging state**: charging devices show a "charging" label; AirPods are recognized as charging when placed in the case (via level-matched anonymous pmset entries)
- **Smart classification**: devices are auto-categorized as keyboard / mouse / microphone / headphones / trackpad, etc.

### 🔋 Four-state menu bar icon (safety first)

| State | Icon | Trigger |
|-------|------|---------|
| low | 🔴 Red | Any device at ≤20% and not charging (highest-priority alert) |
| charging | 🟢 Green | Any device charging |
| full | 🟡 Gold | All devices ≥95% |
| normal | ⚪ Black & white | Default; adapts to light/dark menu bar |

- Auto refresh every 5 minutes, plus manual refresh
- Offline devices keep their last known level for 10 minutes, marked `[Offline]`, and never trigger icon alerts

### 🖥 Desktop widget

The Full install includes a Swift WidgetKit desktop widget that shares data with the menu bar app via snapshot sync.

### 🩺 Data source diagnostics

A built-in "data source status" submenu shows each provider's success/failure, device count, duration, and error message — the first place to look when a device goes missing.

## Installation

### Option 1: Download the DMG (recommended)

Grab it from [Releases](https://github.com/l351i3/BatteryBar/releases):

- **BatteryBar-Full.dmg** — main app + desktop widget
- **BatteryBar-AppOnly.dmg** — main app only

> ⚠️ **Hardware requirement: Apple Silicon (M1/M2/M3/M4)**. The packages are arm64-only and will not run on Intel Macs.
>
> The app is ad-hoc signed; on first launch, **right-click → Open** to bypass Gatekeeper.

### Option 2: Run from source

```bash
git clone https://github.com/l351i3/BatteryBar.git
cd BatteryBar
pip3 install -r requirements.txt
python3 app.py
```

## Building

```bash
./build_release_final.sh
```

Runs the full pipeline: dependency install → all tests → PyInstaller packaging → Xcode widget host build → ad-hoc signing → DMG + SHA-256 manifest.

## Testing

```bash
pip3 install pytest
python3 -m pytest tests/ -q
```

113 unit tests cover all three data providers, the aggregator, classifier, and snapshot store.

## Project structure

```text
BatteryBar/
├── app.py                    # Menu bar UI (rumps) + 4-state icon
├── aggregator.py             # Multi-source aggregation, dedup, priority merge, offline cache
├── provider_registry.py      # Provider registration
├── system_provider.py        # system_profiler + pmset (incl. AirPods charging match)
├── bluetooth_provider.py     # BLE GATT (CoreBluetooth, concurrency-safe)
├── hidpp_provider.py         # Logitech HID++ 2.0 protocol
├── classifier.py             # Device classification
├── models.py                 # Data models (BatteryDevice / snapshot)
├── snapshot_store.py         # Snapshot persistence (atomic writes)
├── widget_snapshot_sync.py   # Widget sandbox snapshot sync
├── resources/                # Icon assets
├── Widget/                   # Swift desktop widget project
└── tests/                    # 113 unit tests
```

## Known Limitations

- **Apple Silicon only**: developed and tested on an M4 Mac; release packages are arm64-only. Intel Macs cannot run the packages; running from source may theoretically work (all dependencies support Intel) but is entirely untested
- **UI language**: Chinese only for now; localization is not yet available
- **Magic Keyboard / Mouse charging over cable**: the device switches to USB HID mode and stops reporting over Bluetooth — a hardware/protocol limitation; charging state is invisible during this
- **HID++ deep sleep**: the first refresh after a device wakes may show a placeholder name (e.g. `HID++ Device Slot 2`); the real name returns on the next refresh
- **No Developer ID signing**: formal distribution requires purchasing a certificate

## Documentation

- [CHANGELOG.md](CHANGELOG.md) — release history
- [DEVELOPMENT.md](DEVELOPMENT.md) — architecture, protocol details (incl. HID++ 2.0 notes), build & debugging guide (Chinese)

## License

[MIT](LICENSE) © 2026 l351i3
