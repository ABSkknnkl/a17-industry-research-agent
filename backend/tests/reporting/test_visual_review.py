"""确定性视觉复检的单元测试。

被测对象是 `app.reporting.visual_review` 的纯函数层，不启动 Playwright、
不调用任何模型、不触碰网络。几何诊断由字典直接构造，因此每个断言都只依赖
"诊断 → 问题清单" 这一段确定性映射。

覆盖：各类检出码、干净输入的零判定、闸门与修复类映射、多轮/多批次的合并语义，
以及本机缺少 Poppler 时的显式降级信号（历史上这里静默失效过两次）。
"""

from __future__ import annotations

import pytest

from app.agents.report_fusion.assembler import build_report_view
from app.reporting.visual_review import (
    add_unreviewed_pages_issue,
    add_unreviewed_vision_pages_issue,
    combine_visual_review_batches,
    deterministic_visual_review,
    has_blocking_visual_issues,
    merge_visual_reviews,
    pdf_page_count,
    repair_classes_for,
    summarize_visual_review,
    visual_gate_passes,
)
from app.schemas.report import ReportViewModel, VisualIssue, VisualReviewReport

# 六种版式正好是 LayoutPattern 的全集；`layout_pattern_count` 的 schema 上限也是 6，
# 所以这里用满 6 种：既避开 LAYOUT_VARIETY_LOW，也不会顶破 schema。
_VARIED_PATTERNS = ["hero_metric", "chart_led", "comparison", "narrative", "table_led", "risk_matrix", "comparison"]
_VARIED_STRUCTURES = ["a>b", "c>d", "e>f", "g>h", "i>j", "k>l", "m>n"]

# 一份"完全没有问题"的诊断：所有检测项都给空集合，打印色保留声明为 exact。
_CLEAN: dict = {
    "viewportWidth": 1440,
    "documentWidth": 1440,
    "documentHeight": 3000,
    "overflowX": False,
    "clipped": [],
    "overlaps": [],
    "smallText": [],
    "unsafeSvgText": [],
    "lowContrast": [],
    "unsafeFigures": [],
    "unsafeHeadings": [],
    "emptyLayoutSlots": [],
    "cjkVerticalStacks": [],
    "captionOverload": [],
    "amplifiedEmptyStates": [],
    "unsafeTableRows": [],
    "nonRepeatingTableHeaders": [],
    "printColorAdjust": "exact",
    "chartDisplays": [],
    "layoutPatterns": list(_VARIED_PATTERNS),
    "layoutStructures": list(_VARIED_STRUCTURES),
}


def _diagnostics(**overrides: object) -> dict:
    """在干净诊断上叠加单个检测项，保证只有被测项触发问题。"""

    payload = dict(_CLEAN)
    payload.update(overrides)
    return payload


@pytest.fixture
def report_view(
    report_analysis,
    report_charts,
    report_chapters,
) -> ReportViewModel:
    return build_report_view(
        run_id="run-visual-review",
        revision=1,
        analysis=report_analysis,
        chart_result=report_charts,
        chapter_result=report_chapters,
        tone="professional",
    )


def _review(
    report: ReportViewModel,
    diagnostics: dict,
    *,
    pdf_bytes: bytes = b"",
    review_round: int = 1,
) -> VisualReviewReport:
    """空 pdf_bytes 让页面级（Poppler）检查整体跳过，便于隔离 DOM 几何检测。"""

    return deterministic_visual_review(
        report,
        diagnostics,
        pdf_bytes=pdf_bytes,
        review_round=review_round,
    )


def _codes(report: VisualReviewReport) -> set[str]:
    return {item.issue_code for item in report.issues}


def _issue(
    code: str,
    severity: str = "major",
    *,
    page: int | None = None,
    source: str = "deterministic",
    resolved: bool = False,
) -> VisualIssue:
    return VisualIssue(
        issue_code=code,
        severity=severity,  # type: ignore[arg-type]
        source=source,  # type: ignore[arg-type]
        page=page,
        description=f"{code} 测试描述",
        fix_action=f"{code} 测试修复动作",
        resolved=resolved,
    )


def _report_of(*issues: VisualIssue, review_round: int = 1) -> VisualReviewReport:
    return VisualReviewReport(
        passed=not any(item.severity in {"critical", "major"} and not item.resolved for item in issues),
        score=1.0,
        review_round=review_round,
        issues=list(issues),
    )


