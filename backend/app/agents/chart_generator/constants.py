"""Single source of truth for Agent 3 chart count thresholds (P0-4, 2026-09-13 方案).

收敛范围：推荐区间/预算常量此前在 planner.py 与 service.py 各定义一份
（5 处 + 1 重复漂移源），本轮全部收敛到本模块。
密度档边界供 Agent5 visual.py 对齐引用（低风险下游，可选同批）。
"""

# 推荐值（软规则，超过后生成风险提示但不删除）
RECOMMENDED_CHARTS = (5, 8)  # 推荐每份报告 5-8 张
RECOMMENDED_PER_CHAPTER = 2  # 推荐每章不超过 2 张
RECOMMENDED_PER_FAMILY = 2  # 推荐同一图表族不超过 2 张
RECOMMENDED_P1_CHARTS = 3  # 推荐 P1 图不超过 3 张
RECOMMENDED_CHAIN_CHARTS = 1  # 推荐产业链图 1 张

# 密度档边界（供 Agent5 visual.py 密度分档引用：<=4 low / 5-8 medium /
# 9-10 high- / >10 high，与推荐区间对齐）
DENSITY_LOW_MAX = 4
DENSITY_MEDIUM_MAX = 8
DENSITY_HIGH_SOFT_MAX = 10

# 技术绝对上限（不可绕过）
HARD_LIMIT_MAX_CANDIDATES = 30  # 单份报告最多候选图表
HARD_LIMIT_CHARTS_PER_CHAPTER = 10  # 单章最多技术渲染图表
HARD_LIMIT_MAX_DATA_POINTS = 100_000  # 单份报告最大数据点
HARD_LIMIT_MAX_POINTS_PER_CHART = 20_000  # 单张图表最大数据点

# 数值标签自动开启阈值（P1-3）：点数 <=12 自动 label，>12 不加
DATALABEL_MAX_POINTS = 12

# 主题色对比度阈值（P1-6，WCAG AA）：文本/图形色对白色背景 >= 4.5:1
CONTRAST_MIN_RATIO = 4.5

# 红涨绿跌语义色（P2-3）：A股语义红涨绿跌
UP_COLOR = "#C0392B"
DOWN_COLOR = "#1E8449"

# 高亮法灰化色（P2-6）：非重点序列灰化
HIGHLIGHT_MUTED_COLOR = "#9CA3AF"

# P1 图表类型集合（planner/service 共用，收敛重复定义）
P1_CHART_TYPES: frozenset[str] = frozenset(
    {"combo", "area", "scatter", "bubble", "heatmap", "boxplot", "treemap"}
)

# 单位占位符集合（P0-2）：这些值不进轴名，规范化为图注
UNIT_PLACEHOLDERS = frozenset({"未提供", "文本", "不适用", ""})
