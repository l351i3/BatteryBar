#!/bin/bash
# 交付前门禁聚合入口。触发方式：pre-push 钩子（.git/hooks/pre-push）+ 交付前手动跑
# 先红验证：2026-08-16，check_links（AGENTS.md 注入死链 → exit 1）
#           check_decisions（implemented 注入 "- [ ]" → exit 1）
# v2 2026-09-14：接入 check_smoke / check_adr_tests / check_provenance / check_plan
#           + gate-sync 权威源一致性；六门禁负路径 fixture 各一次均 exit 1（见主目录同脚本）
set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AUTH="$HOME/.agents/skills/ai-engineering-retrofit/scripts/gates"
fail=0
# 门禁与权威源一致性（权威源：~/.agents/skills/ai-engineering-retrofit/scripts/gates/；
# check_skill_quality 不分发——本项目非 agent skill，见 docs/gates-ledger.md）
for g in check_links.py check_decisions.py check_smoke.py check_adr_tests.py check_provenance.py check_plan.py; do
  diff -q "$AUTH/$g" "$DIR/scripts/gates/$g" >/dev/null 2>&1 || { echo "[gate-sync] 红灯：$g 与权威源不一致"; fail=1; }
done
python3 "$DIR/scripts/gates/check_links.py" "$DIR" || fail=1
python3 "$DIR/scripts/gates/check_decisions.py" "$DIR" || fail=1
python3 "$DIR/scripts/gates/check_smoke.py" "$DIR" || fail=1
python3 "$DIR/scripts/gates/check_adr_tests.py" "$DIR" || fail=1
python3 "$DIR/scripts/gates/check_provenance.py" "$DIR" || fail=1
python3 "$DIR/scripts/gates/check_plan.py" "$DIR" || fail=1
# 单元测试（113 个）不属于本门禁——改 provider/aggregator/models 后单独跑 pytest，见 AGENTS.md
if [ "$fail" -eq 0 ]; then
  echo "[run_all] 全部绿灯"
  # 全绿写 .gates-passed 标记：外发动作以标记新鲜度放行/阻断
  python3 -c 'import json,sys,time; json.dump({"at":time.time(),"by":"run_all"}, open(sys.argv[1]+"/.gates-passed","w"))' "$DIR"
else
  echo "[run_all] 存在红灯，交付前必须修复（不写门禁标记）"
fi
exit "$fail"