# --------------------------------------------------------------------------- #
# 干净输入
# --------------------------------------------------------------------------- #


def test_clean_diagnostics_yield_no_issues(report_view: ReportViewModel) -> None:
    report = _review(report_view, _CLEAN)

    assert report.issues == []
    assert report.passed is True
    assert report.score == 1.0
    assert report.degraded is False
    assert report.reviewer_model is None


def test_clean_diagnostics_report_layout_pattern_count(report_view: ReportViewModel) -> None:
    report = _review(report_view, _CLEAN)

    # 六种版式齐全 → 版式种类计数等于去重后的数量。
    assert report.layout_pattern_count == len(set(_VARIED_PATTERNS))


def test_review_round_is_carried_through(report_view: ReportViewModel) -> None:
    assert _review(report_view, _CLEAN, review_round=2).review_round == 2


# --------------------------------------------------------------------------- #
# DOM 几何检出码：一项诊断 → 一个确定的问题码
# --------------------------------------------------------------------------- #

_DOM_CASES = [
    ("overflowX", True, "OUT_OF_BOUNDS", "critical"),
    ("clipped", [{"text": "被裁切的表格"}], "CLIPPED_CONTENT", "critical"),
    ("overlaps", [[0, 1]], "ELEMENT_OVERLAP", "critical"),
    ("smallText", [{"text": "图注"}], "TEXT_TOO_SMALL", "critical"),
    ("unsafeSvgText", [{"text": "标签", "chart": "CHART-01"}], "CHART_LABEL_OUT_OF_BOUNDS", "critical"),
    ("lowContrast", [{"text": "说明文字"}], "LOW_CONTRAST", "major"),
    ("unsafeFigures", ["chart"], "CHART_CAPTION_SPLIT", "critical"),
    ("unsafeHeadings", ["h2"], "HEADING_ORPHAN", "major"),
    ("emptyLayoutSlots", [{"component": "conclusion-grid"}], "EMPTY_LAYOUT_SLOT", "major"),
    ("cjkVerticalStacks", [{"text": "中文标题"}], "CJK_VERTICAL_STACK", "major"),
    ("captionOverload", [{"tag": "figcaption"}], "CAPTION_OVERLOAD", "major"),
    ("amplifiedEmptyStates", [{"text": "暂无数据"}], "EMPTY_STATE_AMPLIFIED", "major"),
    ("unsafeTableRows", ["row-1"], "TABLE_ROW_SPLIT_RISK", "critical"),
    ("nonRepeatingTableHeaders", ["table"], "TABLE_HEADER_NOT_REPEATABLE", "critical"),
    ("printColorAdjust", "economy", "PRINT_COLOR_ADJUST_MISSING", "critical"),
    (
        "chartDisplays",
        [{"chartId": "CHART-01", "displayKind": "metric_card", "hasMetricSvg": False}],
        "SINGLE_POINT_CHART_ENCODING",
        "critical",
    ),
]


@pytest.mark.parametrize(
    ("key", "value", "expected_code", "expected_severity"),
    _DOM_CASES,
    ids=[case[2] for case in _DOM_CASES],
)
def test_dom_diagnostic_maps_to_expected_issue(
    report_view: ReportViewModel,
    key: str,
    value: object,
    expected_code: str,
    expected_severity: str,
) -> None:
    report = _review(report_view, _diagnostics(**{key: value}))

    matched = [item for item in report.issues if item.issue_code == expected_code]
    assert matched, f"{key} 未产生 {expected_code}，实际={_codes(report)}"
    assert matched[0].severity == expected_severity
    assert matched[0].source == "deterministic"
    assert matched[0].confidence == 1.0
    assert matched[0].resolved is False


def test_metric_card_with_svg_is_not_flagged(report_view: ReportViewModel) -> None:
    # KPI 卡确实渲染成 SVG 时不应误报"单点指标未按指标卡渲染"。
    report = _review(
        report_view,
        _diagnostics(
            chartDisplays=[
                {"chartId": "CHART-01", "displayKind": "metric_card", "hasMetricSvg": True}
            ]
        ),
    )

    assert "SINGLE_POINT_CHART_ENCODING" not in _codes(report)


# --------------------------------------------------------------------------- #
# 版式种类与重复版式
# --------------------------------------------------------------------------- #


