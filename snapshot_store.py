#!/usr/bin/env python3

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path

from aggregator import (
    BatterySnapshot,
    ProviderStatus,
)
from models import (
    BatteryDevice,
    VALID_POWER_STATES,
)


SNAPSHOT_SCHEMA_VERSION = 2

DEFAULT_SNAPSHOT_PATH = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Battery Bar"
    / "snapshot.json"
)


class SnapshotStoreError(Exception):
    pass


class SnapshotValidationError(
    SnapshotStoreError
):
    pass


class SnapshotReadError(
    SnapshotStoreError
):
    pass


class SnapshotWriteError(
    SnapshotStoreError
):
    pass


def _validate_finite_timestamp(
    value,
    field_name,
):
    if (
        isinstance(value, bool)
        or not isinstance(
            value,
            (int, float),
        )
    ):
        raise SnapshotValidationError(
            f"{field_name} must be a number"
        )

    result = float(value)
    
    if (
        not math.isfinite(result)
        or result < 0
    ):
        raise SnapshotValidationError(
            f"{field_name} must be finite "
            "and non-negative"
        )
    
    return result


def _validate_non_negative_number(
    value,
    field_name,
):
    if (
        isinstance(value, bool)
        or not isinstance(
            value,
            (int, float),
        )
    ):
        raise SnapshotValidationError(
            f"{field_name} must be a number"
        )

    result = float(value)
    
    if (
        not math.isfinite(result)
        or result < 0
    ):
        raise SnapshotValidationError(
            f"{field_name} must be finite "
            "and non-negative"
        )
    
    return result


def _validate_required_text(
    value,
    field_name,
):
    if not isinstance(value, str):
        raise SnapshotValidationError(
            f"{field_name} must be a string"
        )

    cleaned = " ".join(
        value.split()
    )
    
    if not cleaned:
        raise SnapshotValidationError(
            f"{field_name} must not be empty"
        )
    
    return cleaned


def _validate_optional_text(
    value,
    field_name,
):
    if value is None:
        return None

    if not isinstance(value, str):
        raise SnapshotValidationError(
            f"{field_name} must be "
            "a string or null"
        )
    
    return value


def _validate_bool(
    value,
    field_name,
):
    if not isinstance(value, bool):
        raise SnapshotValidationError(
            f"{field_name} must be a bool"
        )

    return value


def _validate_optional_bool(
    value,
    field_name,
):
    if value is None:
        return None

    return _validate_bool(
        value,
        field_name,
    )


def _validate_level(
    value,
    field_name,
):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
    ):
        raise SnapshotValidationError(
            f"{field_name} must be an integer"
        )

    if not 0 <= value <= 100:
        raise SnapshotValidationError(
            f"{field_name} must be between "
            "0 and 100"
        )
    
    return value


def _validate_power_state(
    value,
    field_name,
):
    if not isinstance(value, str):
        raise SnapshotValidationError(
            f"{field_name} must be a string"
        )

    normalized = " ".join(
        value.split()
    ).casefold()
    
    if normalized not in VALID_POWER_STATES:
        raise SnapshotValidationError(
            f"{field_name} contains an "
            f"unsupported value: {value}"
        )
    
    return normalized


def _validate_device_payload(
    payload,
    index,
):
    field_prefix = f"devices[{index}]"

    if not isinstance(payload, dict):
        raise SnapshotValidationError(
            f"{field_prefix} must be an object"
        )
    
    expected_fields = {
        "device_id",
        "name",
        "category",
        "transport",
        "level",
        "charging",
        "power_state",
        "source",
        "observed_at",
        "category_source",
        "cached",
    }
    
    if set(payload) != expected_fields:
        missing = sorted(
            expected_fields.difference(payload)
        )
        extra = sorted(
            set(payload).difference(
                expected_fields
            )
        )
        details = []
    
        if missing:
            details.append(
                "missing: "
                + ", ".join(missing)
            )
    
        if extra:
            details.append(
                "extra: "
                + ", ".join(extra)
            )
    
        raise SnapshotValidationError(
            f"{field_prefix} has invalid fields"
            + (
                ": " + "; ".join(details)
                if details
                else ""
            )
        )
    
    try:
        return BatteryDevice(
            device_id=(
                _validate_required_text(
                    payload["device_id"],
                    f"{field_prefix}.device_id",
                )
            ),
            name=(
                _validate_required_text(
                    payload["name"],
                    f"{field_prefix}.name",
                )
            ),
            category=(
                _validate_required_text(
                    payload["category"],
                    f"{field_prefix}.category",
                )
            ),
            transport=(
                _validate_required_text(
                    payload["transport"],
                    f"{field_prefix}.transport",
                )
            ),
            level=(
                _validate_level(
                    payload["level"],
                    f"{field_prefix}.level",
                )
            ),
            charging=(
                _validate_optional_bool(
                    payload["charging"],
                    f"{field_prefix}.charging",
                )
            ),
            source=(
                _validate_required_text(
                    payload["source"],
                    f"{field_prefix}.source",
                )
            ),
            observed_at=(
                _validate_finite_timestamp(
                    payload["observed_at"],
                    f"{field_prefix}.observed_at",
                )
            ),
            category_source=(
                _validate_required_text(
                    payload["category_source"],
                    (
                        f"{field_prefix}."
                        "category_source"
                    ),
                )
            ),
            cached=(
                _validate_bool(
                    payload["cached"],
                    f"{field_prefix}.cached",
                )
            ),
            power_state=(
                _validate_power_state(
                    payload["power_state"],
                    f"{field_prefix}.power_state",
                )
            ),
        )
    except SnapshotValidationError:
        raise
    except (
        TypeError,
        ValueError,
    ) as error:
        raise SnapshotValidationError(
            f"{field_prefix} is invalid: "
            f"{error}"
        ) from error


