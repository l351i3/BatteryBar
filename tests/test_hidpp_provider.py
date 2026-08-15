#!/usr/bin/env python3

# 注：本文件直接导入真实的 models / classifier（与 HANDOVER.md 中
# test_models.py、test_classifier.py 保持一致），不对其做 sys.modules 打桩，
# 以免在 unittest discover 全量运行时污染其他测试对 `models` 模块的引用。

import unittest
from unittest.mock import MagicMock, patch

import hidpp_provider
from models import (
    CATEGORY_KEYBOARD,
    SOURCE_HIDPP,
    TRANSPORT_RECEIVER,
)


def _make_target(**changes):
    """构造一份完整的动态探测 target 字典，方便各用例按需覆写字段。"""
    target = {
        "name": "MX Keys S",
        "product_id": 0xC548,
        "slot": 1,
        "feature_index": 0x08,
        "function": 1,
        "software_id": 0x0F,
        "hid_usage_page": 0x01,
        "hid_usage": 0x06,
        "serial": "2537CE035KJ8",
        "receiver_path": "/dev/hidraw0",
    }
    target.update(changes)
    return target


class HidppProviderDynamicTests(unittest.TestCase):
    def test_build_request_has_20_bytes(self):
        target = _make_target()
        packet, function_client = (
            hidpp_provider._build_request(target)
        )

        self.assertEqual(len(packet), 20)
        self.assertEqual(packet[0], 0x11)
        self.assertEqual(packet[1], target["slot"])
        self.assertEqual(packet[2], target["feature_index"])
        self.assertEqual(packet[3], function_client)

    def test_make_device_model(self):
        target = _make_target()
        device = hidpp_provider._make_device(
            "mx_keys_s", target, 70, 1000.0
        )

        self.assertEqual(device.name, "MX Keys S")
        self.assertEqual(device.category, CATEGORY_KEYBOARD)
        self.assertEqual(device.transport, TRANSPORT_RECEIVER)
        self.assertEqual(device.source, SOURCE_HIDPP)
        self.assertEqual(device.level, 70)
        self.assertEqual(device.power_state, "unknown")
        self.assertEqual(
            device.device_id, "hidpp:c548:2537CE035KJ8"
        )

    def test_matching_response(self):
        target = _make_target()
        _, function_client = (
            hidpp_provider._build_request(target)
        )
        packet = [
            0x11,
            target["slot"],
            target["feature_index"],
            function_client,
            70,
        ]

        self.assertTrue(
            hidpp_provider._is_matching_response(
                packet, target, function_client
            )
        )

    def test_error_response_detection(self):
        target = _make_target()
        _, function_client = (
            hidpp_provider._build_request(target)
        )
        packet = [
            0x11,
            target["slot"],
            0xFF,
            target["feature_index"],
            function_client,
            0x0A,
        ]

        self.assertTrue(
            hidpp_provider._is_error_response(
                packet, target, function_client
            )
        )

    @patch("hidpp_provider.enumerate_hidpp_receivers")
    @patch("hidpp_provider.probe_device_on_slot")
    @patch("hidpp_provider.query_battery_once_with_device")
    @patch("hidpp_provider.hid.device")
    def test_discover_batteries_dynamic(
        self,
        mock_hid_device,
        mock_query_battery_once_with_device,
        mock_probe_device_on_slot,
        mock_enumerate_receivers,
    ):
        mock_enumerate_receivers.return_value = {
            "/dev/hidraw0": 0xC548
        }

        def side_effect_probe(device, pid, slot, receiver_path):
            if slot == 1:
                return _make_target(
                    name="MX Keys S",
                    product_id=pid,
                    slot=slot,
                    receiver_path=receiver_path,
                )
            return None

        mock_probe_device_on_slot.side_effect = (
            side_effect_probe
        )
        mock_query_battery_once_with_device.return_value = 70

        results = hidpp_provider.discover_batteries(
            attempts=1, timeout=0.1, retry_delay=0
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "MX Keys S")
        self.assertEqual(results[0].level, 70)
        self.assertEqual(results[0].category, CATEGORY_KEYBOARD)


