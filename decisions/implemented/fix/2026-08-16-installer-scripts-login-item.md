# 安装脚本登录项修复与脚本生成源变更

## Decision

v2.1.2 后段（2026-08-16）修复随包分发安装/卸载脚本的两个静默 bug：(1) osascript 参数双引号嵌套导致 AppleScript 语法错误，登录项从未真正写入——全部改为单引号包裹、路径硬编码；(2) zsh 脚本使用 bash 专属 `BASH_SOURCE` 导致 `SCRIPT_DIR` 解析失败——改用 `$0`。修复落在 `build_release_final.sh` 的 heredoc 模板（DMG 内脚本的实际源头），外层独立 .sh 同步修复。

## Consequences

- 登录项（开机自启）自 v2.1.2 重建包起真正生效；此前所有已安装用户的开机自启实际是失效的
- 构建期 `zsh -n` 语法检查通过（该检查原本只验语法，验不出引号语义错误——这是它此前漏过 bug 的原因）
- 防护：AGENTS.md 约定「osascript 参数永远单引号」「DMG 内脚本的源头是构建脚本 heredoc」，评审必看
- 教训记录：DEVELOPMENT.md §11 已踩过的坑 #4

## Alternatives considered

- **安装脚本改为独立的 .py / Swift 安装器**：杀鸡用牛刀，且引入新运行时依赖；落选。
- **用 `launchd` plist 替代登录项**：需要写 `~/Library/LaunchAgents` 并 `launchctl load`，权限面更大、卸载更复杂；`osascript System Events` 是 macOS 官方用户级方案；落选。
- **在 osascript 里继续用双引号但转义嵌套**：转义后的字符串可读性极差，下次维护必然再错；单引号 + 硬编码路径无变量注入需求，落选。
