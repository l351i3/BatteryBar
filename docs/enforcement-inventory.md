# 「性质 → 执行者」盘点表

日期：2026-08-16 首次盘点 · 2026-09-14 v2 门禁装配更新 · 依据：《AI 工程约束落地方案》附录四。
范围：BatteryBar 主目录（本表所在仓库，非 git）与 BatteryBar-clean（git 发布源）两个目录装配同一套产物，门禁以权威源副本 + gate-sync 保持一致。

| # | 想要的性质 | 执行者（具体） | 层级(结构/门禁/散文) | 生效阶段 | 自己坏了会怎样 | 空缺处理 |
|---|-----------|---------------|---------------------|---------|---------------|---------|
| 1 | 数据模型合法（level 0-100、power_state 与 charging 一致） | `models.BatteryDevice.__post_init__` 构造期校验（结构） | 结构 | 运行时（构造时抛 ValueError） | 非法设备对象无法构造，构造处崩溃暴露 | 已有 |
| 2 | 每条 pmset 记录的电量在 0-100 | `system_provider.parse_accessory_power` 的 `0 <= level <= 100` 过滤（结构） | 结构 | 解析时静默丢弃非法行 | 非法行被丢弃（可接受：垃圾进不出） | 已有 |
| 3 | 113 个单元测试全绿才能交付 | `python3 -m pytest tests/ -q` + `build_release_final.sh` 第 3 步内嵌 unittest（门禁） | 门禁 | 交付/构建时 | 构建脚本 `set -e` 使测试失败即构建失败 | 已有 |
| 4 | decisions/ 目录结构合规（生命周期×类别封闭集合、proposed 必需章节、implemented 无规格语气残留、无 INDEX.md） | `scripts/gates/check_decisions.py`（门禁；2026-08-16 先红，2026-09-14 复红） | 门禁 | 交付前手动 / pre-push | exit 1 红灯，交付被拦 | 已有 |
| 5 | 文档内本地链接不死 | `scripts/gates/check_links.py`（门禁；2026-08-16 先红，2026-09-14 真红抓到 LICENSE 死链×2） | 门禁 | 交付前手动 / pre-push | exit 1 红灯 | 已有 |
| 6 | 交付前六个门禁 + 权威源一致性都跑过 | `scripts/gates/run_all.sh` 聚合入口（门禁；主目录交付前手动 + 月度盘点，clean 仓库 pre-push 钩子） | 门禁 | 交付前 | pre-push 拒绝推送 / 手动跑时红灯 | 已有 |
| 7 | 版本号四处一致（app.py / Info.plist / spec / build_release*.sh） | 评审必看项：版本相关 PR 必查四文件（散文→评审）；v2.1.2 已对齐 | 散文 | 改版本时 | 版本漂移（曾发生 2.1.0/2.1.1 不一致） | 降级为评审必看项（构建期 `plutil -replace` 会覆盖 Info.plist/spec 的值，真正要盯的是 app.py 与 build 脚本 VERSION） |
| 8 | 设备休眠读名失败不覆盖真名 | `hidpp_provider._DEVICE_NAME_CACHE` 模块级缓存（结构） | 结构 | 运行时 | fallback 名回潮（已修，见 DEVELOPMENT.md §14.18） | 已有 |
| 9 | aggregator 不把 cached 当有效数据源 | `aggregator._prefer` 非缓存优先 + `_select_menu_icon` 跳过 cached（结构） | 结构 | 运行时 | 离线设备触发虚假低电量警报（已修） | 已有 |
| 10 | 备份文件/调试脚本/AI 对话记录不进仓库 | `.gitignore` 规则（结构）+ pre-push 时 git 自然隔离 | 结构 | 提交时 | 仓库膨胀、个人信息泄露（曾清理 2940→78 文件） | 已有；`tabbit_*.md` 例外见 #13 |
| 11 | 构建产物（dist/build/build-release）不进仓库 | `.gitignore` + `git status` 可见性 | 结构 | 提交时 | 仓库膨胀 206MB（曾发生并已重写历史） | 已有 |
| 12 | 主目录改动同步到 clean 仓库 | 评审必看项：改动主目录后必须 `cp` 变更文件到 clean 并 `git push`（散文） | 散文 | 每次改动后 | 两目录漂移（本会话早期发生过） | 降级为评审必看项（曾考虑写同步脚本，见 [ADR](../decisions/rejected/process/2026-08-16-auto-sync-script.md)） |
| 13 | `tabbit_*.md`（AI 对话记录，含个人信息）不进仓库 | `.gitignore` 规则 `tabbit_*.md`（结构） | 结构 | 提交时 | 个人信息泄露 | 有意接受：主目录保留本地副本便于查阅，clean 仓库已隔离 |
| 14 | AGENTS.md 与实际命令/结构不漂移 | 月度人工盘点（散文）：重读 AGENTS.md 对照 `ls tests/`、构建脚本步骤 | 散文 | 每月 | 规则文件腐烂 | 有意接受：项目单人维护，月度频率足够 |
| 15 | 重量级文档先于代码改（DEVELOPMENT.md 是权威描述） | 评审必看项：改 provider/aggregator 行为的 PR 必须同步 DEVELOPMENT.md 对应章节 + CHANGELOG | 散文 | 改动时 | 文档漂移（check_links 只能抓链接死，抓不住内容过期） | 降级为评审必看项 |
| 16 | 外部连接配置变更后必须重冒烟 | `scripts/gates/check_smoke.py`（门禁，2026-09-14 先红）——本项目当前无 .env 无外部连接，门禁走 N/A 绿灯分支但保持装配 | 门禁 | 交付前 | 未来引入 .env 时无冒烟即红灯拦截 | 已有（N/A 预防性装配） |
| 17 | implemented ADR 引用的测试真实存在（防"宣布完成但执行者不存在"） | `scripts/gates/check_adr_tests.py`（门禁，2026-09-14 先红：fixture 引用 test_fake_thing → exit 1） | 门禁 | 交付前 | ADR 引用不存在的测试时红灯 | 本次新增 |
| 18 | 外部系统断言必须带证据标记（防理论污染文档） | `scripts/gates/check_provenance.py`（门禁，2026-09-14 先红：虚构 API 标识符无标记 → exit 1）；未验证理论住 docs/hypotheses.md 台账 | 门禁 | 写入时（跑门禁即查） | 无溯源断言写入 ADR/docs 时红灯 | 本次新增 |
| 19 | 获批计划的需求台账全落实 | `scripts/gates/check_plan.py`（门禁，2026-09-14 先红：approved 计划带未勾条目 → exit 1）；计划住 docs/plans/ | 门禁 | 交付前 | 获批计划未落实时红灯，.gates-passed 不刷新 | 本次新增 |
| 20 | 门禁脚本与权威源一致（防副本漂移/篡改） | run_all.sh 内 gate-sync diff 块（门禁，2026-09-14 负路径：篡改 check_links.py 副本 → 红灯 → 恢复 → 绿灯） | 门禁 | 交付前 | 副本被改或落后权威源时红灯 | 本次新增 |
| 21 | AGENTS.md 引用的决策记录真实存在 | 引用一律写 markdown 链接（结构约定）+ `check_links.py` 守死链（门禁） | 门禁 | 交付前 | 死引用（如曾引用不存在的 ADR-2026-08-16-process-1）被抓红 | 本次新增（8/16 的裸引用改链接并补写 ADR） |

