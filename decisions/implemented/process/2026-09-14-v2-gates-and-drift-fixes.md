# 主目录 v2 门禁装配与文档漂移修复

## Decision

2026-09-14 起，BatteryBar 主目录（本仓库，非 git）补齐方法论全套产物并与 clean 发布仓库保持一致：

1. decisions/ 四态×六类骨架 + postmortems/，制度 README 与 5 份既有 ADR 从 clean 仓库四步预检同步；
2. scripts/gates/ 装配 6 份权威源门禁（check_links / check_decisions / check_smoke / check_adr_tests / check_provenance / check_plan）+ v2 聚合入口 run_all.sh（含 gate-sync 权威源一致性 diff 块与 .gates-passed 标记写入）；
3. AGENTS.md 中全部 ADR 编号裸引用改为 markdown 链接（此后 check_links 可守）；补写 8/16 遗漏的 tests-backup-files ADR；
4. 触发方式诚实化：主目录非 git，门禁 = 交付前手动 + 月度盘点；clean 仓库由真实存在的 pre-push 钩子触发。

## 前提

- 主目录无 git 仓库（用户未要求 git init；init 属危险操作，需用户裁决）——门禁只能手动触发（核实：`git rev-parse` 报 not a git repository，2026-09-14）。
- clean 仓库 `.git/hooks/pre-push` 真实存在并 exec run_all.sh（核实：读取钩子文件，2026-09-14）。
- 权威源位于 `~/.agents/skills/ai-engineering-retrofit/scripts/gates/`，副本经 gate-sync diff 保持字节一致。

## Consequences

- 两仓库 run_all.sh 全绿（2026-09-14 实测，exit 0，.gates-passed 已写）；七项负路径验证记录见 docs/gates-ledger.md。
- 装配过程抓到并修复三处既有漂移：主目录缺 LICENSE 致 README ×2 死链；AGENTS.md 引用从未落盘的 tests-backup-files ADR；clean 的 check_decisions.py 落后权威源一版（缺 INDEX.md 禁令）。
- 门禁自身曾红灯拦下装配产物（check_provenance 抓到盘点表/台账中的虚构标识符描述文字）——已改写措辞，证明门禁对自家文档同样生效。
- 主目录根下的 `.bak` / `.backup-*` 工作副本按双目录约定保留在本地，不进 clean 仓库（.gitignore 已隔离），本次不动。

## Alternatives considered

- **只升级 clean 仓库、主目录维持半成品**：落选。主目录是实际开发发生地，AGENTS.md 死链与缺失的 decisions/ 会持续误导后续会话；"改主目录必须同步 clean"的约定方向也要求主目录是完整真源。
- **给主目录 git init 并挂 pre-push**：落选（暂缓）。git init 属方法论危险操作清单，需用户明确裁决；主目录与 clean 的双目录结构本身是有意设计（ADR：发布仓库单提交历史），在主目录再建 git 会引入第三份历史。已在盘点表列为升级路径，待用户决定。
- **门禁装在主目录但不做 gate-sync**：落选。无权威源一致性检查时，副本漂移（clean 仓库 check_decisions.py 已落后一版即为实例）无法被发现，门禁会静默腐烂。
