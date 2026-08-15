#!/usr/bin/env python3

import time
import logging
import hashlib
import hid

from classifier import (
    DeviceMetadata,
    classify_device,
)
from models import (
    BatteryDevice,
    POWER_STATE_UNKNOWN,
    SOURCE_HIDPP,
    TRANSPORT_RECEIVER,
)

logger = logging.getLogger(__name__)

LOGITECH_VENDOR_ID = 0x046D

DEFAULT_ATTEMPTS = 2
DEFAULT_TIMEOUT = 1.0
DEFAULT_RETRY_DELAY = 0.15

# 电量 Feature 候选，按优先级排序。
# 元素格式：(feature_id, 读取电量用的 function, 查询 Feature Index 用的 software_id)
# 不硬编码只用某一个 Feature：通过 Root.GetFeature (0x0000) 向设备本身查询它支持
# 哪个电量 Feature，命中第一个就用。两种协议的电量百分比都在响应的 res[4]。
#   0x1004 UnifiedBattery (新设备，如 MX Keys S)       —— Function 1 (GetCapability)
#   0x1000 BatteryStatus  (老设备/Unifying，如 MX Anywhere 2S) —— Function 0 (GetBatteryLevelStatus)
#
# 每个候选用不同的 software_id 查询：HID++ 响应会回显请求的 SwID（res[3] 低 4 位）。
# 这样即使前一个查询（设备休眠导致）的迟到响应晚到，也会因 SwID 不匹配而被跳过，
# 不会污染下一个候选项的匹配 —— 从根本上避免“0x1004 的迟到 index 被当成 0x1000 的结果”。
BATTERY_FEATURE_CANDIDATES = [
    (0x1004, 1, 0x01),
    (0x1000, 0, 0x02),
]

HIDPP_TARGETS = {
    "keyboard": {
        "name": "MX Keys",
        "product_id": 0xC548,
        "slot": 1,
        "feature_index": 0x08,
        "function": 1,
        "software_id": 0x0A,
        "hid_usage_page": 0x01,
        "hid_usage": 0x06,
    },
    "mouse": {
        "name": "MX Anywhere 2S",
        "product_id": 0xC52B,
        "slot": 2,
        "feature_index": 0x06,
        "function": 0,
        "software_id": 0x0B,
        "hid_usage_page": 0x01,
        "hid_usage": 0x02,
    },
}


class HidppError(Exception):
    pass


class HidppInterfaceNotFound(HidppError):
    pass


class HidppWriteError(HidppError):
    pass


class HidppProtocolError(HidppError):
    pass


class HidppTimeout(HidppError):
    pass


def _validate_positive_number(value, field_name):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value <= 0
    ):
        raise ValueError(f"{field_name} must be positive")
    return float(value)


def _validate_attempts(attempts):
    if (
        isinstance(attempts, bool)
        or not isinstance(attempts, int)
        or attempts < 1
    ):
        raise ValueError("attempts must be a positive integer")
    return attempts


def _validate_target(target):
    required = {
        "name",
        "product_id",
        "slot",
        "feature_index",
        "function",
        "software_id",
        "hid_usage_page",
        "hid_usage",
    }
    if not isinstance(target, dict):
        raise TypeError("target must be a dictionary")
    missing = required.difference(target)
    if missing:
        raise ValueError("target is missing fields: " + ", ".join(sorted(missing)))


def _drain(device, settle_ms=20):
    try:
        if device.read(64, timeout_ms=settle_ms):
            while device.read(64, timeout_ms=1):
                pass
    except Exception:
        pass


def _build_request(target):
    function_client = (
        ((target["function"] & 0x0F) << 4)
        | (target["software_id"] & 0x0F)
    )
    packet = [
        0x11,
        target["slot"],
        target["feature_index"],
        function_client,
    ] + [0x00] * 16
    return packet, function_client


def _is_error_response(packet, target, function_client):
    return (
        len(packet) >= 6
        and packet[1] == target["slot"]
        and packet[2] == 0xFF
        and packet[3] == target["feature_index"]
        and packet[4] == function_client
    )


