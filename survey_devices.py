#!/usr/bin/env python3

"""
Battery Bar 蓝牙设备快速能力普查

使用方法：
1. 每次只连接一台待测蓝牙设备；
2. 运行本脚本；
3. 输入该设备在 macOS 中显示的名称；
4. 重复测试其他设备；
5. 输入 q 结束并生成 Markdown 报告。

所有系统操作均为只读。
"""

from __future__ import annotations

import datetime as dt
import json
import platform
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional


PMSET = "/usr/bin/pmset"
SYSTEM_PROFILER = "/usr/sbin/system_profiler"
IOREG = "/usr/sbin/ioreg"
SW_VERS = "/usr/bin/sw_vers"

COMMAND_TIMEOUT = 90

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

BATTERY_KEYS = (
    "device_batteryLevel",
    "device_batteryLevelLeft",
    "device_batteryLevelRight",
    "device_batteryLevelCase",
)


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: Optional[int]
    stdout: str
    stderr: str
    timed_out: bool
    error: Optional[str]


def run(
    command: list[str],
    timeout: int = COMMAND_TIMEOUT,
) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
            error=None,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ""
        stderr = error.stderr or ""

        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
    
        return CommandResult(
            command=command,
            returncode=None,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
            error=f"超过 {timeout} 秒",
        )
    except Exception as error:
        return CommandResult(
            command=command,
            returncode=None,
            stdout="",
            stderr="",
            timed_out=False,
            error=f"{type(error).__name__}: {error}",
        )


