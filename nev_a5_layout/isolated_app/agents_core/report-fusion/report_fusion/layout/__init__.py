"""A5 结构化排版层（独立工作区实现，尚未接线到生产 A5）。

模块边界：
- blocks     : LayoutDocument / Block 最小形状与硬校验
- projection : ReportViewModel 或冻结母本 → 布局 AST 的一次投影 + 内容保真 diff
- registry   : 图/表注册表、provenance 与 coverage 判定
"""
from .blocks import Asset, Block, LayoutDocument, LayoutValidationError, make_block_id
from .projection import ContentDiff, content_diff, project_from_html, project_from_view
from .registry import ChartRegistry, CoverageVerdict, RegistryEntry, build_registry, evaluate_coverage

__all__ = [
    "Asset", "Block", "LayoutDocument", "LayoutValidationError", "make_block_id",
    "ContentDiff", "content_diff", "project_from_html", "project_from_view",
    "ChartRegistry", "CoverageVerdict", "RegistryEntry", "build_registry", "evaluate_coverage",
]
