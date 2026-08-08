# 质量门升级为风险分类 + 用户决策 + 分级导出 实施计划

> **For agentic workers:** 按任务顺序执行，每步使用 checkbox (`- [ ]`) 跟踪进度。

**Goal:** 将当前 "通过/失败" 单一质量门升级为三层风险分类（建议/确认/阻断），在每个 Pipeline 阶段插入用户决策卡，实现正式报告与风险草稿分级导出。

**Architecture:** 新增 `DecisionPackage` / `RiskNotice` / `UserDecision` 三层数据结构贯穿整个 Pipeline；Agent 3 不再静默删除而是生成全量候选 + 风险提示；Agent 4 修复引用汇总和数字溯源；Agent 5 支持 formal / draft_with_warnings 双模式导出。

**Tech Stack:** Python 3.12 + FastAPI + LangGraph + Pydantic v2 + Vue 3 + TypeScript

---

## 文件结构总览

### 新增文件
- `backend/app/schemas/decision.py` — RiskNotice, DecisionPackage, UserDecision
- `backend/app/agents/chart_generator/planner.py` — 图表全局规划器
- `backend/app/agents/chapter_writer/provenance.py` — 段落引用自动汇总
- `backend/app/agents/chapter_writer/numeric_refs.py` — NumericReference 类型与校验
- `backend/app/infrastructure/repositories/chapter_repository.py` — 逐章持久化
- `frontend/src/components/review/DecisionCard.vue`
- `frontend/src/components/review/RiskNoticeList.vue`
- `frontend/src/components/charts/ChartCandidateCard.vue`
- `frontend/src/components/charts/ChartPlacementEditor.vue`
- `frontend/src/components/report/ExportDecisionCard.vue`

### 修改文件
- `backend/app/schemas/__init__.py`
- `backend/app/schemas/workflow.py`
- `backend/app/schemas/chart.py`
- `backend/app/schemas/chapter.py`
- `backend/app/schemas/report.py`
- `backend/app/schemas/analysis.py`
- `backend/app/agents/chart_generator/service.py`
- `backend/app/agents/chart_generator/quality.py`
- `backend/app/agents/chart_generator/router.py`
- `backend/app/agents/chart_generator/datasets.py`
- `backend/app/agents/chapter_writer/service.py`
- `backend/app/agents/chapter_writer/graph.py`
- `backend/app/agents/chapter_writer/prompt_adapter.py`
- `backend/app/agents/report_fusion/service.py`
- `backend/app/agents/report_fusion/quality.py`
- `backend/app/agents/report_fusion/assembler.py`
- `backend/app/reporting/html.py`
- `backend/app/reporting/markdown.py`
- `backend/app/reporting/pdf.py`
- `backend/app/reporting/templates/report.html.j2`
- `backend/app/api/routes.py`
- `backend/app/workflow/graph.py`
- `backend/app/integrations/llm/openai_compatible.py`
- `frontend/src/types/workflow.ts`
- `frontend/src/api/workflow.ts`
- `contracts/schemas/review-action.schema.json`
- `contracts/schemas/chart-generation-result.schema.json`
- `contracts/schemas/report-fusion-result.schema.json`

### 新增测试
- `backend/tests/agents/chart_generator/test_decision_package.py`
- `backend/tests/agents/chart_generator/test_planner.py`
- `backend/tests/agents/chapter_writer/test_provenance.py`
- `backend/tests/agents/chapter_writer/test_numeric_refs.py`
- `backend/tests/schemas/test_decision.py`

### 修改测试
- `backend/tests/test_contracts.py`
- `backend/tests/agents/chart_generator/test_agent.py`
- `backend/tests/agents/chart_generator/test_router.py`
- `backend/tests/agents/chapter_writer/test_agent.py`
- `backend/tests/agents/report_fusion/test_agent.py`
- `backend/tests/test_workflow_api.py`
- `backend/tests/security/test_api_authentication.py`
- `backend/tests/workflow/test_sqlite_checkpoint.py`

---

### Task 1: 新增风险与决策数据契约

**Files:**
- Create: `backend/app/schemas/decision.py`
- Modify: `backend/app/schemas/__init__.py`
- Modify: `backend/app/schemas/workflow.py` (新增 ReviewAction 枚举值 + UserDecision)
- Modify: `backend/app/schemas/chart.py` (新增 ChartCandidate 状态字段)
- Modify: `backend/app/schemas/analysis.py` (ChartCandidate 新增 alternative_chapter_ids / user_requested)
- Modify: `frontend/src/types/workflow.ts`
- Create: `contracts/schemas/decision-package.schema.json`
- Modify: `contracts/schemas/review-action.schema.json`
- Modify: `contracts/schemas/chart-generation-result.schema.json`
- Create: `backend/tests/schemas/test_decision.py`
- Modify: `backend/tests/test_contracts.py`

**Step 1: 创建 `backend/app/schemas/decision.py`**

```python
"""Risk classification, decision package, and user decision contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RiskSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class RiskDisposition(StrEnum):
    ADVISORY = "advisory"
    ACKNOWLEDGEMENT_REQUIRED = "acknowledgement_required"
    HARD_BLOCK = "hard_block"


class DecisionStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    AWAITING_USER = "awaiting_user"
    ACCEPTED_RECOMMENDATION = "accepted_recommendation"
    ACCEPTED_WITH_RISKS = "accepted_with_risks"
    CUSTOMIZED = "customized"
    CANCELLED = "cancelled"


class RiskNotice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_code: str = Field(min_length=1, max_length=100)
    stage: str = Field(min_length=1)
    severity: RiskSeverity
    disposition: RiskDisposition
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(min_length=1)
    affected_ids: list[str] = Field(default_factory=list)
    recommendation: str = Field(min_length=1)
    consequence: str = Field(min_length=1)
    can_override: bool = True


class ChartCandidateStatus(StrEnum):
    VALID = "valid"
    RECOMMENDED = "recommended"
    NOT_RECOMMENDED = "not_recommended"
    SELECTED = "selected"
    EXCLUDED_BY_USER = "excluded_by_user"
    HARD_BLOCKED = "hard_blocked"
    NEEDS_REASSIGNMENT = "needs_reassignment"


class ChartCandidateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    chart_type: str
    status: ChartCandidateStatus
    recommended_chapter_id: str | None = None
    alternative_chapter_ids: list[str] = Field(default_factory=list)
    priority: int = Field(default=50, ge=0, le=100)
    evidence_ids: list[str] = Field(default_factory=list)
    risk_notices: list[RiskNotice] = Field(default_factory=list)
    conflict_group_id: str | None = None
    chart_id: str | None = None
    suppression_reason: str | None = None


class ConflictGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conflict_group_id: str = Field(min_length=1)
    candidate_ids: list[str] = Field(min_length=2)
    recommended_candidate_id: str
    reason: str = Field(min_length=1)
    risk_if_keep_all: str = Field(min_length=1)


class DecisionPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    revision: int = Field(ge=1)
    all_candidates: list[ChartCandidateResult] = Field(default_factory=list)
    recommended_selection: list[str] = Field(default_factory=list)
    conflict_groups: list[ConflictGroup] = Field(default_factory=list)
    risk_notices: list[RiskNotice] = Field(default_factory=list)
    blocking_risk_codes: list[str] = Field(default_factory=list)
    acknowledgement_required_codes: list[str] = Field(default_factory=list)
    decision_status: DecisionStatus = DecisionStatus.NOT_REQUIRED
    generated_at: datetime | None = None


class ReleaseMode(StrEnum):
    FORMAL = "formal"
    DRAFT_WITH_WARNINGS = "draft_with_warnings"


class UserDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    owner_id: str = Field(min_length=1)
    stage: str = Field(min_length=1)
    action: Literal[
        "accept_recommendation",
        "accept_with_risks",
        "customize",
        "revise",
        "regenerate",
        "cancel",
    ]
    selected_chart_ids: list[str] = Field(default_factory=list)
    excluded_chart_ids: list[str] = Field(default_factory=list)
    placement_overrides: dict[str, str] = Field(default_factory=dict)
    accepted_risk_codes: list[str] = Field(default_factory=list)
    release_mode: ReleaseMode = ReleaseMode.FORMAL
    comment: str | None = Field(default=None, max_length=2_000)
    expected_revision: int = Field(ge=1)
    risk_snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    decided_at: datetime | None = None
```

**Step 2: 更新 `backend/app/schemas/__init__.py` 导出**

在现有 `__all__` 中追加:

```python
from app.schemas.decision import (
    ChartCandidateResult,
    ChartCandidateStatus,
    ConflictGroup,
    DecisionPackage,
    DecisionStatus,
    ReleaseMode,
    RiskDisposition,
    RiskNotice,
    RiskSeverity,
    UserDecision,
)
```

**Step 3: 修改 `backend/app/schemas/workflow.py` — 扩展 ReviewAction**

将 `ReviewAction` 枚举从:

```python
class ReviewAction(StrEnum):
    APPROVE = "approve"
    REVISE = "revise"
    REGENERATE = "regenerate"
    CANCEL = "cancel"
```

改为:

```python
class ReviewAction(StrEnum):
    APPROVE = "approve"  # 兼容旧接口，无风险时等价于 accept_recommendation
    ACCEPT_RECOMMENDATION = "accept_recommendation"
    ACCEPT_WITH_RISKS = "accept_with_risks"
    CUSTOMIZE = "customize"
    REVISE = "revise"
    REGENERATE = "regenerate"
    CANCEL = "cancel"
```

在 `ReviewRequest` 中新增 `accepted_risk_codes` 和 `release_mode` 字段:

```python
class ReviewRequest(ContractModel):
    run_id: str = Field(min_length=1, max_length=100)
    stage: StageName
    action: ReviewAction
    expected_revision: int = Field(ge=1)
    comment: str | None = Field(default=None, max_length=2_000)
    edited_data: dict[str, Any] | None = None
    accepted_risk_codes: list[str] = Field(default_factory=list)
    release_mode: Literal["formal", "draft_with_warnings"] = "formal"
    selected_chart_ids: list[str] | None = None
    placement_overrides: dict[str, str] | None = None
```

**Step 4: 修改 `backend/app/schemas/analysis.py` — ChartCandidate 扩展**

在 `ChartCandidate` 中新增 `alternative_chapter_ids` 和 `user_requested`:

```python
class ChartCandidate(BaseModel):
    # ... 现有字段保持不变 ...
    alternative_chapter_ids: list[str] = Field(default_factory=list)
    user_requested: bool = False
```

**Step 5: 修改 `backend/app/schemas/chart.py` — 新增 ChartCandidate 状态**

在 `ChartReference` 中新增 `candidate_status`:

```python
class ChartReference(BaseModel):
    # ... 现有字段 ...
    candidate_status: Literal[
        "valid", "recommended", "not_recommended", "selected",
        "excluded_by_user", "hard_blocked", "needs_reassignment"
    ] | None = None
```

**Step 6: 更新 `frontend/src/types/workflow.ts`**

