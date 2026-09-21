#!/usr/bin/env python3
"""Validate structural invariants of a PageCompositionPlan JSON file."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


PAGE_ROLES = {
    "cover", "toc", "list_of_figures", "executive_summary", "chapter_opener", "narrative",
    "chart_page", "comparison_page", "table_page", "appendix", "disclosure", "closing",
}
GRIDS = {
    "cover_editorial", "single_column", "two_column_short", "single_hero", "two_up",
    "hero_plus_two", "two_by_two", "small_multiples", "full_table", "landscape_table",
}
PAGE_SIZES = {"A4_portrait", "A4_landscape", "wide_16_9"}
READING_LEVELS = {"headline", "lead", "support", "detail", "audit"}
SPARSE_ROLES = {"cover", "toc", "list_of_figures", "chapter_opener", "disclosure", "closing"}
PUBLIC_FORBIDDEN_LEVELS = {"audit"}
# 需要标注 chapter_id 的角色：渲染后审计靠它区分“章节正常结束”与“分页失败”
CHAPTER_REQUIRED_ROLES = {
    "executive_summary", "narrative", "chart_page", "comparison_page", "table_page", "appendix",
}
# 离群值降级的允许表达：同轴条形/折线在极值主导时不可读
OUTLIER_DEGRADE_KINDS = {"table", "metric_card", "small_multiples", "log_scale", "split_axis", "annotated_table"}
OUTLIER_RATIO_THRESHOLD = 8.0
RENDER_CONTRACT_KEYS = {"page_selector", "header_selector", "footer_selector", "content_selector"}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sequence(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def validate(payload: Any) -> list[str]:
    issues: list[str] = []
    root = _mapping(payload)
    if not root:
        return ["PLAN_NOT_OBJECT"]
    if root.get("schema_version") != "1.0":
        issues.append("SCHEMA_VERSION_INVALID")
    if root.get("document_profile") not in {
        "brief_note", "research_report", "data_dashboard",
    }:
        issues.append("DOCUMENT_PROFILE_INVALID")
    design_system = _mapping(root.get("design_system"))
    if design_system.get("body_alignment") not in {"left", "start"}:
        issues.append("BODY_ALIGNMENT_NOT_LEFT")
    if not design_system.get("publication_chrome"):
        issues.append("NO_PUBLICATION_CHROME")
    export_layer = root.get("export_layer")
    if export_layer not in {"public", "internal_audit", "combined"}:
        issues.append("EXPORT_LAYER_INVALID")
    if root.get("page_size") not in PAGE_SIZES:
        issues.append("PAGE_SIZE_INVALID")
    # render_contract 声明渲染器必须提供的 DOM 钩子；缺失时测量脚本无法工作，
    # 渲染后审计会退化为肉眼判断。
    contract = _mapping(root.get("render_contract"))
    if contract:
        missing_keys = RENDER_CONTRACT_KEYS - set(contract)
        if missing_keys:
            issues.append(f"RENDER_CONTRACT_INCOMPLETE:{','.join(sorted(missing_keys))}")
    pages = _sequence(root.get("pages"))
    if not pages:
        issues.append("PAGES_EMPTY")
        return issues

    expected_numbers = list(range(1, len(pages) + 1))
    actual_numbers = [_mapping(page).get("page_number") for page in pages]
    if actual_numbers != expected_numbers:
        issues.append("PAGE_NUMBERS_NOT_SEQUENTIAL")

    seen_blocks: set[str] = set()
    referenced_sources: set[str] = set()
    ordinary_grid_run: list[str] = []
    for index, raw_page in enumerate(pages, start=1):
        page = _mapping(raw_page)
        prefix = f"PAGE_{index}"
        role = page.get("page_role")
        if role not in PAGE_ROLES:
            issues.append(f"{prefix}:PAGE_ROLE_INVALID")
        if page.get("grid") not in GRIDS:
            issues.append(f"{prefix}:GRID_INVALID")
        if role in SPARSE_ROLES:
            ordinary_grid_run = []
        else:
            ordinary_grid_run.append(str(page.get("grid")))
            if (
                len(ordinary_grid_run) >= 3
                and len(set(ordinary_grid_run[-3:])) == 1
                and not page.get("repeat_layout_reason")
            ):
                issues.append(f"{prefix}:REPEATED_PAGE_COMPOSITION")
        fill = page.get("estimated_fill")
        if not isinstance(fill, (int, float)) or isinstance(fill, bool) or not 0 <= fill <= 1:
            issues.append(f"{prefix}:ESTIMATED_FILL_INVALID")
        elif fill < 0.65 and role not in SPARSE_ROLES and not page.get(
            "intentional_whitespace", False
        ):
            issues.append(f"{prefix}:UNEXPLAINED_WHITESPACE")

        # 章节归属：渲染后审计靠它区分“章节结束的合法留白”与“分页失败”。
        # 缺这一项时，UNEXPLAINED_WHITESPACE 只能靠角色猜测，会漏判或误判。
        if role in CHAPTER_REQUIRED_ROLES:
            chapter_id = page.get("chapter_id")
            if not isinstance(chapter_id, str) or not chapter_id.strip():
                issues.append(f"{prefix}:CHAPTER_ID_MISSING")

        chapter_starts = 0
        blocks = _sequence(page.get("blocks"))
        if not blocks:
            issues.append(f"{prefix}:BLOCKS_EMPTY")
        for raw_block in blocks:
            block = _mapping(raw_block)
            block_id = block.get("block_id")
            if not isinstance(block_id, str) or not block_id.strip():
                issues.append(f"{prefix}:BLOCK_ID_MISSING")
            elif block_id in seen_blocks:
                issues.append(f"{prefix}:BLOCK_ID_DUPLICATE:{block_id}")
            else:
                seen_blocks.add(block_id)
            span = block.get("span")
            if not isinstance(span, int) or isinstance(span, bool) or not 1 <= span <= 12:
                issues.append(f"{prefix}:BLOCK_SPAN_INVALID:{block_id}")
            if block.get("kind") == "heading" and block.get("size") == "hero":
                chapter_starts += 1
            source_ids = _sequence(block.get("source_ids"))
            referenced_sources.update(
                value for value in source_ids if isinstance(value, str) and value.strip()
            )
            # 阅读层级必须显式声明：渲染后审计靠它区分对外正文与内部审计，
            # 缺失时机器字段与审计精度会漏检。
            level = block.get("reading_level")
            if level not in READING_LEVELS:
                issues.append(f"{prefix}:READING_LEVEL_MISSING:{block_id}")
            if export_layer == "public" and level in PUBLIC_FORBIDDEN_LEVELS:
                issues.append(f"{prefix}:AUDIT_CONTENT_IN_PUBLIC:{block_id}")

            # 去重必须留痕：被合并掉的原始条目 ID 要能追溯，
            # 否则“内容没丢”无法被验证。（extractive_summary 的追溯由 source_ids 承担）
            if block.get("editorial_action") == "deduplicate" and not _sequence(
                block.get("merged_source_ids")
            ):
                issues.append(f"{prefix}:EDITORIAL_ACTION_NO_TRACE:{block_id}")

            table = _mapping(block.get("table"))
            if table:
                if table.get("cjk_label_orientation", "horizontal") != "horizontal":
                    issues.append(f"{prefix}:CJK_VERTICAL_STACK:{block_id}")
                if table.get("continued_from_page") is not None:
                    if not table.get("repeat_header"):
                        issues.append(f"{prefix}:CONTINUED_TABLE_NO_HEADER:{block_id}")
                    if "续" not in str(table.get("caption", "")):
                        issues.append(f"{prefix}:CONTINUED_TABLE_NO_CAPTION:{block_id}")
                header_lines = table.get("header_max_lines", 2)
                if not isinstance(header_lines, int) or isinstance(header_lines, bool) or header_lines > 2:
                    issues.append(f"{prefix}:TABLE_HEADER_TOO_TALL:{block_id}")
                body_rows = table.get("body_row_count")
                minimum_rows = table.get("minimum_body_rows", 4)
                if (
                    table.get("continued_from_page") is not None
                    and isinstance(body_rows, int)
                    and isinstance(minimum_rows, int)
                    and body_rows < minimum_rows
                ):
                    issues.append(f"{prefix}:CONTINUED_TABLE_ORPHAN:{block_id}")

            chart = _mapping(block.get("chart"))
            if chart:
                if chart.get("orientation") == "vertical" and chart.get(
                    "long_cjk_labels", False
                ):
                    issues.append(f"{prefix}:LONG_CJK_LABELS_VERTICAL_CHART:{block_id}")
                caption_lines = chart.get("max_caption_lines", 2)
                if not isinstance(caption_lines, int) or isinstance(caption_lines, bool) or caption_lines > 2:
                    issues.append(f"{prefix}:CAPTION_OVERLOAD:{block_id}")
                visual_task = chart.get("visual_task")
                display_kind = chart.get("display_kind")
                if visual_task == "single_metric" and display_kind not in {None, "metric_card"}:
                    issues.append(f"{prefix}:SINGLE_METRIC_PSEUDO_CHART:{block_id}")
                if visual_task == "trend":
                    point_count = chart.get("point_count")
                    if isinstance(point_count, int) and point_count < 3:
                        issues.append(f"{prefix}:TREND_TOO_FEW_POINTS:{block_id}")
                if (
                    visual_task == "ranking"
                    and chart.get("long_cjk_labels", False)
                    and chart.get("orientation") != "horizontal"
                ):
                    issues.append(f"{prefix}:RANKING_LABEL_LAYOUT_INVALID:{block_id}")
                if (
                    visual_task == "composition"
                    and display_kind in {"pie", "donut"}
                    and isinstance(chart.get("category_count"), int)
                    and chart["category_count"] > 5
                ):
                    issues.append(f"{prefix}:COMPOSITION_TOO_MANY_SLICES:{block_id}")

                # 极值离群：最大绝对值是次大的 8 倍以上时，同轴条形会把其余序列
                # 压成一条线，必须显式降级并记录理由，而不是照常画图。
                ratio = chart.get("max_abs_ratio")
                if isinstance(ratio, (int, float)) and not isinstance(ratio, bool):
                    if (
                        ratio >= OUTLIER_RATIO_THRESHOLD
                        and display_kind not in OUTLIER_DEGRADE_KINDS
                        and not chart.get("degrade_reason")
                    ):
                        issues.append(f"{prefix}:OUTLIER_NOT_DEGRADED:{block_id}")

                # 标签碰撞高发组合：水平发散条形 + 负值 + 长中文标签。
                # 规划期必须声明标签区与绘图区分离，否则渲染后必然重叠。
                if (
                    display_kind == "bar"
                    and chart.get("orientation") == "horizontal"
                    and chart.get("has_negative_values")
                    and chart.get("long_cjk_labels", False)
                    and not chart.get("label_gutter") and not chart.get("label_slot")
                ):
                    issues.append(f"{prefix}:DIVERGING_LABEL_GUTTER_MISSING:{block_id}")

        if chapter_starts > 1 and role != "toc":
            issues.append(f"{prefix}:MULTIPLE_PRIMARY_CHAPTERS")
        if role == "chapter_opener" and len(blocks) < 2:
            issues.append(f"{prefix}:CHAPTER_OPENER_WITHOUT_CONTENT")

    inventory = {
        value for value in _sequence(root.get("content_inventory_ids"))
        if isinstance(value, str) and value.strip()
    }
    dispositions = _mapping(root.get("content_dispositions"))
    accounted_for = referenced_sources | set(dispositions)
    for missing_id in sorted(inventory - accounted_for):
        issues.append(f"CONTENT_UNACCOUNTED:{missing_id}")

    return issues


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_page_plan.py PAGE_COMPOSITION_PLAN.json", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"INVALID_JSON: {exc}", file=sys.stderr)
        return 2
    issues = validate(payload)
    print(json.dumps({"valid": not issues, "issues": issues}, ensure_ascii=False, indent=2))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
