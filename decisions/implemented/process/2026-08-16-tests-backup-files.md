# tests/ 目录不留带后缀的备份文件

## Decision

tests/ 目录只存放 `test_*.py` 形式的正式单元测试与 `__init__.py`，任何编辑器/会话产生的带日期或 `.bak` 后缀的副本一律不进 tests/，也不进 git 仓库（`--` 后缀如 `hidpp_provider` 测试文件的 `202607292031` 日期后缀副本、`.bak` / `.backup-*` 变体同理）。主目录（非 git）可以保留工作副本作个人回溯用，但同步到 clean 仓库时必须排除（`.gitignore` 已隔离）。

## 前提

- pytest 默认收集模式为 `test_*.py`，带日期后缀的文件名（如以数字结尾）不匹配该 glob，因此垃圾副本不会被 pytest 执行——风险仅限仓库卫生与误导阅读，不影响测试结果（依据：pytest 文档默认 `python_files = test_*.py`；实测 `python3 -m pytest tests/ --collect-only -q` 收集数 113，与 tests/ 下 8 个正式文件的函数总数一致，2026-09-14）。

## Consequences

- clean 仓库 tests/ 中的 `202607292031` 后缀副本已于 2026-08-16 清理（核实：tests/ 目录已无该文件），清理后收集数不变，证明它从未被收集执行。
- 后续若 tests/ 再出现带后缀副本，靠评审必看项发现（无机械门禁——有意接受，见盘点表 #10/#14）。
- 同类规则已登记 AGENTS.md「建议（非强制）」节，指向本 ADR。

## Alternatives considered

- **pytest 配置 `collect_ignore` 显式忽略带后缀文件**：落选。治标不治本——垃圾文件仍留在仓库里占位、误导读者，且每出现一种新后缀都要维护忽略清单；正确做法是不让垃圾文件进 tests/。
- **放宽/收紧 pytest 收集模式（`python_files`）以兼容或拦截副本**：落选。动测试基础设施影响所有测试文件的命名契约，为一个文件卫生问题付出全局复杂度，不成比例。
