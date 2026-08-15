#!/usr/bin/env python3

import unittest

from models import (
    BatteryDevice,
    CATEGORY_KEYBOARD,
    SOURCE_HIDPP,
    TRANSPORT_RECEIVER,
)


class BatteryDeviceTests(unittest.TestCase):
    def make_device(self, **changes):
        values = {
            "device_id": "hidpp:receiver:1",
            "name": "MX Keys",
            "category": CATEGORY_KEYBOARD,
            "transport": TRANSPORT_RECEIVER,
            "level": 100,
            "charging": None,
            "source": SOURCE_HIDPP,
            "observed_at": 1000.0,
            "category_source": "hid_usage",
        }
        values.update(changes)
        return BatteryDevice(**values)

    def test_valid_device(self):
        device = self.make_device()
        self.assertEqual(device.level, 100)
        self.assertFalse(device.cached)

    def test_text_is_cleaned(self):
        device = self.make_device(name="  MX   Keys  ")
        self.assertEqual(device.name, "MX Keys")

    def test_invalid_level_is_rejected(self):
        with self.assertRaises(ValueError):
            self.make_device(level=101)

    def test_boolean_level_is_rejected(self):
        with self.assertRaises(TypeError):
            self.make_device(level=True)

    def test_cached_copy_does_not_mutate_original(self):
        original = self.make_device()
        cached = original.with_cached()
        self.assertFalse(original.cached)
        self.assertTrue(cached.cached)

    def test_age_never_becomes_negative(self):
        device = self.make_device(observed_at=1000.0)
        self.assertEqual(
            device.age_seconds(now=900.0), 0.0
        )


if __name__ == "__main__":
    unittest.main()
