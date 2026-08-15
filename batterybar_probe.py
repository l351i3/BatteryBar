#!/usr/bin/env python3

"""
Battery Bar 多源电量诊断脚本

用途：
1. 分步骤采集不同 AirPods / DJI Mic Mini 状态。
2. 同时保存 pmset、蓝牙信息和音频信息。
3. 生成便于分析的 Markdown 报告。
4. 所有操作均为只读，不会修改系统设置。

运行环境：
- macOS

- Python 3

  """

from __future__ import annotations

import datetime as dt
import json
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional


PMSET_PATH = "/usr/bin/pmset"
SYSTEM_PROFILER_PATH = "/usr/sbin/system_profiler"
SW_VERS_PATH = "/usr/bin/sw_vers"

COMMAND_TIMEOUT_SECONDS = 90

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

INTERESTING_TERMS = (
    "airpods",
    "dji",
    "mic mini",
    "bluetooth",
    "connected",
    "battery",
    "case",
    "headphone",
    "headset",
    "microphone",
    "address",
    "uuid",
    "vendor",
    "product",
    "manufacturer",
    "transport",
    "input",
    "output",
)

TEST_STEPS = (
    {
        "slug": "01_baseline",
        "title": "基准状态",
        "instructions": (
            "请连接 DJI Mic Mini 和 AirPods。\n"
            "保持设备处于你平时使用的状态。"
        ),
    },
    {
        "slug": "02_airpods_wearing_case_closed",
        "title": "佩戴 AirPods，电池盒关闭",
        "instructions": (
            "请佩戴 AirPods，并确认它已连接到 Mac。\n"
            "关闭 AirPods 电池盒盒盖。"
        ),
    },
    {
        "slug": "03_airpods_wearing_case_open",
        "title": "佩戴 AirPods，电池盒打开",
        "instructions": (
            "继续佩戴 AirPods并保持连接。\n"
            "把空的 AirPods 电池盒放在 Mac 附近并打开盒盖。"
        ),
    },
    {
        "slug": "04_airpods_in_case_open",
        "title": "AirPods 放入电池盒，盒盖打开",
        "instructions": (
            "请把 AirPods 放回电池盒。\n"
            "保持盒盖打开，并等待大约 10 秒。"
        ),
    },
    {
        "slug": "05_airpods_in_case_closed",
        "title": "AirPods 放入电池盒，盒盖关闭",
        "instructions": (
            "请把 AirPods 留在电池盒内并关闭盒盖。\n"
            "等待大约 10 秒。"
        ),
    },
    {
        "slug": "06_airpods_disconnected",
        "title": "AirPods 已断开",
        "instructions": (
            "请在 macOS 蓝牙设置中断开 AirPods，或者保持它在"
            "关闭的电池盒内直至断开。\n"
            "不要取消配对。"
        ),
    },
    {
        "slug": "07_airpods_reconnected",
        "title": "AirPods 重新连接",
        "instructions": (
            "请重新连接并佩戴 AirPods。\n"
            "等待声音输出切换完成。"
        ),
    },
    {
        "slug": "08_dji_disconnected",
        "title": "DJI Mic Mini 已断开",
        "instructions": (
            "保持 AirPods 当前状态不变。\n"
            "请断开 DJI Mic Mini，但不要取消配对。"
        ),
    },
    {
        "slug": "09_dji_reconnected",
        "title": "DJI Mic Mini 重新连接",
        "instructions": (
            "请重新连接 DJI Mic Mini。\n"
            "等待它重新出现在 macOS 音频输入设备中。"
        ),
    },
)


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: Optional[int]
    stdout: str
    stderr: str
    timed_out: bool
    error: Optional[str]


@dataclass(frozen=True)
class AccessoryRecord:
    system_id: str
    name: str
    level: int
    state: str
    present: bool


def print_heading(text: str) -> None:
    print()
    print("=" * 72)
    print(text)
    print("=" * 72)