def normalize(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def safe_slug(value: str) -> str:
    cleaned = re.sub(
        r"[^0-9a-zA-Z\u4e00-\u9fff]+",
        "-",
        value,
    ).strip("-")
    return cleaned[:60] or "device"


def load_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def save_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def save_command(
    directory: Path,
    prefix: str,
    result: CommandResult,
) -> None:
    (directory / f"{prefix}.txt").write_text(
        result.stdout,
        encoding="utf-8",
        errors="replace",
    )
    save_json(
        directory / f"{prefix}.command.json",
        asdict(result),
    )


def parse_pmset(text: str) -> list[dict[str, Any]]:
    records = []

    for line in text.splitlines():
        match = ACCESSORY_PATTERN.match(line)
        if match is None:
            continue
    
        level = int(match.group("level"))
        if not 0 <= level <= 100:
            continue
    
        records.append(
            {
                "name": " ".join(
                    match.group("name").split()
                ),
                "system_id": match.group("system_id"),
                "level": level,
                "state": (
                    match.group("state").casefold()
                ),
                "present": (
                    match.group("present").casefold()
                    == "true"
                ),
            }
        )
    
    return records


def iter_bluetooth_devices(
    bluetooth_json: Any,
) -> list[dict[str, Any]]:
    devices = []

    if not isinstance(bluetooth_json, dict):
        return devices
    
    sections = bluetooth_json.get(
        "SPBluetoothDataType", []
    )
    
    for section in sections:
        if not isinstance(section, dict):
            continue
    
        for section_key, connected in (
            ("device_connected", True),
            ("device_not_connected", False),
        ):
            groups = section.get(section_key, [])
    
            if not isinstance(groups, list):
                continue
    
            for group in groups:
                if not isinstance(group, dict):
                    continue
    
                for name, properties in group.items():
                    if not isinstance(properties, dict):
                        continue
    
                    devices.append(
                        {
                            "name": str(name),
                            "connected": connected,
                            "properties": properties,
                        }
                    )
    
    return devices


def find_named_device(
    devices: list[dict[str, Any]],
    requested_name: str,
) -> tuple[Optional[dict[str, Any]], list[str]]:
    query = normalize(requested_name)

    exact = [
        device
        for device in devices
        if normalize(device["name"]) == query
    ]
    
    if len(exact) == 1:
        return exact[0], []
    
    partial = [
        device
        for device in devices
        if (
            query in normalize(device["name"])
            or normalize(device["name"]) in query
        )
    ]
    
    if len(partial) == 1:
        return partial[0], []
    
    candidates = [
        device["name"]
        for device in (exact or partial)
    ]
    return None, candidates


def find_pmset_matches(
    records: list[dict[str, Any]],
    device_name: str,
) -> list[dict[str, Any]]:
    target = normalize(device_name)

    return [
        record
        for record in records
        if record["name"]
        and (
            normalize(record["name"]) == target
            or normalize(record["name"]) in target
            or target in normalize(record["name"])
        )
    ]


def find_audio_matches(
    audio_json: Any,
    device_name: str,
) -> list[dict[str, Any]]:
    matches = []
    target = normalize(device_name)

    if not isinstance(audio_json, dict):
        return matches
    
    for section in audio_json.get(
        "SPAudioDataType", []
    ):
        if not isinstance(section, dict):
            continue
    
        for item in section.get("_items", []):
            if not isinstance(item, dict):
                continue
    
            name = str(item.get("_name", ""))
            if not name:
                continue
    
            candidate = normalize(name)
    
            if (
                candidate == target
                or candidate in target
                or target in candidate
            ):
                matches.append(item)
    
    return matches


def bluetooth_batteries(
    properties: dict[str, Any],
) -> dict[str, Any]:
    return {
        key: properties[key]
        for key in BATTERY_KEYS
        if key in properties
    }


def classify_capability(
    bluetooth_device: Optional[dict[str, Any]],
    pmset_matches: list[dict[str, Any]],
    audio_matches: list[dict[str, Any]],
    ioreg_text: str,
    requested_name: str,
) -> tuple[str, list[str]]:
    sources = []
    result = "暂未发现电量"

    if bluetooth_device is not None:
        batteries = bluetooth_batteries(
            bluetooth_device["properties"]
        )
        if batteries:
            sources.append("Bluetooth JSON")
            result = "系统蓝牙报告可直接读取"
    
    if pmset_matches:
        sources.append("pmset")
        if result == "暂未发现电量":
            result = "系统附件电源源可读取"
    
    name_found_in_ioreg = (
        normalize(requested_name)
        in normalize(ioreg_text)
    )
    battery_found_in_ioreg = bool(
        re.search(
            r"BatteryPercent|CurrentCapacity|"
            r"BatteryLevel",
            ioreg_text,
            re.IGNORECASE,
        )
    )
    
    if name_found_in_ioreg and battery_found_in_ioreg:
        sources.append("IORegistry")
        if result == "暂未发现电量":
            result = "IORegistry 可能可读取"
    
    if not sources and audio_matches:
        result = "只能发现音频设备，尚无电量来源"
    
    return result, sources


def collect_device(
    root: Path,
    requested_name: str,
    index: int,
) -> dict[str, Any]:
    directory = root / (
        f"{index:02d}_{safe_slug(requested_name)}"
    )
    directory.mkdir(parents=True, exist_ok=False)

    print("正在采集，请保持设备连接……")
    
    pmset_result = run(
        [PMSET, "-g", "accps"],
        timeout=15,
    )
    bluetooth_result = run(
        [
            SYSTEM_PROFILER,
            "SPBluetoothDataType",
            "-json",
        ]
    )
    audio_result = run(
        [
            SYSTEM_PROFILER,
            "SPAudioDataType",
            "-json",
        ]
    )
    ioreg_result = run(
        [
            IOREG,
            "-r",
            "-l",
            "-k",
            "BatteryPercent",
        ],
        timeout=30,
    )
    ioreg_capacity_result = run(
        [
            IOREG,
            "-r",
            "-l",
            "-k",
            "CurrentCapacity",
        ],
        timeout=30,
    )
    
    save_command(
        directory, "pmset-accps", pmset_result
    )
    save_command(
        directory, "bluetooth", bluetooth_result
    )
    save_command(
        directory, "audio", audio_result
    )
    save_command(
        directory, "ioreg-battery-percent", ioreg_result
    )
    save_command(
        directory,
        "ioreg-current-capacity",
        ioreg_capacity_result,
    )
    
    bluetooth_json = load_json(
        bluetooth_result.stdout
    )
    audio_json = load_json(audio_result.stdout)
    
    if bluetooth_json is not None:
        save_json(
            directory / "bluetooth.json",
            bluetooth_json,
        )
    if audio_json is not None:
        save_json(
            directory / "audio.json",
            audio_json,
        )
    
    pmset_records = parse_pmset(
        pmset_result.stdout
    )
    devices = iter_bluetooth_devices(
        bluetooth_json
    )
    bluetooth_device, ambiguous_names = (
        find_named_device(devices, requested_name)
    )
    
    matched_name = (
        bluetooth_device["name"]
        if bluetooth_device is not None
        else requested_name
    )
    
    pmset_matches = find_pmset_matches(
        pmset_records,
        matched_name,
    )
    audio_matches = find_audio_matches(
        audio_json,
        matched_name,
    )
    
    ioreg_text = (
        ioreg_result.stdout
        + "\n"
        + ioreg_capacity_result.stdout
    )
    
    conclusion, sources = classify_capability(
        bluetooth_device,
        pmset_matches,
        audio_matches,
        ioreg_text,
        matched_name,
    )
    
    properties = (
        bluetooth_device["properties"]
        if bluetooth_device is not None
        else {}
    )
    
    result = {
        "requested_name": requested_name,
        "matched_name": (
            bluetooth_device["name"]
            if bluetooth_device is not None
            else None
        ),
        "ambiguous_candidates": ambiguous_names,
        "connected": (
            bluetooth_device["connected"]
            if bluetooth_device is not None
            else None
        ),
        "address": properties.get("device_address"),
        "minor_type": properties.get(
            "device_minorType"
        ),
        "vendor_id": properties.get(
            "device_vendorID"
        ),
        "product_id": properties.get(
            "device_productID"
        ),
        "bluetooth_batteries": (
            bluetooth_batteries(properties)
        ),
        "pmset_matches": pmset_matches,
        "anonymous_pmset_records": [
            record
            for record in pmset_records
            if not record["name"]
        ],
        "audio_match_count": len(audio_matches),
        "sources": sources,
        "conclusion": conclusion,
        "captured_at": (
            dt.datetime.now()
            .astimezone()
            .isoformat()
        ),
    }
    
    save_json(directory / "RESULT.json", result)
    return result


def format_batteries(
    batteries: dict[str, Any],
) -> str:
    if not batteries:
        return "—"

    labels = {
        "device_batteryLevel": "设备",
        "device_batteryLevelLeft": "左",
        "device_batteryLevelRight": "右",
        "device_batteryLevelCase": "盒",
    }
    
    return "；".join(
        f"{labels.get(key, key)} {value}"
        for key, value in batteries.items()
    )


def format_pmset(
    matches: list[dict[str, Any]],
) -> str:
    if not matches:
        return "—"

    return "；".join(
        f"{record['level']}% {record['state']}"
        for record in matches
    )


def generate_report(
    root: Path,
    results: list[dict[str, Any]],
    system_info: str,
) -> None:
    lines = [
        "# Battery Bar 设备能力普查",
        "",
        f"- 生成时间：{dt.datetime.now().astimezone().isoformat()}",
        f"- 系统：{system_info}",
        "",
        "| 设备 | 连接 | 类型 | 蓝牙报告电量 | pmset 电量 | 结论 |",
        "|---|---|---|---|---|---|",
    ]

    for result in results:
        name = (
            result.get("matched_name")
            or result["requested_name"]
        )
        connected = result.get("connected")
        connected_text = {
            True: "是",
            False: "否",
            None: "未匹配",
        }[connected]
    
        cells = [
            name,
            connected_text,
            result.get("minor_type") or "—",
            format_batteries(
                result.get("bluetooth_batteries", {})
            ),
            format_pmset(
                result.get("pmset_matches", [])
            ),
            result["conclusion"],
        ]
    
        lines.append(
            "| "
            + " | ".join(
                str(cell)
                .replace("|", "\\|")
                .replace("\n", " ")
                for cell in cells
            )
            + " |"
        )
    
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- “系统蓝牙报告可直接读取”表示已有名称、身份及电量。",
            "- “系统附件电源源可读取”表示可以通过具名 `pmset` 条目获得电量。",
            "- “暂未发现电量”不等于绝对不支持，下一步还可测试标准 BLE `180F/2A19`。",
            "- 匿名 `pmset` 条目不会自动分配给任何设备。",
            "",
        ]
    )
    
    (root / "SURVEY.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def main() -> int:
    if platform.system() != "Darwin":
        print("本脚本只能在 macOS 上运行。")
        return 1

    timestamp = dt.datetime.now().strftime(
        "%Y%m%d-%H%M%S"
    )
    root = (
        Path.home()
        / "Desktop"
        / f"BatteryBar-Survey-{timestamp}"
    )
    root.mkdir(parents=True)
    
    sw_vers = run([SW_VERS], timeout=15)
    system_info = "；".join(
        line.strip()
        for line in sw_vers.stdout.splitlines()
        if line.strip()
    )
    
    print("=" * 68)
    print("Battery Bar 蓝牙设备快速能力普查")
    print("=" * 68)
    print()
    print("每次只连接一台待测设备。")
    print("已验证的 AirPods、DJI 和 MX Anywhere 可以跳过。")
    print("输入设备在 macOS 中显示的名称，输入 q 结束。")
    print()
    
    results = []
    index = 1
    
    while True:
        requested_name = input(
            "待测设备名称（q 结束）："
        ).strip()
    
        if requested_name.casefold() == "q":
            break
    
        if not requested_name:
            print("名称不能为空。")
            continue
    
        print()
        print(f"准备测试：{requested_name}")
        print("请确认它已连接到 Mac，并断开其他待测设备。")
        answer = input(
            "准备好后按回车，输入 s 跳过："
        ).strip().casefold()
    
        if answer == "s":
            continue
    
        result = collect_device(
            root,
            requested_name,
            index,
        )
        results.append(result)
        index += 1
    
        print()
        print("检测结果：")
        print(
            "  匹配设备：",
            result.get("matched_name") or "未匹配",
        )
        print(
            "  蓝牙电量：",
            format_batteries(
                result["bluetooth_batteries"]
            ),
        )
        print(
            "  pmset 电量：",
            format_pmset(result["pmset_matches"]),
        )
        print("  结论：", result["conclusion"])
        print()
    
    generate_report(
        root,
        results,
        system_info,
    )
    save_json(
        root / "all-results.json",
        {
            "system": system_info,
            "results": results,
        },
    )
    
    print()
    print("普查完成。")
    print(f"报告：{root / 'SURVEY.md'}")
    print(f"完整结果：{root}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())