class HidppFeatureLookupTests(unittest.TestCase):
    """回归测试：动态探测的 HID++ 2.0 报文字节布局。

    这些用例锁定 Root.GetFeature 的 Feature ID 必须放在长报告 (0x11) 的
    Parameters 区起始 (offset 4-5，大端)；以及 DeviceInfo 必须使用 Function 0。
    之前的版本把 Feature ID 错放到 offset 16-17，导致接收器对每个槽位都返回
    “未找到”，USB 接收器上的设备完全无法被发现。
    """

    def _fake_device(self, read_packets):
        """构造一个伪造的 HID 设备。

        get_feature_index / get_device_name / get_device_serial 在 write 之前
        会先调用 _drain，而 _drain 会持续 read 直到返回 falsy 值。因此这里把
        首次 read（drain 阶段）返回 None 让其立即退出，之后再依次吐出响应包。
        """
        device = MagicMock()
        device.write.return_value = 20  # 长报告固定 20 字节
        device.read.side_effect = [None] + list(read_packets)
        return device

    def test_get_feature_index_places_feature_id_at_offset_4(self):
        device = self._fake_device([
            # 成功响应：[0]=0x11, [1]=slot, [2]=0x00(root),
            # [3]=0x01(func0|sw1), [4]=返回的 index = 0x08
            [0x11, 1, 0x00, 0x01, 0x08] + [0x00] * 15,
        ])

        index = hidpp_provider.get_feature_index(
            device, slot=1, feature_id=0x1004
        )

        written = device.write.call_args[0][0]
        # 关键断言：Feature ID (0x1004) 必须出现在 offset 4-5，而非 16-17
        self.assertEqual(written[4], 0x10)  # 高字节
        self.assertEqual(written[5], 0x04)  # 低字节
        # offset 16-17 必须为 0（旧 bug 把它写在了这里）
        self.assertEqual(written[16], 0x00)
        self.assertEqual(written[17], 0x00)
        self.assertEqual(index, 0x08)

    def test_get_feature_index_zero_index_means_unsupported(self):
        device = self._fake_device([
            [0x11, 1, 0x00, 0x01, 0x00] + [0x00] * 15,
        ])
        index = hidpp_provider.get_feature_index(
            device, slot=1, feature_id=0x1004
        )
        self.assertIsNone(index)

    def test_get_device_serial_uses_function_zero(self):
        device = self._fake_device([
            # DeviceInfo Function 0 响应：[3]=func0|sw3=0x03
            # 序列号在 offset 12-14
            [0x11, 1, 0x03, 0x03,
             0xDE, 0xAD, 0xBE, 0xEF,   # unitId (offset 4-7)
             0x01,                       # transport (offset 8)
             0x00, 0x00, 0x00,           # modelId (offset 9-11)
             0xAB, 0xCD, 0xEF]           # serial (offset 12-14)
            + [0x00] * 5,
        ])

        serial = hidpp_provider.get_device_serial(
            device, slot=1, info_feature_index=0x03
        )

        written = device.write.call_args[0][0]
        # 关键断言：Function 0 (高 4 位)，而不是旧实现的 Function 2 (0x23)
        self.assertEqual(written[3], 0x03)
        self.assertEqual(serial, "ABCDEF")

    def test_get_device_name_parses_chars_from_offset_4(self):
        """锁定 DeviceName Function 1 响应布局：res[4..] 直接是名称字符。

        实测响应 (MX Keys S)：[0x11, slot, name_idx, 0x12,
        'M','X',' ','K','e','y','s',' ','S', 0, 0, ...]
        字符从 offset 4 开始，没有 char_index 回显、没有 length 字段。
        旧实现误以为 res[5..] 才是字符，会把首字母 'M' 丢掉。
        """
        name_chars = list(b"MX Keys S")
        # Function 1 | SwID 0x02 = 0x12
        resp = [0x11, 1, 3, 0x12] + name_chars + [0x00] * (16 - len(name_chars))
        # get_device_name 内部会发两次请求（先查长度，再读字符），
        # 每次请求前都 _drain，因此 mock 需要为两次 drain 各提供一个 None。
        device = MagicMock()
        device.write.return_value = 20
        device.read.side_effect = [
            None,  # drain before length query
            [0x11, 1, 3, 0x02, len(name_chars)] + [0x00] * 15,  # length
            None,  # drain before name query
            resp,   # name chars
        ]

        name = hidpp_provider.get_device_name(
            device, slot=1, name_feature_index=3
        )

        self.assertEqual(name, "MX Keys S")

    def test_get_device_name_retries_with_backoff_on_sleeping_device(self):
        """深度休眠设备：name_len 查询前两次无响应，第三次成功。

        验证指数退避重试机制（0.1s → 0.2s → 0.4s）能从休眠状态恢复。
        """
        name_chars = list(b"MX Master 3")
        device = MagicMock()
        device.write.return_value = 20
        device.read.side_effect = [
            None,   # drain before attempt 1
            None,   # attempt 1: 长度查询无响应（设备休眠）
            None,   # drain before attempt 2
            None,   # attempt 2: 仍无响应
            None,   # drain before attempt 3
            [0x11, 1, 3, 0x02, len(name_chars)] + [0x00] * 15,  # attempt 3: 唤醒成功
            None,   # drain before name char query
            [0x11, 1, 3, 0x12] + name_chars + [0x00] * (16 - len(name_chars)),
        ]

        name = hidpp_provider.get_device_name(
            device, slot=1, name_feature_index=3, timeout=0.05
        )

        self.assertEqual(name, "MX Master 3")