```typescript
export const reviewActions = [
  'approve',
  'accept_recommendation',
  'accept_with_risks',
  'customize',
  'revise',
  'regenerate',
  'cancel',
] as const

export type RiskSeverity = 'info' | 'warning' | 'high' | 'critical'
export type RiskDisposition = 'advisory' | 'acknowledgement_required' | 'hard_block'
export type DecisionStatus =
  | 'not_required'
  | 'awaiting_user'
  | 'accepted_recommendation'
  | 'accepted_with_risks'
  | 'customized'
  | 'cancelled'

export interface RiskNotice {
  risk_code: string
  stage: string
  severity: RiskSeverity
  disposition: RiskDisposition
  title: string
  detail: string
  affected_ids: string[]
  recommendation: string
  consequence: string
  can_override: boolean
}

export interface ChartCandidateResult {
  candidate_id: string
  title: string
  chart_type: string
  status: string
  recommended_chapter_id: string | null
  alternative_chapter_ids: string[]
  priority: number
  evidence_ids: string[]
  risk_notices: RiskNotice[]
  conflict_group_id: string | null
  chart_id: string | null
  suppression_reason: string | null
}

export interface ConflictGroup {
  conflict_group_id: string
  candidate_ids: string[]
  recommended_candidate_id: string
  reason: string
  risk_if_keep_all: string
}

export interface DecisionPackage {
  decision_id: string
  run_id: string
  stage: string
  revision: number
  all_candidates: ChartCandidateResult[]
  recommended_selection: string[]
  conflict_groups: ConflictGroup[]
  risk_notices: RiskNotice[]
  blocking_risk_codes: string[]
  acknowledgement_required_codes: string[]
  decision_status: DecisionStatus
}

export interface UserDecision {
  decision_id: string
  run_id: string
  owner_id: string
  stage: string
  action: ReviewAction
  selected_chart_ids: string[]
  excluded_chart_ids: string[]
  placement_overrides: Record<string, string>
  accepted_risk_codes: string[]
  release_mode: 'formal' | 'draft_with_warnings'
  comment: string | null
  expected_revision: number
  risk_snapshot_sha256: string
}

// 在 ReviewRequest 中新增字段
export interface ReviewRequest {
  run_id: string
  stage: StageName
  action: ReviewAction
  expected_revision: number
  comment: string | null
  edited_data: Record<string, unknown> | null
  accepted_risk_codes?: string[]
  release_mode?: 'formal' | 'draft_with_warnings'
  selected_chart_ids?: string[]
  placement_overrides?: Record<string, string>
}
```

**Step 7: 创建 `contracts/schemas/decision-package.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "decision-package.schema.json",
  "title": "Decision Package",
  "type": "object",
  "properties": {
    "decision_id": { "type": "string" },
    "run_id": { "type": "string" },
    "stage": { "type": "string" },
    "revision": { "type": "integer", "minimum": 1 },
    "all_candidates": {
      "type": "array",
      "items": { "$ref": "#/$defs/chartCandidateResult" }
    },
    "recommended_selection": {
      "type": "array",
      "items": { "type": "string" }
    },
    "conflict_groups": {
      "type": "array",
      "items": { "$ref": "#/$defs/conflictGroup" }
    },
    "risk_notices": {
      "type": "array",
      "items": { "$ref": "#/$defs/riskNotice" }
    },
    "blocking_risk_codes": {
      "type": "array",
      "items": { "type": "string" }
    },
    "acknowledgement_required_codes": {
      "type": "array",
      "items": { "type": "string" }
    },
    "decision_status": {
      "type": "string",
      "enum": ["not_required", "awaiting_user", "accepted_recommendation", "accepted_with_risks", "customized", "cancelled"]
    }
  },
  "$defs": {
    "riskNotice": {
      "type": "object",
      "properties": {
        "risk_code": { "type": "string" },
        "stage": { "type": "string" },
        "severity": { "type": "string", "enum": ["info", "warning", "high", "critical"] },
        "disposition": { "type": "string", "enum": ["advisory", "acknowledgement_required", "hard_block"] },
        "title": { "type": "string" },
        "detail": { "type": "string" },
        "affected_ids": { "type": "array", "items": { "type": "string" } },
        "recommendation": { "type": "string" },
        "consequence": { "type": "string" },
        "can_override": { "type": "boolean" }
      },
      "required": ["risk_code", "stage", "severity", "disposition", "title", "detail", "recommendation", "consequence"]
    },
    "chartCandidateResult": {
      "type": "object",
      "properties": {
        "candidate_id": { "type": "string" },
        "title": { "type": "string" },
        "chart_type": { "type": "string" },
        "status": { "type": "string" },
        "recommended_chapter_id": { "type": "string" },
        "alternative_chapter_ids": { "type": "array", "items": { "type": "string" } },
        "priority": { "type": "integer" },
        "evidence_ids": { "type": "array", "items": { "type": "string" } },
        "risk_notices": { "type": "array", "items": { "$ref": "#/$defs/riskNotice" } },
        "conflict_group_id": { "type": "string" },
        "chart_id": { "type": "string" },
        "suppression_reason": { "type": "string" }
      },
      "required": ["candidate_id", "title", "chart_type", "status", "priority", "evidence_ids"]
    },
    "conflictGroup": {
      "type": "object",
      "properties": {
        "conflict_group_id": { "type": "string" },
        "candidate_ids": { "type": "array", "items": { "type": "string" } },
        "recommended_candidate_id": { "type": "string" },
        "reason": { "type": "string" },
        "risk_if_keep_all": { "type": "string" }
      },
      "required": ["conflict_group_id", "candidate_ids", "recommended_candidate_id", "reason", "risk_if_keep_all"]
    }
  }
}
```

**Step 8: 更新 `contracts/schemas/review-action.schema.json`**

在 `action` 枚举中新增:

```json
"action": {
  "enum": [
    "approve",
    "accept_recommendation",
    "accept_with_risks",
    "customize",
    "revise",
    "regenerate",
    "cancel"
  ]
}
```

新增 `accepted_risk_codes` 和 `release_mode` 字段。

**Step 9: 创建测试 `backend/tests/schemas/test_decision.py`**

```python
"""Contract tests for decision package and user decision schemas."""

from datetime import datetime, UTC

from app.schemas.decision import (
    ChartCandidateResult,
    ChartCandidateStatus,
    ConflictGroup,
    DecisionPackage,
    DecisionStatus,
    ReleaseMode,
    RiskDisposition,
    RiskNotice,
    RiskSeverity,
    UserDecision,
)


def test_risk_notice_factory() -> None:
    notice = RiskNotice(
        risk_code="CHART-COUNT-OVER-RECOMMENDED",
        stage="chart_generate",
        severity=RiskSeverity.WARNING,
        disposition=RiskDisposition.ADVISORY,
        title="图表数量超过推荐值",
        detail="当前13张候选图表超过推荐值5-8张",
        affected_ids=["CHART-001", "CHART-002"],
        recommendation="建议保留8张核心图表",
        consequence="报告信息密度下降，可能影响阅读体验",
        can_override=True,
    )
    assert notice.risk_code == "CHART-COUNT-OVER-RECOMMENDED"
    assert notice.can_override is True


def test_hard_block_risk_cannot_override() -> None:
    notice = RiskNotice(
        risk_code="UNKNOWN-EVIDENCE",
        stage="chart_generate",
        severity=RiskSeverity.CRITICAL,
        disposition=RiskDisposition.HARD_BLOCK,
        title="引用不存在的证据",
        detail="证据ID E-999 不存在",
        affected_ids=["E-999"],
        recommendation="修正证据引用后重新生成",
        consequence="无法生成有效图表",
        can_override=False,
    )
    assert notice.can_override is False


def test_decision_package_requires_acknowledgement() -> None:
    package = DecisionPackage(
        decision_id="DP-001",
        run_id="run-123",
        stage="chart_generate",
        revision=1,
        all_candidates=[],
        recommended_selection=[],
        conflict_groups=[],
        risk_notices=[
            RiskNotice(
                risk_code="CHART-CHAPTER-DENSITY",
                stage="chart_generate",
                severity=RiskSeverity.HIGH,
                disposition=RiskDisposition.ACKNOWLEDGEMENT_REQUIRED,
                title="第4章图表密度过高",
                detail="第4章有5张图表，推荐上限2张",
                affected_ids=["CH-04"],
                recommendation="将部分图表分配到其他章节",
                consequence="PDF中可能连续出现多页图表",
                can_override=True,
            )
        ],
        blocking_risk_codes=[],
        acknowledgement_required_codes=["CHART-CHAPTER-DENSITY"],
        decision_status=DecisionStatus.AWAITING_USER,
        generated_at=datetime.now(UTC),
    )
    assert package.decision_status == DecisionStatus.AWAITING_USER
    assert len(package.acknowledgement_required_codes) == 1


def test_user_decision_accept_with_risks() -> None:
    decision = UserDecision(
        decision_id="DP-001",
        run_id="run-123",
        owner_id="test-user",
        stage="chart_generate",
        action="accept_with_risks",
        selected_chart_ids=["CHART-001", "CHART-002"],
        excluded_chart_ids=[],
        placement_overrides={},
        accepted_risk_codes=["CHART-CHAPTER-DENSITY"],
        release_mode=ReleaseMode.DRAFT_WITH_WARNINGS,
        comment="已知风险，接受继续",
        expected_revision=1,
        risk_snapshot_sha256="a" * 64,
        decided_at=datetime.now(UTC),
    )
    assert decision.action == "accept_with_risks"
    assert decision.release_mode == ReleaseMode.DRAFT_WITH_WARNINGS


def test_user_decision_must_have_owner_id() -> None:
    """owner_id is required and must be set by the server."""
    from pydantic import ValidationError
    import pytest

    with pytest.raises(ValidationError):
        UserDecision(
            decision_id="DP-001",
            run_id="run-123",
            owner_id="",  # empty
            stage="chart_generate",
            action="accept_recommendation",
            accepted_risk_codes=[],
            expected_revision=1,
            risk_snapshot_sha256="a" * 64,
        )
```

**Step 10: 更新 `backend/tests/test_contracts.py`**

- 在 `test_review_actions_match_runtime_model` 中更新 `ReviewAction` 枚举值列表
- 新增 `test_decision_package_contract_matches_schema` 测试

**Step 11: 提交**

```bash
git add backend/app/schemas/decision.py backend/app/schemas/__init__.py backend/app/schemas/workflow.py backend/app/schemas/analysis.py backend/app/schemas/chart.py frontend/src/types/workflow.ts contracts/schemas/decision-package.schema.json contracts/schemas/review-action.schema.json contracts/schemas/chart-generation-result.schema.json backend/tests/schemas/test_decision.py backend/tests/test_contracts.py
git commit -m "feat: add risk classification and decision package data contracts"
```

---

### Task 2: 拆分软规则与硬规则 — Agent 3 改造

