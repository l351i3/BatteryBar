#!/usr/bin/env python3
"""aggregator 单元测试：去重、缓存、来源优先级、Provider 异常隔离。

这些逻辑此前无测试覆盖（DEVELOPMENT.md 第 14 节第 1 条），
属于纯函数逻辑，是补测优先级最高的部分。
"""

import unittest

from aggregator import (
    BatteryAggregator,
    BatterySnapshot,
    ProviderSpec,
    ProviderStatus,
    deduplicate_devices,
)
from models import (
    BatteryDevice,
    CATEGORY_KEYBOARD,
    CATEGORY_MOUSE,
    SOURCE_BLE_STANDARD,
    SOURCE_HIDPP,
    SOURCE_SYSTEM_ACCESSORY,
    SOURCE_SYSTEM_BLUETOOTH,
)


def _device(
    device_id,
    name,
    source=SOURCE_HIDPP,
    level=50,
    observed_at=1000.0,
    cached=False,
    category=CATEGORY_MOUSE,
):
    """快速构造一个 BatteryDevice，默认非缓存。"""
    return BatteryDevice(
        device_id=device_id,
        name=name,
        category=category,
        transport="bluetooth",
        level=level,
        charging=None,
        source=source,
        observed_at=observed_at,
        category_source="test",
        cached=cached,
    )


def _provider(name, devices):
    """构造一个返回固定设备列表的 ProviderSpec。"""
    return ProviderSpec(
        name=name,
        discover=lambda: list(devices),
    )


def _failing_provider(name, error):
    """构造一个总是抛异常的 ProviderSpec，用于测试异常隔离。"""

    def _boom():
        raise error

    return ProviderSpec(name=name, discover=_boom)


class DeduplicateDevicesTests(unittest.TestCase):
    """deduplicate_devices 的两层去重逻辑。"""

    def test_same_id_dedups_keeping_higher_priority_source(self):
        """同一 device_id 的两条记录，保留来源优先级更高者。"""
        hidpp = _device(
            "dev:1", "MX Master", source=SOURCE_HIDPP
        )
        ble = _device(
            "dev:1",
            "MX Master",
            source=SOURCE_BLE_STANDARD,
        )

        result = deduplicate_devices([hidpp, ble])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, SOURCE_HIDPP)

    def test_non_cached_preferred_over_cached(self):
        """同 ID 同来源时，非缓存优先于缓存。"""
        fresh = _device("dev:1", "Mouse", cached=False)
        stale = _device("dev:1", "Mouse", cached=True)

        result = deduplicate_devices([fresh, stale])

        self.assertEqual(len(result), 1)
        self.assertFalse(result[0].cached)

    def test_component_devices_kept_separately(self):
        """AirPods 的 left/right/case 三条记录应全部保留，
        不被按名称去重合并。"""
        left = _device(
            "airpods:1:left", "AirPods · 左耳"
        )
        right = _device(
            "airpods:1:right", "AirPods · 右耳"
        )
        case = _device(
            "airpods:1:case", "AirPods · 电池盒"
        )

        result = deduplicate_devices([left, right, case])

        self.assertEqual(len(result), 3)

    def test_different_id_same_name_same_category_deduped(self):
        """不同 device_id、相同 (名称, category) 的两条无部件
        记录会被合并——这是设计意图：防止同一物理设备被不同
        来源重复计入。两台真正独立的同型号设备需靠名称区分。"""
        d1 = _device("dev:1", "MX Master")
        d2 = _device("dev:2", "MX Master")

        result = deduplicate_devices([d1, d2])

        self.assertEqual(len(result), 1)

    def test_different_name_kept_separately(self):
        """名称不同的设备互不影响，都保留。"""
        d1 = _device("dev:1", "MX Master")
        d2 = _device(
            "dev:2", "MX Anywhere", category=CATEGORY_MOUSE
        )

        result = deduplicate_devices([d1, d2])

        self.assertEqual(len(result), 2)

    def test_same_name_different_category_kept(self):
        """名称相同但 category 不同的设备保留——
        名称去重键含 category。"""
        d1 = _device(
            "dev:1", "Combo", category=CATEGORY_MOUSE
        )
        d2 = _device(
            "dev:2",
            "Combo",
            category=CATEGORY_KEYBOARD,
        )

        result = deduplicate_devices([d1, d2])

        self.assertEqual(len(result), 2)

    def test_non_component_dedup_by_name_and_category(self):
        """无部件后缀的设备，若 (规范化名称, category) 相同，
        即使 device_id 不同也去重——防止同一物理设备被不同
        来源重复计入。"""
        from_system = _device(
            "system-bt:aa:bb:cc",
            "MX Master",
            source=SOURCE_SYSTEM_BLUETOOTH,
        )
        from_ble = _device(
            "bluetooth:xyz",
            "MX Master",
            source=SOURCE_BLE_STANDARD,
        )

        result = deduplicate_devices(
            [from_system, from_ble]
        )

        self.assertEqual(len(result), 1)
        # BLE (300) 优先级高于 system_bluetooth (200)
        self.assertEqual(result[0].source, SOURCE_BLE_STANDARD)