def _validate_provider_status_payload(
    payload,
    index,
):
    field_prefix = (
        f"provider_statuses[{index}]"
    )

    if not isinstance(payload, dict):
        raise SnapshotValidationError(
            f"{field_prefix} must be an object"
        )
    
    expected_fields = {
        "name",
        "succeeded",
        "device_count",
        "duration_seconds",
        "error",
    }
    
    if set(payload) != expected_fields:
        missing = sorted(
            expected_fields.difference(payload)
        )
        extra = sorted(
            set(payload).difference(
                expected_fields
            )
        )
        details = []
    
        if missing:
            details.append(
                "missing: "
                + ", ".join(missing)
            )
    
        if extra:
            details.append(
                "extra: "
                + ", ".join(extra)
            )
    
        raise SnapshotValidationError(
            f"{field_prefix} has invalid fields"
            + (
                ": " + "; ".join(details)
                if details
                else ""
            )
        )
    
    device_count = payload[
        "device_count"
    ]
    
    if (
        isinstance(device_count, bool)
        or not isinstance(
            device_count,
            int,
        )
        or device_count < 0
    ):
        raise SnapshotValidationError(
            f"{field_prefix}.device_count "
            "must be a non-negative integer"
        )
    
    error = _validate_optional_text(
        payload["error"],
        f"{field_prefix}.error",
    )
    
    if (
        error is not None
        and not error.strip()
    ):
        error = None
    
    return ProviderStatus(
        name=_validate_required_text(
            payload["name"],
            f"{field_prefix}.name",
        ),
        succeeded=_validate_bool(
            payload["succeeded"],
            f"{field_prefix}.succeeded",
        ),
        device_count=device_count,
        duration_seconds=(
            _validate_non_negative_number(
                payload["duration_seconds"],
                (
                    f"{field_prefix}."
                    "duration_seconds"
                ),
            )
        ),
        error=error,
    )


def device_to_dict(device):
    if not isinstance(
        device,
        BatteryDevice,
    ):
        raise TypeError(
            "device must be BatteryDevice"
        )

    return {
        "device_id": device.device_id,
        "name": device.name,
        "category": device.category,
        "transport": device.transport,
        "level": device.level,
        "charging": device.charging,
        "power_state": device.power_state,
        "source": device.source,
        "observed_at": device.observed_at,
        "category_source": (
            device.category_source
        ),
        "cached": device.cached,
    }


def provider_status_to_dict(
    status,
):
    if not isinstance(
        status,
        ProviderStatus,
    ):
        raise TypeError(
            "status must be ProviderStatus"
        )

    return {
        "name": status.name,
        "succeeded": status.succeeded,
        "device_count": (
            status.device_count
        ),
        "duration_seconds": (
            status.duration_seconds
        ),
        "error": status.error,
    }


def snapshot_to_dict(snapshot):
    if not isinstance(
        snapshot,
        BatterySnapshot,
    ):
        raise TypeError(
            "snapshot must be BatterySnapshot"
        )

    return {
        "schema_version": (
            SNAPSHOT_SCHEMA_VERSION
        ),
        "updated_at": snapshot.updated_at,
        "devices": [
            device_to_dict(device)
            for device in snapshot.devices
        ],
        "provider_statuses": [
            provider_status_to_dict(
                status
            )
            for status
            in snapshot.provider_statuses
        ],
    }


