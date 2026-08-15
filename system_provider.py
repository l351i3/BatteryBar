#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional

from classifier import (
    DeviceMetadata,
    classify_device,
)
from models import (
    BatteryDevice,
    CATEGORY_HEADPHONES,
    POWER_STATE_CHARGED,
    POWER_STATE_CHARGING,
    POWER_STATE_DISCHARGING,
    POWER_STATE_UNKNOWN,
    SOURCE_SYSTEM_ACCESSORY,
    SOURCE_SYSTEM_BLUETOOTH,
    TRANSPORT_BLUETOOTH,
    charging_from_power_state,
)


PMSET_PATH = "/usr/bin/pmset"
SYSTEM_PROFILER_PATH = (
    "/usr/sbin/system_profiler"
)

DEFAULT_TIMEOUT = 30.0

# Cache for system_profiler SPBluetoothDataType JSON.
# Only the expensive system_profiler call is cached;
# pmset -g accps runs fresh every time.
CACHE_TTL_SECONDS = 10.0
MAX_STALE_AGE_SECONDS = 60.0

ACCESSORY_PATTERN = re.compile(
    r"^\s*-\s*"
    r"(?P<name>.*?)"
    r"\s+\(id=(?P<system_id>\d+)\)"
    r"\s+(?P<level>\d+)%;"
    r"\s*(?P<state>[^\s;]+)"
    r".*?\bpresent:\s*"
    r"(?P<present>true|false)\b",
    re.IGNORECASE,
)

COMPONENT_LABELS = {
    "main": "",
    "left": "左耳",
    "right": "右耳",
    "case": "电池盒",
}


class SystemProviderError(
    Exception
):
    pass


class SystemCommandError(
    SystemProviderError
):
    pass


class SystemCommandTimeout(
    SystemProviderError
):
    pass


@dataclass(frozen=True)
class BluetoothInventoryRecord:
    name: str
    address: str
    connected: bool
    minor_type: Optional[str]
    vendor_id: Optional[str]
    product_id: Optional[str]
    battery_main: Optional[int]
    battery_left: Optional[int]
    battery_right: Optional[int]
    battery_case: Optional[int]


@dataclass(frozen=True)
class AccessoryPowerRecord:
    system_id: str
    name: str
    level: int
    state: str
    present: bool


# --- system_profiler JSON cache ---

_CACHE_LOCK = threading.Lock()
_cache_text = None      # Raw JSON text from system_profiler
_cache_valid_at = 0.0    # monotonic clock when cache was stored
_cache_clock = time.monotonic  # Injectable for testing


def _validate_bluetooth_json(text):
    """Validate system_profiler JSON beyond json.loads.

    Returns parsed dict on success, None on failure.
    A valid response must be a dict with key
    'SPBluetoothDataType' whose value is a list.
    """
    if not isinstance(text, str):
        return None

    try:
        data = json.loads(text)
    except (
        json.JSONDecodeError,
        ValueError,
    ):
        return None

    if not isinstance(data, dict):
        return None

    bt = data.get("SPBluetoothDataType")
    if not isinstance(bt, list):
        return None

    return data


def _get_bluetooth_profiler_json(timeout):
    """Get system_profiler SPBluetoothDataType JSON,
    using cache when fresh.

    Single-flight: concurrent calls within the TTL
    window share the same cached result.

    Stale-on-error: if system_profiler fails, serve
    stale cache if within MAX_STALE_AGE.

    Returns (json_text, is_stale) tuple.
    json_text is None if no cache available and
    command fails.
    """
    global _cache_text, _cache_valid_at
    now = _cache_clock()
    cache_age = now - _cache_valid_at

    with _CACHE_LOCK:
        if _cache_text is not None:
            if cache_age <= CACHE_TTL_SECONDS:
                return _cache_text, False

            if cache_age <= MAX_STALE_AGE_SECONDS:
                # Within stale window — try fresh,
                # fall back to stale on error.
                pass
            # Beyond MAX_STALE_AGE — stale expired.
        # else: no cache at all

    # Attempt fresh system_profiler call.
    try:
        fresh_text = _run_command(
            [
                SYSTEM_PROFILER_PATH,
                "SPBluetoothDataType",
                "-json",
            ],
            timeout=timeout,
        )

        # Validate before caching.
        if (
            _validate_bluetooth_json(fresh_text)
            is not None
        ):
            with _CACHE_LOCK:
                _cache_text = fresh_text
                _cache_valid_at = _cache_clock()
            return fresh_text, False
        else:
            # Malformed — don't overwrite valid cache.
            pass
    except (
        SystemCommandError,
        SystemCommandTimeout,
    ):
        pass

    # Fresh failed; try stale.
    with _CACHE_LOCK:
        stale_text = _cache_text
        stale_valid_at = _cache_valid_at

    if stale_text is not None:
        age = _cache_clock() - stale_valid_at
        if age <= MAX_STALE_AGE_SECONDS:
            return stale_text, True

    return None, False