def test_three_identical_consecutive_patterns_are_repetitive(report_view: ReportViewModel) -> None:
    report = _review(
        report_view,
        _diagnostics(
            layoutPatterns=[
                "hero_metric",
                "hero_metric",
                "hero_metric",
                "chart_led",
                "comparison",
                "narrative",
                "table_led",
            ]
        ),
    )

    assert "REPETITIVE_LAYOUT" in _codes(report)


def test_two_patterns_are_not_enough_for_a_standard_report(report_view: ReportViewModel) -> None:
    report = _review(
        report_view,
        _diagnostics(
            layoutPatterns=[
                "hero_metric",
                "hero_metric",
                "chart_led",
                "chart_led",
                "hero_metric",
                "chart_led",
                "hero_metric",
            ]
        ),
    )

    assert "LAYOUT_VARIETY_LOW" in _codes(report)


def test_two_real_structures_are_not_enough(report_view: ReportViewModel) -> None:
    report = _review(
        report_view,
        _diagnostics(layoutStructures=["a>b", "b>a", "a>b", "b>a", "a>b", "b>a", "a>b"]),
    )

    assert "STRUCTURE_VARIETY_LOW" in _codes(report)


# --------------------------------------------------------------------------- #
# Poppler 缺失：显式降级，而不是静默跳过
# --------------------------------------------------------------------------- #


def test_page_level_checks_report_missing_text_layout(
    report_view: ReportViewModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 带 page 标记的 PDF 字节让 pdf_page_count > 0，但本机没有 pdftotext，
    # 页面级检查（密度 / 空白带 / 分栏 / 孤行 / 页码）会整体跳过。
    monkeypatch.setattr(
        "app.reporting.visual_review.shutil.which",
        lambda _name: None,
    )

    report = _review(report_view, _CLEAN, pdf_bytes=b"1 0 obj << /Type /Page >> endobj")

    assert "PDF_TEXT_LAYOUT_UNAVAILABLE" in _codes(report)
    skipped = next(
        item for item in report.issues if item.issue_code == "PDF_TEXT_LAYOUT_UNAVAILABLE"
    )
    # minor 而非阻塞：缺工具是环境问题，不应该让报告生成不了。
    assert skipped.severity == "minor"
    assert report.passed is True


def test_no_text_layout_signal_without_page_bytes(report_view: ReportViewModel) -> None:
    report = _review(report_view, _CLEAN, pdf_bytes=b"")

    assert "PDF_TEXT_LAYOUT_UNAVAILABLE" not in _codes(report)


def test_pdf_page_count_counts_page_objects() -> None:
    assert pdf_page_count(b"<< /Type /Page >><< /Type /Page >>") == 2
    assert pdf_page_count(b"not a pdf") == 0


# --------------------------------------------------------------------------- #
# 闸门与修复类
# --------------------------------------------------------------------------- #


def test_gate_passes_when_only_minor_findings_remain() -> None:
    report = _report_of(_issue("CAPTION_OVERLOAD", "minor"))

    # 阈值只用于评分口径，交付闸门只看是否有未解决的 critical/major。
    assert visual_gate_passes(report, threshold=0.99) is True
    assert visual_gate_passes(report, threshold=0.0) is True
    assert has_blocking_visual_issues(report) is False


def test_gate_fails_on_unresolved_major_and_recovers_when_resolved() -> None:
    unresolved = _report_of(_issue("HEADING_ORPHAN", "major"))
    resolved = _report_of(_issue("HEADING_ORPHAN", "major", resolved=True))

    assert visual_gate_passes(unresolved, threshold=0.95) is False
    assert has_blocking_visual_issues(unresolved) is True
    assert visual_gate_passes(resolved, threshold=0.95) is True
    assert has_blocking_visual_issues(resolved) is False


def test_gate_fails_on_unresolved_critical() -> None:
    report = _report_of(_issue("OUT_OF_BOUNDS", "critical"))

    assert visual_gate_passes(report, threshold=0.0) is False


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("OUT_OF_BOUNDS", ("visual-repair-safe",)),
        ("CLIPPED_CONTENT", ("visual-repair-safe",)),
        ("ELEMENT_OVERLAP", ("visual-repair-safe",)),
        ("COLUMN_IMBALANCE", ("visual-repair-safe",)),
        ("CHART_LABEL_OUT_OF_BOUNDS", ("visual-repair-safe",)),
        ("CJK_VERTICAL_STACK", ("visual-repair-safe",)),
        ("LOW_CONTENT_DENSITY", ("visual-repair-compact",)),
        ("INTERNAL_WHITESPACE_GAP", ("visual-repair-compact",)),
        ("REPETITIVE_LAYOUT", ("visual-repair-compact",)),
        ("EMPTY_LAYOUT_SLOT", ("visual-repair-compact",)),
        ("EMPTY_STATE_AMPLIFIED", ("visual-repair-compact",)),
        ("CAPTION_OVERLOAD", ("visual-repair-compact",)),
        ("SOURCE_UNREADABLE", ("visual-repair-legible",)),
        ("TEXT_TOO_SMALL", ("visual-repair-legible",)),
        ("LOW_CONTRAST", ("visual-repair-legible",)),
        ("HEADING_ORPHAN", ("visual-repair-pagination",)),
        ("CHART_CAPTION_SPLIT", ("visual-repair-pagination",)),
        ("TABLE_ROW_SPLIT_RISK", ("visual-repair-pagination",)),
        ("TABLE_HEADER_NOT_REPEATABLE", ("visual-repair-pagination",)),
        ("PAGE_ROLE_CONFLICT", ("visual-repair-pagination",)),
    ],
)
def test_repair_class_mapping(code: str, expected: tuple[str, ...]) -> None:
    assert repair_classes_for(_report_of(_issue(code))) == expected