class AggregatorRefreshTests(unittest.TestCase):
    """BatteryAggregator.refresh 的端到端行为。"""

    def test_refresh_runs_all_providers_and_collects_devices(
        self,
    ):
        agg = BatteryAggregator(
            providers=[
                _provider(
                    "hidpp",
                    [
                        _device(
                            "h:1",
                            "MX Master",
                            source=SOURCE_HIDPP,
                        )
                    ],
                ),
                _provider(
                    "ble",
                    [
                        _device(
                            "b:1",
                            "AirPods",
                            source=SOURCE_BLE_STANDARD,
                        )
                    ],
                ),
            ],
            cache_expiry_seconds=3600,
        )

        snapshot = agg.refresh()

        self.assertIsInstance(
            snapshot, BatterySnapshot
        )
        self.assertEqual(len(snapshot.devices), 2)
        self.assertEqual(
            len(snapshot.provider_statuses), 2
        )
        self.assertTrue(
            all(
                s.succeeded
                for s in snapshot.provider_statuses
            )
        )

    def test_failing_provider_does_not_break_others(
        self,
    ):
        """一个 Provider 抛异常，其他 Provider 仍正常返回，
        失败者记为 succeeded=False。"""
        agg = BatteryAggregator(
            providers=[
                _failing_provider(
                    "broken",
                    RuntimeError("boom"),
                ),
                _provider(
                    "good",
                    [
                        _device(
                            "g:1",
                            "Good Mouse",
                        )
                    ],
                ),
            ],
        )

        snapshot = agg.refresh()

        self.assertEqual(len(snapshot.devices), 1)
        statuses = {
            s.name: s for s in snapshot.provider_statuses
        }
        self.assertFalse(statuses["broken"].succeeded)
        self.assertIn(
            "RuntimeError",
            statuses["broken"].error,
        )
        self.assertTrue(statuses["good"].succeeded)

    def test_cache_survives_provider_missing_on_next_refresh(
        self,
    ):
        """第一次刷新发现设备并写缓存；第二次该 Provider
        不再返回该设备时，缓存条目在过期前仍可见（标 cached）。"""
        agg = BatteryAggregator(
            providers=[
                _provider(
                    "p",
                    [
                        _device(
                            "cached:1",
                            "Cached Mouse",
                        )
                    ],
                )
            ],
            cache_expiry_seconds=3600,
        )

        first = agg.refresh()
        self.assertEqual(len(first.devices), 1)
        self.assertFalse(first.devices[0].cached)

        # 第二次：Provider 不再返回任何设备
        agg.providers = (
            ProviderSpec(
                name="p", discover=lambda: []
            ),
        )

        second = agg.refresh()

        # 缓存设备仍在，且标记为 cached
        self.assertEqual(len(second.devices), 1)
        self.assertTrue(second.devices[0].cached)
        self.assertEqual(
            second.devices[0].device_id,
            "cached:1",
        )

    def test_expired_cache_removed(self):
        """超过 cache_expiry_seconds 的缓存条目不再可见。"""
        clock_values = [1000.0]
        agg = BatteryAggregator(
            providers=[
                _provider(
                    "p",
                    [
                        _device(
                            "exp:1",
                            "Expiring Mouse",
                        )
                    ],
                )
            ],
            cache_expiry_seconds=100.0,
            clock=lambda: clock_values[0],
        )

        first = agg.refresh()
        self.assertEqual(len(first.devices), 1)

        # 第二次：Provider 不再返回设备，且时间已超过 100s
        agg.providers = (
            ProviderSpec(
                name="p", discover=lambda: []
            ),
        )
        clock_values[0] = 2000.0

        second = agg.refresh()

        self.assertEqual(len(second.devices), 0)


if __name__ == "__main__":
    import sys

    sys.exit(unittest.main())