def _reset_cache():
    """Clear the system_profiler JSON cache.
    For testing only.
    """
    with _CACHE_LOCK:
        global _cache_text, _cache_valid_at
        _cache_text = None
        _cache_valid_at = 0.0


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


def _clean_text(value):
    if value is None:
        return ""

    return " ".join(
        str(value).split()
    )


def _normalize_name(value):
    return _clean_text(
        value
    ).casefold()


def _normalize_address(value):
    cleaned = _clean_text(
        value
    ).lower()

    return cleaned.replace(
        ":",
        "-",
    )


def _parse_percentage(value):
    if value is None:
        return None

    if isinstance(value, bool):
        return None
    
    if isinstance(value, int):
        level = value
    else:
        match = re.fullmatch(
            r"\s*(\d{1,3})\s*%\s*",
            str(value),
        )
    
        if match is None:
            return None
    
        level = int(
            match.group(1)
        )
    
    if not 0 <= level <= 100:
        return None
    
    return level


def _power_state_from_text(state):
    normalized = _normalize_name(
        state
    )

    if normalized == "charging":
        return POWER_STATE_CHARGING
    
    if normalized == "charged":
        return POWER_STATE_CHARGED
    
    if normalized == "discharging":
        return POWER_STATE_DISCHARGING
    
    return POWER_STATE_UNKNOWN


def _run_command(
    command,
    timeout,
):
    timeout = _validate_timeout(
        timeout
    )

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise SystemCommandTimeout(
            "command timed out after "
            f"{timeout} seconds"
        ) from error
    except OSError as error:
        raise SystemCommandError(
            "unable to execute command: "
            f"{error}"
        ) from error
    
    if completed.returncode != 0:
        detail = _clean_text(
            completed.stderr
        )
    
        raise SystemCommandError(
            detail
            or (
                "command failed with "
                "exit code "
                f"{completed.returncode}"
            )
        )
    
    return completed.stdout


def parse_bluetooth_inventory(
    payload,
):
    if isinstance(payload, str):
        try:
            data = json.loads(
                payload
            )
        except json.JSONDecodeError as error:
            raise SystemProviderError(
                "invalid Bluetooth JSON"
            ) from error
    elif isinstance(payload, dict):
        data = payload
    else:
        raise TypeError(
            "payload must be JSON text "
            "or a dictionary"
        )

    results = []
    
    for section in data.get(
        "SPBluetoothDataType",
        [],
    ):
        if not isinstance(
            section,
            dict,
        ):
            continue
    
        for (
            section_key,
            connected,
        ) in (
            (
                "device_connected",
                True,
            ),
            (
                "device_not_connected",
                False,
            ),
        ):
            groups = section.get(
                section_key,
                [],
            )
    
            if not isinstance(
                groups,
                list,
            ):
                continue
    
            for group in groups:
                if not isinstance(
                    group,
                    dict,
                ):
                    continue
    
                for (
                    name,
                    properties,
                ) in group.items():
                    if not isinstance(
                        properties,
                        dict,
                    ):
                        continue
    
                    cleaned_name = (
                        _clean_text(name)
                    )
                    address = _clean_text(
                        properties.get(
                            "device_address"
                        )
                    )
    
                    if (
                        not cleaned_name
                        or not address
                    ):
                        continue
    
                    results.append(
                        BluetoothInventoryRecord(
                            name=cleaned_name,
                            address=address,
                            connected=connected,
                            minor_type=(
                                _clean_text(
                                    properties.get(
                                        "device_minorType"
                                    )
                                )
                                or None
                            ),
                            vendor_id=(
                                _clean_text(
                                    properties.get(
                                        "device_vendorID"
                                    )
                                )
                                or None
                            ),
                            product_id=(
                                _clean_text(
                                    properties.get(
                                        "device_productID"
                                    )
                                )
                                or None
                            ),
                            battery_main=(
                                _parse_percentage(
                                    properties.get(
                                        "device_batteryLevel"
                                    )
                                )
                            ),
                            battery_left=(
                                _parse_percentage(
                                    properties.get(
                                        "device_batteryLevelLeft"
                                    )
                                )
                            ),
                            battery_right=(
                                _parse_percentage(
                                    properties.get(
                                        "device_batteryLevelRight"
                                    )
                                )
                            ),
                            battery_case=(
                                _parse_percentage(
                                    properties.get(
                                        "device_batteryLevelCase"
                                    )
                                )
                            ),
                        )
                    )
    
    return results


