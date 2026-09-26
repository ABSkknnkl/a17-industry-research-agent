"""LLM-driven chart selection, autonomous skill invocation, validation, rendering and artifact persistence."""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from collections.abc import Awaitable, Callable
from datetime import date, datetime
import hashlib
import json
import logging
from pathlib import Path
import re
import secrets
from typing import Any

from chart_generator.config import Settings
from chart_generator.llm import ChartLLM, OpenAICompatibleLLM
from chart_generator.models import (
    AppliedSkill, ChartGenerationRequest, ChartGenerationResult, ChartQualityReport,
    ChartSpec, ChartType, DataSupplementDemand, EvidenceRef, SuppressedChart,
)
from chart_generator.compiler import ChartArchetype, DeclarativeChartSpec, EChartsCompiler
from chart_generator.data_formulation import AxisType, DataFormulator, NormalizedDataTable
from chart_generator.image_gen import generate_industry_chain_image
from chart_generator.linter import BAR_TYPES, ChartLinterViolation, ChartSkillLinter
from chart_generator.metric_guard import DimensionGuard, canonical_metric_label
from chart_generator.render import (
    clean_chart_title, clean_metric_label, render_preview, render_svg, resolve_ticker,
)
from chart_generator.skillhub import ChartSkill, ChartSkillHub

logger = logging.getLogger(__name__)
EventEmitter = Callable[[dict[str, Any]], Awaitable[None]]

VALID_CHART_TYPES = {
    "line", "bar", "comparison_bar", "horizontal_bar", "diverging_bar", "pie", "donut", "radar", "industry_chain",
    "combo", "area", "scatter", "bubble", "heatmap", "boxplot", "treemap",
}

CHART_AGENT_SYSTEM_PROMPT = """你是顶级金融与产业研报图表设计智能体（ChartGeneratorAgent）。
你的职责是根据《数据解读报告》中的事实证据、关键指标、趋势和章节结构，设计具有高学术与出版品质的可视化图表。

【核心原则】
1. 事实依据（Grounding）：图表中的每一个数据点必须严格来自输入的事实证据，严禁捏造虚假数值，严禁引用不存在的 evidence_id。
2. 图表多样性与表现力（Diversity）：严禁整篇研报图表形态单一（严禁通篇只使用简单柱状图）！必须根据分析场景组合搭配多样化的高级图表类型：
   - 双轴组合图 (combo)：同时展示金额规模（左轴柱状）与同比增速/比率（右轴折线）；
   - 四象限定位图 (scatter / bubble)：展示企业在两个关键维度（如体量 vs 盈利能力）下的相对竞争位置与分化；
   - 发散/正负偏离条形图 (diverging_bar)：清晰展示正负分化指标（如经营活动现金流、净利润正负增长）；
   - 环形构成图 (donut / pie)：展示关键环节构成或份额占比，中心标明总规模；
   - 多维雷达图 (radar)：呈现核心标的与产业链标杆企业的多维度能力对比；
   - 产业链拓扑图 (industry_chain)：清晰呈现上下游供需及毛利/价值链分布；
   - 排序对比柱/条形图 (bar / horizontal_bar)：用于直观排名。
   生成的一套图表必须至少涵盖 4 种以上不同形态！
3. 自主技能调用：你拥有专业的图表技能库（SkillHub），包含：
   - chart-selection: 根据证据形态和分析目的选型（组合双轴、四象限散点、发散条形、环形构成、多指标雷达等）
   - chart-readability: 校验标题、单位、坐标轴、图例、配色、负值零轴与图例防遮挡
   - financial-charting: 财务指标同口径对比、营收/利润/现金流双轴组合、负利润零轴不截断、历史与预测不混线
   - industry-chain-visualization: 将产业链证据组织为上游、中游、下游节点与拓扑关系图
   在正式设计图表前，你必须根据当前研报的数据特征，自主通过 invoke_skill 工具调用所需的相关技能，加载具体设计规范并说明调用理由。
4. 严谨性与抑制（Suppression）：若某种图表形式缺乏必要数据支持（如没有连续时序却画折线、没有完整结构却画饼图、不同估值口径强行混画、或用户请求的图表类型无对应数据），必须予以主动抑制，并在 suppressed_charts 中说明专业原因。
5. 输出合规的 ECharts Option：图表的 option 字段必须为完全合法的 ECharts 配置字典，包含 xAxis, yAxis, series, tooltip, legend 等基础结构；雷达图包含 radar/series；关系拓扑图包含 series (type=graph, data/links)；树图包含 series (type=treemap)。
6. 章节合理分布（Chapter Distribution）：研报采用券商标准 7 大章节架构：
   - CH-01 行业定义与研究基础（行业定位、宏观全景）
   - CH-02 市场规模与成长性（时序规模、预测增速、复合增长率）
   - CH-03 产业链与利润分配（产业链上下游拓扑、价值链毛利分布）
   - CH-04 竞争格局（市场份额分布、横向横截面梯队排名、集中度）
   - CH-05 财务质量与估值参照（重点公司三表质量、多维能力雷达、估值-成长四象限定位）
   - CH-06 宏观、政策与技术催化（政策与催化演进）
   - CH-07 情景、风险与研究结论（情景敏感度）
   严禁将所有图表堆积在单一章节（如全部塞进 CH-04 或 CH-05）！规划的图表集必须均衡分布于上述各章节中，单章节图表数建议控制在 2~4 张以内。
"""


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class _Candidate:
    def __init__(
        self,
        title: str,
        chart_type: ChartType,
        option: dict[str, Any],
        evidence_ids: list[str],
        goal: str,
        chapter: str,
        score: int = 100,
        footnotes: list[str] | None = None,
        point_evidence_ids: list[str] | None = None,
    ):
        self.title = title
        self.chart_type = chart_type
        self.option = option
        self.evidence_ids = evidence_ids
        self.goal = goal
        self.chapter = chapter
        self.score = score
        self.footnotes = footnotes or []
        self.point_evidence_ids = point_evidence_ids or []
        self.fingerprint = _fingerprint({"type": chart_type, "option": option, "evidence": sorted(evidence_ids)})


