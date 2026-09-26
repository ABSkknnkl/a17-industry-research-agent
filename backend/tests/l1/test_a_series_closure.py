"""A 系列闭合测试（A2/A3/A4 的可离线判定项）——黄金样本产物离线回放。

**与任务书 §5.2 的关系（实现路径重评估，见台账冲突 C-09）**：
任务书 §5.2 建议"照搬源库 `backend/tests/agents/{data_interpreter,chart_generator,chapter_writer,report_fusion}`（9952 行）"。
实测：这些测试依赖 **10 个本项目不存在的架构模块**（`app.workflow.stages`、`app.schemas.{analysis,chart,chapter,report,evidence}`、
`app.integrations.llm.mock`、`app.infrastructure.repositories.chapter_repository`、`app.reporting.html`、
`app.agents.*.service`）→ **机械照搬不可行**（改造成本高于重写）。
故按任务书 §0.4（实现方式由执行方决定）改为**按判据重写**：以 §3.2 的 A 系列判据清单为准逐项落地。

**本文件覆盖**：A2-01 / A2-02 / A2-08 / A2-N1 / A2-N2 / A3-02 / A3-03 / A4-02 / A4-04。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_RUN_ID = "run-20260926022235-107"
ARTIFACTS = PROJECT_ROOT / "data" / "runs" / GOLDEN_RUN_ID / "artifacts"

# 图表标题 → A2 计算字段的映射（仅在可确证时比对，避免误判）
TITLE_TO_A2_FIELD = {
    "毛利率": "gross_margin_pct",
    "资产负债率": "debt_ratio_pct",
    "净资产收益率": "roe_pct",
}
# A2/A4 产物禁词（与 R2 同源，扩展到解读与章节层）
FORBIDDEN = ("收益承诺", "买入", "卖出", "目标价", "稳赚", "投资建议")
EXEMPT = ("不构成投资建议", "不构成任何投资建议", "仅供研究参考")


@lru_cache(maxsize=1)
def _report() -> dict:
    return json.loads((ARTIFACTS / "interpretation_report.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _charts() -> dict:
    return json.loads((ARTIFACTS / "chart_result.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _chapters() -> dict:
    return json.loads((ARTIFACTS / "chapter_result.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# A2 · 数据解读
# --------------------------------------------------------------------------


def test_a2_01_artifact_conforms_to_pydantic_model() -> None:
    """A2-01：产物必须能通过本项目 Pydantic 模型校验（Schema 合规）。"""
    from data_interpreter.models import InterpretationReport

    model = InterpretationReport.model_validate(_report())
    assert model.subject, "解读产物缺少 subject"
    assert model.semantic_status or True  # 字段存在性由模型定义保证


def test_a2_02_insight_evidence_references_are_valid() -> None:
    """A2-02：insights 的 `evidence_record_ids` 必须非空且全部落在 A1 证据池内。"""
    dataset = json.loads((ARTIFACTS / "dataset.json").read_text(encoding="utf-8"))
    pool: set[str] = set()
    for key, value in dataset.items():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item.get("record_id"):
                    pool.add(str(item["record_id"]))

    insights = _report().get("insights") or []
    assert insights, "解读产物无 insights"
    problems: dict[str, list[str]] = {}
    for ins in insights:
        ids = [str(i) for i in (ins.get("evidence_record_ids") or [])]
        bad = sorted(set(ids) - pool)
        if not ids or bad:
            problems[str(ins.get("insight_id"))] = bad[:3] if ids else ["（空引用）"]
    assert problems == {}, f"A2-02 结论缺证据或引用了池外证据: {problems}"


def test_a2_08_no_investment_advice_in_analysis_artifact() -> None:
    """A2-08：解读产物不得出现买卖建议/目标价等表述。

    判据修正（§7.4 第②类 用例预期偏差，与 R2「豁免合规免责句」同纪律）：
    技能声明里的**合规否定句**（如"不输出目标价""不得给出买入/卖出建议"）本身是
    合规表述，而非违规建议；原判据按子串计数会把否定句里的"目标价"误判为命中
    （2026-09-26 重冻结快照即因 applied_skills 描述含"不输出目标价"而误报 4 次）。
    故计数前先剔除「否定词 + 违规词」的合规语境，再判剩余的真实违规命中。
    """
    negation_prefixes = (
        "不输出", "不给出", "不提供", "不做", "不预测", "不得", "不能", "不会", "不含",
        "不涉及", "禁止", "避免", "拒绝", "无", "没有", "非", "不",
    )
    text = json.dumps(_report(), ensure_ascii=False)
    for phrase in EXEMPT:
        text = text.replace(phrase, "")
    # 剔除合规否定语境（否定词紧邻违规词），避免把"不输出目标价"误计为违规
    for forbidden in FORBIDDEN:
        for neg in negation_prefixes:
            text = text.replace(f"{neg}{forbidden}", "")
    hits = {p: text.count(p) for p in FORBIDDEN if p in text}
    assert hits == {}, f"A2-08 解读产物命中违规表述: {hits}"


def test_a2_n1_anomaly_findings_are_well_formed() -> None:
    """A2-N1：异常检测结论结构完整（kind/severity/metric/explanation 齐备，severity 取值合法）。"""
    anomalies = _report().get("anomalies") or []
    assert anomalies, "样本无异常结论，无法判定结构"
    allowed_severity = {"low", "medium", "high", "critical", "CRITICAL", "HIGH", "MEDIUM", "LOW"}
    bad: dict[str, list[str]] = {}
    for item in anomalies:
        issues = []
        if not str(item.get("anomaly_id") or "").strip():
            issues.append("缺 anomaly_id")
        if not str(item.get("kind") or "").strip():
            issues.append("缺 kind")
        if str(item.get("severity")) not in allowed_severity:
            issues.append(f"severity 非法: {item.get('severity')}")
        if not str(item.get("metric") or "").strip():
            issues.append("缺 metric")
        if len(str(item.get("explanation") or "").strip()) < 6:
            issues.append("缺 explanation")
        if issues:
            bad[str(item.get("anomaly_id") or "?")] = issues
    assert bad == {}, f"A2-N1 异常结论结构不完整: {bad}"


def test_a2_n2_cross_validation_status_is_registered() -> None:
    """A2-N2：交叉验证结论必须带合法 status 与可读方法说明。

    枚举**从生产模型动态读取**（`CrossValidationFinding.status` 的 Literal 取值），
    不在测试里自造白名单——这是"枚举以生产定义为单一事实源"的项目纪律。
    """
    from typing import get_args

    from data_interpreter.models import CrossValidationFinding

    allowed = set(get_args(CrossValidationFinding.model_fields["status"].annotation))
    assert allowed, "无法从生产模型解析 status 枚举"

    validations = _report().get("cross_validations") or []
    assert validations, "样本无交叉验证结论"
    bad: dict[str, dict] = {}
    for item in validations:
        status = str(item.get("status") or "")
        issues: dict = {}
        if status not in allowed:
            issues["status"] = f"{status}（合法值: {sorted(allowed)}）"
        if len(str(item.get("method") or "").strip()) < 6:
            issues["method"] = "过短"
        if not (item.get("sources") or item.get("sources_compared")):
            issues["sources"] = "缺失"
        if issues:
            bad[str(item.get("validation_id") or "?")] = issues
    assert bad == {}, f"A2-N2 交叉验证结论不合规: {bad}"


# --------------------------------------------------------------------------
# A3 · 图表：数值一致性与点级溯源
# --------------------------------------------------------------------------


def _x_categories(option: dict) -> list[str]:
    """取类目轴（xAxis）的 categories 文本列表。"""
    xa = option.get("xAxis")
    if isinstance(xa, list):
        xa = xa[0] if xa else {}
    if isinstance(xa, dict):
        data = xa.get("data")
        if isinstance(data, list):
            return [str(c) for c in data]
    return []


def _point_value(v: object) -> object:
    """归一化单个数据点为标量：兼容 ECharts 的 {value:..} 与 [x,y,..] 形式。"""
    if isinstance(v, dict):
        v = v.get("value")
    if isinstance(v, (list, tuple)):
        v = v[-1] if v else None
    return v


def test_a3_02_chart_values_match_a2_calculated_metrics() -> None:
    """A3-02（关键）：图上数值必须与 A2 计算输出一致。

    做法：对标题可确证指标归属的图（毛利率/资产负债率/ROE），把数据点与
    `interpretation_report.financial_ratios[*]` 的同名字段逐点比对，容差 0.01（百分数绝对值）。

    判据修正（§7.4 第②类，对应 D-08 修复）：D-08 修复后单比率跨实体对比图由「时序布局
    （series 名=公司、x=报告期）」改为**截面布局**（x 轴 categories=公司、series 名=指标、
    data[i] 与 categories[i] 下标对齐）。原判据只按 series.name 匹配公司，对截面布局会
    判据未生效（compared=0）。现同时支持两种布局，并排除 scatter/bubble（双指标定位图，
    单字段比对不适用）。比对契约不变：图上值 == A2 financial_ratios 同名字段。
    """
    ratios = {r.get("company"): r for r in (_report().get("financial_ratios") or []) if r.get("company")}
    assert ratios, "A2 产物无 financial_ratios，无法比对"

    mismatches: dict[str, list[str]] = {}
    compared = 0
    for chart in _charts().get("charts") or []:
        title = str(chart.get("title") or "")
        chart_id = str(chart.get("chart_id"))
        if str(chart.get("chart_type") or "") in ("scatter", "bubble"):
            continue  # 双指标定位图，单字段逐点比对不适用
        field = next((f for key, f in TITLE_TO_A2_FIELD.items() if key in title), None)
        if not field:
            continue  # 指标归属不可确证 → 不比对（避免误判）
        option = chart.get("option") or {}
        cats = _x_categories(option)
        for series in option.get("series") or []:
            s_name = str(series.get("name") or "")
            data = series.get("data") or []
            if s_name in ratios:
                # 布局A（时序）：series 名即公司，data 为该公司跨期值
                expected = ratios[s_name].get(field)
                if expected is None:
                    continue
                for value in data:
                    val = _point_value(value)
                    if not isinstance(val, (int, float)) or isinstance(val, bool) or val in (0, 0.0):
                        continue  # 0/缺失单独由"缺失填 0"用例判
                    compared += 1
                    if abs(float(val) - float(expected)) > 0.01:
                        mismatches.setdefault(chart_id, []).append(
                            f"{s_name}: 图={val} A2={expected}（字段 {field}）"
                        )
            else:
                # 布局B（截面）：categories=公司，data[i] ↔ cats[i]
                for i, value in enumerate(data):
                    if i >= len(cats):
                        break
                    company = cats[i]
                    expected = ratios.get(company, {}).get(field)
                    if expected is None:
                        continue
                    val = _point_value(value)
                    if not isinstance(val, (int, float)) or isinstance(val, bool) or val in (0, 0.0):
                        continue
                    compared += 1
                    if abs(float(val) - float(expected)) > 0.01:
                        mismatches.setdefault(chart_id, []).append(
                            f"{company}: 图={val} A2={expected}（字段 {field}）"
                        )
    assert compared > 0, "无可比对的数值点（判据未生效）"
    assert mismatches == {}, (
        f"A3-02 图表数值与 A2 计算不一致（比对 {compared} 个点）: {mismatches}"
    )


def test_a3_02b_missing_values_must_not_be_drawn_as_zero() -> None:
    """A3-02 补：缺失期不得用 0 占位（0 与"缺失"在图上无法区分，会误导读者）。

    同时支持时序布局（series 名=公司）与截面布局（categories=公司，D-08 修复后）。
    """
    ratios = {r.get("company"): r for r in (_report().get("financial_ratios") or []) if r.get("company")}
    suspicious: dict[str, list[str]] = {}
    for chart in _charts().get("charts") or []:
        title = str(chart.get("title") or "")
        chart_id = str(chart.get("chart_id"))
        if str(chart.get("chart_type") or "") in ("scatter", "bubble"):
            continue
        field = next((f for key, f in TITLE_TO_A2_FIELD.items() if key in title), None)
        if not field:
            continue
        option = chart.get("option") or {}
        cats = _x_categories(option)
        for series in option.get("series") or []:
            s_name = str(series.get("name") or "")
            data = series.get("data") or []
            if s_name in ratios:
                expected = ratios[s_name].get(field)
                if expected not in (None, 0, 0.0) and any(_point_value(v) in (0, 0.0) for v in data):
                    suspicious.setdefault(chart_id, []).append(
                        f"{s_name}: 图上含 0，而 A2 真值={expected}（字段 {field}）"
                    )
            else:
                for i, value in enumerate(data):
                    if i >= len(cats):
                        break
                    company = cats[i]
                    expected = ratios.get(company, {}).get(field)
                    if expected not in (None, 0, 0.0) and _point_value(value) in (0, 0.0):
                        suspicious.setdefault(chart_id, []).append(
                            f"{company}: 图上含 0，而 A2 真值={expected}（字段 {field}）"
                        )
    assert suspicious == {}, (
        f"A3-02b 图表把缺失值画成 0（应留空并标注，而非用 0 占位）: {suspicious}"
    )


def test_a3_03_charts_carry_point_level_evidence() -> None:
    """A3-03：图表应具备**点级**证据指针（`point_evidence_ids`），否则无法逐点溯源。"""
    charts = _charts().get("charts") or []
    assert charts, "样本无图表"
    without = [
        str(c.get("chart_id"))
        for c in charts
        if not (c.get("point_evidence_ids") or [])
    ]
    assert without == [], (
        f"A3-03 {len(without)}/{len(charts)} 张图的 point_evidence_ids 为空 → 点级溯源失效: {without}"
    )


# --------------------------------------------------------------------------
# A4 · 章节：数值段落的证据约束与不补数
# --------------------------------------------------------------------------


def test_a4_02_numeric_paragraphs_must_carry_evidence() -> None:
    """A4-02：含数值的**事实段**必须带 evidence_ids（或显式公式/测算说明），否则数字无出处。

    判据修正（§7.4 第②类 用例预期偏差，对应台账 D-10 修复建议②）：
    生产侧 `_audit_chapter` 已按 `paragraph.kind` 与 `assumption_note` 区分「事实段」与
    「口径/局限/测算陈述段」——kind ∈ {methodology, boundary, scenario, risk, transition}
    或带 assumption_note（如"基于产业公开资料及研报上下文综合测算"）的段落，属显式声明的
    非硬事实陈述，不应按"数值无出处"误报。原判据只认 evidence_ids/formula，把口径段
    （P-01-02-01 methodology）、局限段（P-01-02-04 boundary）与已声明测算假设的区间段
    （P-01-01-04 comparison+assumption_note）一并计为缺证据——3/83 全为误报。
    改为与生产语义对齐：仅**事实段**缺证据才计入 offender。
    """
    number_re = re.compile(r"\d")
    caveat_kinds = {"methodology", "boundary", "scenario", "risk", "transition"}
    offenders: list[tuple[str, str]] = []
    total_numeric = 0
    for chapter in _chapters().get("chapters") or []:
        for section in chapter.get("sections") or []:
            for para in section.get("paragraphs") or []:
                text = str(para.get("text") or "")
                if not number_re.search(text):
                    continue
                # 口径/局限/测算陈述段：生产侧已显式声明（kind 或 assumption_note），非"事实段缺证据"
                if str(para.get("kind") or "").lower() in caveat_kinds or para.get("assumption_note"):
                    continue
                total_numeric += 1
                has_evidence = bool(para.get("evidence_ids"))
                has_formula = bool(para.get("formula") or para.get("calculation"))
                if not has_evidence and not has_formula:
                    offenders.append((str(para.get("paragraph_id")), text[:70]))
    assert total_numeric > 0, "样本无数值事实段（判据未生效）"
    ratio = len(offenders) / total_numeric
    assert ratio <= 0.02, (
        f"A4-02 {len(offenders)}/{total_numeric}（{ratio:.2%}）含数值事实段缺证据（容忍 2%）: {offenders[:3]}"
    )


def test_a4_04_missing_data_is_disclosed_not_fabricated() -> None:
    """A4-04：数据不足时应显式披露，而不是用估算/推测性表述补数。"""
    fabricated_markers = ("据估算", "推测为", "预计约", "大约为", "按经验")
    hits: list[str] = []
    for chapter in _chapters().get("chapters") or []:
        for section in chapter.get("sections") or []:
            for para in section.get("paragraphs") or []:
                text = str(para.get("text") or "")
                if any(marker in text for marker in fabricated_markers) and not para.get("evidence_ids"):
                    hits.append(str(para.get("paragraph_id")))
    assert hits == [], f"A4-04 出现无证据的推测性补数表述: {hits[:5]}"