**统计**：规则 21 条 · 结构层 7 · 门禁层 10 · 散文层 4 · 有意接受的风险 4（#13 本地隐私文件保留、#14 月度人工盘点、#7 版本一致性靠评审、tests/ 内备份文件无机械门禁靠评审——见 [ADR](../decisions/implemented/process/2026-08-16-tests-backup-files.md)）。

**值回票价的发现**：
- **2026-08-16 首次盘点**：① `tests/test_hidpp_provider.py-202607292031` 垃圾备份混入仓库 tests/ → 清理并记 ADR（该 ADR 当时未落盘，2026-09-14 补写，见上）；② app.py 956 行、build_release_final.sh 483 行越过重力井阈值 → 写入 AGENTS.md；③ 版本一致性/双目录同步/文档同步三条"大家注意"式规则降级为评审必看项。
- **2026-09-14 v2 装配批次**：① 9/5 会话半成品——主目录只写了 AGENTS.md + 盘点表，decisions/ 与 scripts/gates/ 从未建立，AGENTS.md 引用 `decisions/README.md` 为死链 → 本次补齐全套；② AGENTS.md 引用不存在的 ADR-2026-08-16-process-1（纯文本引用，链接门禁抓不到）→ 补写 ADR 并把全部 ADR 引用改为 markdown 链接（#21，此后门禁可守）；③ 主目录缺 LICENSE 文件 → README/README_EN 死链 ×2，check_links 首跑真红抓到 → 从 clean 补齐；④ clean 仓库 check_decisions.py 落后权威源一个版本（缺 INDEX.md 禁令）→ 分发时以权威源覆盖，gate-sync 块防复发；⑤ 触发方式漂移——主目录非 git 却写"git pre-push 也会触发"→ 两仓库 AGENTS.md 分别诚实标注（主目录手动+月度盘点，clean pre-push 钩子核实真实存在）。