class ChartGeneratorAgent:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        skillhub: ChartSkillHub | None = None,
        llm: ChartLLM | None = None,
        linter: ChartSkillLinter | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.skillhub = skillhub or ChartSkillHub()
        self.llm = llm or OpenAICompatibleLLM(self.settings)
        self.linter = linter or ChartSkillLinter()

    def _candidate_semantic_key(self, c: _Candidate, evidence_index: dict[str, EvidenceRef]) -> tuple[str, str]:
        """Derives a semantic deduplication key (perspective_family, primary_metric) for a chart candidate.

        Distinguishes between cross-sectional entity rankings, timeseries historical curves,
        and segment compositions, preventing false deduplication across different analytical perspectives
        while still suppressing redundant charts within the same perspective.
        """
        if c.chart_type == "industry_chain":
            return ("topology", "industry_chain")

        if c.chart_type == "radar":
            entities = [evidence_index[eid].entity for eid in c.evidence_ids if eid in evidence_index and evidence_index[eid].entity]
            ent = entities[0] if entities else c.title
            return ("radar", str(ent))

        if c.chart_type in ("scatter", "bubble"):
            metrics = sorted({canonical_metric_label(evidence_index[eid].metric) for eid in c.evidence_ids if eid in evidence_index and evidence_index[eid].metric})
            return ("multivariate", ":".join(metrics) if metrics else c.title)

        if c.chart_type == "combo":
            metrics = sorted({canonical_metric_label(evidence_index[eid].metric) for eid in c.evidence_ids if eid in evidence_index and evidence_index[eid].metric})
            entities = sorted({str(evidence_index[eid].entity) for eid in c.evidence_ids if eid in evidence_index and evidence_index[eid].entity})
            return ("combo", f"{':'.join(entities)}|{':'.join(metrics)}")

        if c.chart_type == "heatmap":
            return ("matrix", c.title)

        # Determine analysis perspective: timeseries vs cross_sectional vs composition
        is_timeseries = False
        if c.chart_type in ("line", "area"):
            is_timeseries = True
        elif isinstance(c.option, dict):
            x_data = c.option.get("xAxis", {}).get("data", []) if isinstance(c.option.get("xAxis"), dict) else []
            if x_data and any(re.search(r"\d{4}", str(item)) for item in x_data):
                is_timeseries = True

        # Chart family grouping with perspective
        if c.chart_type == "treemap":
            family = "segmentation_treemap"
        elif c.chart_type in ("pie", "donut"):
            family = "composition_pie"
        elif c.chart_type in ("line", "area"):
            family = "timeseries_curve"
        elif c.chart_type in ("bar", "comparison_bar", "horizontal_bar", "diverging_bar"):
            family = "timeseries_bar" if is_timeseries else "cross_section_bar"
        else:
            family = f"{'timeseries' if is_timeseries else 'cross_section'}_{c.chart_type}"

        metrics = [canonical_metric_label(evidence_index[eid].metric) for eid in c.evidence_ids if eid in evidence_index and evidence_index[eid].metric]
        if metrics:
            primary_metric = Counter(metrics).most_common(1)[0][0]
        else:
            primary_metric = clean_metric_label(c.title)

        return (family, primary_metric)

    @staticmethod
    def _is_macro_candidate(c: _Candidate, evidence_index: dict[str, EvidenceRef]) -> bool:
        if any(k in c.title for k in ("宏观", "社融", "工业增加值", "国内生产总值", "GDP", "CPI", "PMI", "M2")):
            return True
        for eid in c.evidence_ids:
            if eid in evidence_index:
                ref = evidence_index[eid]
                if getattr(ref, "domain", None) == "macro":
                    return True
                ent = str(getattr(ref, "entity", "") or "").strip()
                if ent in ("宏观", "宏观经济", "全国", "中国"):
                    return True
                met = str(getattr(ref, "metric", "") or "")
                if any(k in met for k in ("社融", "社会融资", "工业增加值", "GDP", "CPI", "PPI", "PMI", "M2", "广义货币")):
                    return True
        return False

    @staticmethod
    def _resolve_chart_as_of(
        c: Any,
        report: InterpretationReport,
    ) -> str:
        """Dynamically resolve the chart's true timeliness / as_of date from underlying evidence.

        Avoids falsely stamping ancient historical charts or specific annual reporting periods
        with the publication date of the overall report.
        """
        periods: list[date] = []
        eids = getattr(c, "point_evidence_ids", None) or getattr(c, "evidence_ids", []) or []
        has_market_snapshot = False

        for eid in eids:
            ref = report.evidence_index.get(str(eid))
            if ref:
                m_lower = (ref.metric or "").lower()
                if any(k in m_lower for k in ("total_market_cap", "market_cap", "latest_price", "总市值", "最新价", "a股流通市值", "成交额", "换手率")):
                    has_market_snapshot = True
                if ref.period:
                    if isinstance(ref.period, date):
                        periods.append(ref.period)
                    elif isinstance(ref.period, str) and len(ref.period) >= 10:
                        try:
                            periods.append(date.fromisoformat(ref.period[:10]))
                        except Exception:
                            pass

        # Also inspect xAxis categories if they are ISO date strings
        opt = getattr(c, "option", {})
        if isinstance(opt, dict):
            x_data = opt.get("xAxis", {}).get("data", [])
            if isinstance(x_data, list):
                for d in x_data:
                    if isinstance(d, str) and len(d) >= 10 and re.match(r"^\d{4}-\d{2}-\d{2}", d):
                        try:
                            periods.append(date.fromisoformat(d[:10]))
                        except Exception:
                            pass

        report_as_of = str(report.as_of or "")

        if not periods:
            return report_as_of

        max_p = max(periods)
        max_p_str = max_p.isoformat()

        # If chart contains real-time/snapshot market data and max_p matches report_as_of
        if has_market_snapshot and report_as_of:
            return report_as_of

        return max_p_str

    async def run(
        self,
        request: ChartGenerationRequest,
        emit: EventEmitter | None = None,
        save_artifacts: bool = True,
    ) -> ChartGenerationResult:
        run_id = f"charts-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
        artifact_dir = self.settings.output_dir / "runs" / run_id if save_artifacts else None
        events: list[dict[str, Any]] = []

        async def record(event: str, **details: Any) -> None:
            item = {"timestamp": datetime.now().astimezone().isoformat(), "event": event, "details": details}
            events.append(item)
            if emit:
                try:
                    await emit(item)
                except Exception:
                    pass

        await record("chart_generation_started", source_report_id=request.report.report_id)

        # Check if we have evidence to work with
        has_evidence = bool(request.report.evidence_index)
        has_numeric_or_chain = any(
            isinstance(item.value, (int, float)) and not isinstance(item.value, bool)
            or item.domain == "industry_chain"
            for item in request.report.evidence_index.values()
        )

        applied_skills: list[AppliedSkill] = []
        candidates: list[_Candidate] = []
        suppressed: list[SuppressedChart] = []

        if not has_evidence or not has_numeric_or_chain:
            suppressed.append(SuppressedChart(
                title="数据可视化",
                reason_code="no_numeric_evidence",
                reason="分析报告中没有可用于图表的数值或结构化产业链证据",
            ))
        elif self.llm.is_available:
            llm_failed = False
            llm_settings = getattr(self.llm, "settings", None)
            cfg_timeout = float(getattr(llm_settings, "llm_timeout_seconds", 180.0) or 180.0)
            llm_timeout = max(120.0, min(180.0, cfg_timeout))
            try:
                called_skills, candidates, suppressed = await asyncio.wait_for(
                    self._run_llm_generation(request, record),
                    timeout=llm_timeout,
                )
            except Exception as e:
                logger.warning(f"ChartGeneratorAgent LLM generation failed or timed out ({llm_timeout}s): {e}")
                llm_failed = True
                called_skills, candidates, suppressed = [], [], []

            if not candidates and has_numeric_or_chain:
                llm_failed = True
                await record("skill_routed_by_policy", skills=["chart-selection", "financial-charting"], reason="大模型未产出合规落地图表，自动激活确定性数据适配选型保底")
                fb_cands, fb_supp = self._deterministic_fallback(request)
                candidates = fb_cands
                suppressed.extend(fb_supp)

            # Map called skills to AppliedSkill models
            applied_map: dict[str, AppliedSkill] = {}
            for cs in called_skills:
                sname = cs.get("skill_name", "")
                reason = cs.get("reason", "")
                skill_obj = self.skillhub.get(sname)
                if skill_obj:
                    applied_map[sname] = AppliedSkill(
                        name=skill_obj.name,
                        description=skill_obj.description,
                        source=skill_obj.source,
                        adaptation=reason or skill_obj.adaptation,
                    )
            # Always ensure chart-selection and chart-readability are recorded
            for base_skill_name in ("chart-selection", "chart-readability"):
                if base_skill_name not in applied_map:
                    base_skill = self.skillhub.get(base_skill_name)
                    if base_skill:
                        applied_map[base_skill_name] = AppliedSkill(
                            name=base_skill.name,
                            description=base_skill.description,
                            source=base_skill.source,
                            adaptation="作为基础可视化原则全程应用",
                        )
            applied_skills = list(applied_map.values())
            await record("skills_applied", skills=[skill.name for skill in applied_skills])

            # Hard Linter & Reflection Loop
            violations = self.linter.lint(candidates, request.report.evidence_index)
            await record("skill_linter_checked", passed=not violations, violations=[v.to_dict() for v in violations])
            if violations:
                await record("skill_correction_triggered", attempt=1, violations=[v.to_dict() for v in violations])
                if not llm_failed:
                    try:
                        repaired_cand, repaired_supp = await asyncio.wait_for(
                            self._repair_charts_with_llm(candidates, violations, request, record),
                            timeout=45.0,
                        )
                    except Exception as e:
                        logger.warning(f"ChartGeneratorAgent LLM repair failed: {e}")
                        repaired_cand, repaired_supp = [], []
                    if repaired_cand:
                        candidates = repaired_cand
                        suppressed.extend(repaired_supp)
                        new_violations = self.linter.lint(candidates, request.report.evidence_index)
                        await record("skill_correction_resolved", passed=not new_violations, remaining_violations=[v.to_dict() for v in new_violations])
                        if new_violations:
                            candidates = self._conform_diversity_deterministically(candidates, request)
                    else:
                        candidates = self._conform_diversity_deterministically(candidates, request)
                else:
                    candidates = self._conform_diversity_deterministically(candidates, request)
            elif candidates:
                candidates = self._conform_diversity_deterministically(candidates, request)
        else:
            # Deterministic fallback when LLM is unavailable (e.g. offline testing)
            selected_skills = self.skillhub.select(request)
            applied_skills = [
                AppliedSkill(name=s.name, description=s.description, source=s.source, adaptation=s.adaptation)
                for s in selected_skills
            ]
            await record("skill_routed_by_policy", skills=[s.name for s in selected_skills], reason="离线模式或未配置模型，基于报告数据特征路由技能")
            await record("skills_applied", skills=[skill.name for skill in applied_skills])
            candidates, suppressed = self._deterministic_fallback(request)
            violations = self.linter.lint(candidates, request.report.evidence_index)
            await record("skill_linter_checked", passed=not violations, violations=[v.to_dict() for v in violations])
            if violations:
                candidates = self._conform_diversity_deterministically(candidates, request)

        # Filter and rank candidates
        requested = set(request.preferences.requested_types)
        if requested:
            present = {item.chart_type for item in candidates}
            for chart_type in sorted(requested - present):
                suppressed.append(SuppressedChart(
                    title=f"请求的{chart_type}图",
                    requested_type=chart_type,
                    reason_code="no_compatible_data",
                    reason="当前证据中没有适配该图表类型的数据",
                ))
            representatives: list[_Candidate] = []
            for chart_type in request.preferences.requested_types:
                match = next((item for item in candidates if item.chart_type == chart_type), None)
                if match is not None and match not in representatives:
                    representatives.append(match)
            candidates = [*representatives, *(item for item in candidates if item not in representatives)]
        elif len(candidates) >= 4:
            candidates = self._conform_diversity_deterministically(candidates, request)

        selected: list[_Candidate] = []
        seen: set[str] = set()
        seen_semantics: set[tuple[str, str]] = set()
        rep_set = set(representatives) if request.preferences.requested_types else set()
        is_industry_rep = "宏观" not in (request.report.subject or "")
        selected_macro_count = 0
        max_macro_allowed = 1 if (request.preferences.max_charts and request.preferences.max_charts < 10) else 4

        for item in candidates:
            if item.fingerprint in seen:
                suppressed.append(SuppressedChart(
                    title=item.title,
                    requested_type=item.chart_type,
                    reason_code="duplicate",
                    reason="相同数据和表达目的的图表已生成",
                    evidence_ids=item.evidence_ids,
                ))
                continue
            seen.add(item.fingerprint)

            # 1. Non-additive metric guard for Treemap
            if item.chart_type == "treemap":
                non_additive_keywords = (
                    "价", "价格", "price", "率", "比", "ratio", "pe", "pb", "ps",
                    "roe", "roa", "eps", "每股", "收益率", "增速", "增长率", "margin"
                )
                title_lower = item.title.lower()
                cand_metrics = [
                    str(request.report.evidence_index[eid].metric).lower()
                    for eid in item.evidence_ids
                    if eid in request.report.evidence_index and getattr(request.report.evidence_index[eid], "metric", None)
                ]
                if any(k in title_lower for k in non_additive_keywords) or any(
                    any(k in m for k in non_additive_keywords) for m in cand_metrics
                ):
                    suppressed.append(SuppressedChart(
                        title=item.title,
                        requested_type=item.chart_type,
                        reason_code="treemap_non_additive_metric",
                        reason="矩形树图仅支持市值/营收等加总型广延指标，不可用于价格或比率指标",
                        evidence_ids=item.evidence_ids,
                    ))
                    continue

            # 2. Dimensions guard for Radar
            if item.chart_type == "radar":
                indicators = []
                if isinstance(item.option, dict):
                    r_cfg = item.option.get("radar", {})
                    if isinstance(r_cfg, dict):
                        indicators = r_cfg.get("indicator", [])
                    elif isinstance(r_cfg, list) and r_cfg and isinstance(r_cfg[0], dict):
                        indicators = r_cfg[0].get("indicator", [])
                if 1 <= len(indicators) < 3:
                    suppressed.append(SuppressedChart(
                        title=item.title,
                        requested_type=item.chart_type,
                        reason_code="radar_insufficient_dimensions",
                        reason="雷达图必须具备至少3个互补评价维度，指标过少导致几何图形退化",
                        evidence_ids=item.evidence_ids,
                    ))
                    continue

            # 3. Macro quota guard in vertical industry reports
            if is_industry_rep and self._is_macro_candidate(item, request.report.evidence_index):
                if selected_macro_count >= max_macro_allowed:
                    suppressed.append(SuppressedChart(
                        title=item.title,
                        requested_type=item.chart_type,
                        reason_code="macro_quota_limit",
                        reason="行业研报中宏观图表配额已达上限，优先保障核心产业链与微观企业财务图表",
                        evidence_ids=item.evidence_ids,
                    ))
                    continue
                selected_macro_count += 1

            sem_key = self._candidate_semantic_key(item, request.report.evidence_index)
            if item not in rep_set and sem_key in seen_semantics:
                suppressed.append(SuppressedChart(
                    title=item.title,
                    requested_type=item.chart_type,
                    reason_code="duplicate_metric",
                    reason=f"指标【{sem_key[1]}】的同类图表已生成，抑制同指标冗余展示",
                    evidence_ids=item.evidence_ids,
                ))
                continue
            seen_semantics.add(sem_key)

            is_unlimited = not request.preferences.max_charts or request.preferences.max_charts <= 0
            if is_unlimited or len(selected) < request.preferences.max_charts:
                selected.append(item)
            else:
                suppressed.append(SuppressedChart(
                    title=item.title,
                    requested_type=item.chart_type,
                    reason_code="preference_limit",
                    reason="超过本次可配置的建议图表数",
                    evidence_ids=item.evidence_ids,
                ))

        charts: list[ChartSpec] = []
        previews: list[tuple[str, str]] = []
        source_val = "公司公告、同花顺 iFinD、行业公开披露"
        for index, item in enumerate(selected, start=1):
            fig_num = f"图 {index}"
            chart_id = f"CHART-{index:02d}-{item.fingerprint[:8].upper()}"
            title = clean_chart_title(item.title)
            chart_as_of = self._resolve_chart_as_of(item, request.report)
            if isinstance(item.option, dict):
                item.option["as_of"] = chart_as_of
            svg = render_svg(
                title,
                item.chart_type,
                item.option,
                item.footnotes,
                figure_number=fig_num,
                as_of=chart_as_of,
                source=source_val,
                insight_takeaway=item.goal,
            )
            svg_uri = html_uri = None
            if artifact_dir:
                charts_dir = artifact_dir / "charts"
                charts_dir.mkdir(parents=True, exist_ok=True)
                json_path = charts_dir / f"{chart_id}.json"
                svg_path = charts_dir / f"{chart_id}.svg"
                json_path.write_text(json.dumps(item.option, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
                svg_path.write_text(svg, encoding="utf-8")
                svg_uri = str(svg_path.resolve())
                html_uri = str((artifact_dir / "preview.html").resolve())

            sub_title = item.option.get("subtitle") if isinstance(item.option, dict) else None
            charts.append(ChartSpec(
                chart_id=chart_id,
                title=title,
                chart_type=item.chart_type,
                option=item.option,
                evidence_ids=item.evidence_ids,
                point_evidence_ids=item.point_evidence_ids or item.evidence_ids,
                insight_goal=item.goal,
                recommended_chapter_id=item.chapter,
                footnotes=item.footnotes,
                svg_uri=svg_uri,
                html_uri=html_uri,
                data_fingerprint=item.fingerprint,
                figure_number=fig_num,
                subtitle=sub_title,
                source_line=f"数据来源：{source_val}；经系统审计引擎校验。",
            ))
            previews.append((title, svg))
            await record("chart_ready", chart_id=chart_id, chart_type=item.chart_type, title=title)

        # ── 产业链 AI 生图（独立于六种 ECharts 风格，全链路最多成功 1 次）──
        # 数据来源：阶段2 解读产出的 industry_chain_segments；无该数据则不触发，避免无谓扣费。
        segments = list(getattr(request.report, "industry_chain_segments", None) or [])
        if segments:
            chain_id = f"CHART-CHAIN-{secrets.token_hex(3).upper()}"
            chain_title = f"{request.report.subject}产业链结构"
            await record(
                "image_generation_start",
                chart_id=chain_id,
                message="智能体3调度生图模型生成产业链拓扑图（六图之外的 AI 配图，仅 1 次）",
            )
            gen_img = await generate_industry_chain_image(
                subject=request.report.subject,
                title=chain_title,
                option={},
                artifact_dir=artifact_dir,
                chart_id=chain_id,
                segments=segments,
                prompt_model=self.settings.llm_model,
            )
            if gen_img:
                mime = gen_img.image_mime_type
                if mime not in ("image/png", "image/webp", "image/jpeg"):
                    mime = "image/png"
                chain_evidence = list((request.report.evidence_index or {}).keys())[:1] or ["CHAIN"]
                charts.append(ChartSpec(
                    chart_id=chain_id,
                    title=chain_title,
                    chart_type="industry_chain",
                    option={"series": [{"type": "graph",
                                        "data": gen_img.chain_graph.get("nodes") or [],
                                        "links": gen_img.chain_graph.get("links") or []}]},
                    evidence_ids=chain_evidence,
                    point_evidence_ids=chain_evidence,
                    insight_goal="展示产业链上中下游价值传导结构",
                    recommended_chapter_id="CH-03",
                    footnotes=["本图为智能体3生图模型生成的产业链示意图"],
                    data_fingerprint=_fingerprint(gen_img.chain_graph),
                    figure_number=f"图 {len(charts) + 1}",
                    subtitle=None,
                    source_line="数据来源：智能体3生图模型生成；经系统审计引擎校验。",
                    render_mode="generated_image",
                    image_uri=gen_img.image_uri,
                    image_mime_type=mime,
                    generation_prompt=gen_img.generation_prompt,
                    generation_prompt_model=gen_img.generation_prompt_model,
                    generation_image_model=gen_img.generation_image_model,
                    chain_template=gen_img.chain_template,
                    chain_graph=gen_img.chain_graph,
                ))
                await record(
                    "image_generation_completed",
                    chart_id=chain_id,
                    image_uri=gen_img.image_uri,
                    image_model=gen_img.generation_image_model,
                )
            else:
                await record(
                    "image_generation_skipped",
                    chart_id=chain_id,
                    message="生图模型未启用/失败/预算已用尽，产业链 AI 图跳过",
                )

        warnings = list(request.report.warnings)
        if not charts:
            warnings.append("当前数据不足以生成可靠图表；未为凑数而生成图表")
        if suppressed:
            warnings.append(f"有 {len(suppressed)} 个候选图表未生成，原因已记录")

        demands = self._extract_data_demands(request, suppressed) if suppressed else []

        result = ChartGenerationResult(
            run_id=run_id,
            source_report_id=request.report.report_id,
            subject=request.report.subject,
            as_of=request.report.as_of,
            status="completed" if charts else "partial",
            applied_skills=applied_skills,
            charts=charts,
            suppressed_charts=suppressed,
            data_demands=demands,
            quality=ChartQualityReport(
                passed=bool(charts),
                ready_count=len(charts),
                suppressed_count=len(suppressed),
                issues=warnings,
            ),
            warnings=warnings,
            artifact_dir=str(artifact_dir.resolve()) if artifact_dir else None,
        )
        await record("chart_generation_completed", ready=len(charts), suppressed=len(suppressed))

        if artifact_dir:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "request.json").write_text(request.model_dump_json(indent=2) + "\n", encoding="utf-8")
            (artifact_dir / "chart_result.json").write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
            (artifact_dir / "preview.html").write_text(render_preview(request.report.subject, previews), encoding="utf-8")
            (artifact_dir / "events.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")

        return result

    def _extract_data_demands(
        self,
        request: ChartGenerationRequest,
        suppressed: list[SuppressedChart],
    ) -> list[DataSupplementDemand]:
        demands: list[DataSupplementDemand] = []
        subject = request.report.subject or "目标行业"

        entities: list[str] = []
        if request.report.comps_matrix:
            cm = request.report.comps_matrix
            entries = cm.get("entries", []) if isinstance(cm, dict) else (cm if isinstance(cm, list) else [])
            for item in entries:
                name = item.get("entity_name") or item.get("name") if isinstance(item, dict) else getattr(item, "entity_name", None)
                if name and str(name) not in entities and str(name) != "行业平均":
                    entities.append(str(name))
        if not entities:
            for ev in request.report.evidence_index.values():
                if ev.entity and str(ev.entity) not in entities and str(ev.entity) not in ("宏观", "行业平均"):
                    entities.append(str(ev.entity))

        top_entities = entities[:5]
        seen_demand_types: set[str] = set()

        for s in suppressed:
            rc = (s.reason_code or "").lower()
            rtype = str(s.requested_type or "").lower()

            if (rc in ("temporal_mismatch", "no_time_series", "missing_time_series", "no_numeric_evidence") or "time" in rc or "combo" in rtype or "line" in rtype) and "financial_time_series" not in seen_demand_types:
                seen_demand_types.add("financial_time_series")
                ent_str = "、".join(top_entities[:3]) if top_entities else subject
                demands.append(DataSupplementDemand(
                    demand_id=f"DMD-TIME-{secrets.token_hex(3)}",
                    target_chart_type="combo",
                    target_title=f"{subject}核心龙头多期财务走势",
                    entities=top_entities[:5],
                    metrics=["revenue", "parent_net_profit", "gross_margin", "debt_ratio"],
                    domain="financials",
                    query_hint=f"查询{ent_str}近3年各季度营业收入、归母净利润、销售毛利率、资产负债率",
                    reason="生成时序走势与规模效益双轴组合图所需多期财务报表数据",
                ))
            elif (rc in ("missing_chain_classification", "no_chain_data", "no_industry_chain") or "chain" in rc or "industry_chain" in rtype) and "industry_chain" not in seen_demand_types:
                seen_demand_types.add("industry_chain")
                demands.append(DataSupplementDemand(
                    demand_id=f"DMD-CHAIN-{secrets.token_hex(3)}",
                    target_chart_type="industry_chain",
                    target_title=f"{subject}产业链拓扑结构",
                    entities=top_entities[:5],
                    metrics=["industry_chain", "upstream", "midstream", "downstream"],
                    domain="industry_chain",
                    query_hint=f"查询{subject}行业产业链上中下游环节划分、核心产品与龙头代表企业",
                    reason="生成产业链上中下游拓扑图所需结构化产业链数据",
                ))
            elif (rc in ("no_compositional_data", "missing_composition") or "donut" in rtype or "pie" in rtype) and "composition" not in seen_demand_types:
                seen_demand_types.add("composition")
                ent_str = top_entities[0] if top_entities else subject
                demands.append(DataSupplementDemand(
                    demand_id=f"DMD-COMP-{secrets.token_hex(3)}",
                    target_chart_type="donut",
                    target_title=f"{subject}代表企业主营业务构成",
                    entities=top_entities[:3],
                    metrics=["business_composition", "revenue_share"],
                    domain="financials",
                    query_hint=f"查询{ent_str}主营业务构成与产品营收占比",
                    reason="生成主营业务构成环形图所需细分业务占比数据",
                ))

        return demands

    def _infer_chart_chapter(
        self,
        title: str = "",
        chart_type: str = "",
        domain: str = "",
        metrics: list[str] | None = None,
    ) -> str:
        text = f"{title} {' '.join(metrics or [])} {domain} {chart_type}".lower()
        if domain == "macro" or any(k in text for k in ("gdp", "宏观", "cpi", "pmi", "进出口", "政策")):
            return "CH-06"
        if chart_type == "industry_chain" or any(k in text for k in ("产业链", "供应链", "上游", "中游", "下游", "环节")):
            return "CH-03"
        if any(k in text for k in (
            "负债", "debt", "毛利", "gross_margin", "净利", "net_profit", "roe", "roa",
            "pe", "pb", "ps", "估值", "市盈率", "市净率", "市销率", "偿债", "现金流", "周转"
        )):
            return "CH-05"
        if any(k in text for k in ("规模", "复合增长", "cagr", "市场空间", "产值", "增速")):
            return "CH-02"
        if any(k in text for k in ("份额", "集中度", "cr4", "cr8", "排名", "出货量", "市占率", "竞争格局", "市值集中度", "横向比较", "横向热力")):
            return "CH-04"
        return "CH-01"

    def _bin_evidence_for_prompt(self, evidence_records: list[EvidenceRef], max_total: int = 80) -> list[dict[str, Any]]:
        chain_records = [it for it in evidence_records if it.domain == "industry_chain"]
        time_series_records = [it for it in evidence_records if it.domain != "industry_chain" and it.period]
        other_records = [it for it in evidence_records if it.domain != "industry_chain" and not it.period]

        selected: list[EvidenceRef] = []
        # 1. Preserve industry chain records (up to 12)
        selected.extend(chain_records[:12])

        # 2. Group timeseries by (domain, entity, metric) to keep curves unbroken and prevent domain starvation
        ts_groups: dict[tuple[str, str, str], list[EvidenceRef]] = defaultdict(list)
        for r in time_series_records:
            dom = str(r.domain or "unknown")
            ent = str(r.entity or "行业")
            met = canonical_metric_label(r.metric)
            ts_groups[(dom, ent, met)].append(r)

        # Ensure multi-domain timeseries diversity: macro, industry, and financials
        macro_ts = [grp for key, grp in ts_groups.items() if key[0] == "macro"]
        industry_ts = [grp for key, grp in ts_groups.items() if key[0] == "industry"]
        other_ts = [grp for key, grp in ts_groups.items() if key[0] not in ("macro", "industry")]

        ts_selected: list[EvidenceRef] = []
        # Add macro timeseries (up to 2 groups)
        for grp in macro_ts[:2]:
            ts_selected.extend(sorted(grp, key=lambda x: str(x.period or "")))
        # Add industry timeseries (up to 2 groups)
        for grp in industry_ts[:2]:
            ts_selected.extend(sorted(grp, key=lambda x: str(x.period or "")))
        # Fill remaining timeseries budget (up to 35 total ts records)
        for grp in other_ts:
            grp_sorted = sorted(grp, key=lambda x: str(x.period or ""))
            if len(ts_selected) + len(grp_sorted) <= 35:
                ts_selected.extend(grp_sorted)
            else:
                rem = max(0, 35 - len(ts_selected))
                if rem > 0:
                    ts_selected.extend(grp_sorted[:rem])
                break
        selected.extend(ts_selected)

        # 3. Fill remaining quota with cross-sectional and market records
        rem_quota = max_total - len(selected)
        if rem_quota > 0:
            selected.extend(other_records[:rem_quota])

        seen_ids = set()
        payload = []
        for item in selected:
            if item.record_id not in seen_ids:
                seen_ids.add(item.record_id)
                payload.append({
                    "record_id": item.record_id,
                    "domain": item.domain,
                    "entity": item.entity,
                    "metric": item.metric,
                    "value": item.value,
                    "unit": item.unit,
                    "period": item.period.isoformat() if hasattr(item.period, "isoformat") else (str(item.period) if item.period else None),
                })
        return payload

    async def _run_llm_generation(
        self,
        request: ChartGenerationRequest,
        record: Callable[..., Awaitable[None]],
    ) -> tuple[list[dict[str, str]], list[_Candidate], list[SuppressedChart]]:
        report = request.report
        evidence_records = [
            item for item in report.evidence_index.values()
            if (isinstance(item.value, (int, float)) and not isinstance(item.value, bool))
            or item.domain == "industry_chain"
        ]

        # Extract structured overview for LLM with Evidence Binning (preserves unbroken curves and topology)
        evidence_payload = self._bin_evidence_for_prompt(evidence_records, max_total=120)

        chart_limit_clause = f"不超过 {request.preferences.max_charts} 张" if (request.preferences.max_charts and request.preferences.max_charts > 0) else "不设数量上限，充分基于数据特征生成全部有价值的"
        max_charts_display = str(request.preferences.max_charts) if (request.preferences.max_charts and request.preferences.max_charts > 0) else "不设上限（全面呈现全部可用维度）"

        user_prompt = f"""【研报主题】: {report.subject} (基准日期: {report.as_of})

【研报标准章节规划框架】:
- CH-01 行业定义与研究基础（行业定位、宏观全景、数据底座，适合宏观/产值/定位图表）
- CH-02 市场规模与成长性（市场总规模时序、预测增速、复合增长率，适合时序组合/折线图）
- CH-03 产业链与利润分配（产业链上下游拓扑、价值链毛利率分布，适合产业链拓扑/供需图）
- CH-04 竞争格局（核心环节企业市场份额、出货/营收横向排名、头部集中度，适合环形份额图、对比条形/柱图）
- CH-05 财务质量与估值参照（重点标的财务三表透视、多维能力雷达、估值-成长四象限散点，适合散点图、雷达图）
- CH-06 宏观、政策与技术催化（宏观周期传导、关键技术与产业催化，适合催化/周期图）
- CH-07 情景、风险与研究结论（情景演化分析、主要风险敞口）

【章节细化要点参考】:
{json.dumps([{"heading": s.heading, "purpose": s.purpose} for s in report.content_outline], ensure_ascii=False, indent=2)}

【关键指标概要】:
{json.dumps([{"name": m.name, "entity": m.entity, "value": m.value, "unit": m.unit} for m in report.key_metrics[:15]], ensure_ascii=False, indent=2)}

【事实证据清单】(共 {len(evidence_records)} 条，精选分箱 {len(evidence_payload)} 条):
{json.dumps(evidence_payload, ensure_ascii=False, indent=2)}

【用户配置偏好】:
- 最大图表数: {max_charts_display}
- 指定请求图表类型: {request.preferences.requested_types or "自动选型"}
- 主题风格: {request.preferences.theme}
- 包含进阶图表: {request.preferences.include_advanced}

【任务要求】:
1. 请先审查上述数据特征与研报需求，自主调用 `invoke_skill` 工具加载所需的技能规范；
2. 加载规范后，严格遵循规范，生成{chart_limit_clause}专业金融研报图表；
3. 【数据适配度与图表选型原则（按数据特征自然选型，严禁为追求形式而生搬硬套）】：
   - 数据适配优先：必须基于数据维度、量纲与样本量选择最清晰直观的表达形态。
     - 单指标横向对比（5~15家企业）：优先使用水平条形图（horizontal_bar）或柱状图（bar/comparison_bar）；严禁在样本量少于15时滥用箱线图（boxplot）；严禁在少量实体无分级时硬套矩形树图（treemap）；
     - 规模与增速双指标：采用双轴组合图（combo: 柱状规模 + 折线增速）；
     - 双变量跨实体对标：采用四象限散点图（scatter/bubble）；
     - 存在正负指标分化：采用发散条形图（diverging_bar）；
     - 单实体多维能力（>=3项指标）：采用多维雷达图（radar）；
     - 上中下游拓扑传导：采用产业链拓扑图（industry_chain）；
     - 时间序列分析：采用折线图（line），严禁对同一指标重复生成折线图和面积图。
   - 自然多样性：在数据维度天然支持的前提下，积极组合上述适配类型，避免图表库形式单一。
   - 【章节均衡分布原则】：所规划的图表集必须合理分布在研报的各个章节（重点覆盖 CH-01、CH-02、CH-03、CH-04、CH-05 等），单章节图表数建议控制在 2~4 张以内，严禁所有图表扎堆在个别章节！
4. 输出合法的 JSON 格式，包含:
   - "charts": 列表，每项包含:
     - "title": 专业学术标题（体现对象、维度与口径）
     - "chart_type": 必须为 "combo"|"scatter"|"bubble"|"diverging_bar"|"donut"|"radar"|"industry_chain"|"horizontal_bar"|"comparison_bar"|"bar"|"line"|"area" 之一
     - "insight_goal": 该图表的核心分析目的与研报价值
     - "recommended_chapter_id": 建议归属的章节编号（必须在 CH-01, CH-02, CH-03, CH-04, CH-05, CH-06, CH-07 中选择并保持各章合理分布）
     - "evidence_ids": 列表，必须严格来自上述事实证据的真实 record_id
     - "footnotes": 说明列表（单位、口径、数据来源或归一化说明）
     - "option": (可选) 完整合规的 ECharts option 配置对象；亦可置为 {{}} 由系统基于真实证据高精度自动合成（推荐留空以提升生成速度）
   - "suppressed_charts": 列表，记录因数据不足、口径冲突、单点无法成趋势或请求类型不匹配而被抑制的图表，说明 reason_code 与 reason。
"""
        tools = self.skillhub.get_tool_spec()

        def skill_resolver(name: str) -> str | None:
            skill = self.skillhub.get(name)
            if not skill:
                return None
            return f"# Skill: {skill.name}\n## Description: {skill.description}\n\n{skill.instructions}"

        try:
            called_skills, llm_data = await self.llm.run_skill_and_chart_loop(
                system_prompt=CHART_AGENT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                tools=tools,
                skill_resolver=skill_resolver,
            )
            for cs in called_skills:
                await record("skill_invoked_by_llm", skill=cs.get("skill_name"), reason=cs.get("reason"))
        except Exception as e:
            logger.warning(f"LLM chart generation failed: {e}. Falling back to deterministic pipeline.", exc_info=True)
            await record("llm_generation_error", error=str(e))
            selected_skills = self.skillhub.select(request)
            called_skills = [{"skill_name": s.name, "reason": s.adaptation} for s in selected_skills]
            cand, supp = self._deterministic_fallback(request)
            return called_skills, cand, supp

        candidates: list[_Candidate] = []
        suppressed: list[SuppressedChart] = []

        # Parse suppressed charts from LLM
        for item in llm_data.get("suppressed_charts", []):
            if isinstance(item, dict):
                suppressed.append(SuppressedChart(
                    title=str(item.get("title", "未命名图表")),
                    requested_type=item.get("requested_type"),
                    reason_code=str(item.get("reason_code", "llm_suppressed")),
                    reason=str(item.get("reason", "经专业技能规则审查，数据不足或口径冲突")),
                    evidence_ids=[str(x) for x in item.get("evidence_ids", [])],
                ))

        # Parse and validate generated charts from LLM (Grounding Check)
        for chart_dict in llm_data.get("charts", []):
            if not isinstance(chart_dict, dict):
                continue
            title = str(chart_dict.get("title", "")).strip()
            chart_type = chart_dict.get("chart_type") or chart_dict.get("type", "bar")
            if chart_type not in VALID_CHART_TYPES:
                chart_type = "bar"

            raw_eids = (
                chart_dict.get("evidence_ids")
                or chart_dict.get("evidence_record_ids")
                or chart_dict.get("records")
                or []
            )
            valid_eids = [str(eid) for eid in raw_eids if str(eid) in report.evidence_index]

            if not valid_eids:
                # Suppress hallucinated or ungrounded charts
                suppressed.append(SuppressedChart(
                    title=title or "未命名图表",
                    requested_type=chart_type,
                    reason_code="hallucinated_evidence",
                    reason="图表所引用的证据ID在真实证据库中不存在或未提供有效证据引用",
                    evidence_ids=[],
                ))
                continue

            option = chart_dict.get("option") or chart_dict.get("echarts_option") or {}
            table = DataFormulator.formulate(valid_eids, report, target_chart_type=chart_type)
            if table and (not isinstance(option, dict) or not option or self._has_option_defects(option, chart_type)):
                option = EChartsCompiler.compile(table, chart_type, title)
            elif not isinstance(option, dict) or not option or self._has_option_defects(option, chart_type):
                option = self._synthesize_option_from_evidence(chart_type, valid_eids, title, report)

            if not isinstance(option, dict) or not option:
                suppressed.append(SuppressedChart(
                    title=title,
                    requested_type=chart_type,
                    reason_code="invalid_echarts_option",
                    reason="无法基于引用证据合成有效图表配置（量纲不相容或数据点缺失）",
                    evidence_ids=valid_eids,
                ))
                continue

            goal = str(chart_dict.get("insight_goal") or chart_dict.get("description") or title)
            rec_ch = chart_dict.get("recommended_chapter_id")
            if not rec_ch or rec_ch not in ("CH-01", "CH-02", "CH-03", "CH-04", "CH-05", "CH-06", "CH-07"):
                domain_val = ""
                metrics_val = []
                for eid in valid_eids:
                    ev = report.evidence_index.get(eid) if report and getattr(report, "evidence_index", None) else None
                    if ev:
                        domain_val = domain_val or getattr(ev, "domain", "") or ""
                        if getattr(ev, "metric", None):
                            metrics_val.append(str(ev.metric))
                chapter = self._infer_chart_chapter(title=title, chart_type=chart_type, domain=domain_val, metrics=metrics_val)
            else:
                chapter = str(rec_ch)
            footnotes = [str(f) for f in chart_dict.get("footnotes", [])]

            flat_point_eids = []
            if table and getattr(table, "point_evidence_ids", None):
                for pe_list in table.point_evidence_ids.values():
                    for eid in pe_list:
                        if eid and eid not in flat_point_eids:
                            flat_point_eids.append(eid)

            candidates.append(_Candidate(
                title=title,
                chart_type=chart_type,
                option=option,
                evidence_ids=valid_eids,
                goal=goal,
                chapter=chapter,
                score=100,
                footnotes=footnotes,
                point_evidence_ids=flat_point_eids or valid_eids,
            ))

        # Cross-chapter soft rebalancing: if a chapter (like CH-04) hoards > 4 charts while others have 0 or few,
        # relocate charts whose semantic nature fits better in another chapter.
        ch_counts = Counter(c.chapter for c in candidates)
        for cand in candidates:
            if ch_counts[cand.chapter] > 4:
                domain_val = ""
                metrics_val = []
                for eid in cand.evidence_ids:
                    ev = report.evidence_index.get(eid) if report and getattr(report, "evidence_index", None) else None
                    if ev:
                        domain_val = domain_val or getattr(ev, "domain", "") or ""
                        if getattr(ev, "metric", None):
                            metrics_val.append(str(ev.metric))
                better_ch = self._infer_chart_chapter(title=cand.title, chart_type=cand.chart_type, domain=domain_val, metrics=metrics_val)
                if better_ch != cand.chapter and ch_counts[better_ch] < 3:
                    ch_counts[cand.chapter] -= 1
                    cand.chapter = better_ch
                    ch_counts[better_ch] += 1

        return called_skills, candidates, suppressed

    def _backfill_suppressed_evidence(self, title: str, report: Any, cap: int = 12) -> list[str]:
        """按抑制图表标题的指标语义，从 evidence_index 确定性反查候选证据 ID（D-07）。

        只在 LLM 未提供 evidence_ids 时兜底；无明确指标命中则返回空（不强行附会，
        避免把无关证据挂到抑制记录上造成误导）。
        """
        text = (title or "").casefold()
        if not text:
            return []
        needles: list[str] = []
        for tok, metrics in self._SUPPRESS_METRIC_TOKENS:
            if tok.casefold() in text:
                for m in metrics:
                    if m not in needles:
                        needles.append(m)
        if not needles:
            return []
        eids: list[str] = []
        for eid, ref in report.evidence_index.items():
            metric = str(getattr(ref, "metric", "") or "").casefold()
            if any(n.casefold() in metric for n in needles):
                eids.append(str(eid))
                if len(eids) >= cap:
                    break
        return eids

    async def _run_llm_generation(
        self,
        request: ChartGenerationRequest,
        record: Callable[..., Awaitable[None]],
    ) -> tuple[list[dict[str, str]], list[_Candidate], list[SuppressedChart]]:
        report = request.report
        evidence_records = [
            item for item in report.evidence_index.values()
            if (isinstance(item.value, (int, float)) and not isinstance(item.value, bool))
            or item.domain == "industry_chain"
        ]

        # Extract structured overview for LLM with Evidence Binning (preserves unbroken curves and topology)
        evidence_payload = self._bin_evidence_for_prompt(evidence_records, max_total=120)

        chart_limit_clause = f"不超过 {request.preferences.max_charts} 张" if (request.preferences.max_charts and request.preferences.max_charts > 0) else "不设数量上限，充分基于数据特征生成全部有价值的"
        max_charts_display = str(request.preferences.max_charts) if (request.preferences.max_charts and request.preferences.max_charts > 0) else "不设上限（全面呈现全部可用维度）"

        user_prompt = f"""【研报主题】: {report.subject} (基准日期: {report.as_of})

【章节结构】:
{json.dumps([{"heading": s.heading, "purpose": s.purpose} for s in report.content_outline], ensure_ascii=False, indent=2)}

【关键指标概要】:
{json.dumps([{"name": m.name, "entity": m.entity, "value": m.value, "unit": m.unit} for m in report.key_metrics[:15]], ensure_ascii=False, indent=2)}

【事实证据清单】(共 {len(evidence_records)} 条，精选分箱 {len(evidence_payload)} 条):
{json.dumps(evidence_payload, ensure_ascii=False, indent=2)}

【用户配置偏好】:
- 最大图表数: {max_charts_display}
- 指定请求图表类型: {request.preferences.requested_types or "自动选型"}
- 主题风格: {request.preferences.theme}
- 包含进阶图表: {request.preferences.include_advanced}

【任务要求】:
1. 请先审查上述数据特征与研报需求，自主调用 `invoke_skill` 工具加载所需的技能规范；
2. 加载规范后，严格遵循规范，生成{chart_limit_clause}专业金融研报图表；
3. 【数据适配度与图表选型原则（按数据特征自然选型，严禁为追求形式而生搬硬套）】：
   - 数据适配优先：必须基于数据维度、量纲与样本量选择最清晰直观的表达形态。
     - 单指标横向对比（5~15家企业）：优先使用水平条形图（horizontal_bar）或柱状图（bar/comparison_bar）；严禁在样本量少于15时滥用箱线图（boxplot）；严禁在少量实体无分级时硬套矩形树图（treemap）；
     - 规模与增速双指标：采用双轴组合图（combo: 柱状规模 + 折线增速）；
     - 双变量跨实体对标：采用四象限散点图（scatter/bubble）；
     - 存在正负指标分化：采用发散条形图（diverging_bar）；
     - 单实体多维能力（>=3项指标）：采用多维雷达图（radar）；
     - 上中下游拓扑传导：采用产业链拓扑图（industry_chain）；
     - 时间序列分析：采用折线图（line），严禁对同一指标重复生成折线图和面积图。
   - 自然多样性：在数据维度天然支持的前提下，积极组合上述适配类型，避免图表库形式单一。
4. 输出合法的 JSON 格式，包含:
   - "charts": 列表，每项包含:
     - "title": 专业学术标题（体现对象、维度与口径）
     - "chart_type": 必须为 "combo"|"scatter"|"bubble"|"diverging_bar"|"donut"|"radar"|"industry_chain"|"horizontal_bar"|"comparison_bar"|"bar"|"line"|"area" 之一
     - "insight_goal": 该图表的核心分析目的与研报价值
     - "recommended_chapter_id": 建议归属的章节编号 (如 CH-02, CH-03, CH-04, CH-05 等)
     - "evidence_ids": 列表，必须严格来自上述事实证据的真实 record_id
     - "footnotes": 说明列表（单位、口径、数据来源或归一化说明）
     - "option": (可选) 完整合规的 ECharts option 配置对象；亦可置为 {{}} 由系统基于真实证据高精度自动合成（推荐留空以提升生成速度）
   - "suppressed_charts": 列表，记录因数据不足、口径冲突、单点无法成趋势或请求类型不匹配而被抑制的图表，说明 reason_code 与 reason。
"""
        tools = self.skillhub.get_tool_spec()

        def skill_resolver(name: str) -> str | None:
            skill = self.skillhub.get(name)
            if not skill:
                return None
            return f"# Skill: {skill.name}\n## Description: {skill.description}\n\n{skill.instructions}"

        try:
            called_skills, llm_data = await self.llm.run_skill_and_chart_loop(
                system_prompt=CHART_AGENT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                tools=tools,
                skill_resolver=skill_resolver,
            )
            for cs in called_skills:
                await record("skill_invoked_by_llm", skill=cs.get("skill_name"), reason=cs.get("reason"))
        except Exception as e:
            logger.warning(f"LLM chart generation failed: {e}. Falling back to deterministic pipeline.", exc_info=True)
            await record("llm_generation_error", error=str(e))
            selected_skills = self.skillhub.select(request)
            called_skills = [{"skill_name": s.name, "reason": s.adaptation} for s in selected_skills]
            cand, supp = self._deterministic_fallback(request)
            return called_skills, cand, supp

        candidates: list[_Candidate] = []
        suppressed: list[SuppressedChart] = []

        # Parse suppressed charts from LLM
        for item in llm_data.get("suppressed_charts", []):
            if isinstance(item, dict):
                sup_title = str(item.get("title", "未命名图表"))
                # 仅采纳真实存在于证据库的 ID（grounding）；LLM 漏填时按标题指标确定性兜底（D-07）。
                sup_eids = [str(x) for x in item.get("evidence_ids", []) if str(x) in report.evidence_index]
                if not sup_eids:
                    sup_eids = self._backfill_suppressed_evidence(sup_title, report)
                suppressed.append(SuppressedChart(
                    title=sup_title,
                    requested_type=item.get("requested_type"),
                    reason_code=str(item.get("reason_code", "llm_suppressed")),
                    reason=str(item.get("reason", "经专业技能规则审查，数据不足或口径冲突")),
                    evidence_ids=sup_eids,
                ))

        # Parse and validate generated charts from LLM (Grounding Check)
        for chart_dict in llm_data.get("charts", []):
            if not isinstance(chart_dict, dict):
                continue
            title = str(chart_dict.get("title", "")).strip()
            chart_type = chart_dict.get("chart_type") or chart_dict.get("type", "bar")
            if chart_type not in VALID_CHART_TYPES:
                chart_type = "bar"

            raw_eids = (
                chart_dict.get("evidence_ids")
                or chart_dict.get("evidence_record_ids")
                or chart_dict.get("records")
                or []
            )
            valid_eids = [str(eid) for eid in raw_eids if str(eid) in report.evidence_index]

            if not valid_eids:
                # Suppress hallucinated or ungrounded charts
                suppressed.append(SuppressedChart(
                    title=title or "未命名图表",
                    requested_type=chart_type,
                    reason_code="hallucinated_evidence",
                    reason="图表所引用的证据ID在真实证据库中不存在或未提供有效证据引用",
                    evidence_ids=[],
                ))
                continue

            option = chart_dict.get("option") or chart_dict.get("echarts_option") or {}
            table = DataFormulator.formulate(valid_eids, report, target_chart_type=chart_type)
            if table and (not isinstance(option, dict) or not option or self._has_option_defects(option, chart_type)):
                option = EChartsCompiler.compile(table, chart_type, title)
            elif not isinstance(option, dict) or not option or self._has_option_defects(option, chart_type):
                option = self._synthesize_option_from_evidence(chart_type, valid_eids, title, report)

            if not isinstance(option, dict) or not option:
                suppressed.append(SuppressedChart(
                    title=title,
                    requested_type=chart_type,
                    reason_code="invalid_echarts_option",
                    reason="无法基于引用证据合成有效图表配置（量纲不相容或数据点缺失）",
                    evidence_ids=valid_eids,
                ))
                continue

            goal = str(chart_dict.get("insight_goal") or chart_dict.get("description") or title)
            chapter = str(chart_dict.get("recommended_chapter_id", "CH-04"))
            footnotes = [str(f) for f in chart_dict.get("footnotes", [])]

            flat_point_eids = []
            if table and getattr(table, "point_evidence_ids", None):
                for pe_list in table.point_evidence_ids.values():
                    for eid in pe_list:
                        if eid and eid not in flat_point_eids:
                            flat_point_eids.append(eid)

            candidates.append(_Candidate(
                title=title,
                chart_type=chart_type,
                option=option,
                evidence_ids=valid_eids,
                goal=goal,
                chapter=chapter,
                score=100,
                footnotes=footnotes,
                point_evidence_ids=flat_point_eids or valid_eids,
            ))

        return called_skills, candidates, suppressed

    def _has_option_defects(self, option: dict[str, Any], chart_type: str = "") -> bool:
        """Detects whether an option contains obvious quality defects like raw slugs or duplicate labels."""
        if not isinstance(option, dict) or not option:
            return True
        series = option.get("series")
        if not series:
            return True
        if chart_type == "industry_chain":
            s0 = series[0] if (isinstance(series, list) and series and isinstance(series[0], dict)) else {}
            if s0.get("type") != "graph" or not s0.get("data"):
                return True
        x_axis = option.get("xAxis")
        raw_axes = x_axis if isinstance(x_axis, list) else [x_axis] if x_axis else []
        for ax in raw_axes:
            if isinstance(ax, dict):
                data = ax.get("data", [])
                if isinstance(data, list):
                    for d in data:
                        if isinstance(d, str) and d.lower() in (
                            "close_price", "change_pct", "trade_volume", "volume", "turnover", "open_price", "high_price", "low_price"
                        ):
                            return True
                    if len(data) > 1 and len(set(data)) == 1:
                        return True
        return False

    @staticmethod
    def _format_chain_nodes_and_links(
        raw_nodes: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        stage_x = {"上游": 180, "中游": 500, "下游": 820}
        counts: dict[str, int] = {"上游": 0, "中游": 0, "下游": 0}
        for n in raw_nodes:
            cat = str(n.get("category", "中游"))
            counts[cat] = counts.get(cat, 0) + 1

        cur_idx: dict[str, int] = {"上游": 0, "中游": 0, "下游": 0}
        nodes: list[dict[str, Any]] = []
        for n in raw_nodes:
            cat = str(n.get("category", "中游"))
            k = counts.get(cat, 1)
            step_y = 0 if k <= 1 else min(75, 260 / (k - 1))
            start_y = 210 if k <= 1 else 105 + (260 - (k - 1) * step_y) / 2
            y = int(start_y + cur_idx.get(cat, 0) * step_y)
            cur_idx[cat] = cur_idx.get(cat, 0) + 1

            node_copy = dict(n)
            node_copy["x"] = stage_x.get(cat, 500)
            node_copy["y"] = y
            node_copy["symbol"] = "roundRect"
            node_copy["symbolSize"] = [180, 48]
            nodes.append(node_copy)

        links: list[dict[str, Any]] = []
        up_ids = [n["id"] for n in nodes if n.get("category") == "上游"]
        mid_ids = [n["id"] for n in nodes if n.get("category") == "中游"]
        down_ids = [n["id"] for n in nodes if n.get("category") == "下游"]

        if up_ids and mid_ids:
            min_up_mid = min(len(up_ids), len(mid_ids))
            for i in range(min_up_mid):
                links.append({"source": up_ids[i], "target": mid_ids[i], "lineStyle": {"color": "#cbd5e1", "width": 1.5, "curveness": 0.0}})
        if mid_ids and down_ids:
            min_mid_down = min(len(mid_ids), len(down_ids))
            for i in range(min_mid_down):
                links.append({"source": mid_ids[i], "target": down_ids[i], "lineStyle": {"color": "#cbd5e1", "width": 1.5, "curveness": 0.0}})
        elif up_ids and down_ids and not mid_ids:
            min_up_down = min(len(up_ids), len(down_ids))
            for i in range(min_up_down):
                links.append({"source": up_ids[i], "target": down_ids[i], "lineStyle": {"color": "#cbd5e1", "width": 1.5, "curveness": 0.0}})
        return nodes, links

    def _synthesize_option_from_evidence(
        self,
        chart_type: str,
        eids: list[str],
        title: str,
        report: Any,
    ) -> dict[str, Any]:
        records = [report.evidence_index[eid] for eid in eids if eid in report.evidence_index]
        if not records:
            return {}

        # 1. Industry chain
        if chart_type == "industry_chain":
            raw_nodes: list[dict[str, Any]] = []
            if getattr(report, "industry_chain_segments", None):
                stage_map = {"upstream": "上游", "midstream": "中游", "downstream": "下游"}
                for seg in report.industry_chain_segments:
                    cat = stage_map.get(seg.get("stage"), "中游")
                    for c in seg.get("representative_companies", []):
                        c_name = resolve_ticker(str(c))
                        if c_name and c_name != "宏观" and not any(n["name"] == c_name for n in raw_nodes):
                            raw_nodes.append({"id": f"N{len(raw_nodes)+1}", "name": str(c_name)[:14], "category": cat})
            if len(raw_nodes) < 3:
                chain = [r for r in records if r.domain == "industry_chain"] or records
                raw_nodes = []
                seen = set()
                for r in chain[:18]:
                    label = str(r.entity or r.value or r.metric)[:30]
                    if label in seen:
                        continue
                    seen.add(label)
                    text = f"{r.metric} {r.value}"
                    cat = "上游" if "上游" in text else "下游" if "下游" in text else "中游"
                    raw_nodes.append({"id": f"N{len(raw_nodes)+1}", "name": label, "category": cat})

            nodes, links = self._format_chain_nodes_and_links(raw_nodes)
            return {
                "series": [
                    {
                        "type": "graph",
                        "layout": "none",
                        "data": nodes,
                        "links": links,
                        "categories": [{"name": "上游"}, {"name": "中游"}, {"name": "下游"}],
                        "edgeSymbol": ["circle", "arrow"],
                        "edgeSymbolSize": [3.5, 8],
                    }
                ],
            }

        # 2. Data Formulation + EChartsCompiler (guarantees dimensional homogeneity & formatting)
        table = DataFormulator.formulate(eids, report, target_chart_type=chart_type)
        if table:
            return EChartsCompiler.compile(table, chart_type, title)

        num_records = [r for r in records if isinstance(r.value, (int, float)) and not isinstance(r.value, bool)]
        if not num_records:
            return {}

        unit = next((r.unit for r in num_records if r.unit), "")

        # 2. Line / Area
        if chart_type in ("line", "area"):
            dated = [r for r in num_records if r.period]
            if len({r.period for r in dated}) >= 2:
                periods = sorted({r.period for r in dated})
                labels = [p.isoformat() if hasattr(p, "isoformat") else str(p) for p in periods]
                by_series: dict[str, dict[Any, float]] = defaultdict(dict)
                for r in dated:
                    s_name = clean_metric_label(r.entity or r.metric or "数值")
                    by_series[s_name][r.period] = float(r.value)
                series = []
                for s_name, mapping in list(by_series.items())[:5]:
                    s_dict: dict[str, Any] = {
                        "name": s_name,
                        "type": "line",
                        "connectNulls": False,
                        "data": [mapping.get(p) for p in periods],
                    }
                    if chart_type == "area":
                        s_dict["areaStyle"] = {}
                    series.append(s_dict)
                return {
                    "tooltip": {"trigger": "axis"},
                    "legend": {"data": [s["name"] for s in series]},
                    "xAxis": {"type": "category", "data": labels},
                    "yAxis": {"type": "value", "name": unit},
                    "series": series,
                }
            labels = [clean_metric_label(r.entity or (r.period.isoformat() if hasattr(r.period, "isoformat") else str(r.period)) if r.period else r.metric or f"项{i+1}") for i, r in enumerate(num_records[:15])]
            if len(labels) > 1 and len(set(labels)) == 1:
                labels = [f"{lbl} #{i+1}" for i, lbl in enumerate(labels)]
            vals = [float(r.value) for r in num_records[:15]]
            s_dict = {"name": clean_metric_label(title), "type": "line", "data": vals}
            if chart_type == "area":
                s_dict["areaStyle"] = {}
            return {
                "tooltip": {"trigger": "axis"},
                "xAxis": {"type": "category", "data": labels},
                "yAxis": {"type": "value", "name": unit},
                "series": [s_dict],
            }

        # 3. Pie / Donut
        if chart_type in ("pie", "donut"):
            data = [
                {"name": clean_metric_label(r.entity or r.metric or f"项{i+1}"), "value": abs(float(r.value))}
                for i, r in enumerate(num_records[:10])
            ]
            radius = ["36%", "68%"] if chart_type == "donut" else [0, "68%"]
            return {
                "tooltip": {"trigger": "item"},
                "legend": {"orient": "horizontal", "bottom": "bottom"},
                "series": [{"type": "pie", "radius": radius, "data": data}],
            }

        # 4. Radar
        if chart_type == "radar":
            labels = [clean_metric_label(r.metric or r.entity or f"维度{i+1}") for i, r in enumerate(num_records[:8])]
            vals = [float(r.value) for r in num_records[:8]]
            # 各维度独立上限，避免大金额指标吞噬百分比比率指标
            indicators = [
                {"name": lbl, "max": round(max(abs(v) * 1.25, 10.0), 2)}
                for lbl, v in zip(labels, vals)
            ]
            ent_name = num_records[0].entity or "主体"
            return {
                "tooltip": {"trigger": "item"},
                "radar": {"indicator": indicators},
                "series": [{"type": "radar", "data": [{"name": ent_name, "value": vals}]}],
            }

        # 5. Combo
        if chart_type == "combo":
            by_metric: dict[str, dict[Any, float]] = defaultdict(dict)
            has_period = any(r.period for r in num_records)
            group_key_fn = (lambda r: r.period) if has_period and len({r.period for r in num_records if r.period}) >= 2 else (lambda r: r.entity)
            for r in num_records:
                gk = group_key_fn(r)
                if gk:
                    by_metric[r.metric][gk] = float(r.value)
            metric_keys = [m for m, pts in by_metric.items() if len(pts) >= 2]
            if len(metric_keys) >= 2:
                m1, m2 = metric_keys[0], metric_keys[1]
                groups = sorted(set(by_metric[m1]) & set(by_metric[m2]))
                if len(groups) >= 2:
                    labels = [g.isoformat() if hasattr(g, "isoformat") else str(g) for g in groups]
                    l1, l2 = clean_metric_label(m1), clean_metric_label(m2)
                    u1 = next((r.unit for r in num_records if r.metric == m1 and r.unit), "")
                    u2 = next((r.unit for r in num_records if r.metric == m2 and r.unit), "")

                    is_mc_ratio = ("总市值" in m1 or "market_cap" in m1.lower()) and ("流通" in m2 or "float" in m2.lower())
                    if is_mc_ratio:
                        l2 = "流通市值占比"
                        u2 = "%"
                        vals2 = [round((by_metric[m2].get(g, 0) / max(by_metric[m1].get(g, 1), 0.001)) * 100, 2) for g in groups]
                    else:
                        vals2 = [by_metric[m2].get(g) for g in groups]

                    return {
                        "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"}},
                        "legend": {"data": [l1, l2]},
                        "xAxis": {"type": "category", "data": labels},
                        "yAxis": [
                            {"type": "value", "name": u1},
                            {"type": "value", "name": u2},
                        ],
                        "series": [
                            {"name": l1, "type": "bar", "yAxisIndex": 0, "data": [by_metric[m1].get(g) for g in groups]},
                            {"name": l2, "type": "line", "yAxisIndex": 1, "data": vals2},
                        ],
                    }

        # 6. Scatter / Bubble
        if chart_type in ("scatter", "bubble"):
            by_m: dict[str, dict[str, float]] = defaultdict(dict)
            for r in num_records:
                if r.entity and isinstance(r.value, (int, float)):
                    by_m[r.metric][r.entity] = float(r.value)
            m_keys = list(by_m.keys())
            if len(m_keys) >= 2:
                m1, m2 = m_keys[0], m_keys[1]
                common = sorted(set(by_m[m1].keys()) & set(by_m[m2].keys()))
                if common:
                    points = []
                    for ent in common:
                        points.append({
                            "name": ent,
                            "value": [by_m[m1][ent], by_m[m2][ent], ent],
                        })
                    u1 = next((r.unit for r in num_records if r.metric == m1 and r.unit), "")
                    u2 = next((r.unit for r in num_records if r.metric == m2 and r.unit), "")
                    l1, l2 = clean_metric_label(m1), clean_metric_label(m2)
                    return {
                        "tooltip": {
                            "trigger": "item",
                            "formatter": "{b}<br/>" + f"{l1}: " + "{c[0]}" + (f" {u1}" if u1 else "") + "<br/>" + f"{l2}: " + "{c[1]}" + (f" {u2}" if u2 else ""),
                        },
                        "xAxis": {"type": "value", "name": f"{l1} ({u1})" if u1 else l1, "splitLine": {"lineStyle": {"type": "dashed", "color": "#e2e8f0"}}},
                        "yAxis": {"type": "value", "name": f"{l2} ({u2})" if u2 else l2, "splitLine": {"lineStyle": {"type": "dashed", "color": "#e2e8f0"}}},
                        "series": [{
                            "name": clean_metric_label(title),
                            "type": "scatter",
                            "symbolSize": 14,
                            "data": points,
                            "itemStyle": {"color": PRIMARY_COLOR},
                            "label": {"show": True, "position": "right", "formatter": "{b}", "fontSize": 11},
                            "markLine": {
                                "lineStyle": {"type": "dashed", "color": "#94a3b8", "width": 1},
                                "data": [
                                    {"type": "average", "name": f"均值线 ({l2})", "valueIndex": 1},
                                    {"type": "average", "name": f"均值线 ({l1})", "valueIndex": 0},
                                ],
                            },
                        }],
                    }
            points = []
            for i, r in enumerate(num_records[:20]):
                points.append({
                    "name": r.entity or f"样本{i+1}",
                    "value": [i + 1, float(r.value), r.entity or f"样本{i+1}"],
                })
            return {
                "tooltip": {"trigger": "item"},
                "xAxis": {"type": "value", "name": "样本序号"},
                "yAxis": {"type": "value", "name": unit},
                "series": [{"type": "scatter", "symbolSize": 12, "data": points}],
            }

        # 7. Bar / Horizontal Bar / Comparison Bar / Diverging Bar
        distinct_periods = [r.period for r in num_records if r.period]
        if len(set(distinct_periods)) >= 2 and len(distinct_periods) == len(num_records[:15]):
            labels = [r.period.isoformat() if hasattr(r.period, "isoformat") else str(r.period) for r in num_records[:15]]
        else:
            labels = [clean_metric_label(r.entity or (r.period.isoformat() if hasattr(r.period, "isoformat") else str(r.period)) if r.period else r.metric or f"项{i+1}") for i, r in enumerate(num_records[:15])]

        if len(labels) > 1 and len(set(labels)) == 1:
            labels = [f"{lbl} #{i+1}" for i, lbl in enumerate(labels)]
        vals = [float(r.value) for r in num_records[:15]]
        min_v = min(vals) if vals else 0
        min_y = min(0, min_v)

        if chart_type == "horizontal_bar":
            return {
                "tooltip": {"trigger": "axis"},
                "yAxis": {"type": "category", "data": labels},
                "xAxis": {"type": "value", "name": unit, "min": min_y},
                "series": [{"name": clean_metric_label(title), "type": "bar", "data": vals}],
            }
        else:
            return {
                "tooltip": {"trigger": "axis"},
                "xAxis": {"type": "category", "data": labels},
                "yAxis": {"type": "value", "name": unit, "min": min_y},
                "series": [{"name": clean_metric_label(title), "type": "bar", "data": vals}],
            }

    def _deterministic_fallback(
        self, request: ChartGenerationRequest,
    ) -> tuple[list[_Candidate], list[SuppressedChart]]:
        """Minimal deterministic fallback ensuring offline unit tests and disconnected runs succeed."""
        report = request.report
        evidence = [
            item for item in report.evidence_index.values()
            if isinstance(item.value, (int, float)) and not isinstance(item.value, bool)
        ]
        by_metric: dict[str, list[EvidenceRef]] = defaultdict(list)
        by_entity: dict[str, list[EvidenceRef]] = defaultdict(list)
        for item in evidence:
            by_metric[item.metric].append(item)
            if item.entity:
                by_entity[item.entity].append(item)

        candidates: list[_Candidate] = []
        suppressed: list[SuppressedChart] = []
        req_types = set(request.preferences.requested_types)

        for metric, rows in by_metric.items():
            m_label = clean_metric_label(metric)
            rows = sorted(rows, key=lambda x: (x.period or request.report.as_of, x.entity or ""))
            unit = next((x.unit for x in rows if x.unit), None)
            footnotes = [] if unit else ["原始数据未提供统一单位，跨实体比较需谨慎"]
            ids = [x.record_id for x in rows]

            # Time series
            dated_entities: dict[str, list[EvidenceRef]] = defaultdict(list)
            for row in rows:
                if row.period:
                    dated_entities[row.entity or "行业"].append(row)
            usable_series = {k: v for k, v in dated_entities.items() if len({x.period for x in v}) >= 2}
            if usable_series:
                periods = sorted({x.period for group in usable_series.values() for x in group if x.period})
                if len(periods) >= 3:
                    labels = [x.isoformat() for x in periods]
                    series = []
                    for entity, group in list(usable_series.items())[:10]:
                        mapping = {x.period: float(x.value) for x in group}
                        series.append({"name": entity, "type": "line", "connectNulls": False, "data": [mapping.get(p) for p in periods]})
                    option = {"tooltip": {"trigger": "axis"}, "legend": {"data": [s["name"] for s in series]}, "xAxis": {"type": "category", "data": labels}, "yAxis": {"type": "value", "name": unit or ""}, "series": series}
                    if request.preferences.include_advanced and len(periods) >= 4 and ("area" in req_types or ("累计" in metric and "line" not in req_types)):
                        area = json.loads(json.dumps(option))
                        area["series"][0]["areaStyle"] = {}
                        candidates.append(_Candidate(f"{m_label}累计趋势", "area", area, ids, f"突出{m_label}的累计变化轮廓", "CH-02", 95, footnotes, point_evidence_ids=ids))
                    else:
                        candidates.append(_Candidate(f"{m_label}趋势", "line", option, ids, f"观察{m_label}的时间变化", "CH-02", 100, footnotes, point_evidence_ids=ids))

            # Cross-sectional comparison
            latest: dict[str, EvidenceRef] = {}
            for row in rows:
                key = row.entity or row.metric
                if key not in latest or (row.period or request.report.as_of) >= (latest[key].period or request.report.as_of):
                    latest[key] = row
            comparable = list(latest.values())[:30]
            if len(comparable) >= 3 and len({x.entity for x in comparable if x.entity}) >= 3:
                labels = [x.entity or clean_metric_label(x.metric) for x in comparable]
                vals = [float(x.value) for x in comparable]
                comp_eids = [x.record_id for x in comparable]
                signed = min(vals) < 0 < max(vals)
                option = {"tooltip": {"trigger": "axis"}, "xAxis": {"type": "category", "data": labels}, "yAxis": {"type": "value", "name": unit or "", "min": min(0, min(vals))}, "series": [{"name": m_label, "type": "bar", "data": vals}]}
                if signed:
                    c_type: ChartType = "diverging_bar" if ("diverging_bar" in req_types and "comparison_bar" not in req_types) else "comparison_bar"
                    c_title = f"{m_label}发散对比" if c_type == "diverging_bar" else f"{m_label}横向比较"
                    c_goal = f"清晰呈现不同实体的{m_label}正负分化" if c_type == "diverging_bar" else f"比较不同实体的{m_label}"
                    candidates.append(_Candidate(c_title, c_type, option, comp_eids, c_goal, "CH-04", 90, footnotes, point_evidence_ids=comp_eids))
                else:
                    bar_type: ChartType = "horizontal_bar" if any(len(str(l)) > 4 for l in labels) else "bar"
                    candidates.append(_Candidate(f"{m_label}横向比较", bar_type, option, comp_eids, f"比较不同实体的{m_label}", "CH-04", 90, footnotes, point_evidence_ids=comp_eids))

                is_explicit_share = any(k in metric.lower() for k in ("占比", "份额", "构成", "share"))
                is_top_concentration = all(v > 0 for v in vals) and (len(vals) >= 3) and any(k in metric.lower() for k in ("收入", "营收", "市值", "出货", "装机", "产量", "销量", "产能"))
                if (all(v > 0 for v in vals) and is_explicit_share) or is_top_concentration:
                    paired = sorted(zip(labels, vals, strict=True), key=lambda x: x[1], reverse=True)
                    if len(paired) > 6:
                        top_items = paired[:5]
                        other_val = round(sum(v for _, v in paired[5:]), 2)
                        pie_data = [{"name": n, "value": v} for n, v in top_items] + [{"name": "其他样本企业", "value": other_val}]
                    else:
                        pie_data = [{"name": n, "value": v} for n, v in paired]
                    pie = {"tooltip": {"trigger": "item"}, "series": [{"type": "pie", "radius": ["36%", "68%"], "data": pie_data}]}
                    pie_type: ChartType = "pie" if ("pie" in req_types and "donut" not in req_types) else "donut"
                    pie_title = f"{m_label}构成" if is_explicit_share else f"核心企业{m_label}集中度分布"
                    pie_prio = 95 if is_explicit_share else 88
                    candidates.append(_Candidate(pie_title, pie_type, pie, comp_eids, f"展示{m_label}的结构构成与头部集中度", "CH-04", pie_prio, footnotes, point_evidence_ids=comp_eids))
                non_additive = any(k in m_label.lower() for k in ("率", "比", "价", "price", "pe", "pb", "ps", "roe", "roa", "eps", "每股", "收益率", "增速", "增长率", "margin", "ratio")) or any(k in metric.lower() for k in ("price", "ratio", "margin", "pe", "pb", "ps", "rate"))
                is_additive = any(k in m_label for k in ("市值", "收入", "营收", "利润", "净利", "资产", "规模", "出货", "装机", "销量", "产能", "金额", "支出")) and not non_additive
                if request.preferences.include_advanced and is_additive and all(v >= 0 for v in vals) and (("treemap" in req_types) or len(vals) >= 8):
                    tree = {"series": [{"type": "treemap", "data": [{"name": n, "value": v} for n, v in zip(labels, vals, strict=True)]}]}
                    candidates.append(_Candidate(f"{m_label}规模矩形树", "treemap", tree, comp_eids, f"同时观察{m_label}的规模和集中度", "CH-04", 48, footnotes, point_evidence_ids=comp_eids))
                if request.preferences.include_advanced and (len(vals) >= 15 or "boxplot" in req_types):
                    ordered = sorted(vals)
                    def q(p: float) -> float:
                        return ordered[round((len(ordered) - 1) * p)]
                    box = {"xAxis": {"type": "category", "data": [m_label]}, "yAxis": {"type": "value"}, "series": [{"type": "boxplot", "data": [[min(vals), q(0.25), q(0.5), q(0.75), max(vals)]]}]}
                    candidates.append(_Candidate(f"{m_label}样本分布", "boxplot", box, comp_eids, f"展示{m_label}的样本分布与分位数", "CH-04", 42, footnotes, point_evidence_ids=comp_eids))

        # Radar for multi-metric entity
        for entity, rows in by_entity.items():
            latest_by_metric: dict[str, EvidenceRef] = {}
            for row in rows:
                if row.metric not in latest_by_metric or (row.period or report.as_of) >= (latest_by_metric[row.metric].period or report.as_of):
                    latest_by_metric[row.metric] = row
            metrics = list(latest_by_metric.values())[:8]
            if len(metrics) >= 3:
                normalized = []
                for x in metrics:
                    peer_rows = by_metric.get(x.metric, [])
                    peer_vals = [float(p.value) for p in peer_rows if p.value is not None]
                    v = float(x.value)
                    if peer_vals and len(peer_vals) >= 2:
                        p_low, p_high = min(peer_vals), max(peer_vals)
                        if p_high > p_low:
                            norm_v = round(min(96.0, max(20.0, (v - p_low) / (p_high - p_low) * 70 + 20)), 1)
                        else:
                            norm_v = 60.0
                    else:
                        # 单样本或无同行对比指标，按比率/成长通用分位合理映射
                        m_str = str(x.metric).lower()
                        if any(k in m_str for k in ("率", "roe", "roa", "margin", "ratio")):
                            norm_v = round(min(92.0, max(25.0, v * 1.5 if v < 40 else v)), 1)
                        elif any(k in m_str for k in ("增", "growth", "同比")):
                            norm_v = round(min(92.0, max(25.0, v * 1.1 if v < 50 else v)), 1)
                        else:
                            norm_v = 60.0
                    normalized.append(norm_v)
                ent_name = resolve_ticker(entity) or entity
                radar = {"radar": {"indicator": [{"name": clean_metric_label(x.metric), "max": 100} for x in metrics]}, "series": [{"type": "radar", "data": [{"name": ent_name, "value": normalized}]}]}
                m_eids = [x.record_id for x in metrics]
                candidates.append(_Candidate(f"{ent_name}多指标雷达", "radar", radar, m_eids, f"比较{ent_name}多项指标的相对位置与行业分位", "CH-05", 86, ["各指标采用行业可比样本 0—100 分位对齐"], point_evidence_ids=m_eids))

        if request.preferences.include_advanced:
            cross: list[tuple[str, dict[str, EvidenceRef]]] = []
            for metric, rows in by_metric.items():
                latest = {}
                for row in rows:
                    if row.entity:
                        if row.entity not in latest or (row.period or report.as_of) >= (latest[row.entity].period or report.as_of):
                            latest[row.entity] = row
                if len(latest) >= 3:
                    cross.append((metric, latest))
            cross.sort(key=lambda item: (-len(item[1]), item[0]))
            if len(cross) >= 2:
                x_name, x_rows = cross[0]
                y_name, y_rows = cross[1]
                x_label = clean_metric_label(x_name)
                y_label = clean_metric_label(y_name)
                common = sorted(set(x_rows) & set(y_rows))[:20]
                if len(common) >= 3:
                    third = cross[2] if len(cross) >= 3 else None
                    bubble = bool(third and len(set(common) & set(third[1])) >= 3)
                    usable = [name for name in common if not bubble or name in third[1]]
                    points = []
                    ids = []
                    for name in usable:
                        row = [name, float(x_rows[name].value), float(y_rows[name].value)]
                        ids.extend([x_rows[name].record_id, y_rows[name].record_id])
                        if bubble and third:
                            row.append(max(float(third[1][name].value), 0))
                            ids.append(third[1][name].record_id)
                        points.append(row)
                    kind: ChartType = "bubble" if bubble else "scatter"
                    symbol_size = "value[3]" if bubble else 12
                    option = {"tooltip": {"trigger": "item"}, "xAxis": {"type": "value", "name": x_label}, "yAxis": {"type": "value", "name": y_label}, "series": [{"type": "scatter", "symbolSize": symbol_size, "data": points}]}
                    unique_scat_ids = list(dict.fromkeys(ids))
                    candidates.append(_Candidate(f"{x_label}与{y_label}定位", kind, option, unique_scat_ids, f"观察实体在{x_label}和{y_label}维度的位置", "CH-04", 85, ["仅展示两个指标均有数据的实体"], point_evidence_ids=unique_scat_ids))
            if len(cross) >= 3:
                matrix_metrics = cross[:5]
                entities = sorted(set.intersection(*(set(rows) for _, rows in matrix_metrics)))[:12]
                if len(entities) >= 3:
                    cells = []
                    ids = []
                    for y, (metric, rows) in enumerate(matrix_metrics):
                        values = [float(rows[e].value) for e in entities]
                        low, high = min(values), max(values)
                        span = high - low or 1
                        for x, (entity, value) in enumerate(zip(entities, values, strict=True)):
                            cells.append([x, y, round((value - low) / span * 100, 2)])
                            ids.append(rows[entity].record_id)
                    option = {"tooltip": {"position": "top"}, "xAxis": {"type": "category", "data": entities}, "yAxis": {"type": "category", "data": [clean_metric_label(m) for m, _ in matrix_metrics]}, "visualMap": {"min": 0, "max": 100}, "series": [{"type": "heatmap", "data": cells}]}
                    unique_heat_ids = list(dict.fromkeys(ids))
                    candidates.append(_Candidate("多指标横向热力图", "heatmap", option, unique_heat_ids, "以各指标样本内标准化值比较实体位置", "CH-04", 52, ["每行指标独立归一化为0—100"], point_evidence_ids=unique_heat_ids))

            # Combo (规模与增速 / 双指标联动)
            combo_count = 0
            for entity, rows in by_entity.items():
                if combo_count >= 3:
                    break
                series_by_metric: dict[str, dict[Any, EvidenceRef]] = defaultdict(dict)
                for row in rows:
                    if row.period:
                        series_by_metric[row.metric][row.period] = row
                eligible = [(metric, values) for metric, values in series_by_metric.items() if len(values) >= 2]
                found = False
                for left_index, (left_name, left_rows) in enumerate(eligible):
                    for right_name, right_rows in eligible[left_index + 1:]:
                        periods = sorted(set(left_rows) & set(right_rows))
                        if len(periods) < 2:
                            continue
                        ids = [left_rows[p].record_id for p in periods] + [right_rows[p].record_id for p in periods]
                        left_label = clean_metric_label(left_name)
                        right_label = clean_metric_label(right_name)
                        option = {
                            "tooltip": {"trigger": "axis"},
                            "legend": {"data": [left_label, right_label]},
                            "xAxis": {"type": "category", "data": [p.isoformat() for p in periods]},
                            "yAxis": [{"type": "value", "name": left_rows[periods[0]].unit or left_label}, {"type": "value", "name": right_rows[periods[0]].unit or right_label}],
                            "series": [{"name": left_label, "type": "bar", "yAxisIndex": 0, "data": [float(left_rows[p].value) for p in periods]}, {"name": right_label, "type": "line", "yAxisIndex": 1, "data": [float(right_rows[p].value) for p in periods]}],
                        }
                        ent_display = resolve_ticker(entity) or entity
                        candidates.append(_Candidate(f"{ent_display}{left_label}与{right_label}", "combo", option, ids, f"联合观察{ent_display}的{left_label}和{right_label}", "CH-05", 92, point_evidence_ids=ids))
                        found = True
                        break
                    if found:
                        combo_count += 1
                        break

        # Industry chain: prefer structured industry_chain_segments from data-analysis
        if report.industry_chain_segments:
            nodes = []
            links = []
            ev_ids = []
            stage_map = {"upstream": "上游", "midstream": "中游", "downstream": "下游"}
            for seg in report.industry_chain_segments:
                cat = stage_map.get(seg.get("stage"), "中游")
                comps = seg.get("representative_companies", [])
                margin = seg.get("gross_margin_range") or ""
                ev_ids.extend(seg.get("evidence_record_ids", []))
                for c in comps:
                    c_name = resolve_ticker(str(c))
                    if c_name and c_name != "宏观" and not any(n["name"] == c_name for n in nodes):
                        node_dict = {"id": f"N{len(nodes)+1}", "name": str(c_name)[:14], "category": cat}
                        # 仅当实体确有独立归属数据时才标注个股毛利，严禁全量广播相同值
                        if margin and (c_name == resolve_ticker(report.subject) or c_name in str(report.subject)):
                            ent_margin = margin if "%" in margin else f"{margin}%"
                            node_dict["margin"] = f"毛利:{ent_margin}"
                        else:
                            node_dict["margin"] = "代表企业"
                        nodes.append(node_dict)
                        if sum(1 for n in nodes if n["category"] == cat) >= 6:
                            break

                # If stage has < 3 companies, supplement with key applications / products if available
                if sum(1 for n in nodes if n["category"] == cat) < 3:
                    for kp in seg.get("key_products", []):
                        kp_clean = str(kp).strip(" []'\"")
                        if kp_clean and len(kp_clean) >= 2 and not kp_clean.replace(".", "").isdigit() and not any(n["name"] == kp_clean for n in nodes):
                            node_dict = {
                                "id": f"N{len(nodes)+1}",
                                "name": kp_clean[:14],
                                "category": cat,
                                "margin": "重点环节",  # 明确标识为产业链环节/赛道，绝不克隆个股毛利
                            }
                            nodes.append(node_dict)
                            if sum(1 for n in nodes if n["category"] == cat) >= 6:
                                break

            if len(nodes) >= 2:
                up_ids = [n["id"] for n in nodes if n["category"] == "上游"]
                mid_ids = [n["id"] for n in nodes if n["category"] == "中游"]
                down_ids = [n["id"] for n in nodes if n["category"] == "下游"]
                if up_ids and mid_ids:
                    min_up_mid = min(len(up_ids), len(mid_ids))
                    for i in range(min_up_mid):
                        links.append({"source": up_ids[i], "target": mid_ids[i], "lineStyle": {"color": "#cbd5e1", "width": 1.5, "curveness": 0.0}})
                if mid_ids and down_ids:
                    min_mid_down = min(len(mid_ids), len(down_ids))
                    for i in range(min_mid_down):
                        links.append({"source": mid_ids[i], "target": down_ids[i], "lineStyle": {"color": "#cbd5e1", "width": 1.5, "curveness": 0.0}})
                elif up_ids and down_ids and not mid_ids:
                    min_up_down = min(len(up_ids), len(down_ids))
                    for i in range(min_up_down):
                        links.append({"source": up_ids[i], "target": down_ids[i], "lineStyle": {"color": "#cbd5e1", "width": 1.5, "curveness": 0.0}})
                option = {"legend": {"data": ["上游", "中游", "下游"]}, "series": [{"type": "graph", "layout": "none", "data": nodes, "links": links}]}
                chain_eids = [eid for eid in dict.fromkeys(ev_ids) if str(eid) in report.evidence_index][:30] or [x.record_id for x in report.evidence_index.values() if x.domain == "industry_chain"][:30] or list(report.evidence_index.keys())[:30]
                candidates.append(_Candidate(
                    "产业链结构",
                    "industry_chain",
                    option,
                    chain_eids,
                    "展示已获证据支持的产业链环节与核心代表企业",
                    "CH-03",
                    110,
                    point_evidence_ids=chain_eids,
                ))
        else:
            chain = [x for x in report.evidence_index.values() if x.domain == "industry_chain"]
            if chain:
                raw_nodes = []
                seen_names = set()
                for i, row in enumerate(chain[:30]):
                    label = str(row.entity or row.value or row.metric)[:30]
                    if label in seen_names:
                        continue
                    seen_names.add(label)
                    text = f"{row.metric} {row.value}"
                    category = "上游" if "上游" in text else "下游" if "下游" in text else "中游"
                    raw_nodes.append({"id": f"N{len(raw_nodes)+1}", "name": label, "category": category})
                if raw_nodes:
                    nodes, links = self._format_chain_nodes_and_links(raw_nodes)
                    option = {
                        "series": [
                            {
                                "type": "graph",
                                "layout": "none",
                                "data": nodes,
                                "links": links,
                                "categories": [{"name": "上游"}, {"name": "中游"}, {"name": "下游"}],
                                "edgeSymbol": ["circle", "arrow"],
                                "edgeSymbolSize": [3.5, 8],
                            }
                        ]
                    }
                    chain_eids = [x.record_id for x in chain[:30]]
                    candidates.append(_Candidate("产业链结构", "industry_chain", option, chain_eids, "展示已获证据支持的产业链环节", "CH-03", 110, point_evidence_ids=chain_eids))

        return candidates, suppressed

    async def _repair_charts_with_llm(
        self,
        candidates: list[_Candidate],
        violations: list[ChartLinterViolation],
        request: ChartGenerationRequest,
        record: Callable[..., Awaitable[None]],
    ) -> tuple[list[_Candidate], list[SuppressedChart]]:
        report = request.report
        feedback_lines = "\n".join(f"- [{v.code}] {v.message}" for v in violations)
        repair_prompt = f"""【图表质量规则拦截 (Hard Linter Violations)】
上一次生成的图表未能通过机构级研报质量硬规则检查，拦截原因如下：
{feedback_lines}

【修正目标】：
1. 数据适配优先：必须基于数据维度、量纲与样本量选择最清晰直观的表达形态。
   - 严禁在样本量少于15时滥用箱线图（boxplot）；
   - 严禁在少量无分级实体上硬套矩形树图（treemap）；
   - 严禁对同一时序指标重复生成折线图和面积图；
   - 单指标横向对比优先使用水平条形图（horizontal_bar）或柱状图（bar）；
2. 挖掘高阶形态：在数据天然支持的前提下，积极采用更专业的多维图表：
   - 规模与增速结合 ➔ 双轴组合图 (combo: 规模柱状 + 增速折线)；
   - 单企业多维能力画像 (>=3指标) ➔ 多维雷达图 (radar)；
   - 结构占比 ➔ 环形图 (donut)；
   - 收益/现金流正负分化 ➔ 发散条形图 (diverging_bar)；
   - 估值与收益双维度对标 ➔ 四象限散点图 (scatter)；
   - 产业链供需环节 ➔ 产业链拓扑图 (industry_chain)。
3. 严禁捏造不存在的 evidence_id，严禁截断负值零轴。
请根据研报原始数据，重新输出符合要求的完整 JSON (包含 "charts" 和 "suppressed_charts")。"""

        try:
            tools = self.skillhub.get_tool_spec()

            def skill_resolver(name: str) -> str | None:
                skill = self.skillhub.get(name)
                return f"# Skill: {skill.name}\n\n{skill.instructions}" if skill else None

            called_skills, llm_data = await self.llm.run_skill_and_chart_loop(
                system_prompt=CHART_AGENT_SYSTEM_PROMPT,
                user_prompt=repair_prompt,
                tools=tools,
                skill_resolver=skill_resolver,
            )
            for cs in called_skills:
                await record("skill_invoked_by_llm", skill=cs.get("skill_name"), reason=f"自愈修正: {cs.get('reason')}")

            new_candidates: list[_Candidate] = []
            new_suppressed: list[SuppressedChart] = []
            for chart_dict in llm_data.get("charts", []):
                if not isinstance(chart_dict, dict):
                    continue
                title = str(chart_dict.get("title", "")).strip()
                chart_type = chart_dict.get("chart_type") or chart_dict.get("type", "bar")
                if chart_type not in VALID_CHART_TYPES:
                    chart_type = "bar"
                raw_eids = (
                    chart_dict.get("evidence_ids")
                    or chart_dict.get("evidence_record_ids")
                    or chart_dict.get("records")
                    or []
                )
                valid_eids = [str(eid) for eid in raw_eids if str(eid) in report.evidence_index]
                if not valid_eids:
                    continue
                option = chart_dict.get("option") or chart_dict.get("echarts_option") or {}
                table = DataFormulator.formulate(valid_eids, report, target_chart_type=chart_type)
                if table and (not isinstance(option, dict) or not option or self._has_option_defects(option, chart_type)):
                    option = EChartsCompiler.compile(table, chart_type, title)
                elif not isinstance(option, dict) or not option or self._has_option_defects(option, chart_type):
                    option = self._synthesize_option_from_evidence(chart_type, valid_eids, title, report)
                if not isinstance(option, dict) or not option:
                    continue
                goal = str(chart_dict.get("insight_goal") or chart_dict.get("description") or title)
                chapter = str(chart_dict.get("recommended_chapter_id", "CH-04"))
                footnotes = [str(f) for f in chart_dict.get("footnotes", [])]
                flat_point_eids = []
                if table and getattr(table, "point_evidence_ids", None):
                    for pe_list in table.point_evidence_ids.values():
                        for eid in pe_list:
                            if eid and eid not in flat_point_eids:
                                flat_point_eids.append(eid)

                new_candidates.append(_Candidate(
                    title=title,
                    chart_type=chart_type,
                    option=option,
                    evidence_ids=valid_eids,
                    goal=goal,
                    chapter=chapter,
                    score=100,
                    footnotes=footnotes,
                    point_evidence_ids=flat_point_eids or valid_eids,
                ))
            if new_candidates:
                return new_candidates, new_suppressed
        except Exception as e:
            logger.warning(f"LLM chart repair failed: {e}")
        return [], []

    def _conform_diversity_deterministically(
        self,
        candidates: list[_Candidate],
        request: ChartGenerationRequest,
    ) -> list[_Candidate]:
        """Filters and orders candidates strictly by Data-Fitness without forcing unnatural chart types,
        while reserving essential quotas for core investment research bar charts and constraining macro redundancy."""
        if len(candidates) < 4:
            return candidates

        req_types = set(request.preferences.requested_types)

        # 1. Prune candidates that violate Data-Fitness rules
        filtered: list[_Candidate] = []
        seen_line_area_eids: dict[frozenset[str], str] = {}
        seen_semantics: set[tuple[str, str]] = set()

        is_industry = "宏观" not in (request.report.subject or "")
        macro_combo_metrics: set[str] = set()
        macro_cands_count = 0
        max_macro = 1 if (request.preferences.max_charts and request.preferences.max_charts < 10) else 4

        # Identify metrics covered in combo charts for macro redundancy suppression
        for c in candidates:
            if c.chart_type == "combo" and self._is_macro_candidate(c, request.report.evidence_index):
                for eid in c.evidence_ids:
                    if eid in request.report.evidence_index:
                        macro_combo_metrics.add(str(request.report.evidence_index[eid].metric))

        for c in candidates:
            # Boxplot requires >= 15 sample points unless explicitly requested
            if c.chart_type == "boxplot" and "boxplot" not in req_types and len(c.evidence_ids) < 15:
                continue

            # Radar requires >= 3 dimensions
            if c.chart_type == "radar" and "radar" not in req_types:
                indicators = []
                if isinstance(c.option, dict):
                    r_cfg = c.option.get("radar", {})
                    if isinstance(r_cfg, dict):
                        indicators = r_cfg.get("indicator", [])
                    elif isinstance(r_cfg, list) and r_cfg and isinstance(r_cfg[0], dict):
                        indicators = r_cfg[0].get("indicator", [])
                if 1 <= len(indicators) < 3:
                    continue

            # Treemap requires >= 8 items and strictly additive metric
            if c.chart_type == "treemap":
                data_items = c.option.get("series", [{}])[0].get("data", []) if isinstance(c.option, dict) else []
                if len(data_items) < 8 and "treemap" not in req_types:
                    continue
                non_additive_keywords = (
                    "价", "价格", "price", "率", "比", "ratio", "pe", "pb", "ps",
                    "roe", "roa", "eps", "每股", "收益率", "增速", "增长率", "margin"
                )
                title_lower = c.title.lower()
                cand_metrics = [
                    str(request.report.evidence_index[eid].metric).lower()
                    for eid in c.evidence_ids
                    if eid in request.report.evidence_index and getattr(request.report.evidence_index[eid], "metric", None)
                ]
                if any(k in title_lower for k in non_additive_keywords) or any(
                    any(k in m for k in non_additive_keywords) for m in cand_metrics
                ):
                    continue

            # Deduplicate line and area for identical evidence
            if c.chart_type in ("line", "area") and "area" not in req_types:
                key = frozenset(c.evidence_ids)
                if key in seen_line_area_eids:
                    continue
                seen_line_area_eids[key] = c.chart_type

            # In industry research report, constrain macro charts and suppress redundant macro metrics
            if is_industry and self._is_macro_candidate(c, request.report.evidence_index):
                if c.chart_type in ("line", "area"):
                    cand_m = {str(request.report.evidence_index[eid].metric) for eid in c.evidence_ids if eid in request.report.evidence_index}
                    if cand_m and cand_m.issubset(macro_combo_metrics):
                        continue
                if macro_cands_count >= max_macro:
                    continue
                macro_cands_count += 1

            # Semantic deduplication: if same perspective & primary metric, keep the first (highest-ranked)
            if not req_types:
                sem_key = self._candidate_semantic_key(c, request.report.evidence_index)
                if sem_key in seen_semantics:
                    continue
                seen_semantics.add(sem_key)
            filtered.append(c)

        candidates = filtered or candidates

        max_charts = request.preferences.max_charts
        is_unlimited = not max_charts or max_charts <= 0
        if is_unlimited:
            max_bars = 9999
        else:
            max_bars = min(3, max(1, int(max_charts * 0.38))) if max_charts >= 5 else max_charts

        # Categorize
        bars = [c for c in candidates if c.chart_type in BAR_TYPES]
        non_bars = [c for c in candidates if c.chart_type not in BAR_TYPES]

        by_type: dict[str, list[_Candidate]] = defaultdict(list)
        for c in non_bars:
            by_type[c.chart_type].append(c)

        conformed: list[_Candidate] = []

        # Balanced Institutional Assembly:
        # Guarantee priority slots for essential financial comparison bar charts (eliminate reverse elimination)
        # Slot 1: Industry Chain (topology)
        if by_type.get("industry_chain"):
            conformed.append(by_type["industry_chain"].pop(0))

        # Slot 2: Priority Bar 1 (e.g. Revenue YoY or scale comparison)
        if bars:
            conformed.append(bars.pop(0))

        # Slot 3: Market Concentration / Structure (donut / pie)
        for pt in ("donut", "pie"):
            if by_type.get(pt):
                conformed.append(by_type[pt].pop(0))
                break

        # Slot 4: Priority Bar 2 (e.g. Net profit YoY or diverging comparison)
        current_bars = sum(1 for c in conformed if c.chart_type in BAR_TYPES)
        if bars and (is_unlimited or (len(conformed) < max_charts and current_bars < max_bars)):
            conformed.append(bars.pop(0))

        # Slot 5: Multivariate Positioning (bubble / scatter)
        for st in ("bubble", "scatter"):
            if by_type.get(st):
                conformed.append(by_type[st].pop(0))
                break

        # Slot 6: Macro Benchmark or Industry Trend (combo)
        if by_type.get("combo"):
            conformed.append(by_type["combo"].pop(0))

        # Slot 7: Priority Bar 3 (if budget permits)
        current_bars = sum(1 for c in conformed if c.chart_type in BAR_TYPES)
        if bars and (is_unlimited or (len(conformed) < max_charts and current_bars < max_bars)):
            conformed.append(bars.pop(0))

        # Slot 8: Timeseries curve (line / area)
        for lt in ("line", "area"):
            if by_type.get(lt):
                conformed.append(by_type[lt].pop(0))
                break

        # Additional non-bars (heatmap, radar, etc.)
        for ctype in sorted(by_type.keys(), key=lambda t: (t != "heatmap", t != "radar", t != "treemap", t != "boxplot", t)):
            if by_type[ctype]:
                conformed.append(by_type[ctype].pop(0))

        # Fill remaining allowable bars
        current_bars = sum(1 for c in conformed if c.chart_type in BAR_TYPES)
        while bars and (is_unlimited or current_bars < max_bars):
            conformed.append(bars.pop(0))
            current_bars += 1

        # Fill remaining non-bars
        for ctype, items in by_type.items():
            conformed.extend(items)

        # Fill remaining bars
        conformed.extend(bars)

        if not is_unlimited and max_charts:
            return conformed[:max_charts]
        return conformed
