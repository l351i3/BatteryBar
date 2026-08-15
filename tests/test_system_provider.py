#!/usr/bin/env python3

import unittest
from unittest.mock import (
    MagicMock,
    Mock,
    patch,
)

import system_provider
from system_provider import (
    SystemCommandError,
    SystemCommandTimeout,
    _get_bluetooth_profiler_json,
    _reset_cache,
    _validate_bluetooth_json,
)

VALID_BT_JSON = '{"SPBluetoothDataType": []}'
VALID_BT_JSON_WITH_DEVICES = (
    '{"SPBluetoothDataType": [{"device_connected": '
    '[{"Test Mouse": {"device_address": "AA:BB:CC", '
    '"device_minorType": "Mouse", '
    '"device_batteryLevel": "85%"}}]}]}'
)

STALE_CLOCK_CALLS = []  # Modified in each test via setattr


class ValidateBluetoothJSONTests(unittest.TestCase):
    """Tests for _validate_bluetooth_json."""

    def test_valid_json_returns_dict(self):
        result = _validate_bluetooth_json(
            VALID_BT_JSON
        )
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)

    def test_valid_json_has_key(self):
        result = _validate_bluetooth_json(
            VALID_BT_JSON
        )
        self.assertIn(
            'SPBluetoothDataType', result
        )

    def test_non_string_rejects(self):
        self.assertIsNone(
            _validate_bluetooth_json(123)
        )
        self.assertIsNone(
            _validate_bluetooth_json(None)
        )
        self.assertIsNone(
            _validate_bluetooth_json(b'{}')
        )

    def test_invalid_json_syntax_rejects(self):
        self.assertIsNone(
            _validate_bluetooth_json('{bad}')
        )

    def test_non_dict_top_level_rejects(self):
        self.assertIsNone(
            _validate_bluetooth_json('[1,2]')
        )

    def test_missing_key_rejects(self):
        self.assertIsNone(
            _validate_bluetooth_json('{"other": 1}')
        )

    def test_non_list_value_rejects(self):
        self.assertIsNone(
            _validate_bluetooth_json(
                '{"SPBluetoothDataType": "str"}'
            )
        )

    def test_null_value_rejects(self):
        self.assertIsNone(
            _validate_bluetooth_json(
                '{"SPBluetoothDataType": null}'
            )
        )


