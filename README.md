# Battery Bar

[English](README_EN.md) | [简体中文](README.md)

macOS 菜单栏外设电量监控工具。一只眼睛盯住你所有无线设备的电量：AirPods、Magic Keyboard / Mouse / Trackpad、罗技键鼠（Unifying / Bolt 接收器）、以及任意标准 BLE 设备。

![macOS](https://img.shields.io/badge/macOS-14%2B%20(Sonoma)-arm64) ![Arch](https://img.shields.io/badge/arch-Apple%20Silicon%20only-red) ![Python](https://img.shields.io/badge/Python-3.9%2B-blue) ![Tests](https://img.shields.io/badge/tests-113%20passed-brightgreen) ![License](https://img.shields.io/badge/license-MIT-green)

## 功能特性

### 📊 全设备电量监控

| 数据来源 | 覆盖设备 | 说明 |
|----------|----------|------|
| system_profiler + pmset | AirPods、Magic 系列、已配对蓝牙设备 | 含充电状态（macOS 唯一可靠的充电数据源） |
| BLE GATT（CoreBluetooth） | 标准 Battery Service (0x180F) 设备 | 如 DJI Mic 等第三方 BLE 外设 |
| 罗技 HID++ 2.0 | Unifying / Bolt 接收器键鼠 | 动态 Feature 寻址，支持槽位 1–6 多设备 |

- **AirPods 三组件独立显示**：左耳 / 右耳 / 充电盒分开显示电量
- **充电状态**：充电中的设备显示「充电中」；AirPods 放入充电盒即可识别（通过匿名 pmset 条目的电量匹配）
- **智能分类**：设备自动归类为键盘 / 鼠标 / 麦克风 / 耳机 / 触控板等

### 🔋 四态菜单栏图标（安全优先）

| 状态 | 图标 | 触发条件 |
|------|------|----------|
| low | 🔴 红色 | 存在未充电且电量 ≤20% 的设备（最高优先级警报） |
| charging | 🟢 绿色 | 存在正在充电的设备 |
| full | 🟡 金色 | 所有设备电量 ≥95% |
| normal | ⚪ 黑白 | 常规状态，自动适配深/浅色菜单栏 |

- 每 5 分钟自动刷新，也可手动「立即刷新」
- 设备断连后保留最后电量 10 分钟并标记 `[已离线]`，不参与图标告警判定

### 🖥 桌面小组件

Full 安装包含 Swift WidgetKit 桌面小组件，通过快照同步机制与菜单栏应用共享数据。

### 🩺 数据源诊断

菜单内置「数据源状态」子菜单：每个数据源的成功/失败、设备数、耗时、错误信息，排查「为什么没设备」的第一入口。

## 安装

### 方式一：下载 DMG（推荐）

从 [Releases](https://github.com/l351i3/BatteryBar/releases) 下载：

- **BatteryBar-Full.dmg** — 主应用 + 桌面小组件
- **BatteryBar-AppOnly.dmg** — 仅主应用

> ⚠️ **硬件要求：Apple Silicon（M1/M2/M3/M4）**。安装包仅包含 arm64 架构，Intel Mac 无法运行。
>
> 应用为 ad-hoc 签名，首次打开需**右键 → 打开**绕过 Gatekeeper。

### 方式二：源码运行

```bash
git clone https://github.com/l351i3/BatteryBar.git
cd BatteryBar
pip3 install -r requirements.txt
python3 app.py
```

## 构建

```bash
./build_release_final.sh
```

自动完成：依赖安装 → 全量测试 → PyInstaller 打包 → Xcode 构建 Widget 宿主 → ad-hoc 签名 → 生成 DMG + SHA-256 清单。

## 测试

```bash
pip3 install pytest
python3 -m pytest tests/ -q
```

113 个单元测试覆盖全部三个数据源、聚合器、分类器与快照存储。

## 项目结构

```text
BatteryBar/
├── app.py                    # 菜单栏 UI（rumps）+ 四态图标
├── aggregator.py             # 多源聚合、去重、优先级合并、离线缓存
├── provider_registry.py      # 数据源注册
├── system_provider.py        # system_profiler + pmset（含 AirPods 充电匹配）
├── bluetooth_provider.py     # BLE GATT（CoreBluetooth 并发安全）
├── hidpp_provider.py         # 罗技 HID++ 2.0 协议
├── classifier.py             # 设备类型分类器
├── models.py                 # 数据模型（BatteryDevice / 快照）
├── snapshot_store.py         # 快照持久化（原子写入）
├── widget_snapshot_sync.py   # Widget 沙盒快照同步
├── resources/                # 图标资源
├── Widget/                   # Swift 桌面小组件工程
└── tests/                    # 113 个单元测试
```

## 已知限制

- **仅 Apple Silicon**：本项目在 M4 (Apple Silicon) 上开发测试，发布包只含 arm64 架构。Intel Mac 无法运行安装包；源码运行理论上可行（依赖均支持 Intel）但完全未测试
- **Magic Keyboard / Mouse 插线充电**：设备切换为 USB HID 模式，蓝牙通道停止上报数据，属硬件/协议限制，充电状态此时不可见
- **HID++ 设备深度休眠**：首次刷新可能读到占位名（如 `HID++ Device Slot 2`），下一次刷新会自动恢复真实名称
- **无 Developer ID 签名**：正式分发需自购证书

## 文档

- [CHANGELOG.md](CHANGELOG.md) — 版本历史
- [DEVELOPMENT.md](DEVELOPMENT.md) — 架构、协议细节（含 HID++ 2.0 要点）、构建与调试指南

## 许可证

[MIT](LICENSE) © 2026 l351i3
