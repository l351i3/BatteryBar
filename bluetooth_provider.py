#!/usr/bin/env python3

import logging
import threading
import time

import objc
import CoreBluetooth

from Foundation import (
    NSObject,
    NSThread,
)

logger = logging.getLogger(__name__)

from classifier import (
    DeviceMetadata,
    classify_device,
)
from models import (
    BatteryDevice,
    POWER_STATE_UNKNOWN,
    SOURCE_BLE_STANDARD,
    TRANSPORT_BLUETOOTH,
)

BATTERY_SERVICE_UUID = "180F"
BATTERY_LEVEL_UUID = "2A19"

DEFAULT_TIMEOUT = 12.0

BATTERY_SERVICE = (
    CoreBluetooth.CBUUID
    .UUIDWithString_(
        BATTERY_SERVICE_UUID
    )
)

BATTERY_LEVEL = (
    CoreBluetooth.CBUUID
    .UUIDWithString_(
        BATTERY_LEVEL_UUID
    )
)

# Module-level GCD serial queue: all CoreBluetooth API calls
# and delegate callbacks dispatch here.
# queue=None dispatches to main queue; background poll thread
# cannot service main queue → zero callbacks → 0 devices.
# Real-device verified: GCD serial queue works correctly.
#
# Lazily created on first discover_batteries call to keep
# import side-effect free (dispatch may be absent in minimal
# test environments; pure-logic tests must not require it).
_BLE_QUEUE = None

# Protects discover_batteries entry against CBManagerState
# .busy (power state not .poweredOn and not .unknown).
_DISCOVERY_LOCK = threading.Lock()

_SESSION_TAG_LOCK = threading.Lock()
_session_tag_counter = 0


def _get_ble_queue():
    """Lazily create and cache the GCD serial queue.

    Importing dispatch at module load would break pure-logic
    tests in environments without pyobjc-framework-Dispatch,
    even though those tests never touch CoreBluetooth.
    """
    global _BLE_QUEUE
    if _BLE_QUEUE is None:
        from dispatch import (
            dispatch_queue_create,
        )
        _BLE_QUEUE = dispatch_queue_create(
            b'com.batterybar.ble',
            None,
        )
    return _BLE_QUEUE


def _next_session_tag():
    global _session_tag_counter
    with _SESSION_TAG_LOCK:
        _session_tag_counter += 1
        return _session_tag_counter


class BluetoothProviderError(
    Exception
):
    pass


class BluetoothUnavailableError(
    BluetoothProviderError
):
    pass


def _validate_timeout(timeout):
    if (
        isinstance(timeout, bool)
        or not isinstance(
            timeout,
            (int, float),
        )
        or timeout <= 0
    ):
        raise ValueError(
            "timeout must be "
            "a positive number"
        )

    return float(timeout)


def _peripheral_identifier(
    peripheral,
):
    identifier = (
        peripheral.identifier()
    )

    if identifier is None:
        return ""

    value = identifier.UUIDString()

    if value is None:
        return ""

    return str(value)


def _peripheral_name(peripheral):
    value = peripheral.name()

    if value is None:
        return "未知蓝牙设备"

    cleaned = " ".join(
        str(value).split()
    )

    return (
        cleaned
        or "未知蓝牙设备"
    )


def _parse_battery_value(value):
    if value is None:
        return None

    try:
        data = bytes(value)
    except (
        TypeError,
        ValueError,
    ):
        return None

    if len(data) != 1:
        return None

    level = data[0]

    if not 0 <= level <= 100:
        return None

    return level


