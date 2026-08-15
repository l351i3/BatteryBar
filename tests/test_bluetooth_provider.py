#!/usr/bin/env python3

import threading
import time
import unittest
from unittest.mock import (
    MagicMock,
    Mock,
    patch,
)

import bluetooth_provider
from bluetooth_provider import _DiscoverySession

from models import (
    CATEGORY_MICROPHONE,
    CATEGORY_OTHER,
    SOURCE_BLE_STANDARD,
    TRANSPORT_BLUETOOTH,
)


class FakeIdentifier:
    def __init__(self, value):
        self.value = value

    def UUIDString(self):
        return self.value


class FakePeripheral:
    def __init__(self, name, identifier):
        self._name = name
        self._identifier = identifier

    def name(self):
        return self._name

    def identifier(self):
        if self._identifier is None:
            return None
        return FakeIdentifier(self._identifier)


class BluetoothProviderTests(unittest.TestCase):
    # --- Legacy tests (preserved from pre-rewrite) ---

    def test_valid_battery_byte(self):
        self.assertEqual(
            bluetooth_provider._parse_battery_value(
                bytes([75])
            ),
            75,
        )

    def test_zero_is_valid(self):
        self.assertEqual(
            bluetooth_provider._parse_battery_value(
                bytes([0])
            ),
            0,
        )

    def test_invalid_length_is_rejected(self):
        self.assertIsNone(
            bluetooth_provider._parse_battery_value(
                bytes([50, 60])
            )
        )

    def test_invalid_level_is_rejected(self):
        self.assertIsNone(
            bluetooth_provider._parse_battery_value(
                bytes([255])
            )
        )

    def test_missing_value_is_rejected(self):
        self.assertIsNone(
            bluetooth_provider._parse_battery_value(None)
        )

    def test_unknown_device_is_kept(self):
        peripheral = FakePeripheral(
            "Accessory 123", "ABC-123"
        )
        device = bluetooth_provider._make_device(
            peripheral, 61, 1000.0
        )
        self.assertEqual(device.category, CATEGORY_OTHER)
        self.assertEqual(device.transport, TRANSPORT_BLUETOOTH)
        self.assertEqual(device.source, SOURCE_BLE_STANDARD)
        self.assertEqual(device.level, 61)
        self.assertEqual(device.device_id, "bluetooth:abc-123")

    def test_dji_mic_mini_is_microphone(self):
        peripheral = FakePeripheral(
            "DJI Mic Mini 2-FDF43A", "DJI-123"
        )
        device = bluetooth_provider._make_device(
            peripheral, 80, 1000.0
        )
        self.assertEqual(device.category, CATEGORY_MICROPHONE)
        self.assertEqual(device.category_source, "model_override")

    def test_missing_identifier_is_rejected(self):
        peripheral = FakePeripheral("Unknown", None)
        with self.assertRaises(
            bluetooth_provider.BluetoothProviderError
        ):
            bluetooth_provider._make_device(
                peripheral, 50, 1000.0
            )

    def test_finish_marks_delegate_done(self):
        peripheral = FakePeripheral("Mouse", "MOUSE-1")
        delegate = Mock()
        delegate.pending = {"MOUSE-1"}
        delegate.done = False
        bluetooth_provider._finish(delegate, peripheral)
        self.assertEqual(delegate.pending, set())
        self.assertTrue(delegate.done)

    def test_timeout_validation(self):
        for value in (0, -1, True, "12"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    bluetooth_provider._validate_timeout(
                        value
                    )


class DiscoverySessionTests(unittest.TestCase):
    """Tests for _DiscoverySession state machine.

    Uses injected clocks (no real sleep) and mocks
    for CoreBluetooth objects.
    """

    def _make_session(self, tag=1):
        return _DiscoverySession(tag)

    # --- try_finish first-terminal-wins ---

    def test_try_finish_first_call_wins(self):
        session = self._make_session()
        self.assertTrue(
            session.try_finish('completed', 'test')
        )
        self.assertEqual(
            session.terminal_state, 'completed'
        )
        self.assertEqual(
            session.finish_reason, 'test'
        )
        self.assertTrue(session.done_event.is_set())

    def test_try_finish_second_call_loses(self):
        session = self._make_session()
        session.try_finish('completed', 'first')
        self.assertFalse(
            session.try_finish('timeout', 'second')
        )
        # State unchanged
        self.assertEqual(
            session.terminal_state, 'completed'
        )
        self.assertEqual(
            session.finish_reason, 'first'
        )

    def test_try_finish_freezes_result_snapshot(self):
        session = self._make_session()
        session.results = ['a', 'b']
        session.try_finish('completed', 'test')
        # After try_finish, results list can be modified
        # but snapshot is frozen
        session.results.append('c')
        self.assertEqual(
            session.result_snapshot, ['a', 'b']
        )

    # --- cleanup phases ---

    def test_begin_cleanup_returns_objects_once(self):
        session = self._make_session()
        fake_mgr = Mock()
        fake_p = Mock()
        session.manager = fake_mgr
        session.peripherals_snapshot = {
            'p1': fake_p
        }
        result = session.begin_cleanup()
        self.assertIsNotNone(result)
        mgr, periph_list = result
        self.assertIs(mgr, fake_mgr)
        self.assertEqual(len(periph_list), 1)
        # Second call returns None (idempotent)
        self.assertIsNone(
            session.begin_cleanup()
        )

    def test_finish_cleanup_clears_references(self):
        session = self._make_session()
        fake_mgr = Mock()
        fake_delegate = Mock()
        session.manager = fake_mgr
        session.delegate = fake_delegate
        session.finish_cleanup()
        self.assertIsNone(session.manager)
        self.assertIsNone(session.delegate)
        self.assertEqual(
            session.peripherals_snapshot, {}
        )
        self.assertTrue(session.cleaned)
        self.assertTrue(
            session.cleanup_event.is_set()
        )

    def test_finish_cleanup_breaks_delegate_cycle(self):
        session = self._make_session()
        delegate = Mock()
        delegate.session = session
        session.delegate = delegate
        session.finish_cleanup()
        self.assertIsNone(delegate.session)

    # --- _mark_peripheral_done ---

    def test_mark_peripheral_done_discards_pending(
        self,
    ):
        session = self._make_session()
        session.pending = {'p1', 'p2'}
        session.discovery_closed = True
        with session._lock:
            bluetooth_provider._mark_peripheral_done(
                session, 'p1'
            )
        # Not yet complete (p2 still pending)
        self.assertEqual(
            session.pending, {'p2'}
        )
        self.assertIsNone(session.terminal_state)

    def test_mark_peripheral_done_completes_when_empty(
        self,
    ):
        session = self._make_session()
        session.pending = {'p1'}
        session.discovery_closed = True
        with session._lock:
            bluetooth_provider._mark_peripheral_done(
                session, 'p1'
            )
        self.assertEqual(session.pending, set())
        self.assertEqual(
            session.terminal_state, 'completed'
        )
        self.assertTrue(session.done_event.is_set())

    def test_mark_peripheral_done_no_complete_before_discovery_closed(
        self,
    ):
        session = self._make_session()
        session.pending = {'p1'}
        session.discovery_closed = False
        with session._lock:
            bluetooth_provider._mark_peripheral_done(
                session, 'p1'
            )
        self.assertEqual(session.pending, set())
        # NOT complete because discovery not closed
        self.assertIsNone(session.terminal_state)

    # --- _delegate_record_result ---

    def test_record_result_stores_device(self):
        session = self._make_session()
        peripheral = FakePeripheral(
            "TestDevice", "TEST-1"
        )
        with session._lock:
            ok = bluetooth_provider \
                ._delegate_record_result(
                    session,
                    peripheral,
                    75,
                )
        self.assertTrue(ok)
        self.assertEqual(
            len(session.results), 1
        )
        self.assertIn('TEST-1', session.completed)

    def test_record_result_rejects_duplicate(self):
        session = self._make_session()
        peripheral = FakePeripheral(
            "TestDevice", "TEST-1"
        )
        with session._lock:
            bluetooth_provider \
                ._delegate_record_result(
                    session,
                    peripheral,
                    75,
                )
            # Second call should be rejected
            ok = bluetooth_provider \
                ._delegate_record_result(
                    session,
                    peripheral,
                    80,
                )
        self.assertFalse(ok)
        self.assertEqual(
            len(session.results), 1
        )

    def test_record_result_rejects_no_identifier(
        self,
    ):
        session = self._make_session()
        peripheral = FakePeripheral(
            "NoID", None
        )
        with session._lock:
            ok = bluetooth_provider \
                ._delegate_record_result(
                    session,
                    peripheral,
                    50,
                )
        self.assertFalse(ok)

    # --- peripheral_id as keys ---

    def test_peripheral_identifier_lowercase(self):
        peripheral = FakePeripheral(
            "Mouse", "AB-CD"
        )
        pid = bluetooth_provider \
            ._peripheral_identifier(peripheral)
        self.assertEqual(pid, "AB-CD")
        # Device ID uses lowercase
        device = bluetooth_provider._make_device(
            peripheral, 50, 1000.0
        )
        self.assertEqual(
            device.device_id, "bluetooth:ab-cd"
        )

    def test_peripheral_identifier_empty_on_none(
        self,
    ):
        peripheral = FakePeripheral(
            "Unknown", None
        )
        pid = bluetooth_provider \
            ._peripheral_identifier(peripheral)
        self.assertEqual(pid, "")


class GCDQueueTests(unittest.TestCase):
    """Verify GCD serial queue behavior.

    These tests require pyobjc-framework-Dispatch. They are
    skipped if dispatch is not available (e.g. minimal test
    environments), since they exercise real GCD queues.
    """

    def setUp(self):
        try:
            import dispatch  # noqa: F401
        except ImportError:
            self.skipTest(
                "dispatch not available"
            )

    def test_ble_queue_created_lazily(self):
        q = bluetooth_provider._get_ble_queue()
        self.assertIsNotNone(q)

    def test_ble_queue_cached(self):
        q1 = bluetooth_provider._get_ble_queue()
        q2 = bluetooth_provider._get_ble_queue()
        self.assertIs(q1, q2)

    def test_dispatch_async_executes(self):
        from dispatch import dispatch_async
        q = bluetooth_provider._get_ble_queue()
        results = []
        dispatch_async(
            q,
            lambda: results.append('done'),
        )
        # Small sleep to let GCD execute
        time.sleep(0.1)
        self.assertEqual(results, ['done'])

    def test_serial_queue_ordering(self):
        from dispatch import dispatch_async
        q = bluetooth_provider._get_ble_queue()
        order = []
        for i in range(5):
            dispatch_async(
                q,
                lambda idx=i: order.append(idx),
            )
        time.sleep(0.5)
        self.assertEqual(order, [0, 1, 2, 3, 4])


class DiscoveryLockTests(unittest.TestCase):
    """Verify _DISCOVERY_LOCK behavior."""

    def test_lock_is_module_level(self):
        lock = bluetooth_provider._DISCOVERY_LOCK
        self.assertIsInstance(
            lock, type(threading.Lock())
        )

    def test_lock_acquire_release(self):
        lock = bluetooth_provider._DISCOVERY_LOCK
        self.assertTrue(
            lock.acquire(blocking=True, timeout=0.1)
        )
        lock.release()


class UnifiedDeadlineTests(unittest.TestCase):
    """Verify unified deadline behavior in discover_batteries.

    These tests exercise the _discover_inner path which
    requires dispatch and CoreBluetooth. They are skipped
    if dispatch is not available.
    """

    def setUp(self):
        try:
            import dispatch  # noqa: F401
        except ImportError:
            self.skipTest(
                "dispatch not available"
            )

    @patch(
        'bluetooth_provider.CoreBluetooth'
        '.CBCentralManager',
    )
    @patch(
        'bluetooth_provider.BluetoothBatteryDelegate'
    )
    def test_timeout_raises_error_when_cb_init_fails(
        self,
        mock_delegate_cls,
        mock_cb_manager_cls,
    ):
        """If CB init raises, discover should propagate
        the error (deadline expired before any callback).
        """
        mock_delegate_cls.alloc.return_value \
            .init.return_value = Mock()

        # Make initWithDelegate_queue_ raise to
        # simulate init failure
        mock_cb_manager_cls.alloc.return_value \
            .initWithDelegate_queue_ = Mock(
                side_effect=Exception("simulated")
            )

        with self.assertRaises(Exception):
            bluetooth_provider \
                .discover_batteries(timeout=1.0)

    def test_discovery_lock_busy_raises(self):
        """Discovery lock busy should raise within
        the timeout window."""
        lock = bluetooth_provider._DISCOVERY_LOCK
        lock.acquire()

        try:
            with self.assertRaises(
                bluetooth_provider
                .BluetoothProviderError
            ) as ctx:
                bluetooth_provider \
                    .discover_batteries(timeout=0.1)
            self.assertIn(
                'busy',
                str(ctx.exception).lower(),
            )
        finally:
            lock.release()


class BackwardCompatTests(unittest.TestCase):
    """Verify backward-compatible _finish and
    _record_result still work."""

    def test_finish_legacy_with_mock_delegate(
        self,
    ):
        peripheral = FakePeripheral(
            "Mouse", "MOUSE-1"
        )
        delegate = Mock()
        delegate.pending = {"MOUSE-1"}
        delegate.done = False
        bluetooth_provider._finish(
            delegate, peripheral
        )
        self.assertEqual(delegate.pending, set())
        self.assertTrue(delegate.done)

    def test_record_result_legacy(self):
        peripheral = FakePeripheral(
            "KB", "KB-1"
        )
        delegate = Mock()
        delegate.completed = set()
        delegate.results = []
        bluetooth_provider._record_result(
            delegate, peripheral, 80
        )
        self.assertEqual(len(delegate.results), 1)
        self.assertIn('KB-1', delegate.completed)

    def test_record_result_legacy_rejects_duplicate(
        self,
    ):
        peripheral = FakePeripheral(
            "KB", "KB-1"
        )
        delegate = Mock()
        delegate.completed = set()
        delegate.results = []
        bluetooth_provider._record_result(
            delegate, peripheral, 80
        )
        bluetooth_provider._record_result(
            delegate, peripheral, 90
        )
        self.assertEqual(len(delegate.results), 1)


if __name__ == "__main__":
    unittest.main()
