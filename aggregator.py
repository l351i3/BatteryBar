#!/usr/bin/env python3

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from classifier import category_sort_key
from models import (
    BatteryDevice,
    SOURCE_BLE_STANDARD,
    SOURCE_HIDPP,
    SOURCE_SYSTEM_ACCESSORY,
    SOURCE_SYSTEM_BLUETOOTH,
)


DEFAULT_CACHE_EXPIRY_SECONDS = 600.0

SOURCE_PRIORITY = {
    SOURCE_HIDPP: 400,
    SOURCE_BLE_STANDARD: 300,
    SOURCE_SYSTEM_BLUETOOTH: 200,
    SOURCE_SYSTEM_ACCESSORY: 100,
}

COMPONENT_SUFFIXES = (
    ":left",
    ":right",
    ":case",
)

COMPONENT_NAME_SUFFIXES = (
    " · 左耳",
    " · 右耳",
    " · 电池盒",
)


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    discover: Callable[[], list[BatteryDevice]]


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    succeeded: bool
    device_count: int
    duration_seconds: float
    error: Optional[str]


@dataclass(frozen=True)
class BatterySnapshot:
    updated_at: float
    devices: tuple[BatteryDevice, ...]
    provider_statuses: tuple[ProviderStatus, ...]


@dataclass
class CacheEntry:
    device: BatteryDevice
    last_success_at: float


def _validate_timestamp(value, field_name):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
    ):
        raise TypeError(
            f"{field_name} must be a number"
        )

    result = float(value)
    
    if (
        not math.isfinite(result)
        or result < 0
    ):
        raise ValueError(
            f"{field_name} must be finite "
            "and non-negative"
        )
    
    return result


def _validate_expiry(value):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
    ):
        raise TypeError(
            "cache_expiry_seconds must be a number"
        )

    result = float(value)
    
    if (
        not math.isfinite(result)
        or result <= 0
    ):
        raise ValueError(
            "cache_expiry_seconds must be "
            "finite and positive"
        )
    
    return result


def _normalize_name(value):
    return " ".join(
        str(value).casefold().split()
    )


def _base_device_id(device_id):
    for suffix in COMPONENT_SUFFIXES:
        if device_id.endswith(suffix):
            return device_id[:-len(suffix)]

    return device_id


def _source_priority(device):
    return SOURCE_PRIORITY.get(
        device.source,
        0,
    )


def _component_base_name(name):
    normalized = _normalize_name(name)

    for suffix in COMPONENT_NAME_SUFFIXES:
        normalized_suffix = _normalize_name(
            suffix
        )
    
        if normalized.endswith(
            normalized_suffix
        ):
            return normalized[
                :-len(normalized_suffix)
            ].rstrip()
    
    return normalized


def _component_name(device):
    for component in (
        "left",
        "right",
        "case",
    ):
        if device.device_id.endswith(
            f":{component}"
        ):
            return component

    return "main"


def _device_sort_key(device):
    component_order = {
        "left": 0,
        "right": 1,
        "case": 2,
        "main": 3,
    }

    component = _component_name(
        device
    )
    
    return (
        category_sort_key(device.category),
        _component_base_name(device.name),
        component_order[component],
        _normalize_name(device.name),
        device.device_id,
    )


def _prefer(first, second):
    """
    返回两条冲突记录中质量更高的一条。

    优先级：
    1. 非缓存值优先；
    2. 来源优先级更高；
    3. 观测时间更新；
    4. ID 和名称作为确定性收尾。
    """
    # 智能补充：如果高优先级数据的 charging 状态丢失（None），但低优先级数据拥有明确的充电状态，
    # 我们应在比较并确定保留高优先级前，先将低优先级的 charging 状态补充到高优先级数据上。
    if first.charging is None and second.charging is not None:
        first = BatteryDevice(
            device_id=first.device_id,
            name=first.name,
            category=first.category,
            transport=first.transport,
            level=first.level,
            charging=second.charging,
            source=first.source,
            observed_at=first.observed_at,
            category_source=first.category_source,
            cached=first.cached,
            power_state=second.power_state if second.power_state in ("charging", "charged") else first.power_state
        )
    elif second.charging is None and first.charging is not None:
        second = BatteryDevice(
            device_id=second.device_id,
            name=second.name,
            category=second.category,
            transport=second.transport,
            level=second.level,
            charging=first.charging,
            source=second.source,
            observed_at=second.observed_at,
            category_source=second.category_source,
            cached=second.cached,
            power_state=first.power_state if first.power_state in ("charging", "charged") else second.power_state
        )
    
    first_key = (
        not first.cached,
        _source_priority(first),
        first.observed_at,
        first.device_id,
        first.name,
    )
    second_key = (
        not second.cached,
        _source_priority(second),
        second.observed_at,
        second.device_id,
        second.name,
    )
    
    if first_key >= second_key:
        return first
    
    return second