def parse_accessory_power(text):
    if not isinstance(text, str):
        raise TypeError(
            "text must be a string"
        )

    results = []
    
    for line in text.splitlines():
        match = (
            ACCESSORY_PATTERN
            .match(line)
        )
    
        if match is None:
            continue
    
        level = int(
            match.group("level")
        )
    
        if not 0 <= level <= 100:
            continue
    
        results.append(
            AccessoryPowerRecord(
                system_id=match.group(
                    "system_id"
                ),
                name=_clean_text(
                    match.group("name")
                ),
                level=level,
                state=_normalize_name(
                    match.group("state")
                ),
                present=(
                    match.group(
                        "present"
                    ).casefold()
                    == "true"
                ),
            )
        )
    
    return results


def _inventory_index(records):
    index = {}

    for record in records:
        normalized = _normalize_name(
            record.name
        )
    
        if not normalized:
            continue
    
        index.setdefault(
            normalized,
            [],
        ).append(record)
    
    return index


def _stable_name_id(name):
    normalized = _normalize_name(
        name
    )
    digest = hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()[:16]

    return (
        f"system-name:{digest}"
    )


def _bluetooth_base_id(
    record,
):
    address = _normalize_address(
        record.address
    )

    return (
        "system-bluetooth:"
        f"{address}"
    )


def _component_device(
    record,
    component,
    level,
    observed_at,
):
    base_id = _bluetooth_base_id(
        record
    )
    suffix = (
        ""
        if component == "main"
        else f":{component}"
    )

    label = (
        COMPONENT_LABELS[
            component
        ]
    )
    name = (
        record.name
        if not label
        else (
            f"{record.name} · "
            f"{label}"
        )
    )
    
    classification = classify_device(
        DeviceMetadata(
            name=record.name,
            system_category=(
                record.minor_type
            ),
        )
    )
    
    category = (
        classification.category
    )
    
    if component == "case":
        category = (
            CATEGORY_HEADPHONES
        )
    
    return BatteryDevice(
        device_id=base_id + suffix,
        name=name,
        category=category,
        transport=(
            TRANSPORT_BLUETOOTH
        ),
        level=level,
        charging=None,
        source=(
            SOURCE_SYSTEM_BLUETOOTH
        ),
        observed_at=observed_at,
        category_source=(
            classification.source
            if component != "case"
            else "component_group"
        ),
        power_state=(
            POWER_STATE_UNKNOWN
        ),
    )


def bluetooth_inventory_to_devices(
    records,
    observed_at=None,
):
    if observed_at is None:
        observed_at = time.time()

    devices = []
    
    for record in records:
        if not isinstance(
            record,
            BluetoothInventoryRecord,
        ):
            raise TypeError(
                "records must contain "
                "BluetoothInventoryRecord"
            )
    
        components = (
            (
                "main",
                record.battery_main,
            ),
            (
                "left",
                record.battery_left,
            ),
            (
                "right",
                record.battery_right,
            ),
            (
                "case",
                record.battery_case,
            ),
        )
    
        for (
            component,
            level,
        ) in components:
            if level is None:
                continue
    
            devices.append(
                _component_device(
                    record,
                    component,
                    level,
                    observed_at,
                )
            )
    
    return devices


