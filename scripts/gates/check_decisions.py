#!/usr/bin/env python3
"""决策记录结构检查（门禁）。

规则：
1) decisions/ 下每份记录必须位于 <生命周期>/<类别>/ 两层目录内；
   生命周期 ∈ {proposed, implemented, rejected, archived}（封闭集合）；
   类别 ∈ {feature, fix, simplify, architecture, process, testing}（封闭集合）。
2) 文件名必须为 YYYY-MM-DD-<主题>.md。
3) proposed 必含章节：## Problem / ## Proposal / ## Alternatives considered。
4) implemented 不得残留规格语气：未勾选任务 "- [ ]"、将来时标志"我们打算"。
decisions/ 根目录的 README 等单层文件豁免（制度文档本身）。
判定阈值刻意收窄（只查确定性、低歧义的结构事实），避免把判断题做成假阳性门禁。
已验证会红：2026-09-04，fixture（非法类别目录 + 缺必需章节的 proposed）→ exit 1。
用法：python3 check_decisions.py [目标目录]（默认为本 skill 根目录）
"""
import re
import sys
from pathlib import Path

LIFECYCLE = {"proposed", "implemented", "rejected", "archived"}
CATEGORY = {"feature", "fix", "simplify", "architecture", "process", "testing"}
DATE_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-.+\.md$")


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
    droot = root / "decisions"
    if not droot.exists():
        print("[check_decisions] 绿灯（无 decisions/ 目录，尚未建档）")
        return 0
    errors = []
    for p in sorted(droot.rglob("*.md")):
        rel = p.relative_to(droot)
        if len(rel.parts) == 1:  # README 等制度文档
            continue
        if len(rel.parts) != 3:
            errors.append(f"decisions/{rel}: 应位于 <生命周期>/<类别>/ 两层目录内")
            continue
        life, cat, name = rel.parts
        if life not in LIFECYCLE:
            errors.append(f"decisions/{rel}: 生命周期 '{life}' 非法（封闭集合 {sorted(LIFECYCLE)}）")
        if cat not in CATEGORY:
            errors.append(f"decisions/{rel}: 类别 '{cat}' 非法（封闭集合 {sorted(CATEGORY)}）")
        if not DATE_NAME_RE.match(name):
            errors.append(f"decisions/{rel}: 文件名需为 YYYY-MM-DD-<主题>.md")
        text = p.read_text(encoding="utf-8")
        if life == "proposed":
            for sec in ("## Problem", "## Proposal", "## Alternatives considered"):
                if sec not in text:
                    errors.append(f"decisions/{rel}: proposed 缺少必需章节 '{sec}'")
        if life == "implemented":
            if "- [ ]" in text:
                errors.append(f"decisions/{rel}: implemented 含未勾选任务 '- [ ]'（规格语气残留）")
            if "我们打算" in text:
                errors.append(f"decisions/{rel}: implemented 含将来时残留'我们打算'")
    if errors:
        print(f"[check_decisions] 红灯：{len(errors)} 个结构问题")
        for e in errors:
            print("  " + e)
        return 1
    print("[check_decisions] 绿灯（生命周期/类别/命名/必需章节/规格语气全部合规）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
