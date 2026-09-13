#!/usr/bin/env python3
"""check_plan.py — 需求台账门禁（方法论第 8 条「先对齐后动手」的机械执行件）。

契约：项目 `docs/plans/` 下的计划文件（YYYY-MM-DD-<主题>.md）按头部 `状态：` 分级：
- `状态：proposed`：提议中，豁免落实检查（但文件命名仍须合规）
- `rejected`：已否决，豁免落实检查
- 其余（approved/done/其他任何值）视为已获批进入实现：
  1) 不得残留未勾选条目 `- [ ]`（每点需求都必须落实或显式移除）
  2) 每条勾选条目 `- [x]` 必须携带非空 `（执行者：…）` 引用（函数/测试名——
     与 check_adr_tests 同哲学：完成=可指认的清单，不是声明）
  3) 必须含 `## 方案对照` 节：≥2 个 `### 方案` 块 + 先例引用（防止单一方案
     未枚举先例即获批——"主动枚举可能性"的结构化）
  4) 必须含 `## 未决前提与探针` 节：每条影响架构的前提两态处置（验证附证据 /
     接受附裁决），未验证前提"留着"即红——方法论总纲"前提先行"的结构化
  5) 台账不能为空（获批计划零条目 = 需求从未被逐点写下来，红）
无 docs/plans/ 目录 → 绿（不适用）。
与外发闸联动：本门禁接入 run_all 后，未全勾的获批计划使 .gates-passed 不刷新，
外发动作（push/ssh 部署等）被闸拦截——"宣布完成"被机械卡住。

已验证会红：2026-09-12，fixture（approved 未勾选/缺执行者/零台账/缺方案对照/对照仅 1 案）→ exit 1。
用法：python3 check_plan.py [项目根]
"""
import re
import sys
from pathlib import Path

NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-.+\.md$")
ITEM_RE = re.compile(r"^- \[( |x)\] (.+)$")


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    plans = root / "docs" / "plans"
    if not plans.is_dir():
        print("[check_plan] 绿灯（无 docs/plans/，不适用）")
        return 0
    errors = []
    for p in sorted(plans.glob("*.md")):
        rel = p.relative_to(root)
        if not NAME_RE.match(p.name):
            errors.append(f"{rel}: 文件名须为 YYYY-MM-DD-<主题>.md")
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^状态[：:]\s*(\S+)", text, re.M)
        status = re.split(r"[（(]", m.group(1))[0] if m else ""
        items = [(mm.group(1) == "x", mm.group(2).strip())
                 for mm in (ITEM_RE.match(line) for line in text.splitlines()) if mm]
        if status in ("proposed", "rejected"):
            if not items:
                errors.append(f"{rel}: proposed 计划的需求台账为空（讨论清楚一点写一条）")
            continue
        # approved/done：强制方案对照节（先对齐后动手——至少两案+先例出处）
        msc = re.search(r"^## 方案对照.*?$", text, re.M)
        if not msc:
            errors.append(f"{rel}: 获批计划缺 `## 方案对照` 节（≥2 方案 + 先例出处）——未经方案枚举不获批")
            continue
        sec = text[msc.start():]
        nxt = re.search(r"^## (?!方案对照)", sec[3:], re.M)
        sec = sec[:3 + nxt.start()] if nxt else sec
        n_alt = len(re.findall(r"^### ", sec, re.M))
        if n_alt < 2:
            errors.append(f"{rel}: `## 方案对照` 节仅 {n_alt} 个方案（### 计数 <2）——单一方案不是方案对照")
        if "先例" not in sec:
            errors.append(f"{rel}: `## 方案对照` 节缺先例引用（同类系统怎么做+出处）")
        mpre = re.search(r"^## 未决前提与探针.*?$", text, re.M)
        if not mpre:
            errors.append(f"{rel}: 获批计划缺 `## 未决前提与探针` 节（前提先行——未知数不允许'留着'）")
            continue
        presec = text[mpre.start():]
        nxt2 = re.search(r"^## (?!未决前提与探针)", presec[3:], re.M)
        presec = presec[:3 + nxt2.start()] if nxt2 else presec
        prelines = presec.splitlines()
        preitems, i = [], 0
        while i < len(prelines):
            mm = ITEM_RE.match(prelines[i])
            if mm:
                chunks = [mm.group(2).strip()]
                j = i + 1
                while (j < len(prelines) and not ITEM_RE.match(prelines[j])
                       and not prelines[j].startswith("## ") and prelines[j].strip()):
                    chunks.append(prelines[j].strip())
                    j += 1
                preitems.append((mm.group(1) == "x", " ".join(chunks)))
                i = j
            else:
                i += 1
        if not preitems:
            errors.append(f"{rel}: 前提节零条目（无前提也要显式写'验证：不适用'）")
            continue
        for done_p, body in preitems:
            if not done_p:
                errors.append(f"{rel}: 未验证前提 `- [ ] {body[:40]}`——探针跑完转已验证，或显式接受为风险")
                continue
            if not (re.search(r"验证[：:]", body) or re.search(r"接受", body)):
                errors.append(f"{rel}: 前提 `{body[:40]}` 缺处置标注（验证：证据 / 接受：裁决）")
        if not items:
            errors.append(f"{rel}: 获批计划（状态：{status or '未标注'}）无需求台账——需求从未逐点写下来")
            continue
        for done, body in items:
            if re.match(r"P\d", body):
                continue  # 前提条目由「未决前提与探针」节处置（不要求执行者）
            if not done:
                errors.append(f"{rel}: 未落实条目 `- [ ] {body[:40]}`——获批计划必须逐项落实或显式移除")
                continue
            ex = re.search(r"执行者[：:]\s*(\S.*)", body)
            if not ex or not ex.group(1).strip():
                errors.append(f"{rel}: 条目 `{body[:40]}` 缺执行者引用（函数/测试名）")
    if errors:
        print(f"[check_plan] 红灯：{len(errors)} 个计划台账问题")
        for e in errors:
            print("  " + e)
        return 1
    print(f"[check_plan] 绿灯（{len(list(plans.glob('*.md')))} 份计划台账合规）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
