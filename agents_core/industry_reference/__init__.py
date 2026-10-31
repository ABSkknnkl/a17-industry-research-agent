"""行业参考主数据公共包（D1）。

只读、版本化、可追溯：身份（organization/security）、分类成分、
产业链角色候选与冲突记录分别建模，互不替代。
"""

from __future__ import annotations

from industry_reference.identity import (
    normalize_entity_name,
    resolve_organization,
    resolve_security,
    split_security_token,
)
from industry_reference.models import (
    ClassificationMembership,
    ConflictRecord,
    Organization,
    Provenance,
    ReleaseManifest,
    ResolutionResult,
    RoleMembership,
    Security,
)
from industry_reference.registry import IndustryRegistry

__all__ = [
    "ClassificationMembership",
    "ConflictRecord",
    "IndustryRegistry",
    "Organization",
    "Provenance",
    "ReleaseManifest",
    "ResolutionResult",
    "RoleMembership",
    "Security",
    "normalize_entity_name",
    "resolve_organization",
    "resolve_security",
    "split_security_token",
]