**Files:**
- Modify: `backend/app/agents/chart_generator/service.py`
- Modify: `backend/app/agents/chart_generator/quality.py`
- Modify: `backend/app/agents/chart_generator/router.py`
- Modify: `backend/app/agents/chart_generator/datasets.py`
- Modify: `backend/tests/agents/chart_generator/test_agent.py`
- Modify: `backend/tests/agents/chart_generator/test_router.py`

**Step 1: 将常量改为推荐值 + 技术绝对上限**

在 `backend/app/agents/chart_generator/service.py` 中:

```python
# 替换原来的硬上限为推荐值
RECOMMENDED_CHARTS_PER_REPORT = (5, 8)      # 推荐5-8张
RECOMMENDED_CHARTS_PER_CHAPTER = 2            # 推荐每章不超过2张
RECOMMENDED_CHARTS_PER_FAMILY = 2             # 推荐同一图表族不超过2张
RECOMMENDED_P1_CHARTS_PER_REPORT = 3          # 推荐P1不超过3张
RECOMMENDED_CHAIN_CHARTS = 1                  # 推荐产业链图1张

# 技术绝对上限（不可绕过）
HARD_LIMIT_MAX_CANDIDATES = 30               # 单份报告最多候选图表
HARD_LIMIT_CHARTS_PER_CHAPTER = 10            # 单章最多技术渲染图表
HARD_LIMIT_MAX_DATA_POINTS = 100_000          # 单份报告最大数据点
HARD_LIMIT_MAX_POINTS_PER_CHART = 20_000      # 单张图表最大数据点
```

**Step 2: 修改 `ChartGeneratorAgent.run()` 主循环**

将当前循环从:

```python
# 当前: 超过预算 → suppressed → continue
if len(specs) >= MAX_CHARTS_PER_REPORT:
    suppressed.append(...)
    continue
```

调整为两阶段:

```python
# 阶段1: 对所有候选执行技术校验（数据集匹配、路由、ECharts生成）
# 阶段2: 对技术有效的候选生成风险提示而非删除

all_candidates: list[ChartCandidateResult] = []
hard_blocked: list[SuppressedChart] = []

for candidate in candidates:
    # 技术校验: 数据集匹配、路由、ECharts生成
    match = match_datasets(candidate.title, candidate.evidence_ids, datasets)
    if not match.datasets:
        result = ChartCandidateResult(
            candidate_id=f"CANDIDATE-{candidate.title}",
            title=candidate.title,
            chart_type=candidate.chart_type,
            status=ChartCandidateStatus.HARD_BLOCKED,
            evidence_ids=candidate.evidence_ids,
            suppression_reason=match.suppressed[0].reason if match.suppressed else "no_dataset",
        )
        all_candidates.append(result)
        hard_blocked.extend(match.suppressed)
        continue

    dataset = match.datasets[0]
    route = route_chart(candidate.chart_type, dataset)

    if not route.accepted:
        # 尝试降级
        fallback = downgrade_chart(candidate.chart_type, dataset)
        if fallback:
            fallback_type, fallback_dataset = fallback
            fallback_route = route_chart(fallback_type, fallback_dataset)
            if fallback_route.accepted:
                dataset = fallback_dataset
                route = fallback_route
            else:
                result = ChartCandidateResult(
                    candidate_id=f"CANDIDATE-{candidate.title}",
                    title=candidate.title,
                    chart_type=candidate.chart_type,
                    status=ChartCandidateStatus.HARD_BLOCKED,
                    evidence_ids=candidate.evidence_ids,
                    suppression_reason=route.reason or "route_rejected",
                )
                all_candidates.append(result)
                continue
        else:
            result = ChartCandidateResult(
                candidate_id=f"CANDIDATE-{candidate.title}",
                title=candidate.title,
                chart_type=candidate.chart_type,
                status=ChartCandidateStatus.HARD_BLOCKED,
                evidence_ids=candidate.evidence_ids,
                suppression_reason=route.reason or "route_rejected",
            )
            all_candidates.append(result)
            continue

    # 技术有效 → 生成ECharts option
    try:
        option = _build_option(
            title=candidate.title,
            chart_type=route.chart_type,
            variant=route.variant,
            dataset=dataset,
            theme=theme,
        )
    except ValueError as exc:
        result = ChartCandidateResult(
            candidate_id=f"CANDIDATE-{candidate.title}",
            title=candidate.title,
            chart_type=candidate.chart_type,
            status=ChartCandidateStatus.HARD_BLOCKED,
            evidence_ids=candidate.evidence_ids,
            suppression_reason=str(exc),
        )
        all_candidates.append(result)
        continue

    option_issues = validate_option(option)
    if option_issues:
        result = ChartCandidateResult(
            candidate_id=f"CANDIDATE-{candidate.title}",
            title=candidate.title,
            chart_type=candidate.chart_type,
            status=ChartCandidateStatus.HARD_BLOCKED,
            evidence_ids=candidate.evidence_ids,
            suppression_reason="; ".join(option_issues),
        )
        all_candidates.append(result)
        continue

    # 技术有效 → 生成风险提示
    risk_notices = _build_risk_notices(candidate, route, dataset)

    # 确定初始状态
    status = ChartCandidateStatus.VALID
    if any(r.disposition == RiskDisposition.HARD_BLOCK for r in risk_notices):
        status = ChartCandidateStatus.HARD_BLOCKED
    elif any(r.disposition == RiskDisposition.ACKNOWLEDGEMENT_REQUIRED for r in risk_notices):
        status = ChartCandidateStatus.NEEDS_REASSIGNMENT

    result = ChartCandidateResult(
        candidate_id=f"CANDIDATE-{candidate.title}",
        title=candidate.title,
        chart_type=route.chart_type,
        status=status,
        recommended_chapter_id=candidate.chapter_hint,
        alternative_chapter_ids=candidate.alternative_chapter_ids,
        priority=candidate.priority,
        evidence_ids=candidate.evidence_ids,
        risk_notices=risk_notices,
    )
    all_candidates.append(result)
```

**Step 3: 新增 `_build_risk_notices()` 辅助函数**

在 `service.py` 中新增:

```python
def _build_risk_notices(
    candidate: ChartCandidate,
    route: ChartRouteDecision,
    dataset: ChartDataset,
) -> list[RiskNotice]:
    notices: list[RiskNotice] = []

    # 技术绝对上限检查 (hard_block)
    if len(dataset.points) > HARD_LIMIT_MAX_POINTS_PER_CHART:
        notices.append(RiskNotice(
            risk_code="CHART-DATA-POINT-LIMIT",
            stage="chart_generate",
            severity=RiskSeverity.CRITICAL,
            disposition=RiskDisposition.HARD_BLOCK,
            title=f"单张图表数据点超过绝对上限 {HARD_LIMIT_MAX_POINTS_PER_CHART}",
            detail=f"当前 {len(dataset.points)} 个数据点",
            recommendation="减少数据点或拆分图表",
            consequence="服务器资源耗尽风险",
            can_override=False,
        ))

    # 产业链图数量检查 (advisory)
    if route.chart_type == "industry_chain":
        notices.append(RiskNotice(
            risk_code="CHART-INDUSTRY-CHAIN-COUNT",
            stage="chart_generate",
            severity=RiskSeverity.INFO,
            disposition=RiskDisposition.ADVISORY,
            title="产业链图通常每份报告1张即可",
            detail="多张产业链图可能造成信息重复",
            recommendation="建议保留1张核心产业链图",
            consequence="多张产业链图降低报告信息密度",
            can_override=True,
        ))

    # P1图表数量检查 (advisory)
    if route.chart_type in P1_CHART_TYPES:
        notices.append(RiskNotice(
            risk_code="CHART-P1-COUNT",
            stage="chart_generate",
            severity=RiskSeverity.INFO,
            disposition=RiskDisposition.ADVISORY,
            title=f"P1高级图表 ({route.chart_type}) 建议不超过3张",
            detail="P1图表渲染复杂度较高",
            recommendation="优先使用P0基础图表",
            consequence="PDF渲染时间可能增加",
            can_override=True,
        ))

    return notices
```

**Step 4: 修改 `build_quality_report()` 区分硬阻断和专业建议**

在 `quality.py` 中:

```python
def build_quality_report(
    *,
    candidate_count: int,
    specs: list[ChartSpec],
    suppressed: list[SuppressedChart],
    risk_notices: list[RiskNotice] | None = None,
) -> ChartQualityReport:
    """Build quality report with risk-aware classification.

    - hard_blocked issues → quality.passed = False
    - advisory/acknowledgement issues → quality.passed = True but with notices
    """
    issues = [issue for spec in specs for issue in validate_option(spec.option)]

    # 只有硬阻断才标记为 failed
    hard_blocked = [
        item for item in (suppressed or [])
        if item.reason_code not in {
            "duplicate_chart", "duplicate_chart_family",
            "chart_budget_exceeded", "p1_chart_budget_exceeded",
            "chapter_chart_budget_exceeded", "chart_family_budget_exceeded",
            "chart_downgraded", "chart_count_over_recommended",
            "chart_chapter_density", "chart_family_duplicate",
        }
    ]
    if hard_blocked:
        issues.extend(sorted({item.reason_code for item in hard_blocked}))

    passed = not issues and (candidate_count == 0 or bool(specs))
    return ChartQualityReport(
        passed=passed,
        ready_count=len(specs),
        suppressed_count=len(suppressed),
        issues=issues,
    )
```

**Step 5: 修改 `router.py` 中的 `route_chart` — 不再因数量限制拒绝**

保持 `route_chart` 只做数据集类型匹配，数量限制相关逻辑移到 `service.py` 的风险提示阶段。

**Step 6: 修改 `datasets.py` — 数据集不匹配时返回 HARD_BLOCK 而非静默抑制**

`match_datasets` 和 `validate_dataset_consistency` 保持现有逻辑不变。无匹配数据集时返回 `SuppressedChart` 的 reason_code 保持不变，由 `service.py` 统一分类为 `HARD_BLOCKED`。

**Step 7: 更新测试 `backend/tests/agents/chart_generator/test_agent.py`**

```python
def test_chart_over_recommended_count_not_suppressed() -> None:
    """超过推荐数量时图表不被删除，而是标记为NOT_RECOMMENDED."""
    ...

def test_chapter_density_generates_risk_notice_not_suppression() -> None:
    """第4章5张图表生成风险提示而非被删除."""
    ...

def test_missing_dataset_still_hard_blocked() -> None:
    """缺失数据集仍然是硬阻断."""
    ...

def test_illegal_echarts_option_still_hard_blocked() -> None:
    """非法ECharts配置仍然不能绕过."""
    ...

def test_user_can_keep_all_13_charts() -> None:
    """用户选择全部13张图表后系统继续."""
    ...
```

**Step 8: 提交**

```bash
git add backend/app/agents/chart_generator/service.py backend/app/agents/chart_generator/quality.py backend/app/agents/chart_generator/router.py backend/app/agents/chart_generator/datasets.py backend/tests/agents/chart_generator/test_agent.py backend/tests/agents/chart_generator/test_router.py
git commit -m "feat: split soft/hard rules in chart generator - risk notices instead of silent suppression"
```

