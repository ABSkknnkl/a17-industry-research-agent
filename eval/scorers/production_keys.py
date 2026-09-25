"""评测层使用的「生产层维度 key」单一来源。

来源与现状（必须如实登记，不得假装生产层已有对应实现）：

- 源库（`/Users/Zhuanz1/PycharmProjects/同花顺`）中这 5 个 key 定义于
  `app/agents/report_fusion/quality.py`，是**确定性 pre-export 质量门**（5 维 100 分制：
  结构 / 证据 / 引用 / 维度 / 风险），由后端确定性产出、前端只渲染。
- 本项目（行业研究智能体-全链路系统 4）**没有这套 100 分制评分器**：`report_fusion` 只输出
  `ConsistencyReport(passed / issues / warnings / accepted_edits / rejected_edits / terminology_map)`，
  产物中**不存在** `report_quality.score_breakdown` 结构。

因此本文件的定位是：**评测层本地常量**，用于让 `eval/scorers/report_quality.py`（Q1–Q5 判分器）
可被导入与自检；其值与原库保持一致以便将来生产层补齐时可直接对齐。

⚠️ 影响（已写入《系统测试报告》的「风险与未验证项」）：
Q 类判分器在本项目真实产物上**必然 fail-closed**（读不到 score_breakdown → 按 F0-12 语义判 fail），
这是刻意保留的正确行为：**能力缺失必须表现为失败，而不是静默通过**。
生产层补齐质量评分器后，Q 类方可转为可判项。
"""

from __future__ import annotations

# 维度稳定标识：评测层 Q 类按这些 key 取值，不得随意改名。
DIM_STRUCTURE = "structure"
DIM_EVIDENCE = "evidence_coverage"
DIM_CITATION = "citation_consistency"
DIM_DIMENSION = "dimension_coverage"
DIM_RISK = "risk_disclosure"

# 供自检与报告引用：本项目生产层是否存在对应实现。
PRODUCTION_IMPLEMENTATION_PRESENT = False
PRODUCTION_ABSENCE_REASON = (
    "本项目 report_fusion 仅输出 ConsistencyReport 一致性审计，"
    "无 5 维 100 分制 report_quality.score_breakdown 结构"
)