def _is_matching_response(packet, target, function_client):
    return (
        len(packet) >= 5
        and packet[0] in (0x10, 0x11)
        and packet[1] == target["slot"]
        and packet[2] == target["feature_index"]
        and packet[3] == function_client
    )


def query_battery_once_with_device(device, target, timeout=DEFAULT_TIMEOUT):
    _validate_target(target)
    timeout = _validate_positive_number(timeout, "timeout")

    request, function_client = _build_request(target)
    _drain(device)

    written = device.write(request)
    if written != len(request):
        raise HidppWriteError(f"HID 写入长度异常：{written}/{len(request)}")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        packet = device.read(64, timeout_ms=10)
        if not packet:
            time.sleep(0.005)
            continue

        if _is_error_response(packet, target, function_client):
            raise HidppProtocolError(f"HID++ 错误：0x{packet[5]:02X}")

        if _is_matching_response(packet, target, function_client):
            level = packet[4]
            if not 0 <= level <= 100:
                raise HidppProtocolError(f"非法电量：{level}")
            return level

    raise HidppTimeout("设备无响应，可能处于休眠状态")


def query_battery_once(target, timeout=DEFAULT_TIMEOUT):
    _validate_target(target)
    path = find_hidpp_path(target["product_id"])
    device = hid.device()
    try:
        device.open_path(path)
        device.set_nonblocking(True)
        return query_battery_once_with_device(device, target, timeout)
    finally:
        try:
            device.close()
        except Exception:
            pass


def query_battery(
    target,
    attempts=DEFAULT_ATTEMPTS,
    timeout=DEFAULT_TIMEOUT,
    retry_delay=DEFAULT_RETRY_DELAY,
):
    attempts = _validate_attempts(attempts)
    timeout = _validate_positive_number(timeout, "timeout")
    if (
        isinstance(retry_delay, bool)
        or not isinstance(retry_delay, (int, float))
        or retry_delay < 0
    ):
        raise ValueError("retry_delay must be non-negative")

    last_error = None
    for attempt in range(attempts):
        try:
            return query_battery_once(target, timeout=timeout)
        except Exception as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(float(retry_delay))
    raise last_error


def find_hidpp_path(product_id):
    if (
        isinstance(product_id, bool)
        or not isinstance(product_id, int)
        or not 0 <= product_id <= 0xFFFF
    ):
        raise ValueError("product_id must be a 16-bit integer")

    # 优先寻找支持 HID++ 的专用路径 (避免触发额外权限)
    receivers = enumerate_hidpp_receivers()
    for path, pid in receivers.items():
        if pid == product_id:
            return path

    # 兜底：直接查找匹配的 PID 路径
    for item in hid.enumerate(LOGITECH_VENDOR_ID):
        if item.get("product_id") == product_id:
            path = item.get("path")
            if path:
                return path

    raise HidppInterfaceNotFound(f"找不到 HID++ 接口 PID 0x{product_id:04X}")


# ==============================================================================
# 动态探测与发现的核心逻辑
# ==============================================================================