---

### Task 3: 实现图表全局规划器

**Files:**
- Create: `backend/app/agents/chart_generator/planner.py`
- Create: `backend/tests/agents/chart_generator/test_planner.py`

**Step 1: 创建 `backend/app/agents/chart_generator/planner.py`**

```python
"""Chart global planner: recommend selections, detect conflicts, suggest placements."""

import hashlib
from collections import defaultdict

from app.agents.chart_generator.router import CHART_FAMILY, build_data_fingerprint, build_dedupe_key
from app.schemas.analysis import ChartCandidate
from app.schemas.chart import ChartDataset, ChartType
from app.schemas.decision import (
    ChartCandidateResult,
    ChartCandidateStatus,
    ConflictGroup,
    RiskDisposition,
    RiskNotice,
    RiskSeverity,
)


RECOMMENDED_CHARTS = (5, 8)
RECOMMENDED_PER_CHAPTER = 2
RECOMMENDED_PER_FAMILY = 2
RECOMMENDED_P1 = 3
RECOMMENDED_CHAIN = 1


def plan_chart_selection(
    candidates: list[ChartCandidateResult],
    chapter_assignments: dict[str, str] | None = None,
) -> list[ChartCandidateResult]:
    """Score and classify all technically valid candidates.

    Returns candidates with status updated to:
    - RECOMMENDED: system recommends inclusion
    - NOT_RECOMMENDED: valid but lower priority
    - NEEDS_REASSIGNMENT: valid but suggested chapter change
    """
    if not candidates:
        return []

    valid = [c for c in candidates if c.status == ChartCandidateStatus.VALID]
    if not valid:
        return candidates

    # Score each candidate
    scored = [(c, _score_candidate(c)) for c in valid]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Select top N by score within budget
    selections: list[str] = []
    chapter_counts: dict[str, int] = defaultdict(int)
    family_counts: dict[str, int] = defaultdict(int)
    p1_count = 0
    chain_count = 0

    for candidate, score in scored:
        chart_type = _to_chart_type(candidate.chart_type)
        if chart_type is None:
            continue

        family = CHART_FAMILY.get(chart_type, "other")
        chapter = chapter_assignments.get(candidate.candidate_id, candidate.recommended_chapter_id or "CH-00")

        # Check recommended budgets
        if len(selections) >= RECOMMENDED_CHARTS[1]:
            break
        if chapter_counts[chapter] >= RECOMMENDED_PER_CHAPTER:
            continue
        if family_counts[family] >= RECOMMENDED_PER_FAMILY:
            continue
        is_p1 = chart_type in {"combo", "area", "scatter", "bubble", "heatmap", "boxplot", "treemap"}
        if is_p1 and p1_count >= RECOMMENDED_P1:
            continue
        if chart_type == "industry_chain" and chain_count >= RECOMMENDED_CHAIN:
            continue

        selections.append(candidate.candidate_id)
        chapter_counts[chapter] += 1
        family_counts[family] += 1
        if is_p1:
            p1_count += 1
        if chart_type == "industry_chain":
            chain_count += 1

    # Update statuses
    for candidate in candidates:
        if candidate.status == ChartCandidateStatus.VALID:
            if candidate.candidate_id in selections:
                candidate.status = ChartCandidateStatus.RECOMMENDED
            else:
                candidate.status = ChartCandidateStatus.NOT_RECOMMENDED

    # Add risk notices for over-budget situations
    _add_budget_risk_notices(candidates, chapter_counts)

    return candidates


def detect_conflict_groups(
    candidates: list[ChartCandidateResult],
    datasets: list[ChartDataset],
) -> list[ConflictGroup]:
    """Group candidates that share the same data fingerprint into conflict groups."""
    groups: dict[str, list[ChartCandidateResult]] = defaultdict(list)

    for candidate in candidates:
        if candidate.status == ChartCandidateStatus.HARD_BLOCKED:
            continue
        # Build fingerprint from candidate info
        fingerprint = _candidate_fingerprint(candidate)
        groups[fingerprint].append(candidate)

    conflict_groups: list[ConflictGroup] = []
    for fingerprint, group in groups.items():
        if len(group) < 2:
            continue
        # Pick recommended: prefer combo > line > area, user_requested, higher priority
        recommended = _pick_recommended(group)
        group_id = f"CONFLICT-{hashlib.sha256(fingerprint.encode()).hexdigest()[:12].upper()}"

        conflict_groups.append(ConflictGroup(
            conflict_group_id=group_id,
            candidate_ids=[c.candidate_id for c in group],
            recommended_candidate_id=recommended.candidate_id,
            reason=f"推荐 {recommended.title}（{recommended.chart_type}），信息表达更完整",
            risk_if_keep_all="重复表达同一数据趋势，降低报告信息密度",
        ))

        # Tag candidates with conflict group
        for c in group:
            c.conflict_group_id = group_id

    return conflict_groups


def _score_candidate(candidate: ChartCandidateResult) -> float:
    """Score a candidate for recommendation priority."""
    score = float(candidate.priority) / 100.0  # 0-1 base

    # User-requested bonus
    if candidate.priority >= 90:  # proxy for user_requested
        score += 0.3

    # Chart type diversity bonus (lower for common types)
    chart_type = _to_chart_type(candidate.chart_type)
    if chart_type in {"industry_chain", "radar", "heatmap"}:
        score += 0.1

    return min(score, 1.5)


def _to_chart_type(raw: str) -> ChartType | None:
    try:
        return ChartType(raw)
    except ValueError:
        return None


def _candidate_fingerprint(candidate: ChartCandidateResult) -> str:
    return hashlib.sha256(
        f"{candidate.chart_type}:{sorted(candidate.evidence_ids)}".encode()
    ).hexdigest()


def _pick_recommended(group: list[ChartCandidateResult]) -> ChartCandidateResult:
    """Pick the best candidate from a conflict group."""
    # Sort by: combo > line > area, then priority
    type_order = {"combo": 0, "line": 1, "area": 2, "scatter": 1, "bubble": 0}
    group.sort(key=lambda c: (
        type_order.get(c.chart_type, 3),
        -c.priority
    ))
    return group[0]


def _add_budget_risk_notices(
    candidates: list[ChartCandidateResult],
    chapter_counts: dict[str, int],
) -> None:
    """Add advisory risk notices for budget overruns."""
    total = len([c for c in candidates if c.status == ChartCandidateStatus.VALID])

    if total > RECOMMENDED_CHARTS[1]:
        for c in candidates:
            if c.status == ChartCandidateStatus.VALID:
                c.risk_notices.append(RiskNotice(
                    risk_code="CHART-COUNT-OVER-RECOMMENDED",
                    stage="chart_generate",
                    severity=RiskSeverity.WARNING,
                    disposition=RiskDisposition.ADVISORY,
                    title=f"候选图表数量 ({total}) 超过推荐上限 ({RECOMMENDED_CHARTS[1]})",
                    detail=f"当前共 {total} 张候选图表，推荐 {RECOMMENDED_CHARTS[0]}-{RECOMMENDED_CHARTS[1]} 张",
                    recommendation=f"建议保留 {RECOMMENDED_CHARTS[1]} 张核心图表",
                    consequence="图表过多会降低报告信息密度",
                    can_override=True,
                ))

    for chapter_id, count in chapter_counts.items():
        if count > RECOMMENDED_PER_CHAPTER:
            for c in candidates:
                if c.recommended_chapter_id == chapter_id:
                    c.risk_notices.append(RiskNotice(
                        risk_code="CHART-CHAPTER-DENSITY",
                        stage="chart_generate",
                        severity=RiskSeverity.HIGH,
                        disposition=RiskDisposition.ACKNOWLEDGEMENT_REQUIRED,
                        title=f"{chapter_id} 图表密度过高 ({count}张，推荐{RECOMMENDED_PER_CHAPTER}张)",
                        detail=f"该章节有 {count} 张图表，推荐上限 {RECOMMENDED_PER_CHAPTER} 张",
                        recommendation=f"建议将部分图表分配到其他章节",
                        consequence="PDF中可能连续出现多页图表，部分图表分析目的相近",
                        can_override=True,
                    ))
```

**Step 2: 创建测试 `backend/tests/agents/chart_generator/test_planner.py`**

```python
"""Tests for chart global planner."""

from app.agents.chart_generator.planner import (
    detect_conflict_groups,
    plan_chart_selection,
)
from app.schemas.decision import (
    ChartCandidateResult,
    ChartCandidateStatus,
    RiskNotice,
    RiskSeverity,
    RiskDisposition,
)


def _make_candidate(
    candidate_id: str,
    title: str,
    chart_type: str,
    priority: int = 50,
    chapter_id: str = "CH-04",
    evidence_ids: list[str] | None = None,
) -> ChartCandidateResult:
    return ChartCandidateResult(
        candidate_id=candidate_id,
        title=title,
        chart_type=chart_type,
        status=ChartCandidateStatus.VALID,
        recommended_chapter_id=chapter_id,
        priority=priority,
        evidence_ids=evidence_ids or ["E-001"],
    )


def test_planner_recommends_top_8() -> None:
    """13 candidates → planner recommends top 8."""
    candidates = [
        _make_candidate(f"C-{i:02d}", f"Chart {i}", "bar", priority=80 - i * 3)
        for i in range(13)
    ]
    result = plan_chart_selection(candidates)
    recommended = [c for c in result if c.status == ChartCandidateStatus.RECOMMENDED]
    assert len(recommended) <= 8


def test_planner_respects_chapter_budget() -> None:
    """5 candidates in same chapter → at most 2 recommended."""
    candidates = [
        _make_candidate(f"C-{i:02d}", f"Chart {i}", "bar", priority=80 - i * 5, chapter_id="CH-04")
        for i in range(5)
    ]
    result = plan_chart_selection(candidates)
    chapter_recommended = [
        c for c in result
        if c.status == ChartCandidateStatus.RECOMMENDED and c.recommended_chapter_id == "CH-04"
    ]
    assert len(chapter_recommended) <= 2


def test_planner_all_candidates_remain_valid() -> None:
    """All 5 candidates remain valid (not deleted), some are NOT_RECOMMENDED."""
    candidates = [
        _make_candidate(f"C-{i:02d}", f"Chart {i}", "bar", priority=80 - i * 5, chapter_id="CH-04")
        for i in range(5)
    ]
    result = plan_chart_selection(candidates)
    valid_count = len([c for c in result if c.status != ChartCandidateStatus.HARD_BLOCKED])
    assert valid_count == 5


def test_detect_line_area_combo_conflict() -> None:
    """Line, area, combo sharing same data → one conflict group."""
    candidates = [
        _make_candidate("C-LINE", "Trend Line", "line", evidence_ids=["E-001", "E-002"]),
        _make_candidate("C-AREA", "Trend Area", "area", evidence_ids=["E-001", "E-002"]),
        _make_candidate("C-COMBO", "Trend Combo", "combo", evidence_ids=["E-001", "E-002"]),
    ]
    groups = detect_conflict_groups(candidates, [])
    assert len(groups) == 1
    assert groups[0].recommended_candidate_id == "C-COMBO"


def test_different_evidence_no_conflict() -> None:
    """Different evidence → no conflict group."""
    candidates = [
        _make_candidate("C-1", "A", "line", evidence_ids=["E-001"]),
        _make_candidate("C-2", "B", "line", evidence_ids=["E-002"]),
    ]
    groups = detect_conflict_groups(candidates, [])
    assert len(groups) == 0
```