class CacheBehaviorTests(unittest.TestCase):
    """Tests for _get_bluetooth_profiler_json caching.

    Uses injected clock and mocked _run_command.
    """

    def setUp(self):
        _reset_cache()
        self._orig_clock = system_provider._cache_clock

    def tearDown(self):
        system_provider._cache_clock = self._orig_clock
        _reset_cache()

    def _set_clock(self, value):
        """Set a static clock that returns value."""
        system_provider._cache_clock = (
            lambda: value
        )

    def test_fresh_call_runs_command(self):
        """First call with empty cache runs
        system_profiler."""
        self._set_clock(100.0)

        with patch.object(
            system_provider,
            '_run_command',
            return_value=VALID_BT_JSON,
        ) as mock_cmd:
            text, stale = (
                _get_bluetooth_profiler_json(
                    timeout=10.0
                )
            )

        mock_cmd.assert_called_once()
        self.assertEqual(text, VALID_BT_JSON)
        self.assertFalse(stale)

    def test_cached_within_ttl_no_call(self):
        """Within TTL, cache is served without
        subprocess call."""
        self._set_clock(100.0)

        with patch.object(
            system_provider,
            '_run_command',
            return_value=VALID_BT_JSON,
        ):
            _get_bluetooth_profiler_json(
                timeout=10.0
            )

        # Advance clock but stay within TTL (10s)
        self._set_clock(105.0)

        with patch.object(
            system_provider,
            '_run_command',
        ) as mock_cmd:
            text, stale = (
                _get_bluetooth_profiler_json(
                    timeout=10.0
                )
            )

        mock_cmd.assert_not_called()
        self.assertEqual(text, VALID_BT_JSON)
        self.assertFalse(stale)

    def test_expired_ttl_runs_fresh(self):
        """After TTL expires, fresh call is made."""
        self._set_clock(100.0)

        with patch.object(
            system_provider,
            '_run_command',
            return_value=VALID_BT_JSON,
        ):
            _get_bluetooth_profiler_json(
                timeout=10.0
            )

        # Advance beyond TTL (10s)
        self._set_clock(115.0)

        with patch.object(
            system_provider,
            '_run_command',
            return_value=VALID_BT_JSON,
        ) as mock_cmd:
            text, stale = (
                _get_bluetooth_profiler_json(
                    timeout=10.0
                )
            )

        mock_cmd.assert_called_once()
        self.assertFalse(stale)

    def test_stale_on_error_within_max_age(self):
        """Command failure serves stale cache if
        within MAX_STALE_AGE (60s)."""
        self._set_clock(100.0)

        with patch.object(
            system_provider,
            '_run_command',
            return_value=VALID_BT_JSON,
        ):
            _get_bluetooth_profiler_json(
                timeout=10.0
            )

        # Advance beyond TTL but within MAX_STALE_AGE
        self._set_clock(150.0)

        with patch.object(
            system_provider,
            '_run_command',
            side_effect=SystemCommandError(
                "command failed"
            ),
        ) as mock_cmd:
            text, stale = (
                _get_bluetooth_profiler_json(
                    timeout=10.0
                )
            )

        mock_cmd.assert_called_once()
        self.assertEqual(text, VALID_BT_JSON)
        self.assertTrue(stale)

    def test_stale_expired_beyond_max_age(self):
        """Command failure with stale beyond
        MAX_STALE_AGE returns None."""
        self._set_clock(100.0)

        with patch.object(
            system_provider,
            '_run_command',
            return_value=VALID_BT_JSON,
        ):
            _get_bluetooth_profiler_json(
                timeout=10.0
            )

        # Advance beyond MAX_STALE_AGE (60s)
        self._set_clock(200.0)

        with patch.object(
            system_provider,
            '_run_command',
            side_effect=SystemCommandTimeout(
                "timed out"
            ),
        ) as mock_cmd:
            text, stale = (
                _get_bluetooth_profiler_json(
                    timeout=10.0
                )
            )

        mock_cmd.assert_called_once()
        self.assertIsNone(text)
        self.assertFalse(stale)

    def test_no_cache_command_fails_returns_none(
        self,
    ):
        """No cache + command failure = None."""
        self._set_clock(100.0)

        with patch.object(
            system_provider,
            '_run_command',
            side_effect=SystemCommandError(
                "fail"
            ),
        ):
            text, stale = (
                _get_bluetooth_profiler_json(
                    timeout=10.0
                )
            )

        self.assertIsNone(text)
        self.assertFalse(stale)

    def test_malformed_does_not_overwrite_valid(
        self,
    ):
        """Malformed JSON must not overwrite valid
        cached data."""
        self._set_clock(100.0)

        with patch.object(
            system_provider,
            '_run_command',
            return_value=VALID_BT_JSON,
        ):
            _get_bluetooth_profiler_json(
                timeout=10.0
            )

        # Advance beyond TTL
        self._set_clock(115.0)

        # Command returns malformed JSON
        with patch.object(
            system_provider,
            '_run_command',
            return_value='{"wrong": "format"}',
        ):
            text, stale = (
                _get_bluetooth_profiler_json(
                    timeout=10.0
                )
            )

        # Should serve stale (valid) cache
        self.assertEqual(text, VALID_BT_JSON)
        self.assertTrue(stale)

    def test_timeout_error_serves_stale(self):
        """SystemCommandTimeout also serves stale."""
        self._set_clock(100.0)

        with patch.object(
            system_provider,
            '_run_command',
            return_value=VALID_BT_JSON,
        ):
            _get_bluetooth_profiler_json(
                timeout=10.0
            )

        self._set_clock(150.0)

        with patch.object(
            system_provider,
            '_run_command',
            side_effect=SystemCommandTimeout(
                "timeout"
            ),
        ) as mock_cmd:
            text, stale = (
                _get_bluetooth_profiler_json(
                    timeout=10.0
                )
            )

        mock_cmd.assert_called_once()
        self.assertEqual(text, VALID_BT_JSON)
        self.assertTrue(stale)

    def test_reset_cache_clears(self):
        """_reset_cache clears cache state."""
        self._set_clock(100.0)

        with patch.object(
            system_provider,
            '_run_command',
            return_value=VALID_BT_JSON,
        ):
            _get_bluetooth_profiler_json(
                timeout=10.0
            )

        _reset_cache()

        self._set_clock(200.0)

        with patch.object(
            system_provider,
            '_run_command',
            side_effect=SystemCommandError(
                "fail"
            ),
        ):
            text, stale = (
                _get_bluetooth_profiler_json(
                    timeout=10.0
                )
            )

        # No stale cache after reset
        self.assertIsNone(text)


if __name__ == "__main__":
    unittest.main()