def _make_device(
    peripheral,
    level,
    observed_at,
):
    identifier = (
        _peripheral_identifier(
            peripheral
        )
    )

    if not identifier:
        raise BluetoothProviderError(
            "蓝牙设备缺少稳定标识"
        )

    name = _peripheral_name(
        peripheral
    )

    classification = classify_device(
        DeviceMetadata(
            name=name
        )
    )

    return BatteryDevice(
        device_id=(
            "bluetooth:"
            + identifier.lower()
        ),
        name=name,
        category=(
            classification.category
        ),
        transport=(
            TRANSPORT_BLUETOOTH
        ),
        level=level,
        charging=None,
        source=(
            SOURCE_BLE_STANDARD
        ),
        observed_at=observed_at,
        category_source=(
            classification.source
        ),
        power_state=(
            POWER_STATE_UNKNOWN
        ),
    )


class _DiscoverySession:
    """Holds all state for a single discover_batteries call.

    Lifecycle:
      1. Created by discover_batteries.
      2. CoreBluetooth callbacks modify state under
         session._lock.
      3. try_finish() freezes result_snapshot on first
         terminal transition and sets done_event.
      4. Caller waits on done_event, then triggers cleanup.
      5. Two-phase cleanup: snapshot objects (phase 1),
         dispatch_async CoreBluetooth calls (phase 2),
         clear references + signal cleanup_event (phase 3).
    """

    __slots__ = (
        'session_tag',
        'manager',
        'delegate',
        '_lock',
        'terminal_state',
        'finish_reason',
        'cleanup_started',
        'cleaned',
        'done_event',
        'cleanup_event',
        'result_snapshot',
        'state_received',
        'powered_on',
        'discovery_closed',
        'peripherals_snapshot',
        'pending',
        'results',
        'completed',
    )

    def __init__(self, session_tag):
        self.session_tag = session_tag
        self.manager = None
        self.delegate = None
        self._lock = threading.Lock()

        # Terminal state fields (only written by try_finish)
        self.terminal_state = None
        self.finish_reason = None
        self.cleanup_started = False
        self.cleaned = False

        # Dual events for lifecycle coordination
        self.done_event = threading.Event()
        self.cleanup_event = threading.Event()

        # Results frozen at try_finish time
        self.result_snapshot = None

        # CB state tracking
        self.state_received = False
        self.powered_on = False

        # Scan lifecycle: discovery_closed is set when
        # no peripherals found. Before discovery_closed,
        # pending becoming empty does NOT trigger
        # completion (peripherals may still arrive).
        self.discovery_closed = False

        # Peripheral tracking (peripheral_id string keys)
        self.peripherals_snapshot = {}
        self.pending = set()
        self.results = []
        self.completed = set()

    def _try_finish_locked(
        self,
        state,
        reason="",
    ):
        """Attempt terminal transition. MUST be called
        while holding session._lock.

        Sets state fields and snapshot. Does NOT set
        done_event (caller must do that after releasing
        the lock to avoid deadlock in _check_complete).
        Returns True if transition succeeded.
        """
        if self.terminal_state is not None:
            return False

        self.terminal_state = state
        self.finish_reason = reason
        self.result_snapshot = list(
            self.results
        )
        return True

    def try_finish(self, state, reason=""):
        """First-terminal-wins: only first call succeeds.

        Thread-safe. Acquires session._lock internally.
        Must be called WITHOUT _DISCOVERY_LOCK held.
        """
        with self._lock:
            ok = self._try_finish_locked(
                state,
                reason,
            )
        if ok:
            self.done_event.set()
        return ok

    def _check_complete(self):
        """Check if all pending peripherals resolved.

        MUST be called while holding session._lock.
        Caller must NOT hold _DISCOVERY_LOCK.

        If terminal, sets done_event after releasing lock.
        """
        if self.pending:
            return

        if not self.discovery_closed:
            return

        if self._try_finish_locked(
            'completed',
            'all peripherals resolved',
        ):
            # Release lock before setting event to avoid
            # reentrant deadlock if waiters check state.
            pass

        # Note: done_event.set() is NOT called here
        # because we're still holding _lock. The caller
        # (delegate callbacks) must call try_finish()
        # instead, which handles lock + event correctly.
        # Therefore _check_complete is only used as a
        # helper called inside try_finish or from
        # _mark_peripheral_done which uses the
        # _finish_if_complete pattern.

    def begin_cleanup(self):
        """Phase 1 (under session._lock): snapshot objects,
        set cleanup_started.

        Returns (manager, peripherals_list) or None if
        already started.
        """
        with self._lock:
            if self.cleanup_started:
                return None
            self.cleanup_started = True
            mgr = self.manager
            periph_list = list(
                self.peripherals_snapshot
                .values()
            )

        return mgr, periph_list

    def finish_cleanup(self):
        """Phase 3 (under session._lock): clear references,
        set cleaned, break delegate.session cycle,
        signal cleanup_event.
        """
        with self._lock:
            self.manager = None
            self.peripherals_snapshot = {}
            self.cleaned = True

        # Break circular reference:
        # session → delegate.session
        if self.delegate is not None:
            self.delegate.session = None
        self.delegate = None

        self.cleanup_event.set()