def run_command(
    command: list[str],
    timeout: int = COMMAND_TIMEOUT_SECONDS,
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
            stdout = stdout.decode("utf-8", errors="replace")
    
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
    
        return CommandResult(
            command=command,
            returncode=None,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
            error=f"命令执行超过 {timeout} 秒",
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


def ensure_environment() -> None:
    if platform.system() != "Darwin":
        raise RuntimeError("该脚本只能在 macOS 上运行")

    required_commands = (
        PMSET_PATH,
        SYSTEM_PROFILER_PATH,
        SW_VERS_PATH,
    )
    
    missing = [
        path
        for path in required_commands
        if not Path(path).is_file()
    ]
    
    if missing:
        raise RuntimeError(
            "缺少系统命令：" + ", ".join(missing)
        )


def ask_for_output_directory() -> Path:
    default_root = Path.home() / "Desktop"
    default_name = (
        "BatteryBar-Probe-"
        + dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    default_path = default_root / default_name

    print()
    print(f"默认结果目录：{default_path}")
    entered = input(
        "直接按回车使用默认目录，或输入其他路径："
    ).strip()
    
    output_path = (
        Path(entered).expanduser()
        if entered
        else default_path
    )
    
    output_path.mkdir(parents=True, exist_ok=False)
    return output_path


def write_text(path: Path, content: str) -> None:
    path.write_text(
        content,
        encoding="utf-8",
        errors="replace",
    )


def write_json(path: Path, value: Any) -> None:
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


def parse_json_safely(text: str) -> tuple[Any, Optional[str]]:
    try:
        return json.loads(text), None
    except Exception as error:
        return None, f"{type(error).__name__}: {error}"


def parse_accessory_records(text: str) -> list[AccessoryRecord]:
    records: list[AccessoryRecord] = []

    for line in text.splitlines():
        match = ACCESSORY_PATTERN.match(line)
    
        if match is None:
            continue
    
        level = int(match.group("level"))
    
        if not 0 <= level <= 100:
            continue
    
        records.append(
            AccessoryRecord(
                system_id=match.group("system_id"),
                name=" ".join(
                    match.group("name").split()
                ),
                level=level,
                state=match.group("state").casefold(),
                present=(
                    match.group("present").casefold()
                    == "true"
                ),
            )
        )
    
    return records


def value_to_search_text(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        ).casefold()
    except Exception:
        return str(value).casefold()


def extract_interesting_json(
    value: Any,
    path: tuple[str, ...] = (),
    results: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    if results is None:
        results = []

    if isinstance(value, dict):
        object_text = value_to_search_text(value)
    
        if any(
            term in object_text
            for term in INTERESTING_TERMS
        ):
            scalar_fields = {
                str(key): child
                for key, child in value.items()
                if not isinstance(child, (dict, list))
            }
    
            if scalar_fields:
                results.append(
                    {
                        "path": ".".join(path) or "<root>",
                        "fields": scalar_fields,
                    }
                )
    
        for key, child in value.items():
            extract_interesting_json(
                child,
                path + (str(key),),
                results,
            )
    
    elif isinstance(value, list):
        for index, child in enumerate(value):
            extract_interesting_json(
                child,
                path + (str(index),),
                results,
            )
    
    return results


def save_command_result(
    step_directory: Path,
    filename_prefix: str,
    result: CommandResult,
) -> None:
    write_text(
        step_directory / f"{filename_prefix}.stdout.txt",
        result.stdout,
    )
    write_text(
        step_directory / f"{filename_prefix}.stderr.txt",
        result.stderr,
    )
    write_json(
        step_directory / f"{filename_prefix}.command.json",
        asdict(result),
    )


def collect_step(
    output_directory: Path,
    step: dict[str, str],
    step_number: int,
) -> dict[str, Any]:
    step_directory = output_directory / step["slug"]
    step_directory.mkdir(parents=True, exist_ok=False)

    captured_at = dt.datetime.now().astimezone()
    
    print()
    print("正在采集，请暂时不要切换设备状态……")
    
    pmset_result = run_command(
        [PMSET_PATH, "-g", "accps"],
        timeout=15,
    )
    bluetooth_result = run_command(
        [
            SYSTEM_PROFILER_PATH,
            "SPBluetoothDataType",
            "-json",
        ]
    )
    audio_result = run_command(
        [
            SYSTEM_PROFILER_PATH,
            "SPAudioDataType",
            "-json",
        ]
    )
    
    save_command_result(
        step_directory,
        "pmset-accps",
        pmset_result,
    )
    save_command_result(
        step_directory,
        "bluetooth",
        bluetooth_result,
    )
    save_command_result(
        step_directory,
        "audio",
        audio_result,
    )
    
    bluetooth_json, bluetooth_json_error = (
        parse_json_safely(bluetooth_result.stdout)
    )
    audio_json, audio_json_error = (
        parse_json_safely(audio_result.stdout)
    )
    
    if bluetooth_json is not None:
        write_json(
            step_directory / "bluetooth.json",
            bluetooth_json,
        )
    
    if audio_json is not None:
        write_json(
            step_directory / "audio.json",
            audio_json,
        )
    
    accessory_records = parse_accessory_records(
        pmset_result.stdout
    )
    
    interesting_bluetooth = (
        extract_interesting_json(bluetooth_json)
        if bluetooth_json is not None
        else []
    )
    interesting_audio = (
        extract_interesting_json(audio_json)
        if audio_json is not None
        else []
    )
    
    write_json(
        step_directory / "accessory-records.json",
        [asdict(record) for record in accessory_records],
    )
    write_json(
        step_directory / "bluetooth-interesting.json",
        interesting_bluetooth,
    )
    write_json(
        step_directory / "audio-interesting.json",
        interesting_audio,
    )
    
    metadata = {
        "step_number": step_number,
        "slug": step["slug"],
        "title": step["title"],
        "instructions": step["instructions"],
        "captured_at": captured_at.isoformat(),
        "bluetooth_json_error": bluetooth_json_error,
        "audio_json_error": audio_json_error,
    }
    write_json(step_directory / "metadata.json", metadata)
    
    print()
    print("本步骤检测到的附件电源源：")
    
    if not accessory_records:
        print("  未检测到附件电源源")
    else:
        for record in accessory_records:
            name = record.name or "<匿名设备>"
            presence = (
                "present"
                if record.present
                else "not present"
            )
            print(
                f"  {name}: {record.level}% "
                f"[{record.state}, {presence}, "
                f"id={record.system_id}]"
            )
    
    return {
        **metadata,
        "skipped": False,
        "accessory_records": [
            asdict(record)
            for record in accessory_records
        ],
        "pmset_ok": (
            pmset_result.returncode == 0
            and not pmset_result.timed_out
            and pmset_result.error is None
        ),
        "bluetooth_ok": (
            bluetooth_result.returncode == 0
            and not bluetooth_result.timed_out
            and bluetooth_result.error is None
            and bluetooth_json_error is None
        ),
        "audio_ok": (
            audio_result.returncode == 0
            and not audio_result.timed_out
            and audio_result.error is None
            and audio_json_error is None
        ),
        "interesting_bluetooth": interesting_bluetooth,
        "interesting_audio": interesting_audio,
    }


def escape_markdown_cell(value: Any) -> str:
    return (
        str(value)
        .replace("|", "\\|")
        .replace("\n", " ")
    )


def render_record_name(record: dict[str, Any]) -> str:
    name = str(record.get("name", "")).strip()
    return name or "匿名设备"


def generate_markdown_report(
    output_directory: Path,
    system_info: dict[str, Any],
    step_results: list[dict[str, Any]],
) -> str:
    lines = [
        "# Battery Bar 多源诊断报告",
        "",
        f"- 生成时间：{dt.datetime.now().astimezone().isoformat()}",
        f"- 系统：{system_info.get('sw_vers_summary', '未知')}",
        f"- Python：{system_info.get('python_version', '未知')}",
        f"- 结果目录：`{output_directory}`",
        "",
        "## 电源源状态变化",
        "",
        "| 步骤 | 设备或部件 | 系统 ID | 电量 | 状态 | Present |",
        "|---|---|---:|---:|---|---|",
    ]

    for result in step_results:
        if result.get("skipped"):
            lines.append(
                f"| {escape_markdown_cell(result['title'])} "
                "| 已跳过 |  |  |  |  |"
            )
            continue
    
        records = result.get("accessory_records", [])
    
        if not records:
            lines.append(
                f"| {escape_markdown_cell(result['title'])} "
                "| 未发现附件电源源 |  |  |  |  |"
            )
            continue
    
        for record in records:
            lines.append(
                "| "
                + escape_markdown_cell(result["title"])
                + " | "
                + escape_markdown_cell(
                    render_record_name(record)
                )
                + " | "
                + escape_markdown_cell(
                    record.get("system_id", "")
                )
                + " | "
                + escape_markdown_cell(
                    str(record.get("level", "")) + "%"
                )
                + " | "
                + escape_markdown_cell(
                    record.get("state", "")
                )
                + " | "
                + escape_markdown_cell(
                    record.get("present", "")
                )
                + " |"
            )
    
    lines.extend(
        [
            "",
            "## 采集状态",
            "",
            "| 步骤 | pmset | 蓝牙 JSON | 音频 JSON |",
            "|---|---|---|---|",
        ]
    )
    
    for result in step_results:
        if result.get("skipped"):
            lines.append(
                f"| {escape_markdown_cell(result['title'])} "
                "| 跳过 | 跳过 | 跳过 |"
            )
            continue
    
        lines.append(
            f"| {escape_markdown_cell(result['title'])} "
            f"| {'成功' if result.get('pmset_ok') else '失败'} "
            f"| {'成功' if result.get('bluetooth_ok') else '失败'} "
            f"| {'成功' if result.get('audio_ok') else '失败'} |"
        )
    
    lines.extend(
        [
            "",
            "## 初步差分",
            "",
        ]
    )
    
    previous: Optional[dict[str, Any]] = None
    
    for result in step_results:
        if result.get("skipped"):
            continue
    
        if previous is None:
            previous = result
            continue
    
        previous_by_id = {
            item["system_id"]: item
            for item in previous.get(
                "accessory_records", []
            )
        }
        current_by_id = {
            item["system_id"]: item
            for item in result.get(
                "accessory_records", []
            )
        }
    
        added = sorted(
            set(current_by_id) - set(previous_by_id)
        )
        removed = sorted(
            set(previous_by_id) - set(current_by_id)
        )
        changed = []
    
        for system_id in (
            set(previous_by_id) & set(current_by_id)
        ):
            old = previous_by_id[system_id]
            new = current_by_id[system_id]
    
            fields = (
                "name",
                "level",
                "state",
                "present",
            )
            differences = [
                field
                for field in fields
                if old.get(field) != new.get(field)
            ]
    
            if differences:
                changed.append(
                    (system_id, differences, old, new)
                )
    
        lines.append(
            "### "
            + previous["title"]
            + " → "
            + result["title"]
        )
        lines.append("")
    
        if not added and not removed and not changed:
            lines.append("- 附件电源源没有可见变化。")
        else:
            for system_id in added:
                record = current_by_id[system_id]
                lines.append(
                    "- 新增："
                    f"{render_record_name(record)}，"
                    f"{record['level']}%，"
                    f"ID {system_id}。"
                )
    
            for system_id in removed:
                record = previous_by_id[system_id]
                lines.append(
                    "- 消失："
                    f"{render_record_name(record)}，"
                    f"最后电量 {record['level']}%，"
                    f"ID {system_id}。"
                )
    
            for (
                system_id,
                differences,
                old,
                new,
            ) in changed:
                changes = []
    
                for field in differences:
                    changes.append(
                        f"{field}: "
                        f"{old.get(field)!r} → "
                        f"{new.get(field)!r}"
                    )
    
                lines.append(
                    "- 变化："
                    f"{render_record_name(new)}，"
                    f"ID {system_id}；"
                    + "；".join(changes)
                    + "。"
                )
    
        lines.append("")
        previous = result
    
    lines.extend(
        [
            "## 文件说明",
            "",
            "每个步骤目录中包含：",
            "",
            "- `pmset-accps.stdout.txt`：附件电源源原始输出；",
            "- `bluetooth.json`：蓝牙系统报告；",
            "- `audio.json`：音频系统报告；",
            "- `accessory-records.json`：解析后的电源源；",
            "- `bluetooth-interesting.json`：筛选后的蓝牙字段；",
            "- `audio-interesting.json`：筛选后的音频字段；",
            "- `metadata.json`：步骤和采集时间；",
            "- `*.command.json`：命令返回状态及错误信息。",
            "",
        ]
    )
    
    return "\n".join(lines)


def collect_system_info() -> dict[str, Any]:
    sw_vers = run_command(
        [SW_VERS_PATH],
        timeout=15,
    )

    return {
        "captured_at": (
            dt.datetime.now().astimezone().isoformat()
        ),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_version": sys.version,
        "sw_vers_stdout": sw_vers.stdout,
        "sw_vers_stderr": sw_vers.stderr,
        "sw_vers_summary": "；".join(
            line.strip()
            for line in sw_vers.stdout.splitlines()
            if line.strip()
        ),
    }


def confirm_start() -> bool:
    print_heading("Battery Bar 多源电量完整诊断")

    print(
        "本脚本将分步骤提示你切换 AirPods 和 DJI Mic Mini 状态，\n"
        "并自动采集电源源、蓝牙和音频信息。"
    )
    print()
    print("注意：")
    print("- 所有系统命令均为只读。")
    print("- 不会取消设备配对。")
    print("- 每一步可能需要几十秒。")
    print("- 输入 s 可以跳过某一步。")
    print("- 输入 q 可以提前结束并生成已有结果的报告。")
    print()
    
    answer = input("输入 y 开始，其他内容退出：").strip().casefold()
    return answer == "y"


def main() -> int:
    try:
        ensure_environment()
    except Exception as error:
        print(f"环境检查失败：{error}", file=sys.stderr)
        return 1

    if not confirm_start():
        print("已取消。")
        return 0
    
    try:
        output_directory = ask_for_output_directory()
    except Exception as error:
        print(f"无法创建结果目录：{error}", file=sys.stderr)
        return 1
    
    print()
    print(f"结果将保存到：{output_directory}")
    
    system_info = collect_system_info()
    write_json(
        output_directory / "system-info.json",
        system_info,
    )
    
    step_results: list[dict[str, Any]] = []
    
    for index, step in enumerate(TEST_STEPS, start=1):
        print_heading(
            f"步骤 {index}/{len(TEST_STEPS)}：{step['title']}"
        )
        print(step["instructions"])
        print()
        print(
            "完成上述操作后稍等约 10 秒，再按回车采集。\n"
            "输入 s 跳过本步骤，输入 q 提前结束。"
        )
    
        answer = input("> ").strip().casefold()
    
        if answer == "q":
            print("提前结束测试，将生成已有结果的报告。")
            break
    
        if answer == "s":
            step_results.append(
                {
                    "step_number": index,
                    "slug": step["slug"],
                    "title": step["title"],
                    "instructions": step["instructions"],
                    "skipped": True,
                }
            )
            print("已跳过。")
            continue
    
        try:
            result = collect_step(
                output_directory,
                step,
                index,
            )
            step_results.append(result)
        except KeyboardInterrupt:
            print()
            print("收到中断，将生成已有结果的报告。")
            break
        except Exception as error:
            print(
                f"本步骤采集失败："
                f"{type(error).__name__}: {error}"
            )
            step_results.append(
                {
                    "step_number": index,
                    "slug": step["slug"],
                    "title": step["title"],
                    "instructions": step["instructions"],
                    "skipped": False,
                    "error": (
                        f"{type(error).__name__}: {error}"
                    ),
                    "accessory_records": [],
                    "pmset_ok": False,
                    "bluetooth_ok": False,
                    "audio_ok": False,
                }
            )
    
    write_json(
        output_directory / "all-results.json",
        {
            "system_info": system_info,
            "steps": step_results,
        },
    )
    
    report = generate_markdown_report(
        output_directory,
        system_info,
        step_results,
    )
    report_path = output_directory / "REPORT.md"
    write_text(report_path, report)
    
    archive_path: Optional[str] = None
    
    try:
        archive_path = shutil.make_archive(
            str(output_directory),
            "zip",
            root_dir=output_directory.parent,
            base_dir=output_directory.name,
        )
    except Exception as error:
        print(f"警告：无法生成 ZIP：{error}")
    
    print_heading("测试完成")
    print(f"报告：{report_path}")
    print(f"完整结果：{output_directory}")
    
    if archive_path:
        print(f"ZIP 压缩包：{archive_path}")
    
    print()
    print(
        "请优先提供 REPORT.md 的内容。若需要分析蓝牙和音频的"
        "具体标识，再提供生成的 ZIP 文件。"
    )
    
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print()
        print("已取消。")
        raise SystemExit(130)