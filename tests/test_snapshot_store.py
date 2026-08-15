#!/usr/bin/env python3
"""snapshot_store 单元测试：序列化/反序列化校验、原子读写往返。

覆盖 schema 校验、字段验证、非法 payload 拒绝、
写后读回一致性（DEVELOPMENT.md 第 14 节第 1 条）。
"""

import json
import tempfile
import unittest
from pathlib import Path

from aggregator import BatterySnapshot, ProviderStatus
from models import BatteryDevice
from snapshot_store import (
    SNAPSHOT_SCHEMA_VERSION,
    SnapshotReadError,
    SnapshotValidationError,
    deserialize_snapshot,
    read_snapshot,
    read_snapshot_or_none,
    serialize_snapshot,
    snapshot_from_dict,
    snapshot_to_dict,
    write_snapshot_atomic,
)


def _device(
    device_id="hidpp:c548:abc123",
    name="MX Keys S",
):
    return BatteryDevice(
        device_id=device_id,
        name=name,
        category="keyboard",
        transport="receiver",
        level=85,
        charging=None,
        source="hidpp",
        observed_at=1700000000.0,
        category_source="hid_usage",
        cached=False,
        power_state="unknown",
    )


def _status(
    name="hidpp",
    succeeded=True,
    device_count=1,
):
    return ProviderStatus(
        name=name,
        succeeded=succeeded,
        device_count=device_count,
        duration_seconds=1.23,
        error=None if succeeded else "boom",
    )


def _snapshot():
    return BatterySnapshot(
        updated_at=1700000000.0,
        devices=(_device(),),
        provider_statuses=(_status(),),
    )


class SnapshotRoundTripTests(unittest.TestCase):
    """序列化 → 反序列化的完整往返。"""

    def test_serialize_deserialize_preserves_data(self):
        snap = _snapshot()
        text = serialize_snapshot(snap)
        restored = deserialize_snapshot(text)

        self.assertEqual(
            restored.updated_at, snap.updated_at
        )
        self.assertEqual(
            len(restored.devices), 1
        )
        self.assertEqual(
            restored.devices[0].device_id,
            "hidpp:c548:abc123",
        )
        self.assertEqual(
            restored.devices[0].level, 85
        )
        self.assertEqual(
            len(restored.provider_statuses), 1
        )

    def test_serialized_json_has_schema_version(self):
        text = serialize_snapshot(_snapshot())
        payload = json.loads(text)

        self.assertEqual(
            payload["schema_version"],
            SNAPSHOT_SCHEMA_VERSION,
        )

    def test_to_dict_and_from_dict_roundtrip(self):
        """snapshot_to_dict → snapshot_from_dict 等价于
        BatterySnapshot 本身。"""
        snap = _snapshot()
        d = snapshot_to_dict(snap)
        restored = snapshot_from_dict(d)

        self.assertEqual(
            restored.updated_at, snap.updated_at
        )
        self.assertEqual(
            restored.devices, snap.devices
        )
        self.assertEqual(
            restored.provider_statuses,
            snap.provider_statuses,
        )


class SnapshotValidationTests(unittest.TestCase):
    """非法 payload 必须被拒绝。"""

    def test_wrong_schema_version_rejected(self):
        snap = _snapshot()
        d = snapshot_to_dict(snap)
        d["schema_version"] = 999

        with self.assertRaises(
            SnapshotValidationError
        ) as ctx:
            snapshot_from_dict(d)

        self.assertIn("schema_version", str(ctx.exception))

    def test_missing_field_rejected(self):
        d = snapshot_to_dict(_snapshot())
        del d["updated_at"]

        with self.assertRaises(
            SnapshotValidationError
        ) as ctx:
            snapshot_from_dict(d)

        self.assertIn("missing", str(ctx.exception))

    def test_extra_field_rejected(self):
        d = snapshot_to_dict(_snapshot())
        d["unexpected"] = "surprise"

        with self.assertRaises(
            SnapshotValidationError
        ) as ctx:
            snapshot_from_dict(d)

        self.assertIn("extra", str(ctx.exception))

    def test_invalid_level_rejected(self):
        d = snapshot_to_dict(_snapshot())
        d["devices"][0]["level"] = 150

        with self.assertRaises(
            SnapshotValidationError
        ):
            snapshot_from_dict(d)

    def test_duplicate_device_ids_rejected(self):
        dev = _device()
        d = snapshot_to_dict(
            BatterySnapshot(
                updated_at=1700000000.0,
                devices=(dev, dev),
                provider_statuses=(),
            )
        )

        with self.assertRaises(
            SnapshotValidationError
        ) as ctx:
            snapshot_from_dict(d)

        self.assertIn("duplicate", str(ctx.exception))

    def test_invalid_json_rejected(self):
        with self.assertRaises(
            SnapshotValidationError
        ) as ctx:
            deserialize_snapshot("{not valid json")

        self.assertIn("invalid JSON", str(ctx.exception))


class AtomicIOTests(unittest.TestCase):
    """write_snapshot_atomic / read_snapshot 文件 IO。"""

    def test_write_then_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.json"
            snap = _snapshot()

            written_path = write_snapshot_atomic(
                snap, path
            )
            self.assertEqual(written_path, path)
            self.assertTrue(path.exists())

            restored = read_snapshot(path)

            self.assertEqual(
                restored.updated_at,
                snap.updated_at,
            )
            self.assertEqual(
                restored.devices[0].name,
                snap.devices[0].name,
            )

    def test_write_replaces_existing_file(self):
        """原子写入应覆盖旧文件，不留残留 .tmp。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.json"

            write_snapshot_atomic(
                _snapshot(), path
            )
            # 第二次写不同数据
            snap2 = BatterySnapshot(
                updated_at=1999999999.0,
                devices=(),
                provider_statuses=(),
            )
            write_snapshot_atomic(snap2, path)

            restored = read_snapshot(path)
            self.assertEqual(
                restored.updated_at, 1999999999.0
            )

            # 不应残留临时文件
            tmps = list(path.parent.glob(".*.tmp"))
            self.assertEqual(len(tmps), 0)

    def test_read_nonexistent_returns_error(self):
        with self.assertRaises(SnapshotReadError):
            read_snapshot(
                Path("/nonexistent/path/snap.json")
            )

    def test_read_or_none_swallows_error(self):
        result = read_snapshot_or_none(
            Path("/nonexistent/path/snap.json")
        )
        self.assertIsNone(result)


if __name__ == "__main__":
    import sys

    sys.exit(unittest.main())
