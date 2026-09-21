"""Self-contained, autoescaped HTML report renderer."""

import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from app.agents.report_fusion.composition import ensure_page_composition_plan
from app.agents.report_fusion.html_composition import build_html_composition_plan
from app.reporting import text_rules_loader
from app.reporting.html_quality import ensure_html_quality
from app.reporting.presentation import (
    CHART_TYPE_LABELS,
    CHECK_STATUS_LABELS,
    CONFIDENCE_LABELS,
    COVERAGE_STATUS_LABELS,
    DELIVERY_STATUS_LABELS,
    DIMENSION_LABELS,
    IMPACT_LABELS,
    REPORT_DEPTH_LABELS,
    chapter_label,
    citation_lookup,
    section_label,
    source_table_rows,
)
from app.reporting.scenario import build_scenario_cards
from app.reporting.svg import INK, ChartPalette, metric_card_fact
from app.schemas.report import ReportViewModel

logger = logging.getLogger(__name__)

_TEMPLATE_ROOT = Path(__file__).with_name("templates")

# The template ends in .html.j2, so extension-based selection would
# incorrectly disable escaping. Report text is always untrusted.
_ENVIRONMENT = Environment(
    loader=FileSystemLoader(_TEMPLATE_ROOT),
    autoescape=True,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    cache_size=50,
)

_PLACEMENT_PATTERN = re.compile(r"^SEC-(\d{2})-\d{2}$")

# 生产版式固定为外部 report.html.j2（2026-09-21 迁移）。旧模板
# report-industry.html.j2 仅作为人工回滚材料保留，渲染层不再引用。
_TEMPLATE_NAME = "report.html.j2"
_STYLE_NAME = "report-style.css.j2"

# 封面「关键数据」带最多展示几条。四条是版心宽度下的上限：
# 每条 `值 + 口径` 约 40mm，四条 + 间距刚好铺满 180mm 版心。
COVER_FACT_LIMIT = 4

# ---------------------------------------------------------------------------
# 对外文本净化：内部流程语言 → 研报表述
#
# 词表只有一份，在 skills/report-page-composer/scripts/text_rules.py，
# 经 app.reporting.text_rules_loader 加载。本文件**不再持有自己的规则表**。
#
# 2026-09-18 收敛：这里原先有 23 条独立正则（_PUBLIC_TEXT_RULES），
# 与 skill 的词表措辞不同、且缺少状态码与数值精度处理，导致：
#   * 同一段文字在 HTML 与 Markdown 里被净化成不同结果；
#   * 交付 PDF 残留 "competition · partial" 等内部状态码与 81 处 3 位以上小数；
#   * genre 审计只查 MACHINE_FIELD_MAP + PIPELINE_PHRASE_RES，查不到上述残留。
# ---------------------------------------------------------------------------
def sanitize_public_text(value: str) -> str:
    """模板过滤器 `display_text` 的实现，委托给渲染层唯一入口。

    保留本函数名是为了不改动 `report.html.j2` 里 40 处 `| display_text` 调用。
    实现见 `text_rules_loader.sanitize_for_render`：机器 ID 人性化 + 唯一词表。

    若词表加载失败，第二步退化为 no-op 并上报 `report_skill_text_rules_missing`
    —— 不阻断生成，但该次交付会在 genre 审计的 INTERNAL_PROCESS_LANGUAGE 上暴露。
    """

    return text_rules_loader.sanitize_for_render(value)


# ---------------------------------------------------------------------------
# SVG 文本 → HTML 标签层
# Chromium 打印会把 SVG <text> 转成 Type3 轮廓字体（文字转曲线，被 PDF/A
# 与印前流程拒绝）。把 <text> 摘出为按百分比定位的 HTML span 后：
#   - PDF 端 Type3 归零（HTML 文本正常嵌入为可命名字体子集）；
#   - 坐标按 viewBox 换算为百分比，字号用 cqw（容器宽度 1%）跟随缩放，
#     半宽/全宽两种栅格下标签与图形始终对齐。
# ---------------------------------------------------------------------------
_SVG_TEXT_RE = re.compile(r"<text\s+([^>]*)>(.*?)</text>", re.S)
_SVG_VIEWBOX_RE = re.compile(r'viewBox="0\s+0\s+([\d.]+)\s+([\d.]+)"')
_SVG_ATTR_RES = {
    "x": re.compile(r'\bx="([-\d.]+)"'),
    "y": re.compile(r'\by="([-\d.]+)"'),
    "anchor": re.compile(r'text-anchor="(\w+)"'),
    "size": re.compile(r'font-size="([\d.]+)"'),
    "weight": re.compile(r'font-weight="(\d+)"'),
    "fill": re.compile(r'fill="(#[0-9A-Fa-f]{3,8})"'),
}
# 历史品牌蓝一族：存档的 report_view.json 里 <text fill> 仍是这些值。
# 收敛后 svg.py 直接输出品牌色，但旧产物必须继续被正确归一到**当前** profile 的
# 品牌色，否则换 profile 重渲旧报告会出现蓝字压墨绿装饰。
_LEGACY_BRAND_FILLS = ("#0b4fa3", "#0b78b8", "#0da9d6")