def test_repair_classes_are_ordered_and_deduplicated() -> None:
    report = _report_of(
        _issue("HEADING_ORPHAN"),
        _issue("OUT_OF_BOUNDS", "critical"),
        _issue("LOW_CONTRAST"),
        _issue("CAPTION_OVERLOAD"),
        # 同类重复不应产生重复类名。
        _issue("CLIPPED_CONTENT", "critical"),
        _issue("TEXT_TOO_SMALL", "critical"),
    )

    assert repair_classes_for(report) == (
        "visual-repair-safe",
        "visual-repair-compact",
        "visual-repair-legible",
        "visual-repair-pagination",
    )


def test_repair_classes_ignore_resolved_issues() -> None:
    report = _report_of(_issue("OUT_OF_BOUNDS", "critical", resolved=True))

    assert repair_classes_for(report) == ()


def test_repair_classes_empty_for_clean_report(report_view: ReportViewModel) -> None:
    assert repair_classes_for(_review(report_view, _CLEAN)) == ()


# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #


def test_summary_counts_unresolved_by_severity() -> None:
    report = _report_of(
        _issue("OUT_OF_BOUNDS", "critical"),
        _issue("HEADING_ORPHAN", "major"),
        _issue("LOW_CONTRAST", "major", resolved=True),
        _issue("CAPTION_OVERLOAD", "minor"),
    )

    summary = summarize_visual_review(report, review_rounds=2)

    assert summary.critical_count == 1
    assert summary.major_count == 1  # 已解决的不计入
    assert summary.minor_count == 1
    assert summary.review_rounds == 2
    assert summary.passed is False


# --------------------------------------------------------------------------- #
# 多批次 / 多轮次合并
# --------------------------------------------------------------------------- #


def test_merge_without_vision_review_marks_degraded() -> None:
    deterministic = _report_of(_issue("LOW_CONTRAST", "minor"))

    merged = merge_visual_reviews(deterministic, None)

    assert merged.degraded is True
    assert merged.issues == deterministic.issues


def test_merge_keeps_both_sources_and_records_reviewer_model() -> None:
    deterministic = _report_of(_issue("LOW_CONTRAST", "minor"))
    vision = VisualReviewReport(
        passed=False,
        score=0.5,
        review_round=1,
        reviewer_model="vision-judge",
        issues=[_issue("PAGE_RHYTHM_MONOTONOUS", "minor", page=3, source="vision")],
    )

    merged = merge_visual_reviews(deterministic, vision)

    assert merged.reviewer_model == "vision-judge"
    assert {item.issue_code for item in merged.issues} == {
        "LOW_CONTRAST",
        "PAGE_RHYTHM_MONOTONOUS",
    }


