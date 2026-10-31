"""产业链研究共享契约模型（v2，方案 §4）。

═════════════════════════════════════════════════════════════════════════════
设计约束（来自《产业链图AI可执行最终实施方案_20261030.md》）
═════════════════════════════════════════════════════════════════════════════

1. **本包禁止导入 A2/A3 业务 Agent**（A1、A2、A3 通过稳定模型与 bundle 交接）。
2. 所有对外模型必须有 ``schema_version``；对象引用使用 ID，不能用标题当主键。
3. 相同名字不自动合并；同名组织保留候选身份（``identity_status`` 区分）。
4. ``status`` 五态：candidate/supported/contradicted/unresolved/expired。
   程序错误、凭证错误、超时**不是**"反驳事实"——它们进运行诊断（RunDiagnostics），
   永不改写成 contradicted。
5. 模型自报置信度不得直接决定 supported（``verification`` 必须给出独立判定理由）。
6. ``execution_mode`` 是组织参与某活动时的限定条件，不是全局标签。
7. ``coverage_basis`` 必须说明评估依据；仅有 LLM 候选时结构完整性不得标已验证。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "2.1.0"

# ── 常量：实体类型 / 断言状态 / 覆盖依据 / 发布状态 / 执行方式 ─────────────

EntityType = Literal["organization", "product", "activity", "customer_type"]

AssertionStatus = Literal[
    "candidate",     # 候选：仅有模型提议，未验证
    "supported",     # 已支持：有独立证据与验证判定
    "contradicted",  # 被反驳：证据明确否定
    "unresolved",    # 未决：证据冲突无法消解 / 定位不匹配 / 缺关键证据
    "expired",       # 过期：证据曾经支持但已超适用时间
]

ViewKind = Literal["industry", "entity", "product"]

IdentityStatus = Literal["verified", "candidate", "ambiguous", "merged"]

ExecutionMode = Literal["internal", "external", "mixed", "unknown"]

ReleaseStatus = Literal["verified", "partial", "draft", "failed"]

CoverageBasis = Literal[
    "test_golden",            # 测试金标准
    "external_catalog",       # 外部资料结构目录
    "llm_candidate_only",     # 仅有 LLM 候选（不得标已验证）
    "no_basis",               # 无依据
    "profile_policy",         # 版本化画像政策；不是独立金标准
]

DocumentKind = Literal[
    "official_disclosure",   # 官方/主体披露（年报、招股书、官网）
    "authoritative_article", # 可靠原始资料（行业研究报告、技术文献）
    "news_report",           # 新闻报道
    "search_snippet",        # 搜索摘要（仅 candidate 级证据）
    "aggregated_directory",  # 黄页/目录类聚合页
    "other",
]

# ── §4.2 关系词表：少量、语义清晰 ─────────────────────────────────────────

class Predicate(str, Enum):
    """首版关系词表（§4.2）。每种关系有明确的两端类型与限制。"""

    REQUIRES_INPUT = "requires_input"   # 活动使用某类产品/服务输入；不推导具体供货企业
    PRODUCES = "produces"               # 活动产出产品/服务
    PRECEDES = "precedes"               # 工艺/履约次序；分类上下级不得写成工艺次序
    OFFERS = "offers"                    # 组织提供产品/服务的业务能力
    PERFORMS = "performs"               # 组织执行某活动；区分自营/外包/未知
    PARTICIPATES_IN = "participates_in" # 组织以某角色参与某环节；角色写在 qualifiers
    SELLS_THROUGH = "sells_through"     # 渠道关系；不能表示终端使用场景
    SUPPLIES_TO = "supplies_to"         # 企业间供货；需客户范围+产品限定+来源证据
    PROVIDES_SERVICE_TO = "provides_service_to"  # 有明确对象的第三方服务关系
    IS_A = "is_a"                      # 产品分类；不代表工艺或供货
    PART_OF = "part_of"                # 产品构成；不自动推导参与企业


# 关系两端类型约束：predicate -> (subject 允许类型, object 允许类型)
PREDICATE_ENDPOINT_RULES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    #                              subject 允许                    object 允许
    "requires_input":        (("activity",),                     ("product",)),
    "produces":              (("activity",),                     ("product",)),
    "precedes":              (("activity",),                     ("activity",)),
    "offers":                (("organization",),                 ("product",)),
    "performs":              (("organization",),                 ("activity",)),
    "participates_in":       (("organization",),                 ("activity",)),
    "sells_through":         (("organization", "product"),       ("product", "organization")),
    "supplies_to":           (("organization",),                 ("organization", "customer_type")),
    "provides_service_to":   (("organization",),                 ("organization", "activity")),
    "is_a":                 (("product",),                      ("product",)),
    "part_of":              (("product",),                      ("product",)),
}


# ── 工具函数 ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm_key(*parts: str) -> str:
    """稳定 ID 用的规范化键：小写、去空白、拼接。"""
    return "|".join(re.sub(r"\s+", "", p.strip().lower()) for p in parts if p and p.strip())


def stable_id(prefix: str, *key_parts: str) -> str:
    """基于规范化主体内容的确定性 ID（同内容同 ID，跨 revision 可引用）。"""
    raw = _norm_key(*key_parts) or "∅"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


# ── §4.1 模型 ───────────────────────────────────────────────────────────────

class _StrictModel(BaseModel):
    """契约模型基类：禁止未知字段静默透传（防 extra=ignore 漂移）。"""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ChainScope(_StrictModel):
    """研究范围（§5.1 范围解析的产物）。"""

    schema_version: str = Field(default=SCHEMA_VERSION, frozen=True)
    scope_id: str
    subject: str                                   # 主题原文（如「笔记本电脑」）
    view_kind: ViewKind = "industry"
    focal_entity_id: str | None = None             # 企业专属链时聚焦实体
    geography: str = "中国"
    as_of: str                                     # 事实适用时间（如 2026-10）
    granularity: str = "industry_overview"         # 颗粒度
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "ChainScope":
        if self.view_kind == "entity" and not self.focal_entity_id:
            raise ValueError("entity 视图必须提供 focal_entity_id")
        return self


class ChainEntity(_StrictModel):
    """实体：组织/产品/活动/客户类型。同名不自动合并。"""

    schema_version: str = Field(default=SCHEMA_VERSION, frozen=True)
    entity_id: str
    entity_type: EntityType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    identity_status: IdentityStatus = "candidate"
    external_ids: dict[str, str] = Field(default_factory=dict)

    @field_validator("canonical_name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("canonical_name 不能为空")
        return v.strip()


class ChainEvidence(_StrictModel):
    """证据：可定位的原文引用。摘要证据（search_snippet）不自动当作已审原文。"""

    schema_version: str = Field(default=SCHEMA_VERSION, frozen=True)
    evidence_id: str
    document_id: str
    url: str | None = None
    title: str
    document_kind: DocumentKind = "other"
    published_at: str | None = None
    fetched_at: str = Field(default_factory=_now_iso)
    content_hash: str                              # 原文内容哈希（去重/完整性）
    source_family: str                             # 同源转载按同一家族计（不充数）
    locator: str                                   # 页码/段落/字符位置
    quote: str                                     # 原文摘录（保留数字/型号/否定词）

    @field_validator("quote")
    @classmethod
    def _quote_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("quote 不能为空——没有原文定位的断言保持 unresolved")
        return v


class Verification(_StrictModel):
    """验证判定：输入是断言与原文，不是生成器的自我解释（§5.5）。"""

    method: Literal["source_rule", "code_rule", "human_review", "model_assisted", "unverified"] = "unverified"
    verifier_version: str = ""                     # 验证器/规则版本
    rationale: str = ""                            # 判定理由（supported 时必填）
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    conflicting_evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "Verification":
        if self.method != "unverified" and not self.rationale.strip():
            raise ValueError("已验证断言必须给出判定理由")
        return self


class Qualifiers(_StrictModel):
    """断言限定条件（§4.1）：适用产品、组织角色、范围、时间、执行方式。"""

    applicable_products: list[str] = Field(default_factory=list)
    org_role: str | None = None                    # 参与角色（如供应商/整机厂/渠道）
    customer_scope: str | None = None              # 客户/地域范围
    valid_period: str | None = None                # 事实有效时间
    execution_mode: ExecutionMode = "unknown"      # 自营/外包/混合/未知——仅限组织参与活动
    extra: dict[str, str] = Field(default_factory=dict)


class ChainAssertion(_StrictModel):
    """原子断言：主体-谓词-客体 + 限定 + 状态 + 证据。"""

    schema_version: str = Field(default=SCHEMA_VERSION, frozen=True)
    assertion_id: str
    subject_id: str
    predicate: Predicate
    object_id: str
    qualifiers: Qualifiers = Field(default_factory=Qualifiers)
    status: AssertionStatus = "candidate"
    evidence_ids: list[str] = Field(default_factory=list)
    verification: Verification = Field(default_factory=Verification)
    created_at: str = Field(default_factory=_now_iso)

    def endpoint_ok(self, subject_type: str, object_type: str) -> bool:
        rule = PREDICATE_ENDPOINT_RULES.get(self.predicate.value)
        if rule is None:
            return False
        subj_ok, obj_ok = rule
        return subject_type in subj_ok and object_type in obj_ok

    @model_validator(mode="after")
    def _check(self) -> "ChainAssertion":
        # supported 断言必须有证据与已验证判定（§4.1 verification 要求）
        if self.status == "supported":
            if not self.evidence_ids:
                raise ValueError("supported 断言必须挂证据（evidence_ids 非空）")
            if self.verification.method == "unverified":
                raise ValueError("supported 断言必须有已执行的验证判定（method != unverified）")
        return self


class ChainStructure(_StrictModel):
    """结构：范围内的活动集合 + 结构断言 + 覆盖依据。"""

    schema_version: str = Field(default=SCHEMA_VERSION, frozen=True)
    structure_id: str
    scope_id: str
    activity_ids: list[str] = Field(default_factory=list)
    structure_assertion_ids: list[str] = Field(default_factory=list)
    required_activity_ids: list[str] = Field(default_factory=list)
    coverage_basis: CoverageBasis = "llm_candidate_only"
    unresolved: list[str] = Field(default_factory=list)   # 未决问题说明

    @model_validator(mode="after")
    def _check(self) -> "ChainStructure":
        # required 集合必须属于 activity 集合（验收后不得为提分删减）
        missing = set(self.required_activity_ids) - set(self.activity_ids)
        if missing:
            raise ValueError(f"required_activity_ids 不在 activity_ids 内：{sorted(missing)}")
        if self.coverage_basis == "test_golden" and not self.required_activity_ids:
            raise ValueError("以金标准为覆盖依据时必须声明 required_activity_ids")
        return self


class BudgetCounts(_StrictModel):
    """预算已用计数（属 run，不属全局客户端——§5.6）。"""

    search_requests: int = 0
    document_fetches: int = 0
    llm_requests: int = 0
    rounds: int = 0
    wall_seconds: float = 0.0
    cache_hits: int = 0                            # 缓存命中单列，不占真实请求计数


class ResearchBudget(_StrictModel):
    """研究预算（§5.6 首版默认：16 搜索/24 读取/12 LLM/3 轮/240s）。"""

    max_search_requests: int = 16
    max_document_fetches: int = 24
    max_llm_requests: int = 12
    max_rounds: int = 3
    max_wall_seconds: float = 240.0
    used: BudgetCounts = Field(default_factory=BudgetCounts)

    def exceeded(self) -> str | None:
        """返回首个超限维度名；未超限返回 None。"""
        if self.used.search_requests >= self.max_search_requests:
            return "search_requests"
        if self.used.document_fetches >= self.max_document_fetches:
            return "document_fetches"
        if self.used.llm_requests >= self.max_llm_requests:
            return "llm_requests"
        if self.used.rounds >= self.max_rounds:
            return "rounds"
        if self.used.wall_seconds >= self.max_wall_seconds:
            return "wall_seconds"
        return None


class QualityIssue(_StrictModel):
    """质量问题描述（结构/断言/未决项共用）。"""

    severity: Literal["critical", "major", "minor"] = "major"
    code: str                                      # 机器可读错误码
    message: str
    refs: list[str] = Field(default_factory=list)  # 相关 assertion/structure/entity ID


class ChainQualityReport(_StrictModel):
    """质量与发布判断（§6 唯一质量状态）。"""

    schema_version: str = Field(default=SCHEMA_VERSION, frozen=True)
    release_status: ReleaseStatus = "draft"
    structural_issues: list[QualityIssue] = Field(default_factory=list)
    claim_issues: list[QualityIssue] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    evidence_trace_rate: float | None = None       # supported 断言证据可追溯率
    coverage_basis: CoverageBasis = "no_basis"
    coverage_values: dict[str, Any] = Field(default_factory=dict)
    reason_codes: list[str] = Field(default_factory=list)

    @field_validator("evidence_trace_rate")
    @classmethod
    def _trace_rate(cls, v: float | None) -> float | None:
        if v is None:
            return None                            # 分母为零 → not_evaluated（§10）
        if not 0.0 <= v <= 1.0:
            raise ValueError("evidence_trace_rate 必须在 [0,1]")
        return v


class ProductCategory(_StrictModel):
    category_id: str
    name: str
    aliases: list[str]
    application_terms: list[str] = Field(default_factory=list)
    excluded_terms: list[str] = Field(default_factory=list)
    source_refs: list[str]


class ActivityPolicy(_StrictModel):
    activity_key: str
    name: str
    stage: Literal["upstream", "midstream", "downstream", "support"]
    activity_kind: Literal["input", "process", "brand", "channel", "scenario", "service"]
    company_display_policy: Literal["representative", "executor", "scenario", "process"] = "representative"
    default_execution_mode: ExecutionMode = "unknown"
    description: str = ""
    required: bool = True
    category_ids: list[str] = Field(default_factory=list)
    allowed_roles: list[str] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class IndustryProfile(_StrictModel):
    schema_version: str = SCHEMA_VERSION
    profile_id: str
    version: str
    status: Literal["draft", "reviewed"] = "draft"
    subject: str
    aliases: list[str]
    view_kind: ViewKind = "industry"
    granularity: str = "industry_overview"
    geography: str = "global"
    as_of: str
    review_after: str
    source_refs: list[str]
    activities: list[ActivityPolicy]
    categories: list[ProductCategory]

    @model_validator(mode="after")
    def _profile_refs(self):
        keys = [a.activity_key for a in self.activities]
        cats = [c.category_id for c in self.categories]
        if len(set(keys)) != len(keys) or len(set(cats)) != len(cats):
            raise ValueError("画像活动或类别 ID 重复")
        if any(set(a.category_ids) - set(cats) for a in self.activities):
            raise ValueError("画像引用未知产品类别")
        if not self.source_refs or any(not c.source_refs for c in self.categories):
            raise ValueError("画像及类别必须声明依据；待审来源不能标人工通过")
        return self


class MembershipDecision(_StrictModel):
    decision_id: str
    organization_id: str
    activity_key: str
    status: Literal["accepted", "rejected", "unknown"]
    rule_id: str = "product_scope_role"
    rule_version: str = "1.0.0"
    profile_version: str
    input_assertion_ids: list[str] = Field(default_factory=list)
    taxonomy_refs: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class BundleManifest(_StrictModel):
    """manifest：代码/模型/提示词/范围/预算/来源策略版本（§7.1）。"""

    schema_version: str = Field(default=SCHEMA_VERSION, frozen=True)
    run_id: str
    revision: int = 1
    created_at: str = Field(default_factory=_now_iso)
    engine_mode: Literal["legacy", "shadow", "evidence_v2"] = "evidence_v2"
    code_version: str = ""                         # git HEAD
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    budget_snapshot: ResearchBudget = Field(default_factory=ResearchBudget)
    source_policy_version: str = ""
    scope_subject: str = ""
    notes: list[str] = Field(default_factory=list)
    research_strategy: Literal["profile_guided", "explore"] = "explore"
    profile_id: str | None = None
    profile_version: str | None = None


class ChainKnowledgeBundle(_StrictModel):
    """完整版本化语义交接包（A1 → A2/A3 的唯一事实载体）。"""

    schema_version: str = Field(default=SCHEMA_VERSION, frozen=True)
    run_id: str
    revision: int = 1
    scope: ChainScope
    entities: list[ChainEntity] = Field(default_factory=list)
    assertions: list[ChainAssertion] = Field(default_factory=list)
    evidence: list[ChainEvidence] = Field(default_factory=list)
    structure: ChainStructure
    quality: ChainQualityReport = Field(default_factory=ChainQualityReport)
    manifest: BundleManifest
    profile_snapshot: IndustryProfile | None = None
    membership_decisions: list[MembershipDecision] = Field(default_factory=list)

    # ── 引用完整性校验（T1 验收：缺失引用不能进入 bundle）─────────────────
    @model_validator(mode="after")
    def _check_references(self) -> "ChainKnowledgeBundle":
        entity_ids = {e.entity_id for e in self.entities}
        evidence_ids = {e.evidence_id for e in self.evidence}

        dup_entities = _find_duplicates(e.entity_id for e in self.entities)
        if dup_entities:
            raise ValueError(f"实体 ID 重复：{sorted(dup_entities)}")
        dup_evidence = _find_duplicates(e.evidence_id for e in self.evidence)
        if dup_evidence:
            raise ValueError(f"证据 ID 重复：{sorted(dup_evidence)}")
        dup_assertions = _find_duplicates(a.assertion_id for a in self.assertions)
        if dup_assertions:
            raise ValueError(f"断言 ID 重复：{sorted(dup_assertions)}")

        # 断言两端必须指向存在的实体
        for a in self.assertions:
            for role, ref in (("subject", a.subject_id), ("object", a.object_id)):
                if ref not in entity_ids:
                    raise ValueError(f"断言 {a.assertion_id} 的 {role} 引用缺失：{ref}")
            # 证据引用必须存在
            for ev in a.evidence_ids:
                if ev not in evidence_ids:
                    raise ValueError(f"断言 {a.assertion_id} 引用缺失证据：{ev}")

        # 结构引用的活动/断言必须存在
        assertion_ids = {a.assertion_id for a in self.assertions}
        for decision in self.membership_decisions:
            if decision.organization_id not in entity_ids:
                raise ValueError("归属判定引用未知组织")
            if set(decision.input_assertion_ids) - assertion_ids:
                raise ValueError("归属判定引用未知断言")
            if not self.profile_snapshot or decision.activity_key not in {
                    a.activity_key for a in self.profile_snapshot.activities}:
                raise ValueError("归属判定缺少对应画像活动")
            if decision.profile_version != self.profile_snapshot.version:
                raise ValueError("归属判定画像版本不一致")
        if self.profile_snapshot and (
                self.manifest.profile_id != self.profile_snapshot.profile_id
                or self.manifest.profile_version != self.profile_snapshot.version):
            raise ValueError("manifest 与画像快照不一致")
        for act in self.structure.activity_ids:
            if act not in entity_ids:
                raise ValueError(f"结构引用缺失活动实体：{act}")
        for said in self.structure.structure_assertion_ids:
            if said not in assertion_ids:
                raise ValueError(f"结构引用缺失断言：{said}")

        # 结构必须属于同一 scope
        if self.structure.scope_id != self.scope.scope_id:
            raise ValueError("structure.scope_id 与 bundle.scope 不一致")
        # revision 一致性
        if self.manifest.revision != self.revision:
            raise ValueError("manifest.revision 与 bundle.revision 不一致")
        return self

    # ── 便捷访问 ─────────────────────────────────────────────────────────
    def entity_by_id(self, entity_id: str) -> ChainEntity | None:
        return next((e for e in self.entities if e.entity_id == entity_id), None)

    def evidence_by_id(self, evidence_id: str) -> ChainEvidence | None:
        return next((e for e in self.evidence if e.evidence_id == evidence_id), None)

    def supported_assertions(self) -> list[ChainAssertion]:
        return [a for a in self.assertions if a.status == "supported"]


def _find_duplicates(values: Any) -> set[str]:
    seen: set[str] = set()
    dup: set[str] = set()
    for v in values:
        if v in seen:
            dup.add(v)
        seen.add(v)
    return dup


# ── 请求/事件类型（§4.3 契约签名所必需的输入输出类型）────────────────────

class RunDiagnostics(_StrictModel):
    """运行诊断：程序错误、凭证错误、超时记录在这里，不改写成 contradicted。"""

    errors: list[QualityIssue] = Field(default_factory=list)
    warnings: list[QualityIssue] = Field(default_factory=list)
    provider_drops: list[str] = Field(default_factory=list)   # 丢弃原因统计


class ChainResearchRequest(_StrictModel):
    """研究请求（A1 协调器 → 研究服务）。"""

    run_id: str
    scope: ChainScope
    budget: ResearchBudget = Field(default_factory=ResearchBudget)
    engine_mode: Literal["legacy", "shadow", "evidence_v2"] = "evidence_v2"
    research_strategy: Literal["profile_guided", "explore"] = "profile_guided"
    profile_id: str | None = None
    # 增量补查：基于既有 revision 的目标断言/活动
    target_activity_ids: list[str] = Field(default_factory=list)
    target_assertion_ids: list[str] = Field(default_factory=list)
    base_revision: int | None = None