# 未登记的文字色兜底：保持中性灰（体裁硬约束只允许黑/中性灰/品牌色），
# 但**必须留痕** —— 静默改色正是行业链节点白字被改成灰字的成因。
_SVG_FILL_FALLBACK_WARNED: set[str] = set()


def _svg_fill_normalize(palette: ChartPalette) -> dict[str, str]:
    """SVG 文字色 → 家族色板：正文纯黑、次级中性灰、强调仅品牌色。

    键必须覆盖 `svg.INK` 与 `ChartPalette` 的全部取值，外加历史品牌蓝。
    漏登记就会落到兜底并被记进日志。
    """

    mapping = {
        INK.ink.lower(): "#000000",
        INK.label.lower(): "#000000",
        "#2c3b50": "#000000",  # 历史取值
        INK.muted.lower(): palette.neutral_grey,
        # 品牌色块上的白字必须保持白色，不能被归一成中性灰
        INK.on_brand.lower(): INK.on_brand,
        palette.brand.lower(): palette.brand,
    }
    for legacy in _LEGACY_BRAND_FILLS:
        mapping[legacy] = palette.brand
    return mapping


_SVG_TINT_FILL_RE = re.compile(r'fill="#(?:f3f6f9|eaf3fb|f2f6fa|f7f5f0)"', re.I)
_ANCHOR_TRANSFORM = {"middle": "-50%", "start": "0%", "end": "-100%"}


def _namespace_svg_ids(svg: str, chart_id: str) -> str:
    """Make every embedded SVG fragment id unique to one report chart.

    Stored fixtures and imported chart artifacts can legitimately duplicate an
    SVG payload while assigning it a new chart id.  Namespacing at embed time
    prevents duplicate title/marker ids and keeps aria/url fragment references
    attached to the correct chart instance.
    """

    raw_ids = list(dict.fromkeys(re.findall(r'\bid="([^"]+)"', svg)))
    if not raw_ids:
        return svg
    namespace = hashlib.sha256(chart_id.encode("utf-8")).hexdigest()[:10]
    replacements = {
        old: f"图元-{namespace}-{index}" for index, old in enumerate(raw_ids, start=1)
    }
    for old, new in replacements.items():
        svg = svg.replace(f'id="{old}"', f'id="{new}"')
        svg = svg.replace(f'url(#{old})', f'url(#{new})')
        svg = svg.replace(f'href="#{old}"', f'href="#{new}"')
        svg = svg.replace(f'xlink:href="#{old}"', f'xlink:href="#{new}"')
    labelled_by = re.search(r'aria-labelledby="([^"]+)"', svg)
    if labelled_by is not None:
        updated = " ".join(replacements.get(token, token) for token in labelled_by.group(1).split())
        svg = svg[: labelled_by.start(1)] + updated + svg[labelled_by.end(1) :]
    return svg