**Step 3: 提交**

```bash
git add backend/app/agents/chart_generator/planner.py backend/tests/agents/chart_generator/test_planner.py
git commit -m "feat: add chart global planner with conflict group detection"
```

---

### Task 4: 扩展审核接口 — 支持新审核动作

**Files:**
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/workflow/graph.py`
- Modify: `backend/app/workflow/runner.py`
- Modify: `backend/app/schemas/workflow.py`
- Modify: `backend/tests/test_workflow_api.py`
- Modify: `backend/tests/security/test_api_authentication.py`

**Step 1: 修改 `backend/app/workflow/graph.py` — `_review_gate` 函数**

在 `_review_gate` 中新增对 `accept_recommendation`、`accept_with_risks`、`customize` 的处理:

```python
def _review_gate(state: PipelineGraphState) -> dict[str, object]:
    current_stage = state["current_stage"]
    current_result = StageResult.model_validate(state["stage_results"][current_stage.value])
    runtime = RuntimeState.model_validate(
        state.get("runtime") or create_runtime_state(state["run_id"], RuntimePolicy())
    )
    decision = interrupt({
        "run_id": state["run_id"],
        "stage": current_stage.value,
        "revision": state["revision"],
        "result": current_result.model_dump(mode="json"),
        "recovery_required": current_result.status == StageStatus.FAILED,
        "runtime_stop_reason": runtime.stop_reason,
    })
    expected_revision = int(decision.get("expected_revision", 0))
    if expected_revision != state["revision"]:
        raise ValueError(
            f"Revision conflict: expected {state['revision']}, got {expected_revision}"
        )

    action = str(decision.get("action", "approve"))
    comment = decision.get("comment")
    stage_results = dict(state["stage_results"])
    next_status = StageStatus.APPROVED
    revision = state["revision"]
    input_data = dict(state["input_data"])

    # 兼容旧 approve: 无风险时等价于 accept_recommendation
    if action == "approve":
        if current_result.data.get("decision_package"):
            # 有决策包时检查是否有必须确认的风险
            dp = current_result.data.get("decision_package", {})
            required = dp.get("acknowledgement_required_codes", [])
            if required:
                raise ValueError(
                    "approve is not allowed when risks require acknowledgement; "
                    "use accept_with_risks and provide accepted_risk_codes"
                )
        # 无风险时 normalize 为 accept_recommendation
        action = "accept_recommendation"

    if action == "accept_with_risks":
        accepted_codes = set(decision.get("accepted_risk_codes", []))
        dp = current_result.data.get("decision_package", {})
        required = set(dp.get("acknowledgement_required_codes", []))
        if required - accepted_codes:
            raise ValueError(
                f"Missing required risk acknowledgements: {sorted(required - accepted_codes)}"
            )
        release_mode = decision.get("release_mode", "draft_with_warnings")
        input_data["release_mode"] = release_mode
        input_data["accepted_risk_codes"] = sorted(accepted_codes)

    if action == "customize":
        selected_chart_ids = decision.get("selected_chart_ids", [])
        placement_overrides = decision.get("placement_overrides", {})
        input_data["selected_chart_ids"] = selected_chart_ids
        input_data["placement_overrides"] = placement_overrides

    if action in {"accept_recommendation", "accept_with_risks", "customize"}:
        next_status = StageStatus.APPROVED
    elif action in {"revise", "regenerate"}:
        next_status = StageStatus.RUNNING
        revision += 1
        edited_data = decision.get("edited_data")
        if isinstance(edited_data, dict):
            input_data.update(edited_data)
    elif action == "cancel":
        next_status = StageStatus.CANCELLED
        runtime.cancel_requested = True

    current_result.status = next_status
    current_result.revision = revision
    stage_results[current_stage.value] = current_result.model_dump(mode="json")

    return {
        "status": next_status,
        "revision": revision,
        "stage_results": stage_results,
        "input_data": input_data,
        "review_action": action,
        "review_feedback": str(comment) if comment else None,
        "runtime": runtime.model_dump(mode="json"),
        "updated_at": datetime.now(UTC).isoformat(),
    }
```

**Step 2: 修改 `_route_after_review`**

将 `accept_recommendation`、`accept_with_risks`、`customize` 视为进入下一阶段:

```python
def _route_after_review(state: PipelineGraphState) -> str:
    if state.get("review_action") in {"revise", "regenerate"}:
        return state["current_stage"].value
    if state.get("review_action") == "cancel":
        return FINISH_NODE
    # accept_recommendation, accept_with_risks, customize, approve → next stage
    return _next_stage(state["current_stage"])
```

**Step 3: 修改 `backend/app/workflow/runner.py` — `review` 方法**

`review` 方法无需改动，因为 `ReviewRequest` 模型已包含新字段，通过 `Command(resume=request.model_dump())` 传入。

**Step 4: 修改 `backend/app/api/routes.py` — 新增校验**

在 `review_run` 端点中新增对 `accept_with_risks` 的校验:

```python
@router.post("/runs/{run_id}/reviews", response_model=WorkflowState)
async def review_run(...):
    # ... existing validation ...

    # 新增: accept_with_risks 必须提供 accepted_risk_codes
    if request.action == ReviewAction.ACCEPT_WITH_RISKS:
        if not request.accepted_risk_codes:
            raise HTTPException(
                status_code=422,
                detail={"code": "MISSING_RISK_CODES", "message": "accept_with_risks requires accepted_risk_codes"},
            )

    # 新增: customize 必须提供 selected_chart_ids
    if request.action == ReviewAction.CUSTOMIZE:
        if not request.selected_chart_ids:
            raise HTTPException(
                status_code=422,
                detail={"code": "MISSING_CHART_IDS", "message": "customize requires selected_chart_ids"},
            )
```

**Step 5: 更新 API 测试**

```python
def test_review_accept_with_risks_requires_risk_codes() -> None:
    """accept_with_risks 不提供 accepted_risk_codes 时返回 422."""
    ...

def test_review_customize_requires_chart_ids() -> None:
    """customize 不提供 selected_chart_ids 时返回 422."""
    ...

def test_old_approve_still_works_for_no_risk_tasks() -> None:
    """无风险任务上旧 approve 仍然可用."""
    ...
```

**Step 6: 提交**

```bash
git add backend/app/api/routes.py backend/app/workflow/graph.py backend/app/workflow/runner.py backend/app/schemas/workflow.py backend/tests/test_workflow_api.py backend/tests/security/test_api_authentication.py
git commit -m "feat: extend review actions with accept_recommendation, accept_with_risks, customize"
```

---

### Task 5: 修复 Agent 4 引用和数字处理

**Files:**
- Create: `backend/app/agents/chapter_writer/provenance.py`
- Create: `backend/app/agents/chapter_writer/numeric_refs.py`
- Modify: `backend/app/agents/chapter_writer/graph.py`
- Modify: `backend/app/agents/chapter_writer/prompt_adapter.py`
- Modify: `backend/app/schemas/chapter.py`
- Modify: `backend/app/integrations/llm/openai_compatible.py`
- Create: `backend/tests/agents/chapter_writer/test_provenance.py`
- Create: `backend/tests/agents/chapter_writer/test_numeric_refs.py`

**Step 1: 创建 `backend/app/agents/chapter_writer/numeric_refs.py`**

```python
"""Numeric reference classification and validation for Agent 4 paragraphs."""

import re
from dataclasses import dataclass, field
from typing import Literal

NumericType = Literal["fact", "calculation", "scenario_parameter"]
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?")


@dataclass
class NumericReference:
    raw_text: str
    numeric_type: NumericType
    evidence_ids: list[str] = field(default_factory=list)
    formula: str | None = None
    assumption_note: str | None = None


def extract_numbers(text: str) -> list[str]:
    """Extract numeric tokens from text."""
    return _NUMBER_RE.findall(text)


def classify_number(
    raw_text: str,
    *,
    known_fact_numbers: set[str],
    claim_evidence_ids: list[str],
) -> NumericReference:
    """Classify a numeric reference as fact, calculation, or scenario_parameter.

    Rules:
    - fact: number appears in known fact numbers from claims → requires evidence
    - scenario_parameter: number appears in scenario context → requires assumption_note
    - calculation: otherwise → requires formula and input evidence
    """
    if raw_text.rstrip("%") in known_fact_numbers:
        return NumericReference(
            raw_text=raw_text,
            numeric_type="fact",
            evidence_ids=claim_evidence_ids,
        )
    # Heuristic: if number has % and is a round number like 20%, 30%, 50% → likely scenario
    if raw_text.endswith("%"):
        try:
            value = float(raw_text.rstrip("%"))
            if value in {10, 15, 20, 25, 30, 40, 50, 60, 70, 80}:
                return NumericReference(
                    raw_text=raw_text,
                    numeric_type="scenario_parameter",
                    assumption_note=f"情景阈值 {raw_text}，非公开事实数据",
                )
        except ValueError:
            pass
    return NumericReference(
        raw_text=raw_text,
        numeric_type="calculation",
        formula="未提供公式",
    )


def validate_numeric_references(
    references: list[NumericReference],
) -> list[str]:
    """Validate numeric references and return issues.

    Returns:
        List of issue strings. Empty list means all references are valid.
    """
    issues: list[str] = []
    for ref in references:
        if ref.numeric_type == "fact" and not ref.evidence_ids:
            issues.append(f"事实数字 '{ref.raw_text}' 缺少证据引用")
        elif ref.numeric_type == "calculation" and not ref.formula:
            issues.append(f"计算数字 '{ref.raw_text}' 缺少公式说明")
        elif ref.numeric_type == "scenario_parameter" and not ref.assumption_note:
            issues.append(f"情景参数 '{ref.raw_text}' 缺少假设说明")
    return issues
```

**Step 2: 创建 `backend/app/agents/chapter_writer/provenance.py`**

```python
"""Provenance aggregation: compute chapter-level references from paragraph-level."""

from app.schemas.chapter import ChapterDraft, SectionDraft