def enumerate_hidpp_receivers():
    """
    枚举系统中所有可能代表罗技 USB/无线接收器的 HID++ 设备接口。
    
    安全设计：
    1. macOS/Linux 上，每个物理 USB 设备通常暴露多个 Interface 路径（如控制、键、鼠等）。
    2. 如果直接打开 Keyboard/Mouse 基础输入接口 (usage_page == 0x01)，系统会弹出“输入监控”或键盘读写等高危隐私权限。
    3. HID++ 专用的接口其 usage_page 往往为 0xFF00。如果系统上不提供 usage_page 信息 (部分 macOS 版本)，我们做 fallback。
    4. 对每个物理设备 (由 PID 和物理单元标识)，我们【优先】保留 usage_page == 0xFF00 的接口路径；
       其次选择 usage_page == 0x0000 (未知/缺省值) 的路径；
       【绝对不选择】任何 usage_page == 0x01 的通用输入控制路径。
    """
    items = hid.enumerate(LOGITECH_VENDOR_ID)
    if not items:
        return {}

    # 按物理设备进行分组以去重，组 Key: (product_id, 物理标识/路径特征)
    grouped = {}

    for item in items:
        path = item.get("path")
        pid = item.get("product_id")
        if not path or pid is None:
            continue

        usage_page = item.get("usage_page") or 0x0000
        
        # 排除已知的非 HID++ 或有额外输入权限风险的经典接口：
        # usage_page == 0x01 (Generic Desktop Ctrls: Keyboard/Mouse)
        # usage_page == 0x0C (Consumer Devices: Media Keys 等)
        # 这样做能 100% 避免后台触发 macOS 键盘监控/键盘输入监听权限弹窗。
        if usage_page in (0x01, 0x0C):
            continue

        device_serial = item.get("serial_number") or ""
        path_stem = path.decode("utf-8", errors="ignore") if isinstance(path, bytes) else str(path)
        # 去掉常见 interface 的后缀
        for suffix in [":0003", ":0001", ":0002", "-if01", "-if00", "-if02"]:
            if path_stem.endswith(suffix):
                path_stem = path_stem[:-len(suffix)]
                break

        group_key = (pid, device_serial, path_stem)

        if group_key not in grouped:
            grouped[group_key] = []
        grouped[group_key].append((path, usage_page))

    receivers = {}
    for (pid, _, _), interfaces in grouped.items():
        best_path = None
        best_score = -1

        for path, usage_page in interfaces:
            score = 0
            if usage_page == 0xFF00:
                score = 100
            elif usage_page == 0x0000:
                score = 50
            else:
                score = 10

            if score > best_score:
                best_score = score
                best_path = path

        if best_path:
            receivers[best_path] = pid

    return receivers


def get_feature_index(device, slot, feature_id, timeout=0.5, swid=0x01):
    """
    通过 Root Feature (0x0000) 动态获取 Feature ID 的 Index。

    swid 参数允许调用方为每次查询指定不同的 Software ID（响应的 res[3]
    低 4 位会回显它）。在 probe 候选 Feature 列表时给每个候选分配不同的
    swid，可以彻底避免“前一个查询的迟到响应被当成下一个查询的结果”——
    因为 res[3] 能区分响应归属哪个 swid 的请求。
    """
    function_client = (0 << 4) | (swid & 0x0F)
    packet = [
        0x11,
        slot,
        0x00,
        function_client,
        (feature_id >> 8) & 0xFF,
        feature_id & 0xFF,
    ] + [0x00] * 14

    _drain(device)
    written = device.write(packet)
    if written != len(packet):
        return None

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = device.read(64, timeout_ms=10)
        if not res:
            time.sleep(0.005)
            continue
        if (
            len(res) >= 5
            and res[0] in (0x10, 0x11)
            and res[1] == slot
            and res[2] == 0x00
            and res[3] == function_client
        ):
            index = res[4]
            return index if index != 0 else None
        if (
            len(res) >= 6
            and res[1] == slot
            and res[2] == 0xFF
            and res[3] == 0x00
            and res[4] == function_client
        ):
            return None
        if (
            len(res) >= 4
            and res[1] == slot
            and res[2] == 0x8F
        ):
            return None
    return None

def _clean_logitech_name(name: str) -> str:
    """去掉罗技 0x0005 DeviceName 返回的冗余产品前缀。

    Logitech 接收器通过 Feature 0x0005 读取的设备名是完整的出厂全称，
    常见冗余前缀示例：
        "Wireless Mobile Mouse MX Anywhere 2S" → "MX Anywhere 2S"
        "Wireless Mouse MX Master 3"           → "MX Master 3"
        "Wireless Keyboard MX Keys S"          → "MX Keys S"
    策略：按最长匹配优先，去掉已知前缀后 strip。
    """
    prefixes = [
        "Wireless Mobile Mouse ",
        "Wireless Mouse ",
        "Wireless Keyboard ",
        "Wireless Number Pad ",
        "Wireless Trackball ",
        "Wireless Touch Keyboard ",
    ]
    for prefix in prefixes:
        if name.startswith(prefix):
            return name[len(prefix):].strip()
    return name