class DeviceModelIdTests(unittest.TestCase):
    """get_device_model_id 和 modelId 反查兜底。"""

    def test_get_model_id_returns_hex_string(self):
        """modelId 在 0x0003 响应的 offset 9-11（3 字节）。"""
        device = MagicMock()
        device.write.return_value = 20
        device.read.side_effect = [
            None,  # drain
            # [0]=0x11, [1]=slot, [2]=info_idx, [3]=0x03(func0|sw3),
            # offset 4-8: unitId+transport, offset 9-11: modelId
            [0x11, 1, 0x03, 0x03,
             0xDE, 0xAD, 0xBE, 0xEF, 0x01,
             0xB3, 0x6C, 0x00]            # modelId = B36C00
            + [0x00] * 8,
        ]

        model_id = hidpp_provider.get_device_model_id(
            device, slot=1, info_feature_index=0x03
        )

        self.assertEqual(model_id, "B36C00")

    def test_model_id_lookup_table_covers_common_devices(self):
        """反查表应覆盖常见型号，且值为非空字符串。"""
        table = hidpp_provider._KNOWN_MODEL_NAMES
        self.assertGreater(len(table), 5)
        for model_id, name in table.items():
            self.assertIsInstance(model_id, str)
            self.assertIsInstance(name, str)
            self.assertTrue(name.strip())


class WakeupPulseTests(unittest.TestCase):
    """_wakeup_pulse 发送心跳并排空缓冲区。"""

    def test_wakeup_pulse_writes_root_feature_query(self):
        device = MagicMock()
        device.write.return_value = 20
        # _wakeup_pulse 内部调 _drain，_drain 用 device.read() 排空缓冲区。
        # 必须让 read 返回 falsy（None），否则 MagicMock 默认返回 truthy
        # 对象导致 _drain 的 while 循环无限。
        device.read.return_value = None

        hidpp_provider._wakeup_pulse(
            device, slot=1, settle_ms=1
        )

        self.assertEqual(device.write.call_count, 1)
        written = device.write.call_args[0][0]
        self.assertEqual(written[0], 0x11)   # 长报告
        self.assertEqual(written[1], 1)      # slot
        self.assertEqual(written[2], 0x00)   # Root feature
        self.assertEqual(written[3] & 0x0F, 0x09)  # SwID=0x09

    def test_wakeup_pulse_swallows_write_error(self):
        """write 异常不应传播——wakeup 是尽力而为。"""
        device = MagicMock()
        device.write.side_effect = OSError("device gone")
        device.read.return_value = None

        # 不应抛异常
        hidpp_provider._wakeup_pulse(
            device, slot=1, settle_ms=1
        )


class GuessHidUsageTests(unittest.TestCase):
    """回归测试：_guess_hid_usage 对 fallback 名不应归类为鼠标。

    HID++ 设备名读取偶尔失败时 probe_device_on_slot 回退为
    "HID++ Device Slot N"，此名字不含任何产品关键词。
    旧代码默认 return 0x02 (mouse)，导致键盘错误显示在鼠标分类中。
    """

    def test_fallback_name_returns_undefined(self):
        self.assertEqual(
            hidpp_provider._guess_hid_usage("HID++ Device Slot 1"),
            0x00,
        )

    def test_keyboard_name_returns_keyboard_usage(self):
        self.assertEqual(
            hidpp_provider._guess_hid_usage("MX Keys S"),
            0x06,
        )

    def test_mouse_name_returns_mouse_usage(self):
        self.assertEqual(
            hidpp_provider._guess_hid_usage("MX Anywhere 3S"),
            0x02,
        )

    def test_unknown_name_returns_undefined_not_mouse(self):
        """非 fallback 但无法识别的设备名也不应默认为鼠标。"""
        self.assertEqual(
            hidpp_provider._guess_hid_usage("Unknown Gadget"),
            0x00,
        )


if __name__ == "__main__":
    import sys
    sys.exit(unittest.main())