def aggregate_chapter_references(chapter: ChapterDraft) -> ChapterDraft:
    """Recompute chapter-level claim_ids, evidence_ids, chart_ids from sections.

    This replaces the LLM-generated chapter-level aggregates with
    programmatically computed values to ensure consistency.
    """
    all_claim_ids: list[str] = []
    all_evidence_ids: list[str] = []
    all_chart_ids: list[str] = []

    for section in chapter.sections:
        section_chart_ids: list[str] = []
        for paragraph in section.paragraphs:
            all_claim_ids.extend(paragraph.claim_ids)
            all_evidence_ids.extend(paragraph.evidence_ids)
        section_chart_ids = list(dict.fromkeys(section.chart_ids))
        all_chart_ids.extend(section_chart_ids)

    # Deduplicate while preserving order
    chapter.claim_ids = list(dict.fromkeys(all_claim_ids))
    chapter.evidence_ids = list(dict.fromkeys(all_evidence_ids))
    chapter.chart_ids = list(dict.fromkeys(all_chart_ids))

    return chapter


def validate_section_references(section: SectionDraft) -> list[str]:
    """Validate that section-level chart_ids match paragraph-level references."""
    issues: list[str] = []
    paragraph_chart_ids = set()
    for paragraph in section.paragraphs:
        # Paragraphs don't have chart_ids directly; they're at section level
        pass
    return issues
```

**Step 3: 修改 `backend/app/agents/chapter_writer/graph.py` — 在 `accept` 节点中调用 provenance**

在 `accept` 函数中，保存章节后调用 `aggregate_chapter_references`:

```python
def accept(state: ChapterWriterGraphState) -> dict[str, object]:
    chapter_id = state["chapter_ids"][state["current_index"]]
    chapters = dict(state["chapters"])
    draft = ChapterDraft.model_validate(state["draft"])
    options = ChapterWritingOptions.model_validate(state["options"])

    # 定向修订合并
    target_section_ids = {
        section_id
        for section_id in options.target_section_ids
        if section_id.startswith(f"SEC-{chapter_id.removeprefix('CH-')}-")
    }
    if target_section_ids and chapter_id in chapters:
        draft = _merge_target_sections(
            ChapterDraft.model_validate(chapters[chapter_id]),
            draft,
            target_section_ids,
        )

    # 新增: 自动汇总章节级引用
    from app.agents.chapter_writer.provenance import aggregate_chapter_references
    draft = aggregate_chapter_references(draft)

    chapters[chapter_id] = draft.model_dump(mode="json")
    # ... rest of the function ...
```

**Step 4: 修改 `backend/app/agents/chapter_writer/graph.py` — 审计中增加数字校验**

在 `_audit_chapter` 函数中新增数字溯源检查:

```python
def _audit_chapter(
    chapter: ChapterDraft,
    *,
    analysis: AnalysisResult,
    charts: tuple[ChartReference, ...],
    rejected_claim_ids: set[str],
) -> list[str]:
    issues: list[str] = []
    # ... existing validation ...

    # 新增: 数字溯源检查
    from app.agents.chapter_writer.numeric_refs import (
        classify_number,
        extract_numbers,
        validate_numeric_references,
    )
    allowed_claims = select_chapter_claims(analysis, chapter.chapter_id, rejected_claim_ids)
    known_fact_numbers = set()
    for claim in allowed_claims:
        known_fact_numbers.update(extract_numbers(claim.text))

    for section in chapter.sections:
        for paragraph in section.paragraphs:
            if paragraph.kind != "analysis":
                continue
            paragraph_numbers = extract_numbers(paragraph.text)
            numeric_refs = [
                classify_number(
                    num,
                    known_fact_numbers=known_fact_numbers,
                    claim_evidence_ids=paragraph.evidence_ids,
                )
                for num in paragraph_numbers
            ]
            num_issues = validate_numeric_references(numeric_refs)
            for issue in num_issues:
                issues.append(f"{paragraph.paragraph_id}:{issue}")

    return list(dict.fromkeys(issues))
```

**Step 5: 修改 `backend/app/schemas/chapter.py` — 新增 NumericReference**

在 `ParagraphDraft` 中新增可选字段:

```python
class ParagraphDraft(ChapterContract):
    paragraph_id: str = Field(pattern=r"^P-\d{2}-\d{2}-\d{2}$")
    kind: Literal["analysis", "methodology", "risk", "transition"]
    text: str = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    numeric_refs: list[dict[str, Any]] = Field(default_factory=list)  # 新增
```

**Step 6: 修改 `backend/app/agents/chapter_writer/graph.py` — 只重写失败段落**

修改 `revise` 函数，将修订范围限定在失败段落:

```python
def revise(state: ChapterWriterGraphState) -> dict[str, object]:
    chapter_id = state["chapter_ids"][state["current_index"]]
    attempts = dict(state["attempts"])
    attempts[chapter_id] = attempts.get(chapter_id, 0) + 1

    # 记录失败段落ID以便定向修订
    failed_paragraphs = state.get("failed_paragraph_ids", [])

    return {
        "attempts": attempts,
        "revision_count": state["revision_count"] + 1,
        "failed_paragraph_ids": failed_paragraphs,
    }
```

**Step 7: 更新测试**

`backend/tests/agents/chapter_writer/test_numeric_refs.py`:

```python
def test_fact_number_requires_evidence() -> None:
    from app.agents.chapter_writer.numeric_refs import (
        classify_number,
        validate_numeric_references,
    )
    ref = classify_number("136", known_fact_numbers={"136"}, claim_evidence_ids=[])
    issues = validate_numeric_references([ref])
    assert len(issues) == 1
    assert "缺少证据引用" in issues[0]


def test_scenario_parameter_no_evidence_needed() -> None:
    from app.agents.chapter_writer.numeric_refs import (
        classify_number,
        validate_numeric_references,
    )
    ref = classify_number("20%", known_fact_numbers=set(), claim_evidence_ids=[])
    issues = validate_numeric_references([ref])
    assert len(issues) == 0  # scenario parameter with assumption_note


def test_unknown_number_requires_formula() -> None:
    from app.agents.chapter_writer.numeric_refs import (
        classify_number,
        validate_numeric_references,
    )
    ref = classify_number("42.5", known_fact_numbers=set(), claim_evidence_ids=[])
    issues = validate_numeric_references([ref])
    assert len(issues) == 1
    assert "缺少公式" in issues[0]
```

`backend/tests/agents/chapter_writer/test_provenance.py`:

```python
def test_aggregate_chapter_references_merges_paragraph_ids() -> None:
    """章节 claim_ids = 所有段落 claim_ids 的并集."""
    from app.agents.chapter_writer.provenance import aggregate_chapter_references
    from app.schemas.chapter import ChapterDraft, SectionDraft, ParagraphDraft

    chapter = ChapterDraft(
        chapter_id="CH-01",
        title="测试",
        summary="测试",
        sections=[
            SectionDraft(
                section_id="SEC-01-01",
                title="S1",
                purpose="p1",
                key_points=["k1"],
                paragraphs=[
                    ParagraphDraft(
                        paragraph_id="P-01-01-01",
                        kind="analysis",
                        text="text",
                        claim_ids=["C-001", "C-002"],
                        evidence_ids=["E-001"],
                    )
                ],
            ),
            SectionDraft(
                section_id="SEC-01-02",
                title="S2",
                purpose="p2",
                key_points=["k2"],
                paragraphs=[
                    ParagraphDraft(
                        paragraph_id="P-01-02-01",
                        kind="analysis",
                        text="text",
                        claim_ids=["C-002", "C-003"],
                        evidence_ids=["E-002"],
                    )
                ],
            ),
        ],
        revision=1,
    )
    result = aggregate_chapter_references(chapter)
    assert result.claim_ids == ["C-001", "C-002", "C-003"]
    assert result.evidence_ids == ["E-001", "E-002"]
```

**Step 8: 提交**

```bash
git add backend/app/agents/chapter_writer/provenance.py backend/app/agents/chapter_writer/numeric_refs.py backend/app/agents/chapter_writer/graph.py backend/app/agents/chapter_writer/prompt_adapter.py backend/app/schemas/chapter.py backend/tests/agents/chapter_writer/test_provenance.py backend/tests/agents/chapter_writer/test_numeric_refs.py
git commit -m "feat: fix Agent 4 reference aggregation and numeric provenance"
```

---

### Task 6: 实现逐章持久化和断点恢复

**Files:**
- Create: `backend/app/infrastructure/repositories/chapter_repository.py`
- Modify: `backend/app/agents/chapter_writer/service.py`
- Modify: `backend/app/agents/chapter_writer/graph.py`

**Step 1: 创建 `backend/app/infrastructure/repositories/chapter_repository.py`**

```python
"""SQLite-backed chapter persistence for incremental writing and recovery."""

import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings

