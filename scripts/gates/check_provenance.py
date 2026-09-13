#!/usr/bin/env python3
"""check_provenance.py — 外部系统断言的证据来源门禁（防"理论写得到处都是"）。

契约：decisions/implemented/**/*.md 与 docs/*.md（hypotheses.md 台账豁免——
它本来就是放未验证/已证伪理论的地方）中，凡出现外部系统标识符
（默认 SYNO.* API 名；PATTERNS 常量可按项目扩展），该文件必须同时携带
至少一个证据来源/状态标记（MARKERS），否则红灯并列出未溯源的标识符。

依据：方法论第 4/7 条——技术断言必须挂证据；未验证理论只住隔离台账。
背景：m-team-finder 2026-09 会话把虚构的 SYNO.DownloadStation.Setting
写进了脚本+ADR+spec（后被 SYNO.API.Info 实测证伪），清理靠人肉 grep 且有残留。

已验证会红：2026-09-11，fixture（implemented ADR 含 SYNO.Fake.API 且无任何标记）→ exit 1。
用法：python3 check_provenance.py [项目根]
"""
import re
import sys
from pathlib import Path

# 外部系统标识符模式（命中即要求该文件携带证据标记；按项目在副本中扩展后须登记台账）
PATTERNS = [re.compile(r"\bSYNO\.[A-Za-z][A-Za-z0-9.]*")]
# 证据来源 / 诚实状态标签（任一出现即视为已溯源）
MARKERS = ["实测", "源码", "官方文档", "文档原文", "同款", "抓包",
           "SYNO.API.Info", "单次观测", "已证伪", "证伪", "用户确认"]
EXEMPT_DOCS = {"hypotheses.md"}


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    targets = list((root / "decisions" / "implemented").rglob("*.md")) if (root / "decisions" / "implemented").is_dir() else []
    docs = root / "docs"
    if docs.is_dir():
        targets += [p for p in docs.glob("*.md") if p.name not in EXEMPT_DOCS]
    if not targets:
        print("[check_provenance] 绿灯（无 implemented ADR / docs，不适用）")
        return 0

    errors = []
    for p in sorted(targets):
        text = p.read_text(encoding="utf-8", errors="replace")
        ids = sorted({m.group(0) for pat in PATTERNS for m in pat.finditer(text)})
        if ids and not any(mk in text for mk in MARKERS):
            rel = p.relative_to(root)
            errors.append(f"{rel}: 出现外部系统断言 {ids} 但全文无证据标记"
                          f"（{MARKERS[:6]}…）——未验证理论只准住 docs/hypotheses.md")
    if errors:
        print(f"[check_provenance] 红灯：{len(errors)} 个文件的外部断言未溯源")
        for e in errors:
            print("  " + e)
        return 1
    print(f"[check_provenance] 绿灯（{len(targets)} 个文件的 {sum(1 for _ in targets)} 项检查通过：外部断言均带来源/状态标记）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
