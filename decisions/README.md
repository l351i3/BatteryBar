# 决策记录制度

路径即元数据：decisions/<生命周期>/<类别>/YYYY-MM-DD-<主题>.md

- 生命周期：proposed（提议中=规格）→ implemented（已实施，交付时改写为现在时）→ archived（归档即冻结）；rejected（已否决）保留防止重复论证
- 类别（封闭集合）：feature / fix / simplify / architecture / process / testing；不设"重构"——用 simplify（判据：可观察行为是否改变）
- 每份必须有 ## Alternatives considered：真实的替代方案一段（是什么、为什么落选）。记录下来的，不是编造的
- 交付时改写：## Proposal → ## Decision（现在时）；Acceptance criteria 与 Risks 折进 ## Consequences
- 豁免：纯机械或局部编辑。禁止 INDEX.md。结构由 scripts/gates/check_decisions.py 强制