def snapshot_from_dict(payload):
    if not isinstance(payload, dict):
        raise SnapshotValidationError(
            "snapshot must be an object"
        )

    expected_fields = {
        "schema_version",
        "updated_at",
        "devices",
        "provider_statuses",
    }
    
    if set(payload) != expected_fields:
        missing = sorted(
            expected_fields.difference(payload)
        )
        extra = sorted(
            set(payload).difference(
                expected_fields
            )
        )
        details = []
    
        if missing:
            details.append(
                "missing: "
                + ", ".join(missing)
            )
    
        if extra:
            details.append(
                "extra: "
                + ", ".join(extra)
            )
    
        raise SnapshotValidationError(
            "snapshot has invalid fields"
            + (
                ": " + "; ".join(details)
                if details
                else ""
            )
        )
    
    schema_version = payload[
        "schema_version"
    ]
    
    if (
        isinstance(schema_version, bool)
        or not isinstance(
            schema_version,
            int,
        )
    ):
        raise SnapshotValidationError(
            "schema_version must be "
            "an integer"
        )
    
    if (
        schema_version
        != SNAPSHOT_SCHEMA_VERSION
    ):
        raise SnapshotValidationError(
            "unsupported schema_version: "
            f"{schema_version}"
        )
    
    devices_payload = payload[
        "devices"
    ]
    statuses_payload = payload[
        "provider_statuses"
    ]
    
    if not isinstance(
        devices_payload,
        list,
    ):
        raise SnapshotValidationError(
            "devices must be an array"
        )
    
    if not isinstance(
        statuses_payload,
        list,
    ):
        raise SnapshotValidationError(
            "provider_statuses must be "
            "an array"
        )
    
    devices = tuple(
        _validate_device_payload(
            item,
            index,
        )
        for index, item
        in enumerate(devices_payload)
    )
    
    device_ids = [
        device.device_id
        for device in devices
    ]
    
    if (
        len(device_ids)
        != len(set(device_ids))
    ):
        raise SnapshotValidationError(
            "devices contains duplicate "
            "device_id values"
        )
    
    statuses = tuple(
        _validate_provider_status_payload(
            item,
            index,
        )
        for index, item
        in enumerate(statuses_payload)
    )
    
    status_names = [
        status.name
        for status in statuses
    ]
    
    if (
        len(status_names)
        != len(set(status_names))
    ):
        raise SnapshotValidationError(
            "provider_statuses contains "
            "duplicate names"
        )
    
    return BatterySnapshot(
        updated_at=(
            _validate_finite_timestamp(
                payload["updated_at"],
                "updated_at",
            )
        ),
        devices=devices,
        provider_statuses=statuses,
    )


def serialize_snapshot(snapshot):
    payload = snapshot_to_dict(
        snapshot
    )

    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def deserialize_snapshot(text):
    if not isinstance(text, str):
        raise TypeError(
            "text must be a string"
        )

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise SnapshotValidationError(
            "snapshot contains invalid JSON"
        ) from error
    
    return snapshot_from_dict(
        payload
    )


def _fsync_directory(directory):
    flags = os.O_RDONLY

    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    
    descriptor = None
    
    try:
        descriptor = os.open(
            str(directory),
            flags,
        )
        os.fsync(descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def write_snapshot_atomic(
    snapshot,
    path=DEFAULT_SNAPSHOT_PATH,
):
    target = Path(path).expanduser()
    content = serialize_snapshot(
        snapshot
    )

    try:
        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
    except OSError as error:
        raise SnapshotWriteError(
            "unable to create snapshot "
            f"directory: {error}"
        ) from error
    
    temporary_path = None
    
    try:
        descriptor, temporary_name = (
            tempfile.mkstemp(
                prefix=f".{target.name}.",
                suffix=".tmp",
                dir=str(target.parent),
                text=True,
            )
        )
        temporary_path = Path(
            temporary_name
        )
    
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(
                handle.fileno()
            )
    
        os.replace(
            temporary_path,
            target,
        )
        temporary_path = None
    
        _fsync_directory(
            target.parent
        )
    
    except OSError as error:
        raise SnapshotWriteError(
            f"unable to write snapshot: "
            f"{error}"
        ) from error
    
    finally:
        if (
            temporary_path is not None
            and temporary_path.exists()
        ):
            try:
                temporary_path.unlink()
            except OSError:
                pass
    
    return target


def read_snapshot(
    path=DEFAULT_SNAPSHOT_PATH,
):
    target = Path(path).expanduser()

    try:
        text = target.read_text(
            encoding="utf-8"
        )
    except FileNotFoundError as error:
        raise SnapshotReadError(
            "snapshot file does not exist"
        ) from error
    except OSError as error:
        raise SnapshotReadError(
            f"unable to read snapshot: "
            f"{error}"
        ) from error
    
    try:
        return deserialize_snapshot(
            text
        )
    except SnapshotValidationError:
        raise
    except Exception as error:
        raise SnapshotReadError(
            f"unable to decode snapshot: "
            f"{error}"
        ) from error


def read_snapshot_or_none(
    path=DEFAULT_SNAPSHOT_PATH,
):
    try:
        return read_snapshot(path)
    except SnapshotStoreError:
        return None