def deduplicate_devices(devices):
    """
    对设备记录做保守去重。

    第一层按相同 device_id 去重。
    
    第二层仅对没有分部件后缀的设备，
    按规范化名称和类别去重。
    
    AirPods 左耳、右耳和电池盒记录
    会分别保留。
    """
    by_id = {}
    
    for device in devices:
        if not isinstance(
            device,
            BatteryDevice,
        ):
            raise TypeError(
                "devices must contain "
                "BatteryDevice"
            )
    
        existing = by_id.get(
            device.device_id
        )
    
        if existing is None:
            by_id[device.device_id] = (
                device
            )
        else:
            by_id[device.device_id] = (
                _prefer(
                    existing,
                    device,
                )
            )
    
    id_deduplicated = list(
        by_id.values()
    )
    
    component_base_ids = {
        _base_device_id(
            device.device_id
        )
        for device in id_deduplicated
        if (
            _base_device_id(
                device.device_id
            )
            != device.device_id
        )
    }
    
    by_name = {}
    component_devices = []
    
    for device in id_deduplicated:
        base_id = _base_device_id(
            device.device_id
        )
    
        if base_id != device.device_id:
            component_devices.append(
                device
            )
            continue
    
        if (
            device.device_id
            in component_base_ids
        ):
            continue
    
        name_key = (
            _normalize_name(device.name),
            device.category,
        )
    
        existing = by_name.get(
            name_key
        )
    
        if existing is None:
            by_name[name_key] = device
        else:
            by_name[name_key] = (
                _prefer(
                    existing,
                    device,
                )
            )
    
    results = (
        component_devices
        + list(by_name.values())
    )
    
    return sorted(
        results,
        key=_device_sort_key,
    )


class BatteryAggregator:
    def __init__(
        self,
        providers: Sequence[ProviderSpec],
        cache_expiry_seconds=(
            DEFAULT_CACHE_EXPIRY_SECONDS
        ),
        clock=time.time,
        monotonic=time.monotonic,
    ):
        if isinstance(
            providers,
            (str, bytes),
        ):
            raise TypeError(
                "providers must be a sequence "
                "of ProviderSpec"
            )

        validated_providers = []
    
        for provider in providers:
            if not isinstance(
                provider,
                ProviderSpec,
            ):
                raise TypeError(
                    "providers must contain "
                    "ProviderSpec"
                )
    
            validated_providers.append(
                provider
            )
    
        if not callable(clock):
            raise TypeError(
                "clock must be callable"
            )
    
        if not callable(monotonic):
            raise TypeError(
                "monotonic must be callable"
            )
    
        self.providers = tuple(
            validated_providers
        )
        self.cache_expiry_seconds = (
            _validate_expiry(
                cache_expiry_seconds
            )
        )
        self.clock = clock
        self.monotonic = monotonic
        self.cache = {}
    
    def _run_provider(self, provider):
        started = _validate_timestamp(
            self.monotonic(),
            "monotonic result",
        )
    
        try:
            devices = provider.discover()
    
            if devices is None:
                devices = []
    
            devices = list(devices)
    
            for device in devices:
                if not isinstance(
                    device,
                    BatteryDevice,
                ):
                    raise TypeError(
                        f"{provider.name} returned "
                        "a non-BatteryDevice value"
                    )
    
            finished = _validate_timestamp(
                self.monotonic(),
                "monotonic result",
            )
    
            status = ProviderStatus(
                name=provider.name,
                succeeded=True,
                device_count=len(devices),
                duration_seconds=max(
                    0.0,
                    finished - started,
                ),
                error=None,
            )
    
            return devices, status
    
        except Exception as error:
            try:
                finished = (
                    _validate_timestamp(
                        self.monotonic(),
                        "monotonic result",
                    )
                )
                duration = max(
                    0.0,
                    finished - started,
                )
            except Exception:
                duration = 0.0
    
            status = ProviderStatus(
                name=provider.name,
                succeeded=False,
                device_count=0,
                duration_seconds=duration,
                error=(
                    f"{type(error).__name__}: "
                    f"{error}"
                ),
            )
    
            return [], status
    
    def _update_cache(
        self,
        fresh_devices,
        now,
    ):
        # 建立当前真正活跃的设备 ID 集合
        # 只有真正连接（非缓存）的设备才允许刷新时间戳
        for device in fresh_devices:
            # 只有当设备不是从缓存中读出来的，才刷新它的“最后成功时间”
            if not getattr(device, 'cached', False):
                self.cache[device.device_id] = CacheEntry(
                    device=device.with_cached(False),
                    last_success_at=now,
                )
            
        # 强制清理：如果一个设备在 cache 中，但它已经很久没在 fresh_devices 中以“非缓存”身份出现
            
        expired = [
            device_id for device_id, entry in self.cache.items()
            if now - entry.last_success_at > self.cache_expiry_seconds
        ]
    
        for device_id in expired:
            del self.cache[device_id]

    def _visible_devices(
        self,
        fresh_devices,
        now,
    ):
        fresh_by_id = {
            device.device_id: device
            for device in fresh_devices
        }
    
        visible = list(
            fresh_by_id.values()
        )
    
        for (
            device_id,
            entry,
        ) in self.cache.items():
            if device_id in fresh_by_id:
                continue
    
            age = (
                now
                - entry.last_success_at
            )
    
            if (
                age
                <= self.cache_expiry_seconds
            ):
                visible.append(
                    entry.device.with_cached(
                        True
                    )
                )
    
        return deduplicate_devices(
            visible
        )
    
    def refresh(self):
        now = _validate_timestamp(
            self.clock(),
            "clock result",
        )
    
        all_devices = []
        statuses = []
    
        for provider in self.providers:
            devices, status = (
                self._run_provider(
                    provider
                )
            )
    
            all_devices.extend(
                devices
            )
            statuses.append(
                status
            )
    
        fresh_devices = (
            deduplicate_devices(
                all_devices
            )
        )
    
        self._update_cache(
            fresh_devices,
            now,
        )
    
        visible_devices = (
            self._visible_devices(
                fresh_devices,
                now,
            )
        )
    
        return BatterySnapshot(
            updated_at=now,
            devices=tuple(
                visible_devices
            ),
            provider_statuses=tuple(
                statuses
            ),
        )