# --- Helper functions outside the delegate class ---
# PyObjC treats methods on NSObject subclasses as ObjC
# selectors; standalone functions avoid this.


def _log_callback_thread(
    session_tag,
    callback_name,
):
    """Log which thread a CoreBluetooth callback runs on.
    Read-only, no side effects on control flow.
    """
    logger.debug(
        "BLE callback: tag=%s cb=%s "
        "thread=%s ident=%s isMain=%s",
        session_tag,
        callback_name,
        threading.current_thread().name,
        threading.get_ident(),
        NSThread.isMainThread(),
    )


def _mark_peripheral_done(
    session,
    peripheral_id,
):
    """Mark a peripheral as done. If all pending resolved
    and discovery is closed, complete the session.

    Caller must hold session._lock.
    Must be called on the BLE queue (callback context).
    Caller must NOT hold _DISCOVERY_LOCK.
    """
    session.pending.discard(peripheral_id)

    # Check completion while still holding lock
    if (
        not session.pending
        and session.discovery_closed
    ):
        session._try_finish_locked(
            'completed',
            'all peripherals resolved',
        )
        session.done_event.set()


def _delegate_record_result(
    session,
    peripheral,
    level,
):
    """Record a battery result for a peripheral.

    Caller must hold session._lock.
    Must be called on the BLE queue (callback context).
    """
    pid = _peripheral_identifier(
        peripheral
    )

    if (
        not pid
        or pid in session.completed
    ):
        return False

    session.completed.add(pid)

    try:
        device = _make_device(
            peripheral,
            level,
            time.time(),
        )
        session.results.append(device)
    except Exception:
        pass

    return True


# Backwards-compatible helpers for existing tests.
# These work with the old Mock delegate pattern
# (delegate.pending, delegate.done, delegate.results).
def _finish(delegate, peripheral):
    """Legacy helper: mark peripheral done on delegate.
    Used by existing unit tests with Mock delegates.
    """
    identifier = _peripheral_identifier(
        peripheral
    )

    if identifier:
        delegate.pending.discard(
            identifier
        )

    if not delegate.pending:
        delegate.done = True


def _record_result(
    delegate,
    peripheral,
    level,
):
    """Legacy helper: record result on delegate.
    Used by existing unit tests with Mock delegates.
    """
    identifier = _peripheral_identifier(
        peripheral
    )

    if (
        not identifier
        or identifier in delegate.completed
    ):
        return

    try:
        device = _make_device(
            peripheral,
            level,
            time.time(),
        )
        delegate.completed.add(
            identifier
        )
        delegate.results.append(
            device
        )
    except Exception:
        pass


