#!/usr/bin/env python3

import unittest

from classifier import (
    DeviceMetadata,
    category_label,
    classify_device,
)
from models import (
    CATEGORY_HEADPHONES,
    CATEGORY_KEYBOARD,
    CATEGORY_MICROPHONE,
    CATEGORY_MOUSE,
    CATEGORY_OTHER,
)


class ClassifierTests(unittest.TestCase):
    def test_dji_mic_mini_overrides_system_headphones(self):
        result = classify_device(
            DeviceMetadata(
                name="DJI Mic Mini 2-FDF43A",
                system_category="headphones",
                audio_input_channels=1,
                audio_output_channels=2,
            )
        )
        self.assertEqual(result.category, CATEGORY_MICROPHONE)
        self.assertEqual(result.source, "model_override")

    def test_input_only_audio_is_microphone(self):
        result = classify_device(
            DeviceMetadata(
                name="USB Audio Device",
                system_category="headphones",
                audio_input_channels=1,
                audio_output_channels=0,
            )
        )
        self.assertEqual(result.category, CATEGORY_MICROPHONE)

    def test_hid_keyboard_usage(self):
        result = classify_device(
            DeviceMetadata(
                name="Unknown HID",
                hid_usage_page=0x01,
                hid_usage=0x06,
            )
        )
        self.assertEqual(result.category, CATEGORY_KEYBOARD)

    def test_ble_mouse_appearance(self):
        result = classify_device(
            DeviceMetadata(
                name="Unknown BLE Device",
                appearance=0x03C2,
            )
        )
        self.assertEqual(result.category, CATEGORY_MOUSE)

    def test_airpods_name(self):
        result = classify_device(
            DeviceMetadata(name="User's AirPods")
        )
        self.assertEqual(result.category, CATEGORY_HEADPHONES)

    def test_unknown_device_falls_back(self):
        result = classify_device(
            DeviceMetadata(name="Accessory 123")
        )
        self.assertEqual(result.category, CATEGORY_OTHER)

    def test_category_label(self):
        self.assertEqual(
            category_label(CATEGORY_MICROPHONE), "麦克风"
        )


if __name__ == "__main__":
    unittest.main()