def _wakeup_pulse(device, slot, settle_ms=150):
    """向设备发送一个无害探测报文，给深度休眠的设备唤醒时间。

    用 Root Feature (0x0000) Function 0 查询 feature 0x0000（Root 自身）。
    Root Feature 对所有 HID++ 2.0 设备必然存在（index 固定 0x00），
    是已知最安全的“心跳”请求。SwID 用 0x09，与后续 name/serial 查询的
    SwID（0x02/0x03）不同，这样即使该脉冲的响应迟到也不会被误匹配。

    返回后仍会做一次 _drain 排空缓冲区，确保后续查询从干净状态开始。
    """
    sw_id = 0x09
    pulse = [0x11, slot, 0x00, (0 << 4) | sw_id, 0x00, 0x00] + [0x00] * 14
    try:
        device.write(pulse)
    except Exception:
        pass
    # 给设备充分唤醒时间（深度休眠唤醒约需 100-200ms）
    time.sleep(settle_ms / 1000.0)
    _drain(device)


def get_device_name(device, slot, name_feature_index, timeout=0.3):
    sw_id = 0x02
    len_func = (0 << 4) | sw_id
    name_func = (1 << 4) | sw_id

    def _wait_response(func_client, want_len):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            res = device.read(64, timeout_ms=10)
            if not res:
                time.sleep(0.005)
                continue
            if (
                len(res) >= 5
                and res[0] in (0x10, 0x11)
                and res[1] == slot
                and res[2] == name_feature_index
                and res[3] == func_client
            ):
                return bytes(res[4:4 + want_len]) if want_len else res[4]
            if (
                len(res) >= 6
                and res[1] == slot
                and res[2] == 0xFF
                and res[3] == name_feature_index
                and res[4] == func_client
            ):
                return None
        return None

    len_packet = [0x11, slot, name_feature_index, len_func] + [0x00] * 16
    name_len = None
    # 读长度可能因设备休眠而首次无响应。name 查询本身就在唤醒设备，
    # 所以重试一次通常就能拿到长度；首次失败直接回退 16 会导致只读到
    # 截断的名字或读到乱序响应，表现为设备名偶发回退成 slot 占位名。
    #
    # 渐进式重试延迟（指数退避）：首次 0.1s，第二次 0.2s，第三次 0.4s。
    # 深度休眠的设备唤醒较慢，固定短延迟可能仍读不到；逐步加长给设备
    # 更多时间稳定 USB 缓冲区。每次重试前 _drain 彻底排空残留响应。
    retry_delays = (0.1, 0.2, 0.4)
    for attempt in range(3):
        _drain(device)
        if device.write(len_packet) != len(len_packet):
            return None
        name_len = _wait_response(len_func, want_len=0)
        if name_len:
            break
        time.sleep(retry_delays[attempt])
    if not name_len:
        # 仍拿不到长度时退化为单次读取（最多 16 字符）
        name_len = 16

    name_bytes = bytearray()
    while len(name_bytes) < name_len:
        char_index = len(name_bytes)
        packet = [
            0x11, slot, name_feature_index, name_func, char_index,
        ] + [0x00] * 15
        _drain(device)
        if device.write(packet) != len(packet):
            break

        chunk = _wait_response(
            name_func, want_len=min(16, name_len - char_index)
        )
        if not chunk:
            break
        for b in chunk:
            if b == 0:
                break
            name_bytes.append(b)
        if len(chunk) < 16:
            break

    if name_bytes:
        try:
            name = name_bytes.decode("ascii", errors="ignore").strip()
        except Exception:
            return None
        if name and all(ch.isprintable() for ch in name):
            # 罗技 0x0005 DeviceName 返回的原始全名常带冗余前缀，
            # 如 "Wireless Mobile Mouse MX Anywhere 2S" → 去掉前缀 → "MX Anywhere 2S"
            name = _clean_logitech_name(name)
            return name
    return None