def test_merge_lets_dom_geometry_authority_resolve_vision_disagreement() -> None:
    # 浏览器几何检查没有复现"图表语义"类问题时，模型结论降级并标记已解决，
    # 只留在审计轨迹里，不再参与闸门。
    deterministic = _report_of(_issue("LOW_CONTRAST", "minor"))
    vision = VisualReviewReport(
        passed=False,
        score=0.4,
        review_round=1,
        reviewer_model="vision-judge",
        issues=[
            _issue("SINGLE_POINT_CHART_ENCODING", "critical", source="vision"),
            _issue("LOW_CONTENT_DENSITY", "major", source="vision"),
        ],
    )

    merged = merge_visual_reviews(deterministic, vision)
    by_code = {item.issue_code: item for item in merged.issues}

    assert by_code["SINGLE_POINT_CHART_ENCODING"].resolved is True
    assert by_code["SINGLE_POINT_CHART_ENCODING"].severity == "minor"
    assert by_code["LOW_CONTENT_DENSITY"].resolved is True
    # 全部阻塞项被消解后，闸门应当放行。
    assert merged.passed is True


def test_merge_deduplicates_same_code_page_and_source() -> None:
    deterministic = _report_of(_issue("LOW_CONTRAST", "minor", page=2))
    vision = VisualReviewReport(
        passed=True,
        score=1.0,
        review_round=1,
        issues=[_issue("LOW_CONTRAST", "minor", page=2, source="deterministic")],
    )

    merged = merge_visual_reviews(deterministic, vision)

    assert len(merged.issues) == 1


def test_combine_batches_returns_none_for_empty_input() -> None:
    assert combine_visual_review_batches([], total_page_count=10, review_round=2) is None


def test_combine_batches_dedupes_and_keeps_widest_pattern_count() -> None:
    first = VisualReviewReport(
        passed=True,
        score=1.0,
        review_round=1,
        layout_pattern_count=3,
        reviewer_model="vision-a",
        issues=[_issue("LOW_CONTRAST", "minor", page=1, source="vision")],
    )
    second = VisualReviewReport(
        passed=True,
        score=1.0,
        review_round=1,
        layout_pattern_count=5,
        reviewer_model="vision-b",
        issues=[
            _issue("LOW_CONTRAST", "minor", page=1, source="vision"),
            _issue("CAPTION_OVERLOAD", "minor", page=6, source="vision"),
        ],
    )

    combined = combine_visual_review_batches(
        [first, second], total_page_count=12, review_round=2
    )

    assert combined is not None
    assert combined.page_count == 12
    assert combined.review_round == 2
    assert combined.layout_pattern_count == 5
    assert combined.reviewer_model == "vision-a + vision-b"
    assert len(combined.issues) == 2


def test_unreviewed_pages_fail_closed() -> None:
    report = _report_of(_issue("LOW_CONTRAST", "minor"))

    unchanged = add_unreviewed_pages_issue(
        report, expected_page_count=4, rendered_page_count=4
    )
    assert unchanged is report

    clipped = add_unreviewed_pages_issue(
        report, expected_page_count=10, rendered_page_count=4
    )
    assert clipped.passed is False
    assert clipped.degraded is True
    issue = next(item for item in clipped.issues if item.issue_code == "UNREVIEWED_PAGES")
    assert issue.severity == "critical"
    assert issue.page == 5
    assert "expected_pages=10" in issue.evidence


def test_unreviewed_vision_pages_fail_closed_with_ranges() -> None:
    report = _report_of(_issue("LOW_CONTRAST", "minor"))

    unchanged = add_unreviewed_vision_pages_issue(
        report, expected_page_count=3, reviewed_page_numbers={1, 2, 3}
    )
    assert unchanged is report

    partial = add_unreviewed_vision_pages_issue(
        report, expected_page_count=6, reviewed_page_numbers={1, 2, 5}
    )
    issue = next(
        item for item in partial.issues if item.issue_code == "VISION_BATCH_UNREVIEWED"
    )
    assert partial.passed is False
    assert issue.page == 3
    assert "missing_pages=3-4,6" in issue.evidence


# --------------------------------------------------------------------------- #
# 证据裁剪
# --------------------------------------------------------------------------- #


def test_long_evidence_is_clipped_with_a_visible_marker(report_view: ReportViewModel) -> None:
    # 24 图规模的报告会把证据串撑过 schema 上限；静默截断会被读成"样本只有这些"。
    oversized = [{"text": "x" * 400} for _ in range(40)]

    report = _review(report_view, _diagnostics(clipped=oversized))

    issue = next(item for item in report.issues if item.issue_code == "CLIPPED_CONTENT")
    assert len(issue.evidence) <= 1_000
    assert issue.evidence.endswith("…[证据已截断]")
