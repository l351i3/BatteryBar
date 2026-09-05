# 发布仓库为单提交历史 + arm64-only 定位

## Decision

2026-08-16 对外发布时：(1) GitHub 仓库采用全新单提交历史（"v2.1.2 initial public release"），原 12 个开发提交连同其中 206MB 构建垃圾（.venv-build、dist、Xcode DerivedData）不对外；(2) 发布包明确为 Apple Silicon only（`target_arch="arm64"`），README/Release Notes/About 全部标注，Full 包 README 的 Intel 声明修正。

## Consequences

- 仓库 .git 从 206MB 缩到 288KB，clone 秒级
- 开发过程细节（含中间决策）只在本地主目录的 DEVELOPMENT.md 与本 decisions/ 目录中；公开仓库的历史不含早期试错
- Intel Mac 用户被明确排除；未来支持 Intel 需要 universal2 重构建并真机验证（工作量在验证不在构建）
- 版本号 2.1.1→2.1.2 期间的全部行为变更以单提交对外，回溯以 CHANGELOG 为准

## Alternatives considered

- **git-filter-repo 保留历史剔除垃圾**：12 个提交里代码演进价值低（大量是二进制产物与临时修复），过滤工具引入额外依赖且重写后哈希全变仍需 force push；单提交信息量足够，落选。
- **universal2 双架构构建**：pyobjc 有 universal2 轮子，构建可行，但无 Intel 真机验证手段，出了问题无法兜底；诚实标注不支持优于发布未验证的包，落选（rejected 而非放弃：有 Intel 真机后可重启）。