def chart_svg_to_overlay(svg: str, *, palette: ChartPalette | None = None) -> str:
    """把图表 SVG 内的 <text> 改写为 HTML 标签层（Type3 清零 + 双格式一致）。

    `palette` 缺省时用经典研报品牌色，保证单独调用（测试、脚本）也不会
    出现"图表蓝而正文墨绿"的错配。
    """

    palette = palette or ChartPalette.default()

    if "<text" not in svg:
        return svg
    viewbox = _SVG_VIEWBOX_RE.search(svg)
    if viewbox is None:
        return svg
    vb_width, vb_height = float(viewbox.group(1)), float(viewbox.group(2))
    if vb_width <= 0 or vb_height <= 0:
        return svg

    labels: list[str] = []

    def _extract(match: re.Match[str]) -> str:
        attrs, content = match.group(1), match.group(2)
        content = content.strip()
        if not content:
            return ""
        x_match = _SVG_ATTR_RES["x"].search(attrs)
        y_match = _SVG_ATTR_RES["y"].search(attrs)
        if x_match is None or y_match is None:
            return ""
        x_pct = float(x_match.group(1)) / vb_width * 100.0
        y_pct = float(y_match.group(1)) / vb_height * 100.0
        size_match = _SVG_ATTR_RES["size"].search(attrs)
        font_size = float(size_match.group(1)) if size_match else 13.0
        size_cqw = font_size / vb_width * 100.0
        anchor_match = _SVG_ATTR_RES["anchor"].search(attrs)
        tx = _ANCHOR_TRANSFORM.get(anchor_match.group(1) if anchor_match else "middle", "-50%")
        fill_match = _SVG_ATTR_RES["fill"].search(attrs)
        raw_fill = fill_match.group(1).lower() if fill_match else ""
        fill = _svg_fill_normalize(palette).get(raw_fill)
        if fill is None:
            fill = palette.neutral_grey
            if raw_fill not in _SVG_FILL_FALLBACK_WARNED:
                _SVG_FILL_FALLBACK_WARNED.add(raw_fill)
                logger.warning(
                    "chart SVG text fill %r 未登记在色板里，已按中性灰 %s 输出；"
                    "请把它加进 svg.INK 或 ChartPalette",
                    raw_fill or "(missing)",
                    palette.neutral_grey,
                )
        weight_match = _SVG_ATTR_RES["weight"].search(attrs)
        bold = "font-weight:700;" if weight_match and int(weight_match.group(1)) >= 600 else ""
        labels.append(
            f'<span class="svg-label" style="left:{x_pct:.2f}%;top:{y_pct:.2f}%;'
            f"font-size:{size_cqw:.3f}cqw;color:{fill};"
            f'transform:translate({tx},-78%);{bold}">{content}</span>'
        )
        return ""

    shapes_only = _SVG_TEXT_RE.sub(_extract, svg)
    # 浅色调底（Type3 之外的另一个审计雷区：CHART_WRAPPED_IN_CARD）改为纯白
    shapes_only = _SVG_TINT_FILL_RE.sub('fill="#ffffff"', shapes_only)
    return (
        '<div class="chart-svg-wrap">'
        f"{shapes_only}{''.join(labels)}"
        "</div>"
    )


def _placement_chapter(placement_section_id: str) -> int | None:
    """Return the chapter number of a placement, or None when malformed."""

    match = _PLACEMENT_PATTERN.fullmatch(placement_section_id)
    return int(match.group(1)) if match else None


def _safe_locator_text(value: str) -> str:
    """Keep a precise locator visible without reproducing signed query strings."""

    candidate = value.strip()
    if candidate.lower().startswith("fixture://"):
        return "流程测试定位"
    parts = urlsplit(candidate)
    if parts.scheme.lower() in {"http", "https"} and parts.netloc:
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return candidate


def _html_source_rows(report: ReportViewModel) -> list[dict[str, object]]:
    """Build the exhaustive HTML evidence index, including every usage location."""

    usage_by_evidence: dict[str, list[str]] = {}

    def add_usage(evidence_ids: list[str], label: str) -> None:
        for evidence_id in evidence_ids:
            labels = usage_by_evidence.setdefault(evidence_id, [])
            if label not in labels:
                labels.append(label)

    for conclusion in report.executive_summary.conclusions:
        add_usage(conclusion.evidence_ids, "执行摘要 · 核心结论")
    for chapter_index, chapter in enumerate(report.chapters, start=1):
        for section_index, section in enumerate(chapter.sections, start=1):
            label = f"第{chapter_index}章 · 第{section_index}节 {section.title}"
            for paragraph in section.paragraphs:
                add_usage(paragraph.evidence_ids, label)
    for chart in report.charts:
        add_usage(chart.evidence_ids, f"图表 · {chart.title}")

    compact_rows = {
        int(row["citation_number"]): row for row in source_table_rows(report.evidence_catalog)
    }
    rows: list[dict[str, object]] = []
    for entry in report.evidence_catalog:
        usage: list[str] = []
        for evidence_id in entry.evidence_ids:
            for label in usage_by_evidence.get(evidence_id, []):
                if label not in usage:
                    usage.append(label)
        compact = compact_rows.get(entry.citation_number, {})
        rows.append(
            {
                "citation_number": entry.citation_number,
                "material": entry.material_title,
                "publisher": "、".join(entry.publishers) or "未提供",
                "metrics": "、".join(entry.metric_names),
                "scope": "、".join(entry.scopes) or "未提供",
                "available_date": "、".join(entry.available_dates) or "未提供",
                "reporting_period": "、".join(entry.reporting_periods) or "未提供",
                "locator": "；".join(_safe_locator_text(value) for value in entry.locators)
                or "未提供",
                "locator_href": compact.get("locator_href", ""),
                "method_level": " / ".join(
                    value
                    for value in (
                        "、".join(entry.retrieval_methods),
                        "、".join(entry.source_levels),
                        "、".join(entry.audit_labels),
                    )
                    if value
                )
                or "未提供",
                "usage": usage or ["证据台账（本次正文未直接引用）"],
            }
        )
    return rows