def get_device_serial(device, slot, info_feature_index, timeout=0.15):
    function_client = (0 << 4) | 0x03
    packet = [
        0x11,
        slot,
        info_feature_index,
        function_client,
    ] + [0x00] * 16

    _drain(device)
    written = device.write(packet)
    if written != len(packet):
        return None

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = device.read(64, timeout_ms=10)
        if not res:
            time.sleep(0.005)
            continue
        if (
            len(res) >= 15
            and res[0] in (0x10, 0x11)
            and res[1] == slot
            and res[2] == info_feature_index
            and res[3] == function_client
        ):
            serial_bytes = bytes(res[12:15])
            serial_bytes = serial_bytes.rstrip(b"")
            if serial_bytes:
                return "".join(f"{b:02X}" for b in serial_bytes)
            return None
        if (
            len(res) >= 6
            and res[1] == slot
            and res[2] == 0xFF
            and res[3] == info_feature_index
            and res[4] == function_client
        ):
            return None
    return None


def get_device_model_id(device, slot, info_feature_index, timeout=0.3):
    """读取 0x0003 DeviceInfo 的 modelId（offset 9-11，3 字节）。

    modelId 是子设备的真实型号标识（与接收器 PID 无关），可用于名字
    读取失败时的型号反查兜底。返回大写十六进制字符串（如 "B36C000"），
    失败返回 None。
    """
    function_client = (0 << 4) | 0x03
    packet = [
        0x11,
        slot,
        info_feature_index,
        function_client,
    ] + [0x00] * 16

    _drain(device)
    if device.write(packet) != len(packet):
        return None

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = device.read(64, timeout_ms=10)
        if not res:
            time.sleep(0.005)
            continue
        if (
            len(res) >= 12
            and res[0] in (0x10, 0x11)
            and res[1] == slot
            and res[2] == info_feature_index
            and res[3] == function_client
        ):
            model_bytes = bytes(res[9:12])
            return "".join(f"{b:02X}" for b in model_bytes)
        if (
            len(res) >= 6
            and res[1] == slot
            and res[2] == 0xFF
            and res[3] == info_feature_index
            and res[4] == function_client
        ):
            return None
    return None


# modelId → 设备名反查表（名字读取失败时的最后兜底）。
#
# 注意：这里的 modelId 是 0x0003 DeviceInfo 返回的子设备型号标识，
# 与接收器 PID（如 0xC548 Bolt）不同——一个接收器可挂任意型号子设备。
# 表内容来自 Logitech 公开 HID++ 文档与社区实测，按需扩充。
# 这仅用于 fallback：名字能正常读到时完全不查此表。
_KNOWN_MODEL_NAMES = {
    "B36C000": "MX Master 3S",
    "B038000": "MX Master 3",
    "B023000": "MX Master 2S",
    "B340000": "MX Anywhere 3S",
    "B035000": "MX Anywhere 3",
    "B022000": "MX Anywhere 2S",
    "C539000": "MX Keys",
    "CB38000": "MX Keys S",
    "B378000": "MX Keys Mini",
    "B335000": "MX Ergo",
    "B339000": "K780",
    "B342000": "K380",
    "B359000": "M720 Triathlon",
    "B352000": "Pebble Mouse M350",
}


# 设备名字缓存：跨刷新保留上次成功读到的真实名字。
# HID++ 设备频繁休眠，每次刷新都重新唤醒读名字。设备休眠时名字读取
# 失败 → 返回 "HID++ Device Slot N" fallback 名。由于 fallback 名作为
# 非缓存数据返回，aggregator 的 _prefer 会用它覆盖上次的真实名字。
# 此缓存确保：读到真实名字就存下来，后续读取失败时用缓存替代 fallback。
# 纯内存，进程重启清空（设备名极少变化，无需 TTL）。
_DEVICE_NAME_CACHE = {}


