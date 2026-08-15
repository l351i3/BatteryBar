# Changelog

All notable changes to Battery Bar will be documented in this file.

---

## [2.1.2] - 2026-08-15

### Fixed

- **AirPods 充电状态终于可靠显示（匿名 pmset 条目匹配）**
  - 根因：`accessory_power_to_devices` 遇到 `record.name` 为空的 pmset 条目直接 `continue`，丢弃了 AirPods 充电盒中唯一可靠的充电数据源（`- (id=350361794) 100%; charging`）。
  - 修复：`_anonymous_accessory_devices()` 新函数，将匿名条目通过电量百分比与蓝牙清单（`battery_left`/`battery_right`/`battery_case`）精确匹配，绑定到对应组件 ID（`base_id:left` 等）。匹配约束：精确电量相等、唯一设备归属、`claimed` 集合防重复。charging/charged 记录排序优先于 discharging。
  - `_effective_power_state(level, power_state)`：100% + charging → `discharging`（非充电状态）。pmset 在设备充满后仍报 charging（0:00 remaining），实际充电已停止；显示"已充满"会误导用户以为设备在充电回路中，故不显示任何充电标签。

- **菜单栏图标：已充满不再触发充电动画**
  - 根因：`_select_menu_icon` 中 `is_charging` 检查将 `"charged"` 与 `"charging"` 同等处理，导致设备已充满（显示"已充满"文字）时菜单栏图标仍显示绿色充电动画。
  - 修复：`is_charging` 条件排除 `"charged"` 状态——只有真正在充电的设备才触发充电图标。（v2.1.2 后段调整：`_effective_power_state` 已不再产出 `charged` 状态，此修复保留为防御逻辑。）

### Changed

- 新增 6 个 `AnonymousAccessoryMatchTests` 单元测试覆盖：充电绑定、部分电量充电、充电盒匹配、无匹配跳过、charging 优先于 discharging、命名条目不受影响。

---

## [2.1.1] - 2026-08-13

### Added

- **菜单栏 4 态彩色图标系统**
  - 新增 4 套菜单栏图标资源：`MenuBarNormal@2x.png`（正常，黑白自适应）、`MenuBarLow@2x.png`（低电量，红色）、`MenuBarFull@2x.png`（满电，金色）、`MenuBarCharging@2x.png`（充电中，绿色），含 @1x/@2x 双分辨率。
  - 新增 `AppIcon.icns` 自定义应用图标（1024px 源生成 16/32/128/256/512 全尺寸）。
  - `_menu_icon_path(state)` 资源路径解析，支持 PyInstaller 打包后 `sys._MEIPASS/resources/` 定位。
  - `_select_menu_icon(snapshot)` 采用 **Safety-First 优先级**判定：未充电低电量（≤20%）> 充电中 > 全部满电（≥95%）> 正常。

### Changed

- **Template 模式动态控制（关键 bug 修复）**
  - rumps 初始化从 `template=True` 改为 `template=False`，避免 NSStatusItem 被永久标记为模板模式导致彩色图标强制黑白化。
  - `_update_menu_icon` 运行时按状态动态 `setTemplate_`：仅 `normal` 状态启用模板（适配深/浅色菜单栏），`low`/`charging`/`full` 强制关闭模板保留原始彩色像素。
  - 通过 `NSImage.alloc().initByReferencingFile_()` + `button.setImage_()` + `setNeedsDisplay_(True)` 绕过 AppKit 图标缓存。

- **缓存周期大幅缩短**
  - `AUTO_REFRESH_SECONDS`：900s（15 分钟）→ 300s（5 分钟）。
  - `DEFAULT_CACHE_EXPIRY_SECONDS` / `CACHE_EXPIRY_SECONDS`：3600s（1 小时）→ 600s（10 分钟）。

- **缓存设备视觉降级与逻辑隔离**
  - 缓存设备（已断连）在菜单中显示 `[已离线]` 前缀，并使用 `_make_disabled_item` 渲染为灰色不可点击。
  - `_select_menu_icon` 中 `if dev.cached: continue`，缓存设备不参与菜单栏图标状态判定，避免过期数据触发虚假低电量警报。

- **依赖版本锁定**
  - `requirements.txt` 新增 `bleak==0.21.1`、`multipledispatch==1.0.0`。
  - pyobjc 系列从 11.1 降级锁定至 9.2（bleak 要求 `pyobjc-core >= 9.2 且 < 10.0`）。
  - 修复 `ble_standard` 数据源 `ModuleNotFoundError: no module named 'dispatch'`。

### Fixed

- **HID++ Device Slot fallback 名反复出现**
  - 根因：设备休眠时名字读取失败返回 fallback 名，aggregator `_prefer` 因 `not cached` 最高优先级用 fallback 覆盖真实名字。
  - 修复：`hidpp_provider.py` 新增模块级 `_DEVICE_NAME_CACHE` + `_device_cache_key(target)`（key 用 `pid:slot:path_hash`），读到真实名字则更新缓存，fallback 名则用缓存替代。

- **菜单栏图标不随状态变化**
  - 修复 rumps `template=True` 导致的永久黑白化（改为初始化 `template=False` + 运行时动态 `setTemplate_`）。
  - 修复 AppKit 图标缓存导致 `self.icon = path` 不生效（强制新 NSImage 实例）。
  - 移除 `_select_menu_icon` 中对 `category == 'internal'` 的硬编码过滤，所有外设低电量均能触发图标。