def _effective_power_state(
    level,
    power_state,
):
    """pmset 在设备充满后仍报 charging（0:00 remaining）。

    电量已到 100% 时充电实际已停止，视为非充电状态（discharging），
    避免无端显示「已充满」标签——用户看到 100% 就知道是满的，
    不需要额外标签暗示设备仍在充电回路中。
    """
    if (
        power_state
        == POWER_STATE_CHARGING
        and level >= 100
    ):
        return POWER_STATE_DISCHARGING

    return power_state


def _anonymous_accessory_devices(
    records,
    bluetooth_inventory,
    observed_at,
):
    """将 pmset -g accps 的匿名条目（名称为空）转为组件设备记录。

    真机实测：AirPods 放入充电盒时，pmset 会输出不带名称的条目：

        - (id=350361794)  91%; discharging present: true        ← 充电盒
        - (id=350361805)  100%; charging; 0:00 remaining ...     ← 耳机（充电中）

    这些条目带有真实的充电状态，但没有名称，无法走名称匹配。
    这里改用「电量百分比」与蓝牙清单中多组件设备（左耳/右耳/电池盒）
    匹配，把充电状态绑定到对应组件 ID（base_id:left 等），
    供 _deduplicate_system_devices 与 system_profiler 的组件记录合并。

    匹配约束（保守）：
    - 仅考虑带组件电量的蓝牙设备（AirPods 类）；
    - 电量必须精确相等；
    - 匹配必须唯一指向同一台物理设备，跨设备歧义时放弃；
    - charging/charged 记录优先于 discharging 应用
      （左右耳电量相同时会匹配同一批组件，先应用充电状态，
      下游"先到先得 + 仅补 None"合并可避免 discharging 抢占）。
    """
    multi_component = [
        record
        for record in bluetooth_inventory
        if isinstance(
            record,
            BluetoothInventoryRecord,
        )
        and (
            record.battery_left
            is not None
            or record.battery_right
            is not None
            or record.battery_case
            is not None
        )
    ]

    if not multi_component or not records:
        return []

    def _state_priority(item):
        state = _normalize_name(
            item.state
        )
        if state in (
            "charging",
            "charged",
        ):
            return 0
        return 1

    ordered = sorted(
        records,
        key=_state_priority,
    )

    devices = []
    claimed = set()

    for record in ordered:
        matches = []

        for inv_record in (
            multi_component
        ):
            base_id = (
                _bluetooth_base_id(
                    inv_record
                )
            )

            for (
                component,
                level,
            ) in (
                (
                    "left",
                    inv_record
                    .battery_left,
                ),
                (
                    "right",
                    inv_record
                    .battery_right,
                ),
                (
                    "case",
                    inv_record
                    .battery_case,
                ),
            ):
                if (
                    level is None
                    or level != record.level
                ):
                    continue

                device_id = (
                    f"{base_id}:"
                    f"{component}"
                )

                if (
                    device_id
                    in claimed
                ):
                    continue

                matches.append(
                    (
                        inv_record,
                        component,
                    )
                )

        if not matches:
            continue

        addresses = {
            _normalize_address(
                match[0].address
            )
            for match in matches
        }

        if len(addresses) != 1:
            # 跨设备歧义，放弃绑定
            continue

        inv_record = (
            matches[0][0]
        )
        base_id = (
            _bluetooth_base_id(
                inv_record
            )
        )
        power_state = (
            _effective_power_state(
                record.level,
                _power_state_from_text(
                    record.state
                ),
            )
        )
        charging = (
            charging_from_power_state(
                power_state
            )
        )

        for _, component in matches:
            label = (
                COMPONENT_LABELS[
                    component
                ]
            )
            component_id = (
                f"{base_id}:"
                f"{component}"
            )
            claimed.add(
                component_id
            )

            devices.append(
                BatteryDevice(
                    device_id=(
                        component_id
                    ),
                    name=(
                        f"{inv_record.name}"
                        f" · {label}"
                    ),
                    category=(
                        CATEGORY_HEADPHONES
                    ),
                    transport=(
                        TRANSPORT_BLUETOOTH
                    ),
                    level=record.level,
                    charging=charging,
                    source=(
                        SOURCE_SYSTEM_ACCESSORY
                    ),
                    observed_at=(
                        observed_at
                    ),
                    category_source=(
                        "component_group"
                    ),
                    power_state=(
                        power_state
                    ),
                )
            )

    return devices


