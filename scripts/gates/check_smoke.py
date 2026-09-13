#!/usr/bin/env python3
"""check_smoke.py — 外部连接冒烟新鲜度门禁（方法论第 1 条的机械执行件）。

契约（按序判定）：
1) 项目无 .env 且无 scripts/smoke.sh → 绿（无外部连接，不适用）
2) 有 .env 但无 scripts/smoke.sh → 红（有连接配置却无冒烟脚本）
3) 有 smoke.sh 但 state/smoke-ok.json 缺失 → 红（从未冒烟）
4) smoke-ok.json 缺 at/checks 字段 → 红（标记损坏，重跑 scripts/smoke.sh）
5) .env 的 mtime 晚于 smoke-ok 的 at → 红（配置改过未重冒烟——m-team-finder
   2026-09 拼写事故复盘：参数变更后必须重新冒烟，业务脚本才允许继续）

smoke 契约：scripts/smoke.sh 由项目提供（模板见
ai-engineering-retrofit/references/templates.md 第十一节），成功时写
state/smoke-ok.json = {"at": <epoch>, "checks": ["ssh", ...]}，失败 exit 非零。
已知局限：NAS 侧部署脚本（scripts/nas/）的时间戳不参与比对（远端状态本地不可见）。

已验证会红：2026-09-09，fixture（有 .env 无 smoke / smoke-ok 早于 .env mtime）→ exit 1。
用法：python3 check_smoke.py [项目根]（默认为调用者所在目录向上找 .env 的项目）
"""
import json
import os
import sys
from pathlib import Path


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    env = root / ".env"
    smoke_sh = root / "scripts" / "smoke.sh"
    smoke_ok = root / "state" / "smoke-ok.json"

    if not env.exists() and not smoke_sh.exists():
        print("[check_smoke] 绿灯（无 .env 且无冒烟脚本，不适用）")
        return 0
    if env.exists() and not smoke_sh.exists():
        print(f"[check_smoke] 红灯：{root} 有 .env（外部连接配置）但缺 scripts/smoke.sh——"
              f"复制模板建立冒烟脚本（见 ai-engineering-retrofit/references/templates.md 第十一节）")
        return 1
    if not smoke_ok.exists():
        print(f"[check_smoke] 红灯：从未冒烟——先跑 bash scripts/smoke.sh（业务逻辑开发前）")
        return 1
    try:
        mark = json.loads(smoke_ok.read_text(encoding="utf-8"))
        at = float(mark["at"])
        checks = mark["checks"]
        assert isinstance(checks, list) and checks
    except (ValueError, KeyError, AssertionError, TypeError):
        print(f"[check_smoke] 红灯：{smoke_ok} 损坏（需 at + checks）——重跑 bash scripts/smoke.sh")
        return 1
    if env.exists() and env.stat().st_mtime > at:
        print(f"[check_smoke] 红灯：.env 在最近一次冒烟之后被修改过——配置变更必须重新冒烟："
              f"bash scripts/smoke.sh（执行者：本门禁；方法论第 1 条）")
        return 1
    names = ", ".join(str(c) for c in checks)
    print(f"[check_smoke] 绿灯（冒烟新鲜：{names}；.env 未变更）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