- **充电状态智能合并（真机验证未通过，代码已实现）**
  - `aggregator._prefer`：高优先级源 `charging=None` 时，从低优先级源补充明确值，解决 `system_bluetooth`（200）覆盖 `system_accessory`（100）导致充电状态丢失。
  - `system_provider._deduplicate_system_devices`：`SOURCE_SYSTEM_ACCESSORY` 根设备充电状态向 `:left`/`:right`/`:case` 子组件传播；相同 ID 重复项字段级合并。
  - `accessory_power_to_devices`：Smart Suffix Match（`Case` 后缀剥离 + 超集名称回退 + `device_id:case` 对齐）。

- **AirPods 4 充电状态绑定**
  - 去除蓝牙 inventory 中 `connected` 标记的强制过滤。AirPods 4 在耳外充电/休眠时被系统汇报为 disconnected，通过名称超集与最长前缀逻辑正确关联至活跃设备（而非断开的旧款同名设备）。

### 需真机验证

- ⚠️ **充电图标仍未可靠触发**：上述充电状态合并/传播/匹配代码已全部实现，但真机测试中 AirPods 充电、键盘插线时菜单栏充电图标仍未稳定显示。需真机抓包 `pmset -g accps` 输出确认数据源是否返回充电字段。
- ⚠️ **键盘/鼠标充电**：Magic Keyboard/Mouse 插线充电时切换为 USB HID 模式，蓝牙通道停止上报数据，属硬件/协议限制。

## [2.1.0] - 2026-08-09

### Changed

- **BLE Provider 重写（CoreBluetooth 并发安全）**
  - 替换 `queue=None` + NSRunLoop 模型为 GCD 串行队列（`dispatch_queue_create`）
  - 修复后台线程调用 `discover_batteries` 返回 0 设备的问题（`queue=None` 导致回调派发到主队列，后台线程无法服务）
  - 新增 `_DiscoverySession` 管理单次发现的全部状态：双 Event（`done_event` + `cleanup_event`）、`try_finish` 首次终态胜出语义
  - 两阶段 cleanup：`dispatch_async` 取消连接（避免 `dispatch_sync` 死锁）
  - 固定锁层级：`_DISCOVERY_LOCK` → `session._lock`；delegate 回调不获取 `_DISCOVERY_LOCK`
  - `discovery_closed` 守卫：pending 为空但扫描未关闭时不触发完成
  - `peripheral_id` 字符串作 key（不依赖 CBPeripheral 哈希）
  - 统一 deadline 覆盖整个 `discover_batteries` 调用

- **system_provider 缓存优化（减少进程开销）**
  - 新增 `_get_bluetooth_profiler_json()` 缓存 `system_profiler SPBluetoothDataType -json` 输出
  - TTL=10s + stale-on-error（MAX_STALE_AGE=60s）
  - Single-flight 并发安全（`_CACHE_LOCK`）
  - JSON 结构校验（`_validate_bluetooth_json`）：格式错误不覆盖有效缓存
  - pmset 仍然每次执行（实时充电状态）
  - 缓存不使用 `with_cached(True)`（aggregator 将 cached 视为最低优先级）

- **PyInstaller 打包**
  - `BatteryBar.spec` 新增 `"dispatch"` 到 `hidden_imports`（GCD 队列依赖）
  - dispatch 模块改为懒加载（`_get_ble_queue()` 内 `from dispatch import ...`），避免无 pyobjc-framework-Dispatch 环境的 ModuleNotFoundError

### Added

- **24 个新 BLE Provider 测试**（`test_bluetooth_provider.py` 从 10 → 34 用例）
  - `_DiscoverySession` 状态机：try_finish 语义、cleanup 三阶段、`_mark_peripheral_done`、`_delegate_record_result`
  - `discovery_closed` 守卫、`peripheral_id` key
  - GCD 队列行为（懒创建、缓存、dispatch_async、串行顺序）
  - discovery lock、统一 deadline
  - 向后兼容（`_finish`/`_record_result` legacy API）

- **17 个新 system_provider 测试**（新文件 `test_system_provider.py`）
  - JSON 校验：合法/非字符串/语法错误/非 dict/缺键/非 list/null
  - 缓存行为：TTL 命中、TTL 过期刷新、stale-on-error、stale 超龄、无缓存失败、malformed 不覆盖有效缓存、重置

- **CHANGELOG.md**（本文件）

### Fixed

- BLE Provider 后台线程回调不触发（根因：`queue=None` 派发到主队列，后台线程无 NSRunLoop）
- `_check_complete` 死锁（持 `session._lock` 调用 `try_finish` 再次获取同一把锁）→ 拆分 `_try_finish_locked`
- `_get_bluetooth_profiler_json` 中 `_cache_valid_at` 未声明 `global` 导致 `UnboundLocalError`
- 测试中 `peripheral_identifier` 大小写断言不匹配（PyObjC 返回大写）
- 模块级 `from dispatch import ...` 在无 pyobjc-framework-Dispatch 环境导致所有 BLE 测试 error

---

## [2.0.0] - 2026-07-17

### Added

- 初始发布
- 菜单栏常驻图标 + 分类设备列表显示
- 三个 Provider：system_profiler / BLE GATT / HID++
- 聚合器去重 + 内存缓存
- 桌面 Widget（Swift WidgetKit）
- 自动登录项
- 15 分钟自动刷新
- "数据源状态"诊断子菜单
