# Battery Bar

macOS 菜单栏外设电量监控工具（Apple Silicon）。三个数据源（system_profiler+pmset / BLE GATT / 罗技 HID++）经聚合器去重合并，四态菜单栏图标。**权威文档：[DEVELOPMENT.md](DEVELOPMENT.md)**（架构、协议细节、已踩过的坑）；决策依据在 [decisions/README.md](decisions/README.md)；规则盘点在 [docs/enforcement-inventory.md](docs/enforcement-inventory.md)。

## 仓库布局

```
app.py                  # 菜单栏 UI（rumps）+ 四态图标 —— 重力井，见「改动规模」
aggregator.py           # 多源聚合、去重、优先级合并、离线缓存
system_provider.py      # system_profiler + pmset 解析（含 AirPods 匿名条目充电匹配）
bluetooth_provider.py   # BLE GATT（CoreBluetooth，GCD 串行队列）
hidpp_provider.py       # 罗技 HID++ 2.0（模块级名字缓存）
classifier.py models.py # 分类器 / 数据模型（BatteryDevice 构造期校验是合法性守门人）
snapshot_store.py widget_snapshot_sync.py   # 快照持久化 / Widget 沙盒同步（只归这两个模块写，禁止手改 ~/Library 下的 snapshot.json）
resources/              # 图标资源（Info.plist 版本号会被构建脚本覆盖）
tests/                  # 113 个单元测试，test_*.py 模式自动收集
decisions/              # 决策记录（路径即元数据，禁止 INDEX.md）
scripts/gates/          # 交付门禁
build_release_final.sh  # 主构建脚本（内嵌生成 DMG 里的安装脚本——改安装逻辑必须改这里的 heredoc）
```

## 命令

```bash
python3 -m pytest tests/ -q        # 全部单元测试（113 个）；改任何 provider/aggregator/models 后跑
bash build_release_final.sh        # 完整发布构建：依赖→测试→打包→签名→DMG；测试失败即构建失败
bash scripts/gates/run_all.sh      # 交付门禁聚合（死链 + decisions 结构）；git pre-push 也会触发
/opt/homebrew/bin/gh release create vX.Y.Z dist/*.dmg   # 发 Release；gh 已登录，无需 token
```

### 只跑相关的检查

- 改单个 provider → 只跑 `pytest tests/test_<该provider>.py -q`，交付前再全量
- 改 markdown / decisions → 只跑 `run_all.sh`（不跑 pytest）
- 纯文案改动（注释、README）→ 不跑 pytest；`run_all.sh` 仍要过
- **不跑**：`bash build_release.sh`（旧版单 DMG 构建，已被 final 版取代，保留仅作参考）

## 约定

- **pyobjc 版本锁定 9.2** — bleak 0.21.1 要求 `>=9.2,<10.0`，升级前必须先升 bleak（执行者：requirements.txt 固定版本 + 构建时 pip 安装即失败·门禁性；DEVELOPMENT.md §13）
- **禁止 `with_cached(True)` 造数据** — aggregator 把 cached 视为最低优先级，手工造缓存数据会被真数据覆盖（执行者：`aggregator._prefer` 比较逻辑·结构）
- **osascript 参数永远单引号** — 双引号嵌套会静默语法错误，登录项写不进去（执行者：构建脚本 heredoc 模板 + 评审必看项；教训见 DEVELOPMENT.md §11 已踩过的坑 #4、ADR-2026-08-16-fix-1）
- **DMG 内安装脚本的源头是 build_release_final.sh 的 heredoc** — 改安装逻辑必须改构建脚本模板，改外层独立 .sh 对 DMG 无效（执行者：`zsh -n` 构建期语法检查·门禁性）
- **改 provider/aggregator 行为必须同步 DEVELOPMENT.md 对应章节 + CHANGELOG**（执行者：评审必看项·散文）
- **改主目录（BatteryBar/）必须 cp 同步到本仓库并 push**（执行者：评审必看项·散文；盘点表 #12）
- **版本号改动必查三处**：`app.py APP_VERSION`、`build_release_final.sh`、`build_release.sh VERSION`（Info.plist/spec 会被构建覆盖，不用手改）（执行者：评审必看项·散文）

## 已知限制

- **仅 Apple Silicon**：安装包 arm64-only（`BatteryBar.spec target_arch="arm64"`），Intel 不可运行（ADR-2026-08-16-architecture-2）
- **UI 仅中文**：无国际化（ADR-2026-08-16-rejected-1）
- **Magic 键鼠插线充电不可见**：USB HID 模式下蓝牙停报，硬件限制
- **键盘/鼠标 HID++ 深睡首刷可能显示占位名**：名字缓存兜底，第二次刷新恢复

## 建议（非强制）

- `diagnose.sh`（只读诊断）可随 Full 包分发，改名 `diagnose_safely.sh`；目前构建脚本已自动复制
- 新 provider 接入时参照 `tests/test_system_provider.py` 的 mock 模式写测试
- `test_hidpp_provider.py-202607292031` 这类带后缀的备份文件不要留在 tests/ 下（见 ADR-2026-08-16-process-1）

## 改动规模

非机械改动 ≤150 行、复杂逻辑 ≤60 行，超了先拆。

重力井：**`app.py`（956 行）** 与 **`build_release_final.sh`（约 640 行）** —— 禁止再往里加新的独立功能。app.py 的新功能放独立模块由 app 调用；新安装逻辑放独立脚本由构建脚本复制。