def accessory_power_to_devices(
    records,
    bluetooth_inventory,
    observed_at=None,
):
    if observed_at is None:
        observed_at = time.time()

    inventory_index = (
        _inventory_index(
            bluetooth_inventory
        )
    )
    devices = []
    anonymous_records = []

    for record in records:
        if not isinstance(
            record,
            AccessoryPowerRecord,
        ):
            raise TypeError(
                "records must contain "
                "AccessoryPowerRecord"
            )

        if not record.present:
            continue

        if not record.name:
            # AirPods 等设备在 pmset 中是匿名条目（名称为空），
            # 但带有真实的充电状态。收集起来走电量匹配，
            # 不能直接丢弃（否则充电状态永远无法传递）。
            anonymous_records.append(
                record
            )
            continue
    
        # 智能匹配：如果设备名称以 " Case" 结尾（比如 "User的AirPods Case"），
        # 往往对应着蓝牙列表里的根设备名称（"User的AirPods"）。
        # 我们在这里尝试寻找对应的蓝牙基础设备。
        lookup_name = record.name
        is_case_record = False
        if lookup_name.endswith(" Case"):
            lookup_name = lookup_name[:-5]  # 去掉最后的 " Case" 长度（5个字符）
            is_case_record = True

        normalized_name = (
            _normalize_name(
                lookup_name
            )
        )
        candidates = (
            inventory_index.get(
                normalized_name,
                [],
            )
        )
    
        # Smart Matching Logic: If exact match fails (or matches an inactive/disconnected device),
        # look for active or connected devices whose name is a superset containing the lookup name
        # (e.g., "User的AirPods 4" contains "User的AirPods").
        if not candidates or (len(candidates) == 1 and not candidates[0].connected):
            superset_matches = []
            for inv_name, records in inventory_index.items():
                if normalized_name in inv_name:
                    for r in records:
                        superset_matches.append(r)
            if superset_matches:
                # Prioritize by matching length (most specific)
                superset_matches.sort(key=lambda x: len(x.name), reverse=True)
                candidates = [superset_matches[0]]

        if len(candidates) == 1:
            inventory_record = (
                candidates[0]
            )
            base_id = (
                _bluetooth_base_id(
                    inventory_record
                )
            )
            # 如果是专门的 Case 充电盒记录，我们将 ID 定位为 base_id:case，以便与 system_profiler 解析出的组件 ID 完美吻合并直接合并！
            if is_case_record:
                device_id = f"{base_id}:case"
            else:
                device_id = base_id
            minor_type = (
                inventory_record
                .minor_type
            )
        else:
            device_id = (
                _stable_name_id(
                    record.name
                )
            )
            minor_type = None
    
        classification = (
            classify_device(
                DeviceMetadata(
                    name=record.name,
                    system_category=(
                        minor_type
                    ),
                )
            )
        )
    
        power_state = (
            _effective_power_state(
                record.level,
                _power_state_from_text(
                    record.state
                ),
            )
        )

        devices.append(
            BatteryDevice(
                device_id=device_id,
                name=record.name,
                category=(
                    classification.category
                ),
                transport=(
                    TRANSPORT_BLUETOOTH
                ),
                level=record.level,
                charging=(
                    charging_from_power_state(
                        power_state
                    )
                ),
                source=(
                    SOURCE_SYSTEM_ACCESSORY
                ),
                observed_at=(
                    observed_at
                ),
                category_source=(
                    classification.source
                ),
                power_state=(
                    power_state
                ),
            )
        )

    # 匿名条目（AirPods 类）走电量百分比匹配，绑定到组件 ID
    devices.extend(
        _anonymous_accessory_devices(
            anonymous_records,
            bluetooth_inventory,
            observed_at,
        )
    )

    return devices