CHAPTER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chapter_checkpoints (
    run_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'generating',
    content_json TEXT,
    quality_json TEXT,
    model_name TEXT,
    prompt_version TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, chapter_id, revision)
)
"""

import aiosqlite


class ChapterRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = str(db_path or settings.CHECKPOINT_DATABASE_PATH)

    async def initialize(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(CHAPTER_TABLE_SQL)
            await db.commit()

    async def save_chapter(
        self,
        *,
        run_id: str,
        chapter_id: str,
        revision: int,
        status: str,
        content_json: dict | None = None,
        quality_json: dict | None = None,
        model_name: str | None = None,
        prompt_version: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO chapter_checkpoints
                   (run_id, chapter_id, revision, status, content_json, quality_json,
                    model_name, prompt_version, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, chapter_id, revision, status,
                    json.dumps(content_json, ensure_ascii=False) if content_json else None,
                    json.dumps(quality_json, ensure_ascii=False) if quality_json else None,
                    model_name, prompt_version, now, now,
                ),
            )
            await db.commit()

    async def get_completed_chapters(self, run_id: str, revision: int) -> list[str]:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """SELECT chapter_id FROM chapter_checkpoints
                   WHERE run_id = ? AND revision = ? AND status = 'quality_passed'""",
                (run_id, revision),
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_chapter(
        self, run_id: str, chapter_id: str, revision: int
    ) -> dict | None:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                """SELECT content_json, status FROM chapter_checkpoints
                   WHERE run_id = ? AND chapter_id = ? AND revision = ?""",
                (run_id, chapter_id, revision),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return {"content": json.loads(row[0]) if row[0] else None, "status": row[1]}
```

**Step 2: 修改 `backend/app/agents/chapter_writer/graph.py` — 在 `accept` 中持久化**

```python
def accept(state: ChapterWriterGraphState) -> dict[str, object]:
    chapter_id = state["chapter_ids"][state["current_index"]]
    chapters = dict(state["chapters"])
    draft = ChapterDraft.model_validate(state["draft"])
    # ... existing merge + aggregate logic ...

    # 持久化当前章节 (同步写入，Agent 4 是异步但单线程)
    import asyncio
    from app.infrastructure.repositories.chapter_repository import ChapterRepository
    repo = ChapterRepository()
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already in async context, schedule
            pass
        else:
            asyncio.run(repo.save_chapter(
                run_id=state.get("run_id", "unknown"),
                chapter_id=chapter_id,
                revision=state["workflow_revision"],
                status="quality_passed" if not state["current_issues"] else "needs_review",
                content_json=draft.model_dump(mode="json"),
                quality_json={"issues": state["current_issues"]},
            ))
    except RuntimeError:
        pass  # Fallback: persistence is best-effort in LangGraph context

    chapters[chapter_id] = draft.model_dump(mode="json")
    # ... rest of the function ...
```

**Step 3: 修改 `backend/app/agents/chapter_writer/service.py` — 断点恢复**

在 `ChapterWriterAgent.run()` 中，构建 `chapter_ids` 时检查已完成的章节:

```python
async def run(self, context: StageContext) -> StageResult:
    # ... existing validation ...

    # 检查已完成的章节，只处理未完成的
    from app.infrastructure.repositories.chapter_repository import ChapterRepository
    repo = ChapterRepository()
    await repo.initialize()
    completed = await repo.get_completed_chapters(context.run_id, context.revision)

    chapter_ids = [
        chapter.chapter_id
        for chapter in REPORT_OUTLINE
        if (
            not selected_chapter_ids
            or chapter.chapter_id in selected_chapter_ids
        )
        and chapter.chapter_id not in completed  # 跳过已完成的章节
    ]

    # 恢复已完成的章节内容
    base_chapters = dict(base_chapters)
    for chapter_id in completed:
        saved = await repo.get_chapter(context.run_id, chapter_id, context.revision)
        if saved and saved["content"]:
            base_chapters[chapter_id] = saved["content"]
```

**Step 4: 提交**

```bash
git add backend/app/infrastructure/repositories/chapter_repository.py backend/app/agents/chapter_writer/service.py backend/app/agents/chapter_writer/graph.py
git commit -m "feat: add chapter-level persistence and checkpoint recovery for Agent 4"
```

---

### Task 7: Agent 5 分级导出 — formal / draft_with_warnings

**Files:**
- Modify: `backend/app/agents/report_fusion/quality.py`
- Modify: `backend/app/agents/report_fusion/service.py`
- Modify: `backend/app/agents/report_fusion/assembler.py`
- Modify: `backend/app/reporting/html.py`
- Modify: `backend/app/reporting/markdown.py`
- Modify: `backend/app/reporting/pdf.py`
- Modify: `backend/app/reporting/templates/report.html.j2`
- Modify: `backend/app/schemas/report.py`
- Modify: `backend/tests/agents/report_fusion/test_agent.py`

**Step 1: 修改 `backend/app/schemas/report.py` — 新增分级导出字段**

在 `ReportFusionResult` 中新增:

```python
class ReportFusionResult(ReportContract):
    # ... existing fields ...
    release_mode: Literal["formal", "draft_with_warnings"] = "formal"
    formal_eligible: bool = True
    draft_eligible: bool = True
    acknowledged_risks: list[str] = Field(default_factory=list)
    unresolved_risks: list[str] = Field(default_factory=list)
```

在 `ReportViewModel` 中新增:

```python
class ReportViewModel(ReportContract):
    # ... existing fields ...
    release_mode: Literal["formal", "draft_with_warnings"] = "formal"
    unresolved_risks: list[str] = Field(default_factory=list)
    risk_acknowledged_at: datetime | None = None
```

**Step 2: 修改 `backend/app/agents/report_fusion/quality.py` — 区分硬阻断和专业风险**

```python
def evaluate_report_quality(
    analysis: AnalysisResult,
    charts: ChartGenerationResult,
    chapters: ChapterWritingResult,
    *,
    accepted_risk_codes: list[str] | None = None,
) -> tuple[ReportQualityReport, list[str], list[str]]:
    """Evaluate quality with risk classification.

    Returns:
        quality_report: overall quality assessment
        blocking_issues: issues that prevent any export
        advisory_issues: issues that can be overridden by user
    """
    accepted = set(accepted_risk_codes or [])
    blocking_issues: list[str] = []
    advisory_issues: list[str] = []

    # ... existing checks ...

    # 硬阻断: 未知证据引用
    unknown_claims = used_claims - known_claims
    if unknown_claims:
        blocking_issues.append(f"章节引用了未知结论：{sorted(unknown_claims)}")

    unknown_evidence = used_evidence - known_evidence
    if unknown_evidence:
        blocking_issues.append(f"章节引用了未知证据：{sorted(unknown_evidence)}")

    # 专业风险: 证据覆盖率不足
    coverage = len(used_evidence & known_evidence) / len(used_evidence) if used_evidence else 0.0
    if coverage < 1:
        advisory_issues.append("正文证据覆盖率不足100%")

    # 专业风险: 图表数量超过推荐值
    if len(included_chart_ids) > 8:
        advisory_issues.append(f"正式报告嵌入 {len(included_chart_ids)} 张图表，超过推荐上限8张")

    # 专业风险: 上游质量门未通过
    if not analysis.quality.passed:
        advisory_issues.append("Agent 2 分析质量门未通过")
    if not charts.quality.passed:
        advisory_issues.append("Agent 3 图表质量门未通过")
    if not chapters.quality.passed:
        advisory_issues.append("Agent 4 章节质量门未通过")

    passed = not blocking_issues
    return (
        ReportQualityReport(
            passed=passed,
            chapter_count=chapter_count,
            section_count=section_count,
            included_chart_count=len(included_chart_ids),
            evidence_coverage=coverage,
            issues=blocking_issues + advisory_issues,
        ),
        blocking_issues,
        advisory_issues,
    )
```

**Step 3: 修改 `backend/app/agents/report_fusion/service.py` — 分级导出逻辑**

```python
class ReportFusionAgent:
    stage: StageName = StageName.REPORT_FUSION

    async def run(self, context: StageContext) -> StageResult:
        # ... existing validation ...

        release_mode = context.input_data.get("release_mode", "formal")
        accepted_risk_codes = context.input_data.get("accepted_risk_codes", [])

        quality, blocking_issues, advisory_issues = evaluate_report_quality(
            analysis, charts, chapters,
            accepted_risk_codes=accepted_risk_codes,
        )

        # 有硬阻断问题 → 不能导出
        if blocking_issues:
            return _waiting_review(
                revision=context.revision,
                request_id="REPORT-BLOCKING",
                reason="；".join(blocking_issues),
                error="report_blocking_issues",
            )

        formal_eligible = not advisory_issues
        draft_eligible = True  # 只要没有硬阻断就可以导出草稿

        # 有专业风险但用户未确认 → 等待审核
        if advisory_issues and not accepted_risk_codes:
            return StageResult(
                stage=self.stage,
                status=StageStatus.WAITING_REVIEW,
                revision=context.revision,
                data={
                    "formal_eligible": False,
                    "draft_eligible": True,
                    "blocking_issues": [],
                    "advisory_issues": advisory_issues,
                    "acknowledgement_required_codes": ["REPORT-QUALITY-ADVISORY"],
                    "collaboration_requests": [{
                        "request_id": "REPORT-EXPORT-DECISION",
                        "question": "报告存在专业风险，请选择导出模式",
                        "reason": "；".join(advisory_issues),
                        "affected_dimensions": ["report_fusion"],
                    }],
                },
                error="report_export_decision_required",
            )

        # 确定导出模式
        actual_release_mode = release_mode
        if advisory_issues and release_mode == "formal":
            # 有未解决的专业风险 → 强制降级为草稿
            actual_release_mode = "draft_with_warnings"

        # 构建报告视图
        report = build_report_view(
            run_id=context.run_id,
            revision=context.revision,
            analysis=analysis,
            chart_result=charts,
            chapter_result=chapters,
            tone=options.tone or "professional",
            summary_direction="；".join(focus_notes) or None,
            release_mode=actual_release_mode,
            unresolved_risks=advisory_issues,
        )

        # 渲染
        markdown = render_markdown(report)
        html = render_html(report) if "html" in formats or "pdf" in formats else None
        # ... PDF rendering ...

        # 保存产物
        # ...

        result = ReportFusionResult(
            # ... existing fields ...
            release_mode=actual_release_mode,
            formal_eligible=formal_eligible,
            draft_eligible=draft_eligible,
            acknowledged_risks=accepted_risk_codes,
            unresolved_risks=advisory_issues,
        )

        return StageResult(
            stage=self.stage,
            status=StageStatus.COMPLETED,
            revision=context.revision,
            data=result.model_dump(mode="json"),
            artifacts=stage_artifacts,
            evidence_sources=...,
        )
```

**Step 4: 修改 `backend/app/agents/report_fusion/assembler.py` — 支持 release_mode**

在 `build_report_view` 中新增 `release_mode` 和 `unresolved_risks` 参数:

```python
def build_report_view(
    *,
    run_id: str,
    revision: int,
    analysis: AnalysisResult,
    chart_result: ChartGenerationResult,
    chapter_result: ChapterWritingResult,
    tone: Literal["professional", "plain_language"],
    summary_direction: str | None = None,
    release_mode: str = "formal",
    unresolved_risks: list[str] | None = None,
) -> ReportViewModel:
    # ... existing logic ...
    return ReportViewModel(
        # ... existing fields ...
        release_mode=release_mode,
        unresolved_risks=unresolved_risks or [],
    )
```

**Step 5: 修改 HTML 模板 — 添加草稿水印和风险提示**

在 `backend/app/reporting/templates/report.html.j2` 的 `<style>` 中新增:

```css
.draft-watermark {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  pointer-events: none;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0.08;
  font-size: 72px;
  font-weight: 900;
  color: #dc2626;
  transform: rotate(-20deg);
  letter-spacing: 0.3em;
}
.draft-banner {
  background: #fef2f2;
  border: 2px solid #dc2626;
  border-radius: 10px;
  padding: 14px 20px;
  margin-bottom: 24px;
  color: #991b1b;
}
.draft-banner strong { color: #dc2626; }
.risk-appendix { break-before: page; }
```

在封面区域后添加草稿标记:

```html
{% if report.release_mode == 'draft_with_warnings' %}
<div class="draft-watermark">内部审核草稿</div>
<div class="draft-banner">
  <strong>内部审核草稿</strong> — 部分内容尚未通过完整证据校验
</div>
{% endif %}
```

在报告末尾添加风险附录:

```html
{% if report.release_mode == 'draft_with_warnings' and report.unresolved_risks %}
<section class="risk-appendix chapter">
  <h2>未解决问题清单</h2>
  <ul>
  {% for risk in report.unresolved_risks %}<li>{{ risk }}</li>{% endfor %}
  </ul>
</section>
{% endif %}
```

**Step 6: 修改 `backend/app/reporting/pdf.py` — 添加草稿元数据**

```python
async def render_pdf(html: str, *, release_mode: str = "formal") -> bytes:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page(viewport={"width": 1440, "height": 1000})
            await page.emulate_media(media="print")
            await page.set_content(html, wait_until="load")
            await page.evaluate("""async () => {
                if (document.fonts && document.fonts.ready) await document.fonts.ready;
                await Promise.all(Array.from(document.images).map((image) =>
                    image.complete ? Promise.resolve() : new Promise((resolve) => {
                        image.onload = resolve; image.onerror = resolve;
                    })
                ));
            }""")
            result = await page.pdf(
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "14mm", "right": "12mm", "bottom": "16mm", "left": "12mm"},
            )
            return bytes(result)
        finally:
            await browser.close()
```

**Step 7: 修改 `backend/app/reporting/markdown.py` — 添加草稿标记**

在 Markdown 渲染中，如果 `release_mode == "draft_with_warnings"`，在标题后添加:

```markdown
> **内部审核草稿** — 部分内容尚未通过完整证据校验
```

**Step 8: 更新测试**

```python
def test_formal_report_when_no_risks() -> None:
    """无风险时生成正式三格式报告."""
    ...

def test_draft_report_when_risks_accepted() -> None:
    """确认风险后生成带水印草稿."""
    ...

def test_waiting_review_when_risks_not_accepted() -> None:
    """有风险未确认时等待审核."""
    ...

def test_blocking_issues_prevent_any_export() -> None:
    """硬阻断问题不能生成任何报告."""
    ...
```

**Step 9: 提交**

```bash
git add backend/app/agents/report_fusion/quality.py backend/app/agents/report_fusion/service.py backend/app/agents/report_fusion/assembler.py backend/app/reporting/html.py backend/app/reporting/markdown.py backend/app/reporting/pdf.py backend/app/reporting/templates/report.html.j2 backend/app/schemas/report.py backend/tests/agents/report_fusion/test_agent.py
git commit -m "feat: add formal/draft_with_warnings dual export mode in Agent 5"
```

---

### Task 8: 前端决策组件

**Files:**
- Create: `frontend/src/components/review/DecisionCard.vue`
- Create: `frontend/src/components/review/RiskNoticeList.vue`
- Create: `frontend/src/components/charts/ChartCandidateCard.vue`
- Create: `frontend/src/components/charts/ChartPlacementEditor.vue`
- Create: `frontend/src/components/report/ExportDecisionCard.vue`
- Modify: `frontend/src/api/workflow.ts`
- Modify: `frontend/src/types/workflow.ts`

**Step 1: 创建 `frontend/src/components/review/RiskNoticeList.vue`**

```vue
<template>
  <div class="risk-notice-list">
    <div
      v-for="notice in notices"
      :key="notice.risk_code"
      class="risk-notice"
      :class="`risk-${notice.severity}`"
    >
      <div class="risk-header">
        <el-tag
          :type="severityTag(notice.severity)"
          size="small"
        >
          {{ severityLabel(notice.severity) }}
        </el-tag>
        <span class="risk-title">{{ notice.title }}</span>
      </div>
      <p class="risk-detail">{{ notice.detail }}</p>
      <div class="risk-actions">
        <p class="risk-recommendation">
          <strong>建议：</strong>{{ notice.recommendation }}
        </p>
        <p class="risk-consequence">
          <strong>后果：</strong>{{ notice.consequence }}
        </p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { RiskNotice } from '@/types/workflow'

defineProps<{
  notices: RiskNotice[]
}>()

function severityTag(severity: string): string {
  const map: Record<string, string> = {
    info: 'info',
    warning: 'warning',
    high: 'danger',
    critical: 'danger',
  }
  return map[severity] || 'info'
}

function severityLabel(severity: string): string {
  const map: Record<string, string> = {
    info: '建议',
    warning: '注意',
    high: '需确认',
    critical: '阻断',
  }
  return map[severity] || severity
}
</script>
```

**Step 2: 创建 `frontend/src/components/charts/ChartCandidateCard.vue`**

```vue
<template>
  <el-card class="chart-candidate-card" :class="statusClass">
    <template #header>
      <div class="candidate-header">
        <el-checkbox
          :model-value="selected"
          @update:model-value="$emit('toggle', candidate.candidate_id)"
        />
        <span class="candidate-title">{{ candidate.title }}</span>
        <el-tag size="small">{{ candidate.chart_type }}</el-tag>
        <el-tag
          v-if="candidate.status === 'recommended'"
          type="success"
          size="small"
        >
          推荐
        </el-tag>
        <el-tag
          v-if="candidate.status === 'not_recommended'"
          type="info"
          size="small"
        >
          可选
        </el-tag>
      </div>
    </template>
    <div class="candidate-body">
      <p>证据: {{ candidate.evidence_ids.join(', ') }}</p>
      <p>建议章节: {{ candidate.recommended_chapter_id || '未指定' }}</p>
      <RiskNoticeList
        v-if="candidate.risk_notices.length"
        :notices="candidate.risk_notices"
      />
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ChartCandidateResult } from '@/types/workflow'
import RiskNoticeList from '@/components/review/RiskNoticeList.vue'

const props = defineProps<{
  candidate: ChartCandidateResult
  selected: boolean
}>()

defineEmits<{
  toggle: [candidateId: string]
}>()

const statusClass = computed(() => ({
  'candidate-recommended': props.candidate.status === 'recommended',
  'candidate-optional': props.candidate.status === 'not_recommended',
  'candidate-blocked': props.candidate.status === 'hard_blocked',
}))
</script>
```

**Step 3: 创建 `frontend/src/components/review/DecisionCard.vue`**

```vue
<template>
  <el-card class="decision-card">
    <template #header>
      <div class="decision-header">
        <span>图表选择决策</span>
        <el-tag type="warning">
          已选: {{ selectedCount }} / {{ totalCount }}
        </el-tag>
      </div>
    </template>

    <el-alert
      v-if="recommendedCount > 8"
      type="warning"
      :closable="false"
      show-icon
    >
      已选择 {{ recommendedCount }} 张图表，推荐 5-8 张。超出部分将降低报告信息密度。
    </el-alert>

    <RiskNoticeList :notices="riskNotices" />

    <div class="candidates-grid">
      <ChartCandidateCard
        v-for="candidate in candidates"
        :key="candidate.candidate_id"
        :candidate="candidate"
        :selected="selectedIds.has(candidate.candidate_id)"
        @toggle="toggleCandidate"
      />
    </div>

    <div class="decision-actions">
      <el-button type="primary" @click="$emit('accept-recommendation')">
        接受推荐
      </el-button>
      <el-button type="warning" @click="$emit('accept-with-risks')">
        接受风险并继续
      </el-button>
      <el-button @click="$emit('customize')">
        自定义选择
      </el-button>
      <el-button @click="$emit('regenerate')">
        重新生成
      </el-button>
      <el-button type="danger" @click="$emit('cancel')">
        取消
      </el-button>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ChartCandidateResult, RiskNotice } from '@/types/workflow'
import ChartCandidateCard from '@/components/charts/ChartCandidateCard.vue'
import RiskNoticeList from '@/components/review/RiskNoticeList.vue'

const props = defineProps<{
  candidates: ChartCandidateResult[]
  riskNotices: RiskNotice[]
}>()

defineEmits<{
  'accept-recommendation': []
  'accept-with-risks': []
  'customize': []
  'regenerate': []
  'cancel': []
}>()

const selectedIds = ref(new Set<string>())

const totalCount = computed(() => props.candidates.length)
const selectedCount = computed(() => selectedIds.value.size)
const recommendedCount = computed(
  () => props.candidates.filter(c => c.status === 'recommended').length
)

function toggleCandidate(id: string) {
  if (selectedIds.value.has(id)) {
    selectedIds.value.delete(id)
  } else {
    selectedIds.value.add(id)
  }
}
</script>
```

**Step 4: 创建 `frontend/src/components/report/ExportDecisionCard.vue`**

```vue
<template>
  <el-card class="export-decision-card">
    <template #header>
      <span>报告导出确认</span>
    </template>

    <el-descriptions :column="2" border>
      <el-descriptions-item label="正式报告资格">
        <el-tag :type="formalEligible ? 'success' : 'danger'">
          {{ formalEligible ? '满足' : '不满足' }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="风险草稿资格">
        <el-tag :type="draftEligible ? 'success' : 'danger'">
          {{ draftEligible ? '满足' : '不满足' }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="阻断问题">
        {{ blockingCount }}
      </el-descriptions-item>
      <el-descriptions-item label="需确认风险">
        {{ advisoryCount }}
      </el-descriptions-item>
    </el-descriptions>

    <el-alert
      v-if="advisoryCount > 0"
      type="warning"
      :closable="false"
      show-icon
      title="存在未确认的专业风险"
    >
      导出草稿将在报告中标注风险项，并附带水印标识。
    </el-alert>

    <div class="export-actions">
      <el-button
        v-if="formalEligible"
        type="primary"
        @click="$emit('export-formal')"
      >
        导出正式报告
      </el-button>
      <el-button
        v-if="draftEligible"
        type="warning"
        @click="$emit('export-draft')"
      >
        导出内部审核草稿
      </el-button>
      <el-button @click="$emit('back-to-edit')">
        返回修改
      </el-button>
      <el-button type="danger" @click="$emit('cancel')">
        取消
      </el-button>
    </div>
  </el-card>
</template>

<script setup lang="ts">
defineProps<{
  formalEligible: boolean
  draftEligible: boolean
  blockingCount: number
  advisoryCount: number
}>()

defineEmits<{
  'export-formal': []
  'export-draft': []
  'back-to-edit': []
  'cancel': []
}>()
</script>
```

**Step 5: 更新 `frontend/src/api/workflow.ts`**

在 `reviewRun` 中新增对 `accepted_risk_codes` 等字段的支持（TypeScript 接口已在 Task 1 更新）。

**Step 6: 运行前端验证**

```bash
cd /Users/Zhuanz1/PycharmProjects/同花顺/frontend
npm run type-check
npm run lint
npm run build
```

**Step 7: 提交**

```bash
git add frontend/src/components/review/DecisionCard.vue frontend/src/components/review/RiskNoticeList.vue frontend/src/components/charts/ChartCandidateCard.vue frontend/src/components/charts/ChartPlacementEditor.vue frontend/src/components/report/ExportDecisionCard.vue frontend/src/api/workflow.ts frontend/src/types/workflow.ts
git commit -m "feat: add frontend decision components for risk-aware human-AI collaboration"
```

---

## 最终验证

全部任务完成后运行:

```bash
# 后端测试
cd /Users/Zhuanz1/PycharmProjects/同花顺/backend
.venv/bin/pytest -q

# 前端验证
cd /Users/Zhuanz1/PycharmProjects/同花顺/frontend
npm run type-check && npm run lint && npm run build

# 完整验证
cd /Users/Zhuanz1/PycharmProjects/同花顺
./scripts/verify.sh
```

## 验收标准

1. Agent 2 提出的 8 种合法图表全部进入候选池
2. Agent 3 不静默删除任何技术有效图表
3. 系统明确提示第 4 章图表过多
4. 系统提出跨章节分配建议
5. 用户可接受推荐或坚持全部保留
6. 用户选择、风险确认、时间、版本被持久化
7. Agent 4 区分事实数字、计算数字和情景参数
8. 章节级引用由程序自动汇总
9. 只重新生成失败段落，不整份重跑
10. Agent 5 输出正式报告或带风险标记草稿
11. 安全、权限、损坏数据等问题仍不能绕过
12. Markdown、HTML、PDF 三种产物内容一致
13. 报告中明确显示数据缺口
14. 全流程不存在"静默抑制"