class AnonymousAccessoryMatchTests(unittest.TestCase):
    """匿名 pmset 条目（AirPods 类）电量匹配测试。

    真机实测：AirPods 在充电盒中时，pmset -g accps 输出
    不带名称的条目（level + state），需要通过与蓝牙清单组件
    电量的精确匹配绑定到 :left/:right/:case 组件 ID。
    """

    def _make_inventory(self):
        return [
            system_provider
            .BluetoothInventoryRecord(
                name=(
                    "User的"
                    "AirPods 4"
                ),
                address=(
                    "40:B3:FA:"
                    "E5:6C:E0"
                ),
                connected=True,
                minor_type=(
                    "Headphones"
                ),
                vendor_id=None,
                product_id=None,
                battery_main=None,
                battery_left=100,
                battery_right=100,
                battery_case=91,
            ),
        ]

    def _make_record(
        self,
        level,
        state,
    ):
        return system_provider \
            .AccessoryPowerRecord(
                system_id="350361794",
                name="",
                level=level,
                state=state,
                present=True,
            )

    def test_charging_record_binds_to_components(
        self,
    ):
        inventory = (
            self._make_inventory()
        )
        records = [
            self._make_record(
                100,
                "charging",
            ),
        ]

        devices = (
            system_provider
            .accessory_power_to_devices(
                records,
                inventory,
            )
        )

        self.assertEqual(
            len(devices),
            2,
        )

        for dev in devices:
            self.assertFalse(
                dev.charging
            )
            # 100% + charging 视为非充电状态
            self.assertEqual(
                dev.power_state,
                "discharging",
            )
            self.assertTrue(
                dev.device_id
                .endswith(
                    (":left",
                     ":right"),
                )
            )

    def test_partial_level_charging_stays_charging(
        self,
    ):
        """未充满的充电记录保持 charging 状态。"""
        inventory = [
            system_provider
            .BluetoothInventoryRecord(
                name=(
                    "Test"
                    " AirPods"
                ),
                address=(
                    "AA:BB:CC:"
                    "DD:EE:FF"
                ),
                connected=True,
                minor_type=(
                    "Headphones"
                ),
                vendor_id=None,
                product_id=None,
                battery_main=None,
                battery_left=67,
                battery_right=None,
                battery_case=None,
            ),
        ]
        records = [
            self._make_record(
                67,
                "charging",
            ),
        ]

        devices = (
            system_provider
            .accessory_power_to_devices(
                records,
                inventory,
            )
        )

        self.assertEqual(
            len(devices),
            1,
        )
        self.assertTrue(
            devices[0].charging
        )
        self.assertEqual(
            devices[0]
            .power_state,
            "charging",
        )

    def test_case_level_binds_to_case(
        self,
    ):
        inventory = (
            self._make_inventory()
        )
        records = [
            self._make_record(
                91,
                "discharging",
            ),
        ]

        devices = (
            system_provider
            .accessory_power_to_devices(
                records,
                inventory,
            )
        )

        self.assertEqual(
            len(devices),
            1,
        )
        self.assertTrue(
            devices[0]
            .device_id
            .endswith(":case")
        )
        self.assertFalse(
            devices[0]
            .charging
        )

    def test_no_level_match_skips(
        self,
    ):
        inventory = (
            self._make_inventory()
        )
        records = [
            self._make_record(
                55,
                "charging",
            ),
        ]

        devices = (
            system_provider
            .accessory_power_to_devices(
                records,
                inventory,
            )
        )

        self.assertEqual(
            len(devices),
            0,
        )

    def test_charging_wins_over_discharging(
        self,
    ):
        """左右耳电量相同时，charging 记录先应用。

        用非 100% 电量验证（100% + charging 已按
        _effective_power_state 规则转为 discharging）。
        """
        inventory = [
            system_provider
            .BluetoothInventoryRecord(
                name=(
                    "User的"
                    "AirPods 4"
                ),
                address=(
                    "40:B3:FA:"
                    "E5:6C:E0"
                ),
                connected=True,
                minor_type=(
                    "Headphones"
                ),
                vendor_id=None,
                product_id=None,
                battery_main=None,
                battery_left=80,
                battery_right=80,
                battery_case=None,
            ),
        ]
        records = [
            self._make_record(
                80,
                "discharging",
            ),
            self._make_record(
                80,
                "charging",
            ),
        ]

        devices = (
            system_provider
            .accessory_power_to_devices(
                records,
                inventory,
            )
        )

        self.assertEqual(
            len(devices),
            2,
        )

        for dev in devices:
            self.assertTrue(
                dev.charging
            )
            self.assertEqual(
                dev.power_state,
                "charging",
            )

    def test_named_records_unaffected(
        self,
    ):
        """有名条目仍走名称匹配，不受匿名逻辑影响。"""
        inventory = [
            system_provider
            .BluetoothInventoryRecord(
                name=(
                    "DJI Mic"
                    " Mini"
                ),
                address=(
                    "9C:5A:8A:"
                    "05:E8:88"
                ),
                connected=True,
                minor_type=(
                    "Headset"
                ),
                vendor_id=None,
                product_id=None,
                battery_main=None,
                battery_left=None,
                battery_right=None,
                battery_case=None,
            ),
        ]
        records = [
            system_provider
            .AccessoryPowerRecord(
                system_id="1",
                name=(
                    "DJI Mic"
                    " Mini"
                ),
                level=40,
                state=(
                    "discharging"
                ),
                present=True,
            ),
        ]

        devices = (
            system_provider
            .accessory_power_to_devices(
                records,
                inventory,
            )
        )

        self.assertEqual(
            len(devices),
            1,
        )
        self.assertEqual(
            devices[0].name,
            (
                "DJI Mic"
                " Mini"
            ),
        )
