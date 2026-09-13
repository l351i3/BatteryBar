# 门禁台账（本地化声明）

权威源：`~/.agents/skills/ai-engineering-retrofit/scripts/gates/`（canonical 七份）。
本项目分发 6 份：check_links / check_decisions / check_smoke / check_adr_tests / check_provenance / check_plan；聚合入口 scripts/gates/run_all.sh 含 gate-sync diff 块。

## 本地化声明

- **check_skill_quality.py 不分发**：本项目非 agent skill，无 SKILL.md 可查；run_all.sh 的 gate-sync diff 块相应缩减为 6 项（2026-09-14）。
- **check_smoke.py 在位但当前不适用**：项目无 .env、无外部连接配置，门禁走「无 .env 且无冒烟脚本」绿灯分支；未来引入 .env 时门禁自动生效（2026-09-14）。
- **check_provenance.py 使用默认 PATTERNS（SYNO.\*）**：本项目无群晖依赖，命中概率低；保持默认不扩展，避免维护项目专属模式（2026-09-14）。

## 先红验证记录

| 门禁 | 日期 | 方式 |
|------|------|------|
| check_links | 2026-08-16 / 2026-09-14 | fixture 死链 md → exit 1；2026-09-14 真红：主目录 LICENSE 死链 ×2 |
| check_decisions | 2026-08-16 / 2026-09-14 | implemented 注入 "- [ ]" → exit 1 |
| check_smoke | 2026-09-14 | touch .env（有 .env 无 smoke.sh）→ exit 1 |
| check_adr_tests | 2026-09-14 | fixture ADR 引用 test_fake_thing → exit 1 |
| check_provenance | 2026-09-14 | fixture 虚构 API 标识符无证据标记 → exit 1 |
| check_plan | 2026-09-14 | fixture approved 计划带未勾条目 → exit 1 |
| gate-sync | 2026-09-14 | 篡改 check_links.py 副本 → 红灯 → 恢复权威源 → 绿灯 |