def _deduplicate_system_devices(
    devices,
):
    # 1. 提取所有组件设备的基础 ID (不带 :left, :right, :case 后缀的 ID)
    component_bases = {
        device.device_id.rsplit(
            ":",
            1,
        )[0]
        for device in devices
        if (
            device.source
            == SOURCE_SYSTEM_BLUETOOTH
            and device.device_id.endswith(
                (
                    ":left",
                    ":right",
                    ":case",
                )
            )
        )
    }

    # 2. 找到所有来自 pmset (SOURCE_SYSTEM_ACCESSORY) 且携带充电状态的根设备，并建立基础 ID 映射
    accessory_charging_map = {}
    for device in devices:
        if (
            device.source == SOURCE_SYSTEM_ACCESSORY
            and device.charging is not None
        ):
            accessory_charging_map[device.device_id] = (
                device.charging,
                device.power_state,
            )

    results = []
    seen = set()
    
    for device in devices:
        # 3. 如果当前设备是分出来的子组件 (带有组件后缀)，我们将对应根物理设备的真实充电状态传递给它
        base_id = device.device_id.rsplit(":", 1)[0] if ":" in device.device_id else device.device_id
        if base_id in accessory_charging_map:
            charging_val, power_val = accessory_charging_map[base_id]
            # 只有当组件本身充电状态未知或不存在时，才继承根物理设备的充电状态
            if device.charging is None:
                device = BatteryDevice(
                    device_id=device.device_id,
                    name=device.name,
                    category=device.category,
                    transport=device.transport,
                    level=device.level,
                    charging=charging_val,
                    source=device.source,
                    observed_at=device.observed_at,
                    category_source=device.category_source,
                    power_state=power_val if device.power_state == "unknown" else device.power_state
                )

        # 4. 过滤多余的根设备：如果一个根设备已经有了展开的子组件，去重时就不需要再独立展示它的根设备了
        if (
            device.source
            == SOURCE_SYSTEM_ACCESSORY
            and device.device_id
            in component_bases
        ):
            continue
    
        if device.device_id in seen:
            # 5. 如果是像蓝牙键盘这样没有后缀但存在于不同源的设备，如果已有的记录里充电状态为 None，
            # 而当前重复项中具有有效的充电状态，则应进行合并，而不是直接 continue 丢弃。
            existing_idx = next((i for i, d in enumerate(results) if d.device_id == device.device_id), None)
            if existing_idx is not None:
                existing_dev = results[existing_idx]
                if existing_dev.charging is None and device.charging is not None:
                    results[existing_idx] = BatteryDevice(
                        device_id=existing_dev.device_id,
                        name=existing_dev.name,
                        category=existing_dev.category,
                        transport=existing_dev.transport,
                        level=existing_dev.level,
                        charging=device.charging,
                        source=existing_dev.source,
                        observed_at=existing_dev.observed_at,
                        category_source=existing_dev.category_source,
                        power_state=device.power_state if existing_dev.power_state == "unknown" else existing_dev.power_state
                    )
            continue
    
        seen.add(
            device.device_id
        )
        results.append(device)
    
    return sorted(
        results,
        key=lambda item: (
            item.name.casefold(),
            item.device_id,
        ),
    )


def discover_batteries(
    timeout=DEFAULT_TIMEOUT,
):
    timeout = _validate_timeout(
        timeout
    )
    observed_at = time.time()

    # Use cached system_profiler JSON (single-flight,
    # stale-on-error).
    bluetooth_text, _is_stale = (
        _get_bluetooth_profiler_json(timeout)
    )

    inventory = []
    if bluetooth_text is not None:
        try:
            inventory = (
                parse_bluetooth_inventory(
                    bluetooth_text
                )
            )
        except Exception:
            inventory = []
    
    try:
        pmset_text = _run_command(
            [
                PMSET_PATH,
                "-g",
                "accps",
            ],
            timeout=min(
                timeout,
                15.0,
            ),
        )
        accessory_records = (
            parse_accessory_power(
                pmset_text
            )
        )
    except Exception:
        accessory_records = []
    
    devices = []
    
    try:
        devices.extend(
            bluetooth_inventory_to_devices(
                inventory,
                observed_at=(
                    observed_at
                ),
            )
        )
    except Exception:
        pass
    
    try:
        devices.extend(
            accessory_power_to_devices(
                accessory_records,
                inventory,
                observed_at=(
                    observed_at
                ),
            )
        )
    except Exception:
        pass
    
    return (
        _deduplicate_system_devices(
            devices
        )
    )