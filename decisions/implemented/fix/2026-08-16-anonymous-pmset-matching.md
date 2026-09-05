# 匿名 pmset 条目按电量匹配绑定充电状态

## Decision

`system_provider._anonymous_accessory_devices()` 将 `pmset -g accps` 输出的无名称条目（AirPods 在充电盒中时系统不报设备名）按电量百分比与蓝牙清单多组件设备（left/right/case）精确匹配，充电状态绑定到 `base_id:<component>` 组件 ID。约束：电量精确相等、唯一设备归属（跨设备歧义放弃）、`claimed` 集合防重复、charging/charged 记录排序优先于 discharging。`_effective_power_state` 将 100%+charging 映射为 discharging（pmset 充满后仍报 charging，实际已停止）。

## Consequences

- AirPods 充电状态首次可靠显示（v2.1.2，113 测试含 6 个匿名匹配专项用例）
- 100% 设备不再显示"充电中"或"已充满"标签，只显示电量
- 局限：若两台同型号 AirPods 电量恰好相等且都在充电盒中，匹配歧义时双方都放弃（保守正确优于错误绑定）
- 验证：真机 pmset 输出（2026-08-14 三次抓包）+ 单元测试回归

## Alternatives considered

- **要求 Apple 修复 / 等 system_profiler 提供充电字段**：`system_profiler SPBluetoothDataType -json` 至今无充电字段，等不到；落选。
- **IORegistry 深挖充电状态**：IOKit 接口无公开文档保证稳定，且 SIP 限制下部分键值读不到；维护成本高，落选。
- **时间序列推断（电量上升即充电）**：需要跨刷新周期存历史，5 分钟间隔下推断延迟大且易误判（用一下掉 1% 又充回去）；落选。

## 落选的其他匹配键

- **normalize_name 名称匹配**：匿名条目根本没有名称，无键可匹配——这是选择电量匹配的根本原因。
