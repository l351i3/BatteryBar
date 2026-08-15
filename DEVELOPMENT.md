# Battery Bar 开发文档

> 本文档面向后续维护与二次开发者，覆盖功能、架构、实现细节、构建发布、测试与已知改进项。

---

## 目录

1. [项目概述](#1-项目概述)
2. [功能特性](#2-功能特性)
3. [系统架构](#3-系统架构)
4. [核心数据模型](#4-核心数据模型)
5. [Provider 详解](#5-provider-详解)
   - 5.1 [System Provider](#51-system-provider)
   - 5.2 [Bluetooth (BLE) Provider](#52-bluetooth-ble-provider)
   - 5.3 [HID++ Provider（重点）](#53-hidpp-provider重点)
6. [聚合器与去重](#6-聚合器与去重)
7. [分类器](#7-分类器)
8. [快照持久化与 Widget 同步](#8-快照持久化与-widget-同步)
9. [菜单栏 UI](#9-菜单栏-ui)
10. [桌面 Widget（Swift）](#10-桌面-widgetswift)
11. [构建与打包](#11-构建与打包)
12. [测试](#12-测试)
13. [配置常量速查](#13-配置常量速查)
14. [已知问题与改进方向](#14-已知问题与改进方向)
15. [调试与诊断工具](#15-调试与诊断工具)
16. [附录：HID++ 2.0 协议要点](#16-附录hidpp-20-协议要点)

---

## 1. 项目概述

**Battery Bar** 是一款 macOS 外设电量聚合显示工具，以菜单栏（menu bar）常驻图标 + 可选桌面 Widget 的形式，统一展示系统中各类无线外设的电池电量。

**设计目标：**

- 统一聚合多个异构数据源（系统 API、BLE GATT、USB HID++），对用户呈现一致的电量视图。
- 设备发现**完全动态**，不硬编码任何产品型号、PID 或槽位。
- 对休眠/延迟响应的设备具备鲁棒性（重试、SwID 区分、超时兜底）。
- 尽量不触发 macOS 隐私授权弹窗（尤其避免"输入监控"权限）。

**技术栈：**

| 层 | 技术 |
|----|------|
| 菜单栏 UI | Python `rumps` 0.4.0（封装 AppKit `NSStatusBar`） |
| 桌面 Widget | Swift + WidgetKit（原生 Xcode 工程） |
| 设备探测 | `hidapi`（USB HID）、`pyobjc` CoreBluetooth（BLE GATT）、`subprocess`（系统命令） |
| 打包 | PyInstaller（Python 主程序）+ xcodebuild（原生 Widget 宿主） |
| 签名 | ad-hoc（无 Developer ID） |

**平台要求：** macOS 14.0+（Widget 需要 Sonoma），Apple Silicon（arm64）。

---

## 2. 功能特性

### 对用户

- 🔋 菜单栏常驻图标（4 态：正常/低电量红/满电金/充电绿），点击展开分类设备列表（键盘/鼠标/麦克风/耳机/音箱/触控板/触控笔/手柄/其他）。
- 每台设备显示：名称、电量百分比、电源状态（充电中/已充满）、`[已离线]` 缓存标记。
- 支持 AirPods 等多部件设备，分部件（左耳/右耳/电池盒）独立显示。
- "立即刷新"手动触发；默认每 **5 分钟**自动刷新（v2.1.1 从 15 分钟缩短）。
- "数据源状态"子菜单显示各 Provider 的成功/失败、设备数、耗时、错误信息。
- 首次启动自动加入登录项（开机自启，无 Dock 图标）。
- 桌面 Widget（需安装 Full 包）：小/中/大三档，颜色按电量分级（红 ≤10%、橙 ≤25%），通过文件监视实时刷新。

### 对设备

| 设备类型 | 支持来源 | 电量 | 充电状态 | 多部件 |
|----------|----------|------|----------|--------|
| AirPods / Beats | System (`system_profiler` + `pmset`) | ✅ | ⚠️ | ✅ 左/右/盒 |
| 罗技 Unifying/Bolt 外设 | HID++ | ✅ | ❌ | ❌ |
| 标准 BLE Battery Service 外设 | BLE GATT (0x180F) | ✅ | ❌ | ❌ |
| 其他系统附件 (`pmset`) | System | ✅ | ⚠️ | ❌ |

> ⚠️ 充电状态说明：`pmset -g accps` 能返回 AirPods 等附件的 `charging` 状态字段，但由于数据源优先级覆盖（`system_bluetooth` 200 > `system_accessory` 100）和跨设备 ID 匹配的不确定性，当前版本已实现智能合并策略（`_prefer` 补充 + `_deduplicate_system_devices` 传播），但**实际真机验证中充电图标仍未可靠触发**。键盘/鼠标在插线充电时会切换为 USB HID 模式，蓝牙通道不再上报数据。详见 §14 第 17 条。

---

## 3. 系统架构

### 数据流总览

```
┌─────────────────────────────────────────────────────────────┐
│  三个 Provider 顺序执行（system → ble_standard → hidpp）       │
│                                                              │
│  system_provider          bluetooth_provider   hidpp_provider│
│   system_profiler          CoreBluetooth         hidapi USB  │
│   pmset -g accps           GATT 0x180F/0x2A19    HID++ 2.0   │
└──────────────┬───────────────────────────────────────────────┘
               │ 产出 List[BatteryDevice]
               ▼
┌─────────────────────────────────────────────────────────────┐
│  BatteryAggregator.refresh()                                  │
│   1. 去重（device_id → name+category 两层）                    │
│   2. 更新内存缓存（3600s 过期）                                 │
│   3. 合并新鲜 + 未过期缓存设备                                   │
│   产出 BatterySnapshot                                        │
└──────────────┬───────────────────────────────────────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
┌─────────────┐   ┌──────────────────────────────────────────┐
│ 菜单栏渲染    │   │ write_snapshot_atomic() → snapshot.json   │
│ build_menu_  │   │   ~/Library/Application Support/          │
│ rows()       │   │       Battery Bar/snapshot.json            │
│ rumps        │   └──────────────┬───────────────────────────┘ │
└─────────────┘                  ▼                              │
                   sync_widget_snapshot() → Widget 容器目录       │
                          │                                     │
                          ▼                                     │
              ┌───────────────────────────────┐                │
              │ BatteryBarNative (Swift)       │                │
              │  FSEvents 监视 snapshot.json   │                │
              │  → WidgetCenter.reloadTimelines│                │
              └──────────────┬────────────────┘                │
                             ▼                                  │
              ┌───────────────────────────────┐                │
              │ BatteryBarWidget (WidgetKit)   │                │
              │  读取 snapshot.json → SwiftUI   │                │
              └───────────────────────────────┘                │
```

### 目录结构（核心文件）

```
BatteryBar/
├── app.py                     # 菜单栏入口（rumps.App），958 行
├── models.py                  # BatteryDevice 数据模型 + 校验，325 行
├── classifier.py              # 设备分类优先级链，376 行
├── aggregator.py              # 聚合/去重/缓存引擎，600 行
├── provider_registry.py       # Provider 装配（依赖注入），40 行
├── system_provider.py         # 系统命令数据源，1049 行
├── bluetooth_provider.py      # BLE GATT 数据源，507 行
├── hidpp_provider.py          # Logitech HID++ 数据源（核心），~800 行
├── snapshot_store.py          # 快照原子读写 + 校验，859 行
├── widget_snapshot_sync.py    # 快照同步到 Widget 沙盒容器，194 行
├── tests/                     # 单元测试（7 个文件，114 用例）
├── resources/                 # 资源文件目录
│   ├── Info.plist             # 主应用 bundle 元数据
│   ├── AppIcon.icns           # 应用图标（1024px 源生成 16/32/128/256/512）
│   ├── MenuBarNormal@2x.png   # 正常电量图标（@1x + @2x）
│   ├── MenuBarLow@2x.png      # 低电量图标（红色）
│   ├── MenuBarFull@2x.png     # 满电图标
│   └── MenuBarCharging@2x.png # 充电中图标（绿色）
├── entitlements.plist         # 主应用 entitlements（app-sandbox + app-group）
├── BatteryBar.spec            # PyInstaller 打包配置
├── requirements.txt           # Python 依赖锁定（含 bleak + pyobjc 9.2）
├── build_release.sh           # 基础构建（venv→测试→PyInstaller→xcodebuild→DMG）
├── build_release_final.sh     # 主打包脚本（调用上面，产出 Full + AppOnly 两份 DMG）
└── Widget/BatteryBarNative/   # 原生 Swift Widget 宿主工程
    ├── BatteryBarNativeApp.swift          # 宿主：FSEvents 文件监视 + 登录项
    ├── BatteryBarWidget/
    │   ├── BatteryBarWidget.swift         # WidgetKit TimelineProvider + SwiftUI
    │   └── BatteryBarWidgetBundle.swift   # Bundle 入口
    └── BatteryBarWidgetExtension.entitlements  # app-sandbox=true（必需）
```

---

## 4. 核心数据模型

### `BatteryDevice`（`models.py`，不可变 frozen dataclass）

```python
@dataclass(frozen=True)
class BatteryDevice:
    device_id: str            # 全局唯一 ID，去重主键
    name: str                 # 显示名（已清洗空白）
    category: str             # 9 类之一（见下）
    transport: str            # system/bluetooth/usb/receiver/unknown
    level: int                # 0-100
    charging: Optional[bool]  # True/False/None（未知）
    source: str               # 5 种来源之一（见下）
    observed_at: float        # unix 时间戳
    category_source: str      # 分类判定来源标记
    cached: bool = False      # 是否来自缓存
    power_state: Optional[str] = None  # charging/charged/discharging/unknown
```

**关键字段约束（`__post_init__` 校验）：**

- `level` 必须是 int（拒绝 bool），范围 0-100
- `charging` 与 `power_state` 必须一致（若两者都给定），否则抛 `ValueError`
- `name`/`device_id`/`category_source` 不能为空，且会做空白规范化
- `observed_at` 必须有限且非负

**9 种 category：** `keyboard` `mouse` `microphone` `headphones` `speaker` `trackpad` `stylus` `controller` `other`

**5 种 source（决定聚合优先级）：**

| source | 优先级 | 说明 |
|--------|--------|------|
| `hidpp` | 400 | Logitech HID++，最可靠 |
| `ble_standard` | 300 | BLE GATT Battery Service |
| `system_bluetooth` | 200 | system_profiler 蓝牙清单 |
| `system_accessory` | 100 | pmset 附件电源 |

**device_id 命名约定：**

- HID++：`hidpp:{pid:04x}:{serial}` 或无序列号时 `hidpp:{pid:04x}:slot-{md5(path)[:6]}-{slot}`
- BLE：`bluetooth:{peripheral_identifier_lowercase}`
- System 蓝牙：`system-bluetooth:{address}`
- 多部件后缀：`:left` `:right` `:case`（AirPods）

---

## 5. Provider 详解

所有 Provider 实现统一契约：`discover() -> List[BatteryDevice]`。Aggregator 在 `_run_provider` 中**捕获一切异常**并记录到 `ProviderStatus`，所以单个 Provider 崩溃不会影响其他 Provider——但这也意味着**部分失败会被静默吞掉**（表现为 `succeeded=True, device_count=0`），调试时需查"数据源状态"子菜单。

### 5.1 System Provider

**文件：** `system_provider.py`（1049 行）

负责从 macOS 系统数据源读取蓝牙及附件设备信息，并将设备名称、标识符、电量、连接状态和充电状态转换为统一的设备模型。

系统蓝牙数据与附件电源数据可能来自不同接口：蓝牙数据通常提供设备地址、连接状态和组件电量，而附件电源数据可能提供更准确的充电状态。由于两个数据源对同一设备的命名和标识方式并不完全一致，System Provider 需要在数据进入聚合层之前完成关联、补充与去重。

#### 多部件设备模糊关联匹配（Smart Suffix Match）

AirPods 等多部件设备可能被蓝牙数据源拆分为左耳、右耳和充电盒，并使用带组件后缀的设备标识：

```
system-bluetooth:<address>:left
system-bluetooth:<address>:right
system-bluetooth:<address>:case
```

附件电源数据源（`pmset -g accps`）则可能只返回设备名称，并将充电盒作为独立附件上报，例如：`User的AirPods Case`。这种记录没有蓝牙地址，也不会直接使用 `:case` 组件标识。

**已实现的匹配逻辑（`accessory_power_to_devices`，v2.1.1+）：**

1. **Case 后缀剥离**：如果附件名称以 `” Case”` 结尾（如 `User的AirPods Case`），自动去掉后缀得到 `User的AirPods`，用于蓝牙 inventory 查找。匹配成功后将 `device_id` 定位为 `base_id:case`，与 system_profiler 的组件 ID 完美对齐。
2. **精确名称匹配**：先在蓝牙 inventory 索引中按规范化名称精确查找候选设备。
3. **超集名称回退（Generational Overriding）**：如果精确匹配无结果，或唯一候选是未连接设备（可能为旧款），则遍历 inventory 查找名称包含 lookup name 的设备（如 `AirPods 4` 包含 `AirPods`）。按名称长度降序排列，选择最具体的匹配项。这解决了用户同时拥有 `User的AirPods`（旧款，未连接）和 `User的AirPods 4`（新款，活跃）时的绑定歧义。
4. **候选选择**：仅接受单候选结果（确定性绑定）；多个候选时退化为 `_stable_name_id`（基于名称的 ID）。

#### 匿名条目匹配（v2.1.2）

AirPods 在充电盒中时，`pmset -g accps` 输出的条目**没有设备名称**（仅有 id 和电量/充电状态）：

```
- (id=350361884)  96%; discharging present: true         ← 充电盒
- (id=350361885)  100%; charging; 0:00 remaining ...     ← 耳机（充电中）
```

这些匿名条目是 AirPods 充电状态的**唯一可靠数据源**。v2.1.1 及更早版本在 `record.name` 为空时直接 `continue`，丢弃了全部充电数据。

**`_anonymous_accessory_devices()`**（v2.1.2 新增）通过电量百分比将匿名条目与蓝牙清单中的多组件设备（`battery_left`/`battery_right`/`battery_case`）匹配：

- **匹配约束**：电量精确相等、唯一设备归属（跨设备歧义时放弃）、`claimed` 集合防止同一组件被重复绑定。
- **优先级排序**：charging/charged 记录排序优先于 discharging（左右耳电量相同时先应用充电状态，下游合并避免 discharging 抢占）。
- **`_effective_power_state(level, power_state)`**：100% + charging → `discharging`（非充电状态）。pmset 在设备充满后仍报 charging（0:00 remaining），实际充电已停止；显示”已充满”标签会误导用户以为设备仍在充电，故 100% 时不显示任何充电标签。

#### 活跃状态宽容度（No-Connected-Filter）

设备关联**不**把 `connected == True` 作为强制条件。

AirPods 进入低功耗状态、放入充电盒或暂时停止音频活动后，macOS 返回的连接状态可能是 `False`/`None`，或者在连续两次查询之间发生短暂变化。此时设备的电量和附件电源信息仍可能有效。如果在候选匹配阶段直接过滤所有非连接设备，就会造成以下问题：

- 充电盒记录无法关联到对应的 AirPods；
- 低功耗或休眠设备的电量记录被错误丢弃；
- 充电状态被绑定到名称相近的旧设备；
- 数据无法进入聚合层，菜单栏状态也就无法改变。

在 `accessory_power_to_devices` 的超集匹配中，`connected` 作为回退触发条件之一（唯一候选不连接时触发超集搜索），而非准入门槛。

#### 充电状态向组件传播

附件电源数据（`pmset -g accps`）可能只为设备根记录提供 `charging` 或 `power_state`，而蓝牙数据源保存的是左耳、右耳和充电盒等组件记录（这些组件来自 `system_profiler`，`charging=None`）。`_deduplicate_system_devices` 在去重前将充电状态补充到相应组件，避免根记录被过滤后丢失唯一的充电信息。

**已实现的传播逻辑（`_deduplicate_system_devices`，v2.1.1）：**

1. **充电映射表构建**：收集所有 `SOURCE_SYSTEM_ACCESSORY` 且 `charging is not None` 的设备，建立 `device_id → (charging, power_state)` 映射。
2. **组件继承**：遍历所有设备时，对带组件后缀（`:left`/`:right`/`:case`）的设备，检查其 base_id 是否在充电映射表中。若组件本身 `charging is None`，则从映射表继承充电状态。**不覆盖组件已有的明确状态**。
3. **重复项字段级合并**：对于相同 `device_id` 的重复记录（如蓝牙键盘在两个数据源中都出现），不再简单丢弃后出现的记录。如果已有记录 `charging is None` 而新记录有明确的 `charging`，则合并为新记录保留两者信息。
4. **根设备过滤**：如果一个根设备 ID 已有展开的子组件（`:left`/`:right`/`:case`），来自 `SOURCE_SYSTEM_ACCESSORY` 的根记录会被过滤掉，避免重复显示。

#### 与菜单栏状态的关系

System Provider 只负责产生可靠、可追踪的设备状态，不直接决定菜单栏使用哪个图标。完整的数据链路为：

```
macOS 数据源 → System Provider 解析与关联 → 设备字段合并与去重
    → Aggregator 生成统一快照 → App 选择菜单栏状态 → 状态栏图标更新
```

多部件关联失败或充电字段在去重过程中丢失时，界面层即使逻辑正确，也不会收到 `charging=True`。排查菜单栏状态不更新时，应逐层验证上述链路。

### 5.2 Bluetooth (BLE) Provider

**文件：** `bluetooth_provider.py`（~520 行）

**原理：** 通过 PyObjC 调用 CoreBluetooth，读取标准 BLE Battery Service。

**线程模型（GCD 串行队列）：**

```
模块级 _BLE_QUEUE = dispatch_queue_create(b'com.batterybar.ble', None)

CBCentralManager.alloc().initWithDelegate_queue_(delegate, _BLE_QUEUE)
                                          ↑
                                  回调派发到 GCD 串行队列
                                  （非主队列，不依赖 NSRunLoop）
```

**会话生命周期（`_DiscoverySession`）：**

```
创建 session → CBCentralManager.init → 等待 done_event
                                        ↑
                                   try_finish (首次终态胜出)
                                   ├─ completed: 所有 peripherals 处理完
                                   ├─ failed: 蓝牙不可用
                                   └─ timeout: deadline 到期
                                        ↓
                              begin_cleanup (快照对象)
                                        ↓
                              dispatch_async(cancelPeripheral)
                                        ↓
                              finish_cleanup (清引用/断环)
                                        ↓
                              等待 cleanup_event
```

**协议：**

```
CBCentralManager
  → retrieveConnectedPeripheralsWithServices_([0x180F])  # 只取已连接的
    → connect(peripheral)
      → discoverServices([0x180F])
        → discoverCharacteristics([0x2A19])
          → readValueForCharacteristic  # 1 字节，0-100
```

**关键常量：**

| 常量 | 值 | 说明 |
|------|----|------|
| `DEFAULT_TIMEOUT` | 12.0s | discover_batteries 统一超时 |
| `BATTERY_SERVICE` | 0x180F | Battery Service UUID |
| `BATTERY_LEVEL` | 0x2A19 | Battery Level UUID |
| `CACHE_TTL_SECONDS` | 10s | system_profiler 缓存 TTL |
| `MAX_STALE_AGE_SECONDS` | 60s | 过期缓存最大可用年龄 |

**并发安全设计：**

- **锁层级**：`_DISCOVERY_LOCK` → `session._lock`（固定，不可逆序）
- **delegate 回调**：只获取 `session._lock`，不获取 `_DISCOVERY_LOCK`
- **持锁不调 CoreBluetooth/logging**：避免重入和性能问题
- **`discovery_closed` 守卫**：pending 为空但扫描未关闭时不触发完成
- **`peripheral_id` 字符串 key**：不依赖 CBPeripheral 的 Python 哈希

**特点：**

- GCD 串行队列保证回调顺序；后台轮询线程用 `threading.Event.wait()`（无 polling）。
- 不扫描、只取已连接外设（避免主动扫描的能耗和权限开销）。
- AirPods / DJI Mic Mini 不暴露 0x180F，所以查不到（靠 system_provider 兜底）。

**局限：**

- 无充电状态、无多部件
- 单外设失败无重试，直接 skip

### 5.3 HID++ Provider（重点）

**文件：** `hidpp_provider.py`（~740 行）。这是本项目的**核心难点**，也是历次 bug 集中地。

#### 5.3.1 接收器枚举（`enumerate_hidpp_receivers`）

```python
hid.enumerate(0x046D)  # Logitech vendor ID
```

**关键设计——避开隐私权限：**

macOS 上打开 `usage_page=0x01`（键盘/鼠标）或 `0x0C`（消费键）的 HID 接口会触发"输入监控"权限弹窗。本函数：

- **打分**：`usage_page=0xFF00`（厂商自定义，真正的 HID++ 接口）→ 100 分；`0x0000` → 50 分；`0x01`/`0x0C` → 10 分
- **每个物理设备只选最高分接口**（按 pid + serial + 路径前缀分组）
- 这样只打开 0xFF00 接口，**完全不触发键盘监听权限**

返回 `Dict[path, product_id]`，path 在 macOS 上是 `bytes`（如 `b'DevSrvsID:4294970718'`）。

#### 5.3.2 动态电量 Feature 发现（核心，非硬编码）

HID++ 2.0 有**两套**电量协议，必须向设备本身询问它支持哪个：

```python
# hidpp_provider.py 第 27 行
BATTERY_FEATURE_CANDIDATES = [
    (0x1004, 1, 0x01),  # UnifiedBattery:     Function 1, SwID=0x01（新设备：MX Keys S, MX Anywhere 3S）
    (0x1000, 0, 0x02),  # BatteryStatus:      Function 0, SwID=0x02（老设备/Unifying：MX Anywhere 2S）
]
```

**发现流程（`probe_device_on_slot`）：**

1. 对每个 slot（1-6），遍历候选列表
2. 对每个候选，用 `Root.GetFeature (0x0000)` 询问"你支持 feature 0x1004 吗？"
3. 设备返回 feature index（>0 支持，=0 不支持）
4. 命中第一个支持的候选，记录其 `feature_index` 和 `function`

**两种协议电量都在响应的 `res[4]`**（已实测确认），所以下游读取代码统一。

#### 5.3.3 SwID 区分响应（关键 bug 修复点）

**问题背景：** 同一台休眠设备，连续发 0x1004 和 0x1000 两个查询。设备被第一个请求唤醒后，**两个响应可能交错返回**，导致 0x1000 的查询匹配到 0x1004 的延迟响应，读到错误电量。

**解决方案：** 每个候选用**不同的 Software ID**（SwID）。HID++ 响应的 `res[3]` 低 4 位会回显请求的 SwID，据此区分：

- 0x1004 查询用 SwID=0x01
- 0x1000 查询用 SwID=0x02

这样即使响应乱序，也能通过 `res[3]` 准确归属，**杜绝跨协议响应串位**。

> ⚠️ **历史教训**：MX Anywhere 3S 曾显示 15%（实际 85%），根因就是两个候选共用 SwID=0x01，导致 0x1004 的延迟响应污染了 0x1000 查询。改用不同 SwID 后 6/6 全对。**改动 HID++ 报文前务必吃透协议再动手。**

#### 5.3.4 报文字节布局（20 字节长报告）

```
偏移  内容                          说明
[0]   0x11                          HID++ 长报告标识
[1]   slot                          设备槽位 1-6
[2]   feature_index                 Root.GetFeature 返回的索引
[3]   (function<<4) | (swid & 0xF)  高 4 位=函数号，低 4 位=Software ID
[4-5] feature_id（大端）            仅 Root.GetFeature 请求需要
[6-19] 0x00 填充
```

**响应匹配：** `res[0] in (0x10,0x11)` 且 `res[1]==slot` 且 `res[2]==feature_index` 且 `res[3]==请求的 function_client`。

**错误识别：** `res[2]==0xFF`（错误）或 `res[2]==0x8F`（未知设备/空 slot）。

#### 5.3.5 其他 Feature

| Feature | 用途 | 函数 |
|---------|------|------|
| 0x0000 | Root（GetFeatureIndex） | 0 |
| 0x0005 | DeviceName | 0=查长度，1=读字符 |
| 0x0003 | DeviceInfo（序列号） | 0，序列号在 `res[12:15]` |

#### 5.3.6 鲁棒性设计

- **`_drain(device, settle_ms=20)`**：每次 write 前 read 到空，丢弃 20ms 窗口内的在途残留响应，防止跨查询串位。
- **`_wakeup_pulse(device, slot, settle_ms=150)`**：发送 Root Feature 自查询（SwID=0x09）作为心跳唤醒深度休眠设备。唤醒耗时 100-200ms，settle 后再 `_drain` 排空缓冲区。SwID=0x09 与后续查询的 SwID（0x02/0x03）分离，避免唤醒响应串位。
- **电量探测后 settling delay**：`probe_device_on_slot` 中电量 feature 找到后加 `time.sleep(0.1)`，让 USB 管道稳定，避免紧接着的 feature 查询因设备未就绪而超时（实测 MX Keys S 冷启动的关键修复）。
- **Name/info feature wakeup 重试**：`name_idx` 或 `info_idx` 首次查询失败（`timeout=0.5s`）时，发 `_wakeup_pulse(settle_ms=200)` 后以更长 timeout (0.8s) 重试一次。深度休眠设备首次唤醒不充分，重试通常能成功。
- **空 slot 快速退出**：`0x8F` 在 ~2ms 内返回，探测时长 <0.1s 判定为空 slot 直接返回 None（放在候选循环**外**，避免误杀只支持 0x1000 的设备）。
- **名字长度查询 3 次指数退避重试**：休眠设备首次无响应，重试延迟 `0.1s → 0.2s → 0.4s`，给设备逐步加长的唤醒时间；全部失败则退化为读 16 字符。
- **`isprintable()` 校验**：解码后若含不可打印字符（残留响应污染），拒绝该名字，回退 slot 占位名。
- **modelId 反查兜底**：名字读取失败时，通过 0x0003 DeviceInfo 的 modelId（offset 9-11）反查 `_KNOWN_MODEL_NAMES` 字典（14 个常见型号），避免显示无意义 Slot 编号。
- **`_clean_logitech_name`**：去除罗技冗余前缀（"Wireless Mobile Mouse MX Anywhere 2S" → "MX Anywhere 2S"）。
- **`_guess_hid_usage`**：根据设备名猜测 HID usage（用于分类）。fallback 名 "HID++ Device Slot N" 返回 `0x00`（不归类为鼠标，避免键盘错入鼠标分类）。

#### 5.3.7 receiver_path 的 bytes 陷阱

macOS hidapi 返回的 path 是 `bytes`。`_make_device` 中对 path 做 `hashlib.md5(path.encode())`，但 bytes 没有 `.encode()` 会抛 `AttributeError`，被 aggregator 吞掉后表现为"探测到设备但 device_count=0"。**必须先 `isinstance(path, bytes)` 判断并 decode。**

---

## 6. 聚合器与去重

**文件：** `aggregator.py`（600 行）

### 刷新流程（`refresh()`）

```
for provider in [system, ble_standard, hidpp]:   # 顺序执行
    devices, status = _run_provider(provider)     # 异常全捕获
    all_devices.extend(devices)
    statuses.append(status)

fresh = deduplicate_devices(all_devices)          # 第一轮去重
_update_cache(fresh, now)                          # 写缓存（非 cached 副本）
visible = _visible_devices(fresh, now)             # 合并新鲜 + 未过期缓存
return BatterySnapshot(now, visible, statuses)
```

### 两层去重（`deduplicate_devices`）

1. **按 `device_id`**：相同 ID 取质量更高者（`_prefer`）
2. **按 `(规范化名称, category)`**：仅对无部件后缀的设备，防止同一物理设备被不同来源重复计入。有部件后缀的设备（AirPods 左/右/盒）单独保留。

### 质量比较（`_prefer`）与充电状态智能合并

```
1. 非缓存 优于 缓存
2. source 优先级高者优先（HIDPP 400 > BLE 300 > ...）
3. observed_at 更新者优先
4. device_id / name 兜底（确定性）
```

**v2.1.1 新增：充电状态智能补充。** 在比较优先级前，先检查两边的 `charging` 字段。如果高优先级记录的 `charging is None` 而低优先级记录有明确的 `charging`（或反之），则在比较前将缺失方用对方的值补充。这解决了 `system_bluetooth`（优先级 200，`charging=None`）覆盖 `system_accessory`（优先级 100，`charging=True`）导致充电状态丢失的问题。`power_state` 同理，仅在值为 `"charging"` 或 `"charged"` 时补充。

### 缓存

- 纯内存，不持久（每次进程重启清空）
- 默认 **600s 过期**（v2.1.1 从 3600s 缩短至 600s）
- 缓存设备在 UI 显示 `[已离线]` 标记并置灰
- 作用：单个 Provider 偶发失败时，仍显示上次成功的数据

---

## 7. 分类器

**文件：** `classifier.py`（376 行）

### 优先级链（`classify_device`）

```
1. MODEL_OVERRIDES    型号强制覆盖（如 "dji mic mini" → microphone）
2. 音频能力            有 audio_input → microphone；纯 output → headphones
3. HID_USAGE_MAP      (usage_page, usage) 精确映射
4. BLE_APPEARANCE_MAP 外观 UUID 映射
5. SYSTEM_CATEGORY_MAP 系统类别字符串
6. NAME_RULES         名称关键词匹配
7. fallback           → other
```

### HID_USAGE_MAP

```python
(0x01, 0x02): mouse       (0x01, 0x06): keyboard
(0x01, 0x05): controller  (0x01, 0x07): keyboard
(0x0D, 0x02): stylus      (0x0D, 0x05): trackpad
```

> 注意：`(0x01, 0x00)` 不在表中 → 返回 None → 继续走后续分类。HID++ Provider 对 fallback 名返回 `0x00` 正是利用这一点。

### 名称规则

`NAME_RULES` 是有序元组，按类别分组，每组多个关键词（含中文：`键盘`/`鼠标`/`耳机`等）。规范化为小写 + 空白合并后做包含匹配。

---

## 8. 快照持久化与 Widget 同步

### `snapshot_store.py`（859 行）

**路径：** `~/Library/Application Support/Battery Bar/snapshot.json`

**Schema v2**，原子写入（tempfile + fsync + os.replace），完整往返校验（写后读回验证）。包含：`schema_version`、`updated_at`、`devices[]`、`provider_statuses[]`。

### `widget_snapshot_sync.py`（194 行）

Widget 运行在独立沙盒容器，无法直接读主应用的 Application Support 目录。所以主应用刷新后，把 snapshot.json **复制**到两个容器：

```
~/Library/Containers/io.github.l351i3.batterybar.widgethost.widget/Data/.../snapshot.json
~/Library/Containers/io.github.l351i3.batterybar.widgethost/Data/.../snapshot.json
```

复制同样是原子操作（tempfile + fsync + os.replace + 目录 fsync）。任一目标失败不影响另一个。

---

## 9. 菜单栏 UI

**文件：** `app.py`（958 行）

### 关键设计

- **`rumps.App`** 子类 `BatteryBarApp`，标题为 🔋 emoji。
- **`NSApplicationActivationPolicyAccessory`**：无 Dock 图标。
- **`threading.Lock`** 串行化刷新（防止定时器和手动刷新并发）。
- **后台线程刷新**：`_refresh_worker` 在 daemon 线程跑聚合，完成后 `AppHelper.callAfter` 回主线程更新 UI。
- **`_set_item_enabled`**：同时设 rumps callback 和底层 `NSMenuItem.setEnabled_`，避免菜单重建后灰白状态不一致。
- **设备行用"空操作回调"**：rumps 无回调项会显示灰色；设备行需要白色，所以给个空 callback `on_device_item`（点击无效果）。

### 菜单栏图标系统（v2.1.1 重构）

#### 4 态图标

| 状态 | 文件 | 显示颜色 | Template 模式 |
|------|------|----------|--------------|
| normal | `MenuBarNormal@2x.png` | 黑白（系统自适应） | ✅ ON |
| low | `MenuBarLow@2x.png` | 红色 | ❌ OFF |
| charging | `MenuBarCharging@2x.png` | 绿色 | ❌ OFF |
| full | `MenuBarFull@2x.png` | 金色 | ❌ OFF |

#### 状态选择（`_select_menu_icon`，Safety-First 优先级）

```
1. 低电量（≤20% 且未充电） → low      （最高优先级安全警告）
2. 正在充电                → charging
3. 所有设备 ≥95%          → full
4. 其他                    → normal
```

**关键设计决策：**

- **缓存设备隔离**：`if dev.cached: continue` — 已断连的缓存设备（电量可能凝固在低值）不参与图标状态判定，避免过期数据触发虚假警报。
- **无 category 过滤**：所有外设（无论内置/附件）都参与低电量判定，不再仅限 `internal` 类别。
- **低电量需未充电**：`level <= 20 and not is_charging` — 正在充电的低电量设备不触发 low（威胁已解除）。
- **已充满 ≠ 充电中（v2.1.2 修复）**：`is_charging` 条件排除 `power_state == "charged"` 的设备。`"charged"`（已充满）的 `charging` 布尔值为 `True`（`models.py` 设计），但菜单栏图标不应显示充电动画。因此 `is_charging = dev.charging is True and dev.power_state != "charged"`。

#### Template 模式动态控制（关键 bug 修复）

**问题背景：** macOS AppKit 对菜单栏图标默认应用 Template Image 机制，系统会将图标视为形状占位符，根据菜单栏背景色自动填充黑白。这导致红色低电量图标和绿色充电图标被强制黑白化。

**解决方案（`_update_menu_icon`）：**

1. **初始化时 `template=False`**：`rumps.App.__init__` 中必须传 `template=False`。如果传 `template=True`，rumps 在底层会将整个 NSStatusItem **永久标记为模板模式**，之后任何设置图标的操作都会被强制黑白化，无法恢复。
2. **运行时动态 setTemplate_**：每次切换图标时，通过 PyObjC 直接操作 NSStatusItem 的 button：
   ```python
   new_image = NSImage.alloc().initByReferencingFile_(path)
   is_template = (state == 'normal')  # 仅 normal 用模板
   new_image.setTemplate_(is_template)
   button.setImage_(new_image)
   button.setNeedsDisplay_(True)
   ```
3. **绕过 AppKit 缓存**：rumps 和 AppKit 对文件路径有强缓存，`self.icon = path` 可能复用旧 NSImage 实例。通过 `NSImage.alloc().initByReferencingFile_()` 强制实例化全新的 NSImage 对象，确保 template 属性正确应用。

### 菜单结构

```
🔋 标题
├── [类别标题]（灰）键盘
│   ├── 设备名    电量%
│   └── 设备组（多部件）
│       ├── 左耳  电量%
│       └── 右耳  电量%
├── [类别]鼠标 ...
├── ──────────
├── 上次刷新：2026-08-04 12:00:00（灰）
├── 立即刷新
├── 数据源状态 ▸（子菜单）
├── ──────────
├── 关于 Battery Bar
└── 退出
```

### 缓存设备视觉降级

- **`_format_level`**：缓存设备电量前添加 `[已离线]` 前缀。
- **`_render_menu`**：缓存设备条目使用 `_make_disabled_item` 渲染为灰色不可点击，明确区分实时数据与过期缓存数据。

### 自动登录项

`_ensure_login_item()` 通过 osascript 检查并添加登录项（首次启动）。

---

## 10. 桌面 Widget（Swift）

**工程：** `Widget/BatteryBarNative/`（Xcode 工程，需 macOS 14+ / WidgetKit）

### `BatteryBarNativeApp.swift`（宿主）

- 注册为登录项（LSUIElement）
- `WidgetReloadMonitor`：用 `DispatchSource.makeFileSystemObjectSource`（FSEvents）监视宿主容器内的 snapshot.json
- 文件变化时调用 `WidgetCenter.shared.reloadTimelines()` 刷新所有 Widget

### `BatteryBarWidget.swift`

- `Provider: TimelineProvider`，从 snapshot.json 读取设备列表
- SwiftUI 渲染，SF Symbols 图标
- 三档尺寸：small（3 设备）/ medium（5）/ large（10）
- 电量颜色：`>25%` 绿、`11-25%` 橙、`≤10%` 红
- 充电中显示 ⚡

### 沙盒要求

Widget 扩展**必须**开启 `app-sandbox=true`（`BatteryBarWidgetExtension.entitlements`），否则 WidgetKit 无法加载。主 Python 应用**不开沙盒**（需直接 HID/蓝牙访问）。

---

## 11. 构建与打包

### 两层构建脚本

```
build_release_final.sh   # 主入口（用户执行这个）
  └── build_release.sh   # 基础构建（被调用）
```

### `build_release.sh` 流程

1. 校验工具链（python3 / codesign / plutil / hdiutil / xcodebuild）
2. 创建隔离 venv（`.venv-build`），安装 `requirements.txt`
3. `py_compile` 语法检查所有源文件
4. `python -m unittest discover` 跑全部测试
5. **`rm -rf build dist`**（⚠️ 这一步会删掉 dist/）
6. PyInstaller 按 `BatteryBar.spec` 构建（arm64, console=False）
7. plutil 修正 Info.plist 字段
8. 主应用 `codesign --force --deep --sign -`（ad-hoc）
9. `xcodebuild` 构建原生宿主 + Widget 扩展
10. Widget 扩展单独签名（注入 app-sandbox entitlements）
11. 生成单一 DMG

### `build_release_final.sh` 流程

1. 清理旧 DMG（**只 rm -f dmg，不删 dist 目录**）
2. 调用 `build_release.sh`
3. 校验产物存在
4. Widget 扩展重签（确保 app-sandbox）
5. **`mkdir -p` staging 目录（必须在 build 之后，因为 build 会 rm -rf dist）**
6. 组装 Full 包（主应用 + 原生宿主）和 AppOnly 包（仅主应用）
7. 生成幂等的 install/uninstall 脚本（zsh，含 `zsh -n` 语法检查）
8. 生成 README.md
9. `hdiutil` 创建两份 DMG
10. 生成 `manifest.json`（SHA-256 校验）

### ⚠️ 已踩过的坑

1. **DMG 里没有 app**：曾因 staging 目录在 `rm -rf dist` 之前创建，被一并删掉。修复：staging 在 build 之后创建。
2. **PyInstaller 遗漏依赖**：`hidden_imports` 必须显式列出 AppKit/CoreBluetooth/Foundation/PyObjCTools/objc/rumps。
3. **Widget 不刷新**：扩展必须签名带 `app-sandbox`，否则 pluginkit 不加载。

### 运行构建

构建脚本通过 `$(dirname "$0")` 自动定位工程根目录，不依赖固定路径，可在任意位置执行：

```bash
cd <工程根目录>
bash build_release_final.sh
# 产出：dist/BatteryBar-Full.dmg, dist/BatteryBar-AppOnly.dmg, dist/manifest.json
```

---

## 12. 测试

### 运行

```bash
cd <工程根目录>
python3 -m unittest discover -s tests -v
```

### 覆盖范围

| 文件 | 用例数 | 覆盖 |
|------|--------|------|
| `test_models.py` | 6 | BatteryDevice 校验、age、缓存副本 |
| `test_classifier.py` | 7 | HID usage、名称规则、fallback、AirPods、DJI |
| `test_bluetooth_provider.py` | 34 | 字节解析、长度校验、超时、未知设备、**_DiscoverySession 状态机（try_finish/cleanup/标记完成/discovery_closed）、GCD 队列行为、discovery lock、统一 deadline、向后兼容** |
| `test_hidpp_provider.py` | 25 | 报文构造、响应匹配、Feature 偏移、序列号、名字解析、`_guess_hid_usage` fallback、wakeup pulse、指数退避重试、modelId 反查、**多 Feature 候选探测（0x1004/0x1000）、SwID 区分、name/info feature wakeup 重试** |
| `test_aggregator.py` | 10 | 两层去重、来源优先级、缓存/非缓存、Provider 异常隔离、缓存过期 |
| `test_system_provider.py` | 17 | **JSON 校验（7 类输入）、缓存命中/过期/刷新、stale-on-error、stale 超龄、无缓存失败、malformed 不覆盖有效缓存** |
| `test_snapshot_store.py` | 14 | 序列化往返、schema 校验、字段缺失/多余/非法拒绝、原子写读、临时文件清理 |
| **合计** | **114** | **7 个测试文件** |

**未覆盖：** widget_snapshot_sync、app.py。前者涉及文件系统沙盒副作用；app.py 的 `build_menu_rows` 可抽离为纯函数后补测（见第 14 节第 2 条）。

### 真机验证脚本（手动）

HID++ 涉及真实硬件，单元测试只能 mock。真机验证用临时脚本连跑多次：

```python
import hidpp_provider
for i in range(6):
    devs = hidpp_provider.discover_batteries()
    print(f"run {i+1}:", [(d.name, d.level) for d in devs])
```

期望：多接收器、多设备、电量稳定、无 fallback 名。

---

## 13. 配置常量速查

### app.py

| 常量 | 值 | 含义 |
|------|----|------|
| `APP_VERSION` | `"2.1.2"` | 应用版本号 |
| `APP_BUNDLE_ID` | `io.github.l351i3.batterybar` | Bundle ID |
| `AUTO_REFRESH_SECONDS` | 300 | 自动刷新间隔（5 分钟，v2.1.1 从 900 缩短） |
| `CACHE_EXPIRY_SECONDS` | 600 | 缓存过期（10 分钟，v2.1.1 从 3600 缩短） |

### hidpp_provider.py

| 常量 | 值 | 含义 |
|------|----|------|
| `LOGITECH_VENDOR_ID` | 0x046D | 罗技 USB 厂商 |
| `DEFAULT_TIMEOUT` | 1.0s | 单次 HID++ 请求超时 |
| `DEFAULT_ATTEMPTS` | 2 | 电量查询重试次数 |
| `DEFAULT_RETRY_DELAY` | 0.15s | 重试间隔 |
| slot 范围 | 1-6 | 每接收器最多 6 设备 |
| `BATTERY_FEATURE_CANDIDATES` | `[(0x1004,1,0x01), (0x1000,0,0x02)]` | 电量 Feature 候选列表（按优先级），格式 `(feature_id, function, swid)` |

### bluetooth_provider.py

| 常量 | 值 | 说明 |
|------|----|------|
| `DEFAULT_TIMEOUT` | 12.0s | discover_batteries 统一超时 |
| `BATTERY_SERVICE` | 0x180F | Battery Service UUID |
| `BATTERY_LEVEL` | 0x2A19 | Battery Level UUID |

### system_provider.py

| 常量 | 值 | 说明 |
|------|----|------|
| `DEFAULT_TIMEOUT` | 30.0s | system_profiler 超时 |
| `CACHE_TTL_SECONDS` | 10.0s | system_profiler JSON 缓存 TTL |
| `MAX_STALE_AGE_SECONDS` | 60.0s | 过期缓存最大可用年龄 |

### aggregator.py

| 常量 | 值 |
|------|----|
| `DEFAULT_CACHE_EXPIRY_SECONDS` | 600.0（v2.1.1 从 3600.0 缩短） |
| SOURCE_PRIORITY | hidpp:400, ble:300, sys_bt:200, sys_acc:100 |

### 依赖版本（`requirements.txt`）

| 包 | 版本 | 说明 |
|----|------|------|
| `rumps` | 0.4.0 | 菜单栏 UI |
| `hidapi` | 0.15.0 | USB HID |
| `pyobjc-core` | 9.2 | ⚠️ 锁定 9.2，bleak 要求 <10.0 |
| `pyobjc-framework-Cocoa` | 9.2 | 同上 |
| `pyobjc-framework-CoreBluetooth` | 9.2 | 同上 |
| `bleak` | 0.21.1 | BLE 蓝牙库 |
| `multipledispatch` | 1.0.0 | bleak 运行时依赖（dispatch 模块） |
| `pyinstaller` | 6.14.2 | 打包 |

> ⚠️ **版本锁定原因**：`bleak 0.21.1` 在 macOS 上依赖 `pyobjc-core >= 9.2 且 < 10.0`。若升级 pyobjc 到 10.x/11.x，bleak 会因版本冲突无法安装或运行异常（`ble_standard` 数据源报错 `ModuleNotFoundError: no module named 'dispatch'`）。严禁单独升级 pyobjc 系列。

---

## 14. 已知问题与改进方向

### 代码质量

1. ~~**测试覆盖不足**：aggregator 的去重/缓存、snapshot_store 的读写校验、system_provider 的解析均无单测。~~
   **已修复**：新增 `test_aggregator.py`（10 用例）和 `test_snapshot_store.py`（14 用例），覆盖去重/缓存/序列化/校验/原子 IO。总测试从 36 增至 73（6 个文件）。
2. **`app.py` 958 行偏长**：`build_menu_rows` 和格式化函数可拆到独立 `menu_builder.py`，便于复用和测试。
3. ~~**项目根目录有大量备份/历史文件**~~：已整理到 `~/BatteryBar-clean/`，仅保留必要文件。
4. ~~**CHANGELOG.md 为空**：应记录版本变更。~~
   **已修复**：创建 `CHANGELOG.md`，记录 v2.0.0 初始发布与 v2.1.0 变更（BLE GCD 重写、system_provider 缓存、lazy dispatch、+41 测试）。

### 功能增强

5. **HID++ 充电状态**：0x1004 UnifiedBattery 的 Capability 响应实际包含充电状态位（`res[5]`），目前未解析。可补充以显示罗技设备的充电状态。
6. **HID++ 0x1001/扩展候选**：候选列表可扩展（如 UNIFIED_BATTERY 0x1004 的 GetStatus Function 2 提供实时状态，或 0x1001 老协议兜底）。
7. **BLE 主动扫描**：当前只取已连接外设。可增加可选的短时扫描发现更多设备（权衡功耗）。
8. **Intel Mac 支持**：当前 PyInstaller spec 锁 `target_arch="arm64"`。可改 universal2 或单独构建 x86_64。
9. **本地化**：UI 硬编码中文，可抽 i18n。

### 鲁棒性

10. **system_provider 输出格式漂移**：依赖 system_profiler JSON 结构，macOS 版本升级可能破坏。建议加 schema 版本探测和兜底。
11. **Provider 部分失败可见性**：当前 `succeeded=True, device_count=0` 静默。可在 UI 区分"成功但无设备"vs"部分子查询失败"。
12. ~~**HID++ 名字读取偶发 fallback（HID++ Device Slot 1 等）**：~~
    **已修复（多层防御）**：

    - **现象描述**：用户首次刷新或偶尔刷新时，罗技设备名称无法正确加载，只显示 "HID++ Device Slot 1"、"HID++ Device Slot 2" 等占位符，需要再次刷新才能正确显示。
    - **深层原因分析**：
      1. **深度休眠唤醒竞争**：在 `hidpp_provider.py` 中，外设（尤其是低功耗键盘如 MX Keys S）经常进入深度休眠。电量探测阶段的重试已将设备唤醒，但 USB 管道可能还不稳定。紧接着查 name feature (0x0005) 和 info feature (0x0003) 时设备还没准备好，单次 `timeout=0.5` 超时 → `name_idx=None` → 跳过名字读取 → fallback 为占位名。
      2. **过早退化回退机制 (Premature Fallback)**：当长度查询失败时，代码会立即退化为不带长度的单次盲读（认为长度为 16 字节），并循环发送分段读取。然而此时设备刚被唤醒，内部接收缓冲区或系统 USB 管道可能还堆积着之前的残留响应，或者设备还未完全就绪，导致分段字符读取超时或错误。最终因为没有获得有效的 `name_bytes` 彻底失败返回 `None`，退化为 Slot 占位符。
      3. **为什么第二次刷新能成功**：因为在第一次刷新尝试中，高频的重试报文已经成功将外设**彻底唤醒**。当用户立刻进行第二次刷新时，设备处于完全活跃状态（Active Mode），因此长度查询和字符读取能够畅通无阻地瞬时完成。
    - **已实施的修复（四层防御）**：
      1. **Settling delay**：电量 feature 探测成功后，加 `time.sleep(0.1)` 让 USB 管道稳定，避免紧接着的 feature 查询因设备未就绪而超时。
      2. **Name/info feature wakeup 重试**：`name_idx` 或 `info_idx` 首次查询失败时，发 `_wakeup_pulse(settle_ms=200)` 后以更长 timeout (0.8s) 重试一次。实测 MX Keys S 冷启动首次查询失败、重试成功。
      3. **Wakeup pulse 预热**：名字读取前发 `_wakeup_pulse`（Root Feature 自查询，SwID=0x09），给设备额外唤醒时间。
      4. **指数退避重试**：`get_device_name` 内部 name_len 查询使用渐进式延迟 `0.1s → 0.2s → 0.4s`。
      5. **modelId 反查兜底**：名字仍失败时，通过 0x0003 DeviceInfo 的 modelId（offset 9-11）反查 `_KNOWN_MODEL_NAMES` 字典（14 个常见型号），避免显示无意义 Slot 编号。
    - **对应测试**：`BatteryFeatureCandidateTests.test_probe_retries_name_feature_after_wakeup`、`test_probe_retries_info_feature_after_wakeup` 验证了重试逻辑。
13. ~~**`bluetooth_provider.py` 中 `CoreBluetooth` 的并发安全与 delegate 内存生命周期管理隐患**：~~
    **已实施（待真机验证）**：

    **已验证的事实（真机实测）：**
    - `queue=None`（传 `nil` 给 `initWithDelegate_queue_`）导致 CoreBluetooth 回调派发到**主队列**（main dispatch queue）。
    - 当 `discover_batteries` 从后台 daemon 线程调用时（`app.py` 的 `BatteryBarRefresh` 线程），该线程的 NSRunLoop **不服务主队列** → 回调永远不触发 → 返回 0 设备。
    - `dispatch_queue_create(b'com.batterybar.ble', None)` 创建 GCD 串行队列。CoreBluetooth 回调派发到 GCD 线程（`Dummy-1`，`isMain=False`）。后台轮询线程只轮询 `threading.Event`，无需 NSRunLoop。**真机验证通过**。
    - PyObjC `dispatch_async(queue, callable)` 接受 Python callable，串行队列保证 FIFO 顺序。`DISPATCH_QUEUE_SERIAL` 等价于 `None`。
    - **PyObjC block 不强持有 Python 对象**：block 捕获的 Python 对象在 `del` 后访问会 `NameError` 导致进程崩溃。cleanup block 必须确保捕获对象在执行前存活。

    **已实施的修改：**
    - GCD 串行队列替换 `queue=None` + NSRunLoop 模型。模块级 `_BLE_QUEUE = dispatch_queue_create(b'com.batterybar.ble', None)`。
    - `_DiscoverySession` 管理单次发现调用的全部状态：双 Event（`done_event` + `cleanup_event`）、`try_finish` 首次终态胜出语义、`result_snapshot` 冻结。
    - 两阶段 cleanup：(1) `begin_cleanup` 快照对象并设 `cleanup_started`；(2) `dispatch_async` CoreBluetooth 调用到 BLE 队列（**不用 dispatch_sync 避免死锁**）；(3) `finish_cleanup` 清引用、断 `delegate.session` 引用环、设 `cleanup_event`。
    - 固定锁层级：`_DISCOVERY_LOCK` → `session._lock`。delegate 回调不获取 `_DISCOVERY_LOCK`。持锁不调 CoreBluetooth/logging。
    - `_mark_peripheral_done` 含 `discovery_closed` 守卫：pending 为空但 discovery 未关闭时**不触发完成**（peripherals 可能仍在到达）。
    - `peripheral_id` 字符串作 key（不依赖 CBPeripheral 哈希）。
    - 统一 deadline 覆盖整个 `discover_batteries` 调用。
    - `_DISCOVERY_LOCK` 串行化 `CBManagerState .busy`。
    - 24 个新测试覆盖：try_finish 语义、cleanup 三阶段、_mark_peripheral_done、discovery_closed 守卫、GCD 队列行为、discovery lock、统一 deadline、向后兼容。

    **需真机验证：**
    - 连续刷新（15 分钟自动 × 多轮）设备列表稳定
    - 系统休眠/唤醒后 BLE 恢复
    - 蓝牙开关切换后行为
    - 设备断连/重连
    - 多设备同时连接

14. ~~**`system_provider.py` 中重度依赖 `system_profiler` CLI 导致的响应堵塞与系统负载瓶颈**：~~
    **已实施（待真机验证）**：

    **已验证的事实：**
    - `system_profiler SPBluetoothDataType -json` 单次调用耗时 **2s ~ 8s**。
    - `pmset -g accps` 单次调用耗时 **<100ms**（快）。
    - aggregator 的 `_prefer` 使用 `not device.cached` 作为**最高优先级**去重键。如果 provider 用 `with_cached(True)` 标记结果，aggregator 会将其视为过期数据。**system_provider 缓存不得使用 `with_cached(True)`**。

    **已实施的修改：**
    - `_get_bluetooth_profiler_json(timeout)` 缓存 system_profiler JSON 原始文本。pmset 每次仍然执行。
    - **Single-flight** + `_CACHE_LOCK`：TTL 窗口内的并发调用共享缓存结果。
    - **TTL=10s**（`CACHE_TTL_SECONDS`）：TTL 内直接返回缓存，不启动子进程。
    - **Stale-on-error**：system_profiler 失败时，若缓存未超过 `MAX_STALE_AGE=60s`，返回过期缓存。
    - **JSON 校验**（`_validate_bluetooth_json`）：不仅 `json.loads`，还要求顶层为 dict 且包含 `SPBluetoothDataType` 键（值为 list）。格式错误的响应**不覆盖**有效缓存。
    - **可注入时钟**（`_cache_clock`）用于测试。
    - 17 个新测试覆盖：JSON 校验（7 类输入）、缓存命中/过期/过期刷新、stale-on-error、stale 超龄、无缓存失败、malformed 不覆盖。

    **需真机验证：**
    - 高频刷新（连续多次"立即刷新"）不再堆积 system_profiler 进程
    - 缓存命中率在实际使用中的表现
    - macOS 版本升级后 system_profiler JSON 格式变化的容错

### 构建/发布

15. **无 Developer ID 签名**：用户首次打开需右键"打开"绕过 Gatekeeper。正式发布应申请 Developer ID。
16. **Widget 与主应用 bundle ID 体系**：主应用 `io.github.l351i3.batterybar`，Widget 宿主 `io.github.l351i3.batterybar.widgethost`，Widget 扩展 `io.github.l351i3.batterybar.widgethost.widget`，app-group `group.io.github.l351i3.batterybar`。这套 ID 体系相互关联，改动一处需同步其余。

### 充电状态（v2.1.1 重点，仍需真机验证）

17. ~~**AirPods 充电状态获取**：~~ **已修复（v2.1.2）**

    **根因：** `accessory_power_to_devices` 遇到 `record.name` 为空的 pmset 条目（AirPods 在充电盒中时的唯一充电数据源）直接 `continue` 丢弃。v2.1.1 的三层防御（智能合并、充电传播、Smart Suffix Match）逻辑正确，但数据在入口就被丢弃，从未进入下游链路。

    **修复（v2.1.2）：**
    - `_anonymous_accessory_devices()`：将匿名条目通过电量百分比与蓝牙清单多组件设备精确匹配，绑定到对应组件 ID。`claimed` 集合防重复，charging 优先排序。
    - `_effective_power_state(level, power_state)`：100% + charging → `discharging`（非充电状态）。pmset 充满后仍报 charging（0:00 remaining）但实际已停止充电，100% 设备不显示充电/充满标签。
    - `_select_menu_icon` 中 `is_charging` 排除 `"charged"` 状态（防御逻辑，`charged` 已不再从 pmset 数据产出）。

    **仍存在的限制：**
    - 键盘/鼠标充电：Magic Keyboard/Mouse 插线充电时切换为 USB HID 模式，蓝牙通道停止上报数据，属硬件/协议限制，软件无法绕过。

18. ~~**HID++ Device Slot fallback 名反复出现**：~~ **已修复（v2.1.1）**

    **根因：** 每次刷新都重新唤醒设备读名字。设备休眠时名字读取失败 → 返回 `"HID++ Device Slot N"` 作为非缓存数据 → aggregator 的 `_prefer` 因 `not cached` 最高优先级，用 fallback 名覆盖上次的真实名字。

    **修复：** `hidpp_provider.py` 新增模块级 `_DEVICE_NAME_CACHE` 字典 + `_device_cache_key(target)` 辅助函数。key 用 positional（`pid:slot:path_hash`），不依赖 serial（serial 本身也可能读不到）。`probe_device_on_slot` 返回前：读到真实名字则更新缓存；fallback 名则用缓存的真实名字替代。纯内存，进程重启清空（名字极少变化，无需 TTL）。

    **附带的图标逻辑修复：** `_select_menu_icon` 中曾因 `if dev.cached: continue` 导致缓存设备（含低电量的）被跳过。v2.1.1 重新引入了带条件的缓存隔离（仅排除 `cached` 设备的图标判定），配合 `[已离线]` 视觉降级。

19. ~~**菜单栏图标不随状态变化（黑白化、低电量不触发）**：~~ **已修复（v2.1.1）**

    **根因（多因素）：**
    1. **Template 模式黑白化**：rumps 初始化时 `template=True` 会导致整个 NSStatusItem 永久标记为模板模式，红色/绿色彩色图标被强制黑白。
    2. **AppKit 缓存**：`self.icon = path` 复用旧 NSImage 实例，template 属性无法更新。
    3. **category 过滤**：`_select_menu_icon` 曾限制仅 `internal` 类别设备触发低电量，外设（鼠标/键盘/AirPods）低电量被忽略。

    **修复：**
    - 初始化改 `template=False`，运行时按状态动态 `setTemplate_`（仅 `normal` 用模板，其余彩色）。
    - `NSImage.alloc().initByReferencingFile_()` 强制新实例 + `button.setImage_()` + `setNeedsDisplay_(True)` 绕过缓存。
    - 移除 category 过滤，所有外设参与低电量判定。

20. ~~**缓存设备永久驻留 / 状态冻结误导**：~~ **已修复（v2.1.1）**

    - `DEFAULT_CACHE_EXPIRY_SECONDS` 从 3600s（1 小时）缩短至 600s（10 分钟）。
    - `AUTO_REFRESH_SECONDS` 从 900s（15 分钟）缩短至 300s（5 分钟）。
    - 缓存设备 UI 显示 `[已离线]` 前缀 + 灰色禁用样式。
    - 缓存设备不参与菜单栏图标状态判定（`_select_menu_icon` 中 `if dev.cached: continue`）。

---

## 15. 调试与诊断工具

### 内置诊断菜单

菜单栏 → "数据源状态" 子菜单显示每个 Provider 的：成功/失败、设备数、耗时、错误信息（含异常类型和消息）。**这是排查"为什么没设备"的第一入口。**

### `diagnose.sh`（只读诊断）

随 Full 包分发（`diagnose_safely.sh`）。只读收集系统蓝牙、HID、电源信息，不改系统状态。

### `survey_devices.py` / `batterybar_probe.py`

交互式 CLI 工具，逐步探测 AirPods / DJI / 蓝牙能力，用于开发期定位 BLE 协议问题。

### 手动跑 Provider

```python
# 单独跑某个 Provider
import hidpp_provider
print(hidpp_provider.discover_batteries())

import bluetooth_provider
print(bluetooth_provider.discover_batteries())

import system_provider
print(system_provider.discover_batteries())
```

### 查看快照

```bash
cat ~/Library/Application\ Support/Battery\ Bar/snapshot.json | python3 -m json.tool
```

---

## 16. 附录：HID++ 2.0 协议要点

> 本节是开发中踩坑后的经验沉淀，供后续改 HID++ 报文时参考。**改 HID++ 前务必先吃透协议再动手。**

### 报文类型

| Byte[0] | 类型 | 长度 |
|---------|------|------|
| 0x10 | 短报告（软件） | 7 字节 |
| 0x11 | 长报告（设备） | 20 字节 |

本项目统一用长报告 0x11（兼容性最好）。

### 字节布局（长报告请求）

```
[0]    0x11            报告类型
[1]    slot            设备槽位（接收器=0xFF，子设备=1-6）
[2]    feature_index   Root.GetFeature 返回的索引
[3]    fn<<4 | swid    高4位=Function ID，低4位=Software ID
[4-19] parameters      参数区
```

### 响应匹配三要素

1. `res[1] == 请求 slot`
2. `res[2] == 请求的 feature_index`（Root 请求时 = 0x00）
3. `res[3] == 请求的 (function<<4 | swid)`（**SwID 回显是区分并发查询响应的关键**）

### 错误响应

- `res[2] == 0xFF`：通用错误，`res[4]` 是错误码
- `res[2] == 0x8F`：未知 device index（空 slot），~2ms 内返回

### 关键 Feature

| ID | 名称 | 说明 |
|----|------|------|
| 0x0000 | Root | GetFeatureIndex（询问设备支持哪些 feature） |
| 0x0003 | DeviceInfo | 序列号在 `res[12:15]`，Function 0 |
| 0x0005 | DeviceName | F0=查长度，F1=读字符（每轮 16 字符） |
| 0x1000 | BatteryStatus (legacy) | F0=GetBatteryLevelStatus，电量 `res[4]` |
| 0x1004 | UnifiedBattery | F1=GetCapability，电量 `res[4]`；状态位在 `res[5]`（未利用） |

### 设备休眠行为

- HID++ 外设**频繁休眠**，首次请求用于唤醒，可能无响应。
- 唤醒后响应正常，所以**重试机制不可或缺**。
- **键盘（如 MX Keys S）比鼠标休眠更深**：长时间不用后单次 wakeup pulse 不足以唤醒，需电量探测重试 + settling delay + name feature wakeup 重试多层组合才能可靠读到名字。
- 电量 feature 探测阶段的 4 次重试本身就充当唤醒报文，但唤醒后 USB 管道需要额外 settling 时间才稳定。
- 名字长度查询尤其敏感，需要 wakeup pulse 预热 + 指数退避重试。

### 空 slot 检测

接收器对未配对的 slot 返回 0x8F，约 2ms。利用响应耗时 <0.1s 可快速跳过空 slot，避免 6 slot × 4 重试的长等待。**注意此判断必须在候选 Feature 循环之外**，否则会把"只支持 0x1000 不支持 0x1004"的设备误判为空 slot。

---

**文档版本：** 2.1.2 · 最后更新：2026-08-15
