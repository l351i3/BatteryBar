# 「性质 → 执行者」盘点表

日期：2026-08-16 · 依据：《AI 工程约束落地方案》附录四 · 本项目首次盘点。
范围：BatteryBar-clean（git 仓库、发布源）；BatteryBar 主目录经 `同步约定` 跟进（见 #12）。

| # | 想要的性质 | 执行者（具体） | 层级(结构/门禁/散文) | 生效阶段 | 自己坏了会怎样 | 空缺处理 |
|---|-----------|---------------|---------------------|---------|---------------|---------|
| 1 | 数据模型合法（level 0-100、power_state 与 charging 一致） | `models.BatteryDevice.__post_init__` 构造期校验（结构） | 结构 | 运行时（构造时抛 ValueError） | 非法设备对象无法构造，构造处崩溃暴露 | 已有 |
| 2 | 每条 pmset 记录的电量在 0-100 | `system_provider.parse_accessory_power` 的 `0 <= level <= 100` 过滤（结构） | 结构 | 解析时静默丢弃非法行 | 非法行被丢弃（可接受：垃圾进不出） | 已有 |
| 3 | 113 个单元测试全绿才能交付 | `python3 -m pytest tests/ -q` + `build_release_final.sh` 第 3 步内嵌 unittest（门禁） | 门禁 | 交付/构建时 | 构建脚本 `set -e` 使测试失败即构建失败 | 已有 |
| 4 | decisions/ 目录结构合规（生命周期×类别封闭集合、proposed 必需章节、implemented 无规格语气残留） | `scripts/gates/check_decisions.py`（门禁，2026-08-16 先红验证） | 门禁 | 交付前手动 / pre-push | exit 1 红灯，交付被拦 | 本次新增 |
| 5 | 文档内本地链接不死 | `scripts/gates/check_links.py`（门禁，2026-08-16 先红验证） | 门禁 | 交付前手动 / pre-push | exit 1 红灯 | 本次新增 |
| 6 | 交付前两个门禁 + 测试都跑过 | `scripts/gates/run_all.sh` 聚合入口（门禁；git 侧挂 pre-push，无 git 的主目录靠交付前手动） | 门禁 | 交付前 | pre-push 拒绝推送 / 手动跑时红灯 | 本次新增 |
| 7 | 版本号四处一致（app.py / Info.plist / spec / build_release*.sh） | 评审必看项：版本相关 PR 必查四文件（散文→评审）；v2.1.2 已对齐 | 散文 | 改版本时 | 版本漂移（曾发生 2.1.0/2.1.1 不一致） | 降级为评审必看项（构建期 `plutil -replace` 会覆盖 Info.plist/spec 的值，真正要盯的是 app.py 与 build 脚本 VERSION） |
| 8 | 设备休眠读名失败不覆盖真名 | `hidpp_provider._DEVICE_NAME_CACHE` 模块级缓存（结构） | 结构 | 运行时 | fallback 名回潮（已修，见 DEVELOPMENT.md §14.18） | 已有 |
| 9 | aggregator 不把 cached 当有效数据源 | `aggregator._prefer` 非缓存优先 + `_select_menu_icon` 跳过 cached（结构） | 结构 | 运行时 | 离线设备触发虚假低电量警报（已修） | 已有 |
| 10 | 备份文件/调试脚本/AI 对话记录不进仓库 | `.gitignore` 规则（结构）+ pre-push 时 git 自然隔离 | 结构 | 提交时 | 仓库膨胀、个人信息泄露（曾清理 2940→78 文件） | 已有；`tabbit_*.md` 例外见 #13 |
| 11 | 构建产物（dist/build/build-release）不进仓库 | `.gitignore` + `git status` 可见性 | 结构 | 提交时 | 仓库膨胀 206MB（曾发生并已重写历史） | 已有 |
| 12 | 主目录改动同步到 clean 仓库 | 评审必看项：改动主目录后必须 `cp` 变更文件到 clean 并 `git push`（散文） | 散文 | 每次改动后 | 两目录漂移（本会话早期发生过） | 降级为评审必看项（曾考虑写同步脚本，见 ADR-2026-08-16-process-2） |
| 13 | `tabbit_*.md`（AI 对话记录，含个人信息）不进仓库 | `.gitignore` 规则 `tabbit_*.md`（结构） | 结构 | 提交时 | 个人信息泄露 | 有意接受：主目录保留本地副本便于查阅，clean 仓库已隔离 |
| 14 | AGENTS.md 与实际命令/结构不漂移 | 月度人工盘点（散文）：重读 AGENTS.md 对照 `ls tests/`、构建脚本步骤 | 散文 | 每月 | 规则文件腐烂 | 有意接受：项目单人维护，月度频率足够 |
| 15 | 重量级文档先于代码改（DEVELOPMENT.md 是权威描述） | 评审必看项：改 provider/aggregator 行为的 PR 必须同步 DEVELOPMENT.md 对应章节 + CHANGELOG | 散文 | 改动时 | 文档漂移（check_links 只能抓链接死，抓不住内容过期） | 降级为评审必看项 |

**统计**：规则 15 条 · 结构层 8 · 门禁层 4 · 散文层 3 · 有意接受的风险 3（#13 本地隐私文件保留、#14 月度人工盘点、#7 版本一致性靠评审）。

**值回票价的发现**：
- **文档漂移**：① `tests/test_hidpp_provider.py-202607292031` 垃圾备份文件混在 git 仓库的 tests/ 里，`pytest tests/` 不收集（文件名不以 test_ 开头无妨——实际以 `test_hidpp_provider.py-` 开头不匹配 `test_*.py` 模式，无执行影响，但属仓库垃圾）→ 第 3 步清理并记 ADR；② DEVELOPMENT.md §15 称 `diagnose.sh` "随 Full 包分发（diagnose_safely.sh）"，构建脚本第 6 步确实复制并改名——核实后一致，无漂移；③ app.py 约 950 行，接近 800 行重力井阈值 → 第 2 步写入 AGENTS.md。
- **裸奔规则**：版本一致性（#7）、双目录同步（#12）、文档同步（#15）原本都是"大家注意"式散文，已降级标注为评审必看项并写明具体查什么。
