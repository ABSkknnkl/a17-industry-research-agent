"""Shared Agent 3 chart thresholds, palettes, and rendering constants."""

# Recommended chart budgets (soft limits).
RECOMMENDED_CHARTS = (5, 8)
RECOMMENDED_PER_CHAPTER = 2
RECOMMENDED_PER_FAMILY = 2
RECOMMENDED_P1_CHARTS = 3
RECOMMENDED_CHAIN_CHARTS = 1

# Density bands aligned with the recommended report range.
DENSITY_LOW_MAX = 4
DENSITY_MEDIUM_MAX = 8
DENSITY_HIGH_SOFT_MAX = 10

# Technical hard limits.
HARD_LIMIT_MAX_CANDIDATES = 30
HARD_LIMIT_CHARTS_PER_CHAPTER = 10
HARD_LIMIT_MAX_DATA_POINTS = 100_000
HARD_LIMIT_MAX_POINTS_PER_CHART = 20_000

# Layout classification: dense charts take a full row (display_size=full),
# sparse charts are laid out two-per-row (display_size=half).
DISPLAY_SIZE_FULL_MIN_POINTS = 10

# Category-axis label sampling: cap the visible tick labels so thumbnail,
# preview dialog and the offline SVG report share the same label set.
DISPLAY_CATEGORY_MAX_LABELS = 12

# Rendering thresholds and semantic colors.
DATALABEL_MAX_POINTS = 12
CONTRAST_MIN_RATIO = 4.5
UP_COLOR = "#C0392B"
DOWN_COLOR = "#1E8449"
HIGHLIGHT_MUTED_COLOR = "#9CA3AF"
FINANCE_DASHBOARD_COLORS = [
    "#3473EA",
    "#69B2ED",
    "#F3AC28",
    "#7C3AED",
    "#D14B3F",
    "#2CA58D",
    "#5B6CFA",
    "#E07A5F",
]

P1_CHART_TYPES: frozenset[str] = frozenset(
    {
        "combo",
        "area",
    }
)
UNIT_PLACEHOLDERS = frozenset({"未提供", "文本", "不适用", ""})
