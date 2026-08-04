"""Versioned, deterministic 7-chapter/21-section report outline."""

from app.schemas.chapter import OutlineChapter, OutlineSection

OUTLINE_VERSION = "2026.1"


def _chapter(number: int, title: str, sections: tuple[tuple[str, str], ...]) -> OutlineChapter:
    return OutlineChapter(
        chapter_id=f"CH-{number:02d}",
        title=title,
        sections=[
            OutlineSection(
                section_id=f"SEC-{number:02d}-{index:02d}",
                title=section_title,
                purpose=purpose,
            )
            for index, (section_title, purpose) in enumerate(sections, start=1)
        ],
    )


REPORT_OUTLINE: tuple[OutlineChapter, ...] = (
    _chapter(
        1,
        "行业定义与研究基础",
        (
            ("行业定义、研究边界与证券范围", "界定行业、市场和证券类型范围。"),
            ("数据口径、研究时点与分析方法", "说明数据可得日、币种和可比性边界。"),
            ("行业发展阶段与当前核心矛盾", "概括已获证据支持的发展阶段与核心矛盾。"),
        ),
    ),
    _chapter(
        2,
        "市场规模与成长性",
        (
            ("市场规模与历史增长趋势", "呈现可追溯的规模与增长证据。"),
            ("需求驱动因素与细分市场变化", "说明需求端驱动因素及其边界。"),
            ("供需关系、产能与行业周期", "分析供需、产能和周期传导关系。"),
        ),
    ),
    _chapter(
        3,
        "产业链与利润分配",
        (
            ("上游资源、原材料与关键供应环节", "说明上游供应与约束。"),
            ("中游核心产品、制造与服务环节", "说明中游价值创造与竞争因素。"),
            ("下游需求、议价关系与利润迁移", "说明下游需求及利润传导方向。"),
        ),
    ),
    _chapter(
        4,
        "竞争格局",
        (
            ("市场结构、集中度与竞争阶段", "概括可验证的竞争结构。"),
            ("主要参与者及其竞争位置", "在可比口径下说明参与者位置。"),
            ("竞争壁垒、差异化因素与潜在进入者", "分析壁垒及其可持续性。"),
        ),
    ),
    _chapter(
        5,
        "财务质量与估值参照",
        (
            ("收入、利润与盈利能力", "呈现盈利指标及其可持续性边界。"),
            ("现金流、资产负债与财务质量", "说明三表勾稽和财务质量校验结果。"),
            ("估值水平、历史区间与跨市场可比性", "在完成口径校验后呈现估值参照。"),
        ),
    ),
    _chapter(
        6,
        "宏观、政策与技术催化",
        (
            ("宏观经济变量与行业传导路径", "说明宏观变量与行业的传导关系。"),
            ("政策、监管与合规环境", "说明政策时点、范围和可能影响。"),
            ("技术趋势、事件催化与监测指标", "说明催化条件和后续验证指标。"),
        ),
    ),
    _chapter(
        7,
        "情景、风险与研究结论",
        (
            ("基准、乐观和悲观三种情景", "呈现共享事实底座下的三种情景。"),
            ("核心风险、反证条件与跟踪指标", "说明风险传导及可证伪条件。"),
            ("核心结论、适用边界与待验证事项", "汇总结论且保留不确定性。"),
        ),
    ),
)