def _device_cache_key(target):
    """生成稳定的设备位置 key。

    用 pid + slot + receiver_path 的 hash，不依赖 serial（serial 本身
    也可能因设备休眠而读不到）。同一物理连接下此 key 不变。
    """
    raw_path = (
        target.get("receiver_path") or ""
    )
    if isinstance(raw_path, bytes):
        path_str = raw_path.decode(
            "utf-8", errors="ignore"
        )
    else:
        path_str = str(raw_path)
    path_hash = hashlib.md5(
        path_str.encode("utf-8", errors="ignore")
    ).hexdigest()[:6]
    return (
        f"{target['product_id']:04x}"
        f":{target['slot']}"
        f":{path_hash}"
    )

_MOUSE_KEYWORDS    = {"mouse", "anywhere", "master", "trackball", "lift", "pebble", "g304", "g305", "g502", "g903", "m720", "mx master"}
_KEYBOARD_KEYWORDS = {"keyboard", "keys", "k800", "k850", "k380", "k780", "k400", "ergo", "craft", "mx keys"}
_HEADSET_KEYWORDS  = {"headset", "zone", "h800", "h820", "g733", "g933", "g935"}

def _guess_hid_usage(name: str) -> int:
    n = name.lower()
    # fallback 名 "HID++ Device Slot N" 不含任何产品关键词，
    # 返回 0x00（Generic Desktop/undefined）让 classifier 走后续分类
    # 而非错误地默认归类为鼠标。
    if n.startswith("hid++ device"):
        return 0x00
    if any(k in n for k in _KEYBOARD_KEYWORDS):
        return 0x06
    if any(k in n for k in _HEADSET_KEYWORDS):
        return 0x04
    if any(k in n for k in _MOUSE_KEYWORDS):
        return 0x02
    return 0x00


def probe_device_on_slot(device, pid, slot, receiver_path):
    battery_idx = None
    battery_function = None
    for attempt in range(4):
        attempt_start = time.monotonic()
        for feature_id, func, swid in BATTERY_FEATURE_CANDIDATES:
            idx = get_feature_index(device, slot, feature_id, timeout=0.4, swid=swid)
            if idx is not None:
                battery_idx = idx
                battery_function = func
                break
        if battery_idx is not None:
            break
        if time.monotonic() - attempt_start < 0.1:
            return None
        time.sleep(0.15)
    if battery_idx is None:
        return None

    name = f"HID++ Device Slot {slot}"
    name_idx = get_feature_index(device, slot, 0x0005, timeout=0.5)
    if name_idx is None:
        _wakeup_pulse(device, slot, settle_ms=200)
        name_idx = get_feature_index(device, slot, 0x0005, timeout=0.5)
    if name_idx is not None:
        _wakeup_pulse(device, slot, settle_ms=150)
        fetched_name = get_device_name(device, slot, name_idx, timeout=0.8)
        if fetched_name:
            name = fetched_name

    # 首次完整尝试仍为 fallback 时，再做一轮完整重试。
    # 深度休眠键盘（MX Keys S）唤醒慢，电池探测阶段的报文可能不够
    # 充分，第一轮名字读取的 get_device_name 内部分片仍可能超时。
    if name.startswith("HID++ Device"):
        _wakeup_pulse(device, slot, settle_ms=200)
        name_idx = get_feature_index(
            device, slot, 0x0005, timeout=0.5
        )
        if name_idx is not None:
            _wakeup_pulse(device, slot, settle_ms=150)
            fetched_name = get_device_name(
                device, slot, name_idx, timeout=0.8
            )
            if fetched_name:
                name = fetched_name

    serial = None
    info_idx = get_feature_index(device, slot, 0x0003, timeout=0.5)
    if info_idx is None and name.startswith("HID++ Device"):
        # 名字读取失败时 modelId 反查是最后兜底，同样需要 retry。
        _wakeup_pulse(device, slot, settle_ms=200)
        info_idx = get_feature_index(device, slot, 0x0003, timeout=0.5)
    if info_idx is not None:
        serial = get_device_serial(device, slot, info_idx, timeout=0.8)

    # 名字读取失败时的最后兜底：用 modelId 反查已知型号表。
    # 这避免了向用户展示无意义的 "HID++ Device Slot N" 占位名。
    # 注意 modelId 是子设备型号（与接收器 PID 无关）。
    if name.startswith("HID++ Device") and info_idx is not None:
        model_id = get_device_model_id(
            device, slot, info_idx, timeout=0.3
        )
        if model_id:
            looked_up = _KNOWN_MODEL_NAMES.get(
                model_id.upper()
            )
            if looked_up:
                name = looked_up

    # 名字缓存：读到真实名字就存；fallback 名用缓存替代。
    cache_key = _device_cache_key(
        {
            "product_id": pid,
            "slot": slot,
            "receiver_path": receiver_path,
        }
    )
    if not name.startswith("HID++ Device"):
        _DEVICE_NAME_CACHE[cache_key] = name
    elif cache_key in _DEVICE_NAME_CACHE:
        name = _DEVICE_NAME_CACHE[cache_key]

    return {
        "name": name,
        "product_id": pid,
        "slot": slot,
        "feature_index": battery_idx,
        "function": battery_function,
        "software_id": 0x0F,
        "serial": serial,
        "hid_usage_page": 0x01,
        "hid_usage": _guess_hid_usage(name),
        "receiver_path": receiver_path,
    }


