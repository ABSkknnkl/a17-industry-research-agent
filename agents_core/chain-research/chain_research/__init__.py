"""chain-research：A1 产业链研究共享包（v2）。

职责边界（方案 §2/§4）：
- A1 是产业链信息责任主体，本包承载其研究作业的核心契约与实现；
- 本包**不导入** A2/A3 业务 Agent；A2/A3 通过 ChainKnowledgeBundle 交接；
- 首版技术栈：Pydantic + JSON 快照 + SQLite + 文件缓存（不引图数据库）。
"""

from chain_research.models import (   # noqa: F401
    SCHEMA_VERSION,
    AssertionStatus,
    BundleManifest,
    BudgetCounts,
    ChainAssertion,
    ChainEntity,
    ChainEvidence,
    ChainKnowledgeBundle,
    ChainQualityReport,
    ChainResearchRequest,
    ChainScope,
    ChainStructure,
    CoverageBasis,
    EntityType,
    ExecutionMode,
    IdentityStatus,
    PREDICATE_ENDPOINT_RULES,
    Predicate,
    Qualifiers,
    ReleaseStatus,
    ResearchBudget,
    RunDiagnostics,
    Verification,
    stable_id,
)
from chain_research.store import (   # noqa: F401
    ChainStore,
    chain_v2_dir,
    document_cache_key,
)
from chain_research.providers import (   # noqa: F401
    DoubaoSearchProvider,
    DocumentFetchProvider,
    KbEnrichmentProvider,
    ProviderError,
    ProviderErrorKind,
    RawSearchResult,
    RunContext,
    SourceDocument,
)

__all__ = [
    "SCHEMA_VERSION",
    "AssertionStatus",
    "BundleManifest",
    "BudgetCounts",
    "ChainAssertion",
    "ChainEntity",
    "ChainEvidence",
    "ChainKnowledgeBundle",
    "ChainQualityReport",
    "ChainResearchRequest",
    "ChainScope",
    "ChainStructure",
    "CoverageBasis",
    "EntityType",
    "ExecutionMode",
    "IdentityStatus",
    "PREDICATE_ENDPOINT_RULES",
    "Predicate",
    "Qualifiers",
    "ReleaseStatus",
    "ResearchBudget",
    "RunDiagnostics",
    "Verification",
    "stable_id",
    "ChainStore",
    "chain_v2_dir",
    "document_cache_key",
    "DoubaoSearchProvider",
    "DocumentFetchProvider",
    "KbEnrichmentProvider",
    "ProviderError",
    "ProviderErrorKind",
    "RawSearchResult",
    "RunContext",
    "SourceDocument",
]
