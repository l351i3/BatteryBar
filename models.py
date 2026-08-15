#!/usr/bin/env python3

from dataclasses import dataclass, replace
from typing import Optional
import math
import time


CATEGORY_KEYBOARD = "keyboard"
CATEGORY_MOUSE = "mouse"
CATEGORY_MICROPHONE = "microphone"
CATEGORY_HEADPHONES = "headphones"
CATEGORY_SPEAKER = "speaker"
CATEGORY_TRACKPAD = "trackpad"
CATEGORY_STYLUS = "stylus"
CATEGORY_CONTROLLER = "controller"
CATEGORY_OTHER = "other"

VALID_CATEGORIES = frozenset({
    CATEGORY_KEYBOARD,
    CATEGORY_MOUSE,
    CATEGORY_MICROPHONE,
    CATEGORY_HEADPHONES,
    CATEGORY_SPEAKER,
    CATEGORY_TRACKPAD,
    CATEGORY_STYLUS,
    CATEGORY_CONTROLLER,
    CATEGORY_OTHER,
})

TRANSPORT_SYSTEM = "system"
TRANSPORT_BLUETOOTH = "bluetooth"
TRANSPORT_USB = "usb"
TRANSPORT_RECEIVER = "receiver"
TRANSPORT_UNKNOWN = "unknown"

VALID_TRANSPORTS = frozenset({
    TRANSPORT_SYSTEM,
    TRANSPORT_BLUETOOTH,
    TRANSPORT_USB,
    TRANSPORT_RECEIVER,
    TRANSPORT_UNKNOWN,
})

SOURCE_SYSTEM = "system"
SOURCE_SYSTEM_BLUETOOTH = "system_bluetooth"
SOURCE_SYSTEM_ACCESSORY = "system_accessory"
SOURCE_BLE_STANDARD = "ble_standard"
SOURCE_HIDPP = "hidpp"

VALID_SOURCES = frozenset({
    SOURCE_SYSTEM,
    SOURCE_SYSTEM_BLUETOOTH,
    SOURCE_SYSTEM_ACCESSORY,
    SOURCE_BLE_STANDARD,
    SOURCE_HIDPP,
})

POWER_STATE_CHARGING = "charging"
POWER_STATE_CHARGED = "charged"
POWER_STATE_DISCHARGING = "discharging"
POWER_STATE_UNKNOWN = "unknown"

VALID_POWER_STATES = frozenset({
    POWER_STATE_CHARGING,
    POWER_STATE_CHARGED,
    POWER_STATE_DISCHARGING,
    POWER_STATE_UNKNOWN,
})


def _clean_required_text(value, field_name):
    if not isinstance(value, str):
        raise TypeError(
            f"{field_name} must be a string"
        )

    cleaned = " ".join(value.split())
    
    if not cleaned:
        raise ValueError(
            f"{field_name} must not be empty"
        )
    
    return cleaned


def _validate_timestamp(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
    ):
        raise TypeError(
            "observed_at must be a number"
        )

    timestamp = float(value)
    
    if (
        not math.isfinite(timestamp)
        or timestamp < 0
    ):
        raise ValueError(
            "observed_at must be finite "
            "and non-negative"
        )
    
    return timestamp


def power_state_from_charging(charging):
    if charging is True:
        return POWER_STATE_CHARGING

    if charging is False:
        return POWER_STATE_DISCHARGING
    
    if charging is None:
        return POWER_STATE_UNKNOWN
    
    raise TypeError(
        "charging must be bool or None"
    )


def charging_from_power_state(power_state):
    if power_state in {
        POWER_STATE_CHARGING,
        POWER_STATE_CHARGED,
    }:
        return True

    if power_state == POWER_STATE_DISCHARGING:
        return False
    
    if power_state == POWER_STATE_UNKNOWN:
        return None
    
    raise ValueError(
        f"unsupported power state: {power_state}"
    )


def power_state_label(power_state):
    labels = {
        POWER_STATE_CHARGING: "充电中",
        POWER_STATE_CHARGED: "已充满",
        POWER_STATE_DISCHARGING: "",
        POWER_STATE_UNKNOWN: "",
    }

    if power_state not in labels:
        raise ValueError(
            f"unsupported power state: {power_state}"
        )
    
    return labels[power_state]


@dataclass(frozen=True)
class BatteryDevice:
    device_id: str
    name: str
    category: str
    transport: str
    level: int
    charging: Optional[bool]
    source: str
    observed_at: float
    category_source: str
    cached: bool = False
    power_state: Optional[str] = None

    def __post_init__(self):
        object.__setattr__(
            self,
            "device_id",
            _clean_required_text(
                self.device_id,
                "device_id",
            ),
        )
    
        object.__setattr__(
            self,
            "name",
            _clean_required_text(
                self.name,
                "name",
            ),
        )
    
        if self.category not in VALID_CATEGORIES:
            raise ValueError(
                f"unsupported category: "
                f"{self.category}"
            )
    
        if self.transport not in VALID_TRANSPORTS:
            raise ValueError(
                f"unsupported transport: "
                f"{self.transport}"
            )
    
        if self.source not in VALID_SOURCES:
            raise ValueError(
                f"unsupported source: "
                f"{self.source}"
            )
    
        if (
            isinstance(self.level, bool)
            or not isinstance(self.level, int)
        ):
            raise TypeError(
                "level must be an integer"
            )
    
        if not 0 <= self.level <= 100:
            raise ValueError(
                "level must be between 0 and 100"
            )
    
        if (
            self.charging is not None
            and not isinstance(
                self.charging,
                bool,
            )
        ):
            raise TypeError(
                "charging must be bool or None"
            )
    
        if self.power_state is None:
            normalized_power_state = (
                power_state_from_charging(
                    self.charging
                )
            )
        else:
            if not isinstance(
                self.power_state,
                str,
            ):
                raise TypeError(
                    "power_state must be "
                    "a string or None"
                )
    
            normalized_power_state = (
                " ".join(
                    self.power_state.split()
                ).casefold()
            )
    
            if (
                normalized_power_state
                not in VALID_POWER_STATES
            ):
                raise ValueError(
                    "unsupported power_state: "
                    f"{self.power_state}"
                )
    
            expected_charging = (
                charging_from_power_state(
                    normalized_power_state
                )
            )
    
            if self.charging != expected_charging:
                raise ValueError(
                    "charging is inconsistent "
                    "with power_state"
                )
    
        object.__setattr__(
            self,
            "power_state",
            normalized_power_state,
        )
    
        object.__setattr__(
            self,
            "observed_at",
            _validate_timestamp(
                self.observed_at
            ),
        )
    
        object.__setattr__(
            self,
            "category_source",
            _clean_required_text(
                self.category_source,
                "category_source",
            ),
        )
    
        if not isinstance(self.cached, bool):
            raise TypeError(
                "cached must be a bool"
            )
    
    def with_cached(self, cached=True):
        if not isinstance(cached, bool):
            raise TypeError(
                "cached must be a bool"
            )
    
        return replace(
            self,
            cached=cached,
        )
    
    def age_seconds(self, now=None):
        if now is None:
            now = time.time()
    
        current_time = _validate_timestamp(now)
    
        return max(
            0.0,
            current_time - self.observed_at,
        )