class BluetoothBatteryDelegate(
    NSObject
):
    """CoreBluetooth delegate for a single discovery session.

    Holds a back-reference (session) to the _DiscoverySession.
    Cleared during session.finish_cleanup() to break the
    reference cycle: session → delegate.session.
    """

    def init(self):
        self = objc.super(
            BluetoothBatteryDelegate,
            self,
        ).init()

        if self is None:
            return None

        self.session = None
        return self

    # --- CBCentralManagerDelegate ---

    def centralManagerDidUpdateState_(
        self,
        manager,
    ):
        session = self.session
        if session is None:
            return

        _log_callback_thread(
            session.session_tag,
            "centralManagerDidUpdateState",
        )

        with session._lock:
            session.state_received = True

            if (
                manager.state()
                != CoreBluetooth
                .CBManagerStatePoweredOn
            ):
                session._try_finish_locked(
                    'failed',
                    'bluetooth not powered on',
                )
                session.done_event.set()
                return

            session.powered_on = True

            peripherals = (
                manager
                .retrieveConnectedPeripheralsWithServices_(
                    [BATTERY_SERVICE]
                )
                or []
            )

            for peripheral in peripherals:
                pid = _peripheral_identifier(
                    peripheral
                )

                if not pid:
                    continue

                session.peripherals_snapshot[
                    pid
                ] = peripheral
                session.pending.add(pid)
                peripheral.setDelegate_(
                    self
                )
                manager \
                    .connectPeripheral_options_(
                        peripheral,
                        None,
                    )

            if not peripherals:
                session.discovery_closed = True
                session._try_finish_locked(
                    'completed',
                    'no connected peripherals',
                )
                session.done_event.set()

    def centralManager_didConnectPeripheral_(
        self,
        manager,
        peripheral,
    ):
        session = self.session
        if session is None:
            return

        _log_callback_thread(
            session.session_tag,
            "didConnectPeripheral",
        )

        peripheral.setDelegate_(self)
        peripheral.discoverServices_(
            [BATTERY_SERVICE]
        )

    def centralManager_didFailToConnectPeripheral_error_(
        self,
        manager,
        peripheral,
        error,
    ):
        session = self.session
        if session is None:
            return

        pid = _peripheral_identifier(
            peripheral
        )

        with session._lock:
            _mark_peripheral_done(
                session,
                pid,
            )

    def centralManager_didDisconnectPeripheral_error_(
        self,
        manager,
        peripheral,
        error,
    ):
        session = self.session
        if session is None:
            return

        pid = _peripheral_identifier(
            peripheral
        )

        with session._lock:
            _mark_peripheral_done(
                session,
                pid,
            )

    # --- CBPeripheralDelegate ---

    def peripheral_didDiscoverServices_(
        self,
        peripheral,
        error,
    ):
        session = self.session
        if session is None:
            return

        pid = _peripheral_identifier(
            peripheral
        )

        if error is not None:
            with session._lock:
                _mark_peripheral_done(
                    session,
                    pid,
                )
            return

        with session._lock:
            for service in (
                peripheral.services()
                or []
            ):
                if (
                    service.UUID()
                    == BATTERY_SERVICE
                ):
                    peripheral \
                        .discoverCharacteristics_forService_(
                            [BATTERY_LEVEL],
                            service,
                        )
                    return

            _mark_peripheral_done(
                session,
                pid,
            )

    def peripheral_didDiscoverCharacteristicsForService_error_(
        self,
        peripheral,
        service,
        error,
    ):
        session = self.session
        if session is None:
            return

        pid = _peripheral_identifier(
            peripheral
        )

        if error is not None:
            with session._lock:
                _mark_peripheral_done(
                    session,
                    pid,
                )
            return

        with session._lock:
            for characteristic in (
                service.characteristics()
                or []
            ):
                if (
                    characteristic.UUID()
                    == BATTERY_LEVEL
                ):
                    peripheral \
                        .readValueForCharacteristic_(
                            characteristic
                        )
                    return

            _mark_peripheral_done(
                session,
                pid,
            )

    def peripheral_didUpdateValueForCharacteristic_error_(
        self,
        peripheral,
        characteristic,
        error,
    ):
        session = self.session
        if session is None:
            return

        _log_callback_thread(
            session.session_tag,
            "didUpdateValueForCharacteristic",
        )

        pid = _peripheral_identifier(
            peripheral
        )

        with session._lock:
            if error is None:
                level = _parse_battery_value(
                    characteristic.value()
                )

                if level is not None:
                    _delegate_record_result(
                        session,
                        peripheral,
                        level,
                    )

            _mark_peripheral_done(
                session,
                pid,
            )