def render_html(
    report: ReportViewModel,
    *,
    continuous_numbering: bool = True,
    repair_classes: tuple[str, ...] = (),
) -> str:
    template = _ENVIRONMENT.get_template(_TEMPLATE_NAME)
    citation_map = citation_lookup(report.evidence_catalog)
    editorial_decisions = {
        item.chapter_id: item
        for item in (report.editorial_plan.chapter_decisions if report.editorial_plan else [])
    }
    page_plan = ensure_page_composition_plan(report)
    condensed_chapter_ids = set(page_plan.condensed_chapter_ids)
    html_composition_plan = build_html_composition_plan(
        report,
        condensed_chapter_ids=condensed_chapter_ids,
    )
    html_section_layouts = {
        item.section_id: item for item in html_composition_plan.section_decisions
    }
    has_section_editorial_plan = bool(
        report.editorial_plan and report.editorial_plan.section_decisions
    )
    page_decisions = {
        item.chapter_id: item for item in page_plan.chapter_decisions
    }
    chart_slots = {
        chart_id: slot
        for decision in page_plan.chapter_decisions
        for chart_id, slot in decision.chart_slots.items()
    }
    featured_chart_ids = {
        chart_id for item in editorial_decisions.values() for chart_id in item.featured_chart_ids
    }
    section_featured_chart_ids = {
        item.section_id: item.featured_chart_ids
        for item in (report.editorial_plan.section_decisions if report.editorial_plan else [])
    }
    featured_chart_ids.update(
        chart_id for chart_ids in section_featured_chart_ids.values() for chart_id in chart_ids
    )
    featured_paragraph_ids = {
        paragraph_id
        for item in editorial_decisions.values()
        for paragraph_id in item.featured_paragraph_ids
    }

    def evidence_entries(evidence_ids: list[str]) -> list[object]:
        entries: list[object] = []
        seen: set[int] = set()
        for evidence_id in evidence_ids:
            entry = citation_map.get(evidence_id)
            if entry is not None and entry.citation_number not in seen:
                seen.add(entry.citation_number)
                entries.append(entry)
        return entries

    # 图表与正文装饰共用同一个品牌色：palette 由当前 profile 派生。
    # 旧存档的 template_profile 为 None，from_profile 会回退经典研报色。
    chart_palette = ChartPalette.from_profile(
        report.visual_decision.template_profile
    )
    charts_by_section: dict[str, list[dict[str, object]]] = {}
    charts_by_chapter: dict[int, list[dict[str, object]]] = {}
    unplaced: list[dict[str, object]] = []
    for chart in report.charts:
        item = chart.model_dump(exclude={"svg"})
        item["svg"] = Markup(
            chart_svg_to_overlay(
                _namespace_svg_ids(chart.svg, chart.chart_id),
                palette=chart_palette,
            )
        )
        section_id = chart.placement_section_id
        chapter_number = _placement_chapter(section_id) if section_id else None
        if chapter_number is not None:
            # ``chapter_number`` can only be resolved from a non-empty section id.
            assert section_id is not None
            charts_by_section.setdefault(section_id, []).append(item)
            charts_by_chapter.setdefault(chapter_number, []).append(item)
        else:
            # placement 为空或格式非法（防御：schema pattern 已拦截）都归入附录，
            # 单个坏字段不允许让图表凭空消失或炸掉整份 HTML 导出。
            label = "附录指标" if chart.display_kind == "metric_card" else "附图"
            item["display_number"] = f"{label}-{len(unplaced) + 1}"
            unplaced.append(item)

    for section_id, items in charts_by_section.items():
        preferred = {
            chart_id: index
            for index, chart_id in enumerate(section_featured_chart_ids.get(section_id, []))
        }
        items.sort(key=lambda item: preferred.get(str(item["chart_id"]), len(preferred)))

    # 有落点的图表**不在这里编号**。
    #
    # 编号必须等于正文里的实际出现顺序，而"实际出现顺序"由模板决定（章首 hero
    # 图组 → 各小节内联图组 → table_led 章尾图组）。在 Python 侧按落点预发编号，
    # 一旦落点被摊开（``spread_chart_placements``）就会与模板的遍历顺序错位 ——
    # 2026-09-18 实测交付 HTML 里 CH-01 渲染成 `指标1-7, 图1-1 … 图1-6`、
    # CH-03 渲染成 `图3-3, 指标3-1, 指标3-2, 指标3-4`，编号在正文里来回跳。
    # 现在由模板的 ``figure_counter`` 在输出图的那一刻发号，单一来源、不可能漂移。

    # 封面「关键数据」带：从单指标事实卡回读**自述性**数值（带 亿/万 量级）。
    #
    # 2026-09-18：封面此前是纯文字信息堆（实测两栏网格占 0.68 页），交付反馈
    # 「第一页字数太多」「很不好看」。放大数字是最有效的封面锚点，但放大后的
    # 数字一旦缺口径就会变成误读源 —— 所以只收 `_format_value()` 折过量级的
    # 读数（`10,602.62亿`），纯比率（`11.35`）不上封面。
    cover_facts: list[dict[str, str]] = []
    seen_facts: set[tuple[str, str]] = set()
    for chart in report.charts:
        if len(cover_facts) >= COVER_FACT_LIMIT:
            break
        fact = metric_card_fact(chart.svg)
        if fact is None:
            continue
        key = (fact["name"], fact["value"])
        if key in seen_facts:
            continue
        seen_facts.add(key)
        cover_facts.append(
            {
                "value": sanitize_public_text(fact["value"]),
                "name": sanitize_public_text(fact["name"]),
                "entity": sanitize_public_text(fact["entity"]),
            }
        )

    scenario_cards = build_scenario_cards(
        list(report.executive_summary.scenarios), sanitize=sanitize_public_text
    )

    rendered = template.render(
        report=report,
        cover_facts=cover_facts,
        scenario_cards=scenario_cards,
        charts_by_section=charts_by_section,
        charts_by_chapter=charts_by_chapter,
        unplaced_charts=unplaced,
        evidence_entries=evidence_entries,
        source_rows=_html_source_rows(report),
        chapter_label=chapter_label,
        section_label=section_label,
        display_text=sanitize_public_text,
        confidence_labels=CONFIDENCE_LABELS,
        report_depth_labels=REPORT_DEPTH_LABELS,
        delivery_status_labels=DELIVERY_STATUS_LABELS,
        dimension_labels=DIMENSION_LABELS,
        coverage_status_labels=COVERAGE_STATUS_LABELS,
        impact_labels=IMPACT_LABELS,
        check_status_labels=CHECK_STATUS_LABELS,
        chart_type_labels=CHART_TYPE_LABELS,
        visual_style_labels={
            "data_manual": "数据手册型",
            "analysis_note": "分析笔记型",
            "deep_research": "深度研究型",
        },
        template_profile_labels={
            "classic_research": "经典研报型",
            "modern_analysis": "现代分析型",
            "data_intensive": "数据密集型",
            "narrative_flow": "叙事流畅型",
        },
        editorial_decisions=editorial_decisions,
        featured_chart_ids=featured_chart_ids,
        featured_paragraph_ids=featured_paragraph_ids,
        page_plan=page_plan,
        page_decisions=page_decisions,
        condensed_chapter_ids=condensed_chapter_ids,
        chart_slots=chart_slots,
        html_composition_plan=html_composition_plan.as_dict(),
        html_section_layouts=html_section_layouts,
        has_section_editorial_plan=has_section_editorial_plan,
        repair_classes=repair_classes,
    )
    ensure_html_quality(report, rendered)
    return rendered
