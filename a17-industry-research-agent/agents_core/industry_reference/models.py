"""行业主数据公共契约（D1）。

设计原则（V8 最终方案 §8.3）：
- 身份、证券、分类成分、产业链角色是**四类不同记录**，不混用。
- 每条记录携带 provenance（源文件 SHA + JSON Pointer），可逐条追溯。
- 身份已确认 ≠ 角色已确认；rank/weight 只表示成分口径，不生成 leader_score。
- 冲突不自动和解：以 conflict / candidate / pending_review 显式落库。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

IdentityStatus = Literal["accepted", "candidate", "conflict", "pending_review", "rejected", "unknown"]
OrganizationType = Literal["listed_company", "unlisted_company", "brand", "institution", "unknown"]
RoleStatus = Literal["accepted", "candidate", "conflict", "pending_review", "rejected", "unknown"]
Disposition = Literal["accepted", "candidate", "conflict", "pending_review", "rejected"]


class Provenance(BaseModel):
    """来源溯源：每条主数据记录都必须能回到原文件的具体位置。"""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_file: str
    source_sha256: str
    json_pointer: str
    source_declared_as_of: str | None = None
    imported_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class Organization(BaseModel):
    """组织主体。母子公司、品牌与运营主体不自动合并。"""

    model_config = ConfigDict(extra="forbid")

    organization_id: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    identity_status: IdentityStatus = "candidate"
    organization_type: OrganizationType = "listed_company"
    group_hint: str | None = None
    notes: list[str] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)


class Security(BaseModel):
    """证券：保留前导 0 与显式交易所；未知项不猜。"""

    model_config = ConfigDict(extra="forbid")

    security_id: str
    organization_id: str
    market: str = ""          # A股 / 港股 / 美股 / 未知
    exchange: str = ""        # SH / SZ / BJ / HK / US ...
    ticker: str = ""          # 原始代码（保留前导 0 与后缀）
    bare_ticker: str = ""
    valid_from: str | None = None
    valid_to: str | None = None
    identity_status: IdentityStatus = "candidate"
    provenance: list[Provenance] = Field(default_factory=list)


class ClassificationMembership(BaseModel):
    """分类成分：申万等成分口径，不等于产业链角色，也不等于龙头资格。"""

    model_config = ConfigDict(extra="forbid")

    membership_id: str
    classification_system: str
    classification_version: str
    level1_code: str = ""
    level1_name: str = ""
    level2_code: str = ""
    level2_name: str = ""
    security_id: str | None = None
    ticker: str = ""
    company_name: str = ""
    rank: int | None = None
    weight: float | None = None
    source_declared_as_of: str | None = None
    declared_count: int | None = None
    actual_count: int | None = None
    count_mismatch: bool = False
    identity_status: IdentityStatus = "candidate"
    provenance: list[Provenance] = Field(default_factory=list)


class RoleMembership(BaseModel):
    """产业链角色归属：按主题 + 活动 + 角色限定，不提升为已核事实。"""

    model_config = ConfigDict(extra="forbid")

    role_id: str
    organization_id: str
    theme_id: str
    theme_name: str
    category_id: str = ""
    activity_key: str = ""
    role: str = ""                    # leading_brand / leading_upstream / supplier / ...
    source_segment: str = ""
    source_subfield: str = ""
    source_declared_tier: str = ""    # 原文件的"龙头/核心/配套"，不升级为置信度
    scope_market: list[str] = Field(default_factory=list)
    scope_notes: str = ""
    role_status: RoleStatus = "candidate"
    evidence_refs: list[str] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)


class ConflictRecord(BaseModel):
    """冲突/差异记录：不裁定、不自动设别名，等待人工核验。"""

    model_config = ConfigDict(extra="forbid")

    conflict_id: str
    kind: Literal[
        "severe_identity_conflict",   # 同代码不同主体
        "name_difference",            # 名称差异（别名/状态/更名/主体错误）
        "missing_in_classification",  # 核心名单有、申万无
        "missing_market_label",       # BJ 证券 market 为空
        "count_mismatch",             # declared_count != actual
    ]
    ticker: str = ""
    names: list[str] = Field(default_factory=list)
    classification: str = ""     # alias_variant / status_variant / rename_candidate / same_group_different_listing / subject_error
    disposition: Disposition = "pending_review"
    reason: str = ""
    provenance: list[Provenance] = Field(default_factory=list)


class ReleaseManifest(BaseModel):
    """发布清单：版本、输入哈希、条目计数与未发布原因。"""

    model_config = ConfigDict(extra="forbid")

    release_id: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    source_hashes: dict[str, str] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    dispositions: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ResolutionResult(BaseModel):
    """身份解析结果：返回状态与依据，不只返回布尔白名单。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted", "candidate", "conflict", "unknown"]
    organization_id: str | None = None
    canonical_name: str | None = None
    securities: list[str] = Field(default_factory=list)
    reason: str = ""
    candidates: list[dict[str, Any]] = Field(default_factory=list)