def _make_device(target_key, target, level, observed_at):
    classification = classify_device(
        DeviceMetadata(
            name=target["name"],
            hid_usage_page=target["hid_usage_page"],
            hid_usage=target["hid_usage"],
        )
    )

    # hidapi 在 macOS 上返回的 path 是 bytes（如 b'DevSrvsID:4294970718'），
    # 必须先 decode 成 str 再 encode 给 hashlib。直接对 bytes 调 .encode() 会抛
    # AttributeError，被 aggregator 吞掉后表现为"探测到设备但 device_count=0"。
    raw_path = target.get("receiver_path") or ""
    if isinstance(raw_path, bytes):
        path_str = raw_path.decode("utf-8", errors="ignore")
    else:
        path_str = str(raw_path)
    path_hash = hashlib.md5(path_str.encode("utf-8", errors="ignore")).hexdigest()[:6]
    
    device_uid = target.get("serial") or f"slot-{path_hash}-{target['slot']}"
    device_id = f"hidpp:{target['product_id']:04x}:{device_uid}"

    return BatteryDevice(
        device_id=device_id,
        name=target["name"],
        category=classification.category,
        transport=TRANSPORT_RECEIVER,
        level=level,
        charging=None,
        source=SOURCE_HIDPP,
        observed_at=observed_at,
        category_source=classification.source,
        power_state=POWER_STATE_UNKNOWN,
    )


def discover_batteries(
    attempts=DEFAULT_ATTEMPTS,
    timeout=DEFAULT_TIMEOUT,
    retry_delay=DEFAULT_RETRY_DELAY,
):
    results = []
    observed_at = time.time()

    receivers = enumerate_hidpp_receivers()
    if not receivers:
        logger.debug("No Logitech HID++ receivers discovered.")
        return results

    for path, pid in receivers.items():
        device = hid.device()
        try:
            device.open_path(path)
            device.set_nonblocking(True)

            for slot in range(1, 7):
                try:
                    target = probe_device_on_slot(device, pid, slot, path)
                    if not target:
                        continue

                    level = None
                    last_err = None
                    for attempt in range(attempts):
                        try:
                            level = query_battery_once_with_device(device, target, timeout)
                            break
                        except Exception as e:
                            last_err = e
                            if attempt + 1 < attempts:
                                time.sleep(retry_delay)

                    if level is not None:
                        target_key = target["name"].lower().replace(" ", "_")
                        results.append(
                            _make_device(
                                target_key,
                                target,
                                level,
                                observed_at,
                            )
                        )
                    else:
                        logger.warning(f"Failed to query battery for {target['name']}: {last_err}")
                except Exception as e:
                    logger.error(f"Error querying slot {slot} on receiver {pid:04X}: {e}")
        except Exception as e:
            logger.error(f"Failed to open receiver path {path}: {e}")
        finally:
            try:
                device.close()
            except Exception:
                pass

    return results
