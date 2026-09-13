#!/usr/bin/env python3
"""check_adr_tests.py — ADR↔测试映射门禁（防"宣布完成但执行者不存在"）。

契约：decisions/implemented/**/*.md（对"已完成"的声称）中引用的测试必须真实存在：
1) `test_<name>`（正则 test_[a-z0-9_]+）：tests/**/*.py 源码中必须存在以它为前缀的
   `def test_<name>...` 函数（前缀匹配吸收 "tests/test_mt.py" 这类路径引用截断出
   的模块名——test_mt 前缀命中 test_mt_push_addfile 即算）
2) `T<数字>`：必须出现在 tests/**/*.py 源码或 docs/test-plan.md（测试编号台账，
   历史编号被取代后仍在台账中留痕）任一处
proposed/ 与 rejected/ 不查（允许引用尚未存在的测试）。
无 decisions/implemented/ 或 tests/ → 绿（尚无测试体系，不适用）。

方法论依据：第 5 条"完工=可指认的清单"——ADR 里的测试引用是指认凭证，
引用不存在的测试=引用了不存在的实现（m-team-finder 双空间门退化事故的直接解药）。

已验证会红：2026-09-09，fixture（implemented ADR 引用 test_fake_thing 与 T999）→ exit 1。
用法：python3 check_adr_tests.py [项目根]（默认本目录）
"""
import re
import sys
from pathlib import Path

TEST_ID_RE = re.compile(r"\btest_[a-z0-9_]+")
TN_RE = re.compile(r"\bT\d+\b")
EXCLUDE_DIRS = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv"}


def _sources(root: Path, subdirs: list) -> str:
    blob = []
    for sub in subdirs:
        d = root / sub
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.py")):
            if not (set(p.parts) & EXCLUDE_DIRS):
                blob.append(p.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(blob)


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    impl = root / "decisions" / "implemented"
    if not impl.is_dir():
        print("[check_adr_tests] 绿灯（无 decisions/implemented/，不适用）")
        return 0
    tests_blob = _sources(root, ["tests", "scripts"])
    if not tests_blob.strip():
        print("[check_adr_tests] 绿灯（无测试源码，不适用）")
        return 0
    plan = root / "docs" / "test-plan.md"
    plan_blob = plan.read_text(encoding="utf-8", errors="replace") if plan.exists() else ""

    errors, refs = [], 0
    for p in sorted(impl.rglob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(root)
        for name in sorted(set(TEST_ID_RE.findall(text))):
            refs += 1
            if not re.search(rf"def {re.escape(name)}[a-z0-9_]*\(", tests_blob):
                errors.append(f"{rel}: 引用的 `{name}` 在 tests/ 中无对应函数（前缀匹配也未命中）")
        for tn in sorted(set(TN_RE.findall(text))):
            refs += 1
            if not (re.search(rf"(?<![A-Za-z0-9]){tn}(?![0-9])", tests_blob)
                    or re.search(rf"(?<![A-Za-z0-9]){tn}(?![0-9])", plan_blob)):
                errors.append(f"{rel}: 引用的编号 {tn} 在 tests/ 与 docs/test-plan.md 均未出现")
    if errors:
        print(f"[check_adr_tests] 红灯：{len(errors)} 个失效测试引用（implemented ADR 引用了不存在的执行者）")
        for e in errors:
            print("  " + e)
        return 1
    print(f"[check_adr_tests] 绿灯（implemented ADR 的 {refs} 处测试引用全部真实存在）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
