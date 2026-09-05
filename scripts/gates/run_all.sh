#!/bin/bash
# 交付前门禁聚合入口。触发方式：pre-push 钩子（git 侧）+ 交付前手动跑（主目录无 git）
# 先红验证：2026-08-16，check_links（AGENTS.md 注入死链 → exit 1）
#           check_decisions（implemented 注入 "- [ ]" → exit 1）
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fail=0
python3 "$DIR/scripts/gates/check_links.py" "$DIR" || fail=1
python3 "$DIR/scripts/gates/check_decisions.py" "$DIR" || fail=1
if [ "$fail" -eq 0 ]; then echo "[run_all] 全部绿灯"; else echo "[run_all] 存在红灯，交付前必须修复"; fi
exit "$fail"
