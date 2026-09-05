#!/usr/bin/env python3
"""文档死链检查（门禁）。

范围：目标目录下所有手写 .md（排除 state/、daily-reports/ 等生成物目录）。
规则：显式 markdown 链接 [text](target) 中的本地路径必须存在（剥离 #锚点后解析）。
边界（v1 有意收窄，防假阳性）：外部 http(s)/mailto 链接不联网校验；锚点可达性不校验。
信号源取严格档——只认显式 markdown 链接，散文里的裸文件名不算声称。
已验证会红：2026-09-04，fixture 含死链 → exit 1；修复后 → exit 0。
用法：python3 check_links.py [目标目录]（默认为本 skill 根目录）
"""
import re
import sys
from pathlib import Path

SKIP_DIRS = {"state", "daily-reports", ".git", "__pycache__", "node_modules"}
FENCE_RE = re.compile(r"```.*?```", re.S)
CODE_SPAN_RE = re.compile(r"`[^`\n]*`")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\n]+)\)")


def iter_md(root: Path):
    for p in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        yield p


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
    if not root.exists():
        print(f"[check_links] 红灯：目标目录不存在 {root}")
        return 1
    errors = []
    files = list(iter_md(root))
    for md in files:
        text = CODE_SPAN_RE.sub("", FENCE_RE.sub("", md.read_text(encoding="utf-8")))
        for m in LINK_RE.finditer(text):
            target = m.group(1).strip().strip("<>").split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:", "ftp:")):
                continue
            if not (md.parent / target).resolve().exists():
                errors.append(f"{md.relative_to(root)}: 死链 -> {target}")
    if errors:
        print(f"[check_links] 红灯：{len(errors)} 个死链")
        for e in errors:
            print("  " + e)
        return 1
    print(f"[check_links] 绿灯：{len(files)} 个 md 文件的本地链接全部可达（http 链接 v1 不校验）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