def discover_batteries(
    timeout=DEFAULT_TIMEOUT,
):
    timeout = _validate_timeout(
        timeout
    )

    # Unified deadline covers entire call.
    deadline = time.monotonic() + timeout
    session_tag = _next_session_tag()

    # Acquire discovery lock to serialize against
    # CBManagerState .busy.
    if not _DISCOVERY_LOCK.acquire(
        blocking=True,
        timeout=timeout,
    ):
        raise BluetoothProviderError(
            "discovery lock busy at entry"
        )

    try:
        return _discover_inner(
            session_tag,
            deadline,
        )
    finally:
        _DISCOVERY_LOCK.release()


def _discover_inner(
    session_tag,
    deadline,
):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise BluetoothProviderError(
            "timeout before CB init"
        )

    session = _DiscoverySession(
        session_tag
    )

    ble_queue = _get_ble_queue()

    delegate = (
        BluetoothBatteryDelegate
        .alloc()
        .init()
    )
    delegate.session = session
    session.delegate = delegate

    manager = (
        CoreBluetooth
        .CBCentralManager
        .alloc()
        .initWithDelegate_queue_(
            delegate,
            ble_queue,
        )
    )
    session.manager = manager

    logger.debug(
        "BLE session %s: manager created, "
        "thread=%s",
        session_tag,
        threading.current_thread().name,
    )

    # Wait for done_event (business completion).
    # threading.Event.wait() — no polling.
    remaining = deadline - time.monotonic()
    if remaining > 0:
        session.done_event.wait(
            timeout=remaining
        )

    # If done_event not set, force timeout.
    if not session.done_event.is_set():
        session.try_finish(
            'timeout',
            'deadline expired',
        )

    # --- Two-phase cleanup ---
    # Phase 1: snapshot objects to clean up
    cleanup_objects = session.begin_cleanup()
    if cleanup_objects is not None:
        mgr, periph_list = cleanup_objects

        # Phase 2: dispatch_async CoreBluetooth calls
        # to the BLE queue (never dispatch_sync to
        # avoid deadlock).
        #
        # cleanup_event is a threading.Event (Python
        # object). PyObjC blocks do NOT strong-hold
        # Python objects, so we must ensure
        # cleanup_event stays alive until the block
        # executes. Since session is still on the
        # stack and finish_cleanup hasn't cleared
        # cleanup_event, it remains reachable.
        # finish_cleanup only clears .manager and
        # .delegate, not .done_event/.cleanup_event.
        cleanup_evt = session.cleanup_event

        def _do_cleanup():
            for p in periph_list:
                try:
                    mgr.cancelPeripheralConnection_(
                        p
                    )
                except Exception:
                    pass
            cleanup_evt.set()

        from dispatch import dispatch_async
        dispatch_async(
            ble_queue,
            _do_cleanup,
        )

        # Phase 3: clear references, break cycles,
        # signal cleanup_event (redundant if dispatch
        # block already set it, but harmless since
        # set() is idempotent).
        session.finish_cleanup()

        # Wait for cleanup_event
        remaining = deadline - time.monotonic()
        if remaining > 0:
            session.cleanup_event.wait(
                timeout=remaining
            )
    else:
        session.finish_cleanup()

    # Determine result
    if (
        session.state_received
        and not session.powered_on
    ):
        raise BluetoothUnavailableError(
            "蓝牙不可用或未开启"
        )

    results = session.result_snapshot or []

    return sorted(
        results,
        key=lambda device: (
            device.name.casefold(),
            device.device_id,
        ),
    )
