"""LLM-driven chart selection, autonomous skill invocation, validation, rendering and artifact persistence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path
import secrets
from typing import Any

from chart_generator.config import Settings
from chart_generator.llm import ChartLLM, OpenAICompatibleLLM
from chart_generator.models import (
    AppliedSkill, ChartGenerationRequest, ChartGenerationResult, ChartQualityReport,
    ChartSpec, ChartType, EvidenceRef, SuppressedChart,
)
from chart_generator.compiler import ChartArchetype, DeclarativeChartSpec, EChartsCompiler
from chart_generator.data_formulation import AxisType, DataFormulator, NormalizedDataTable
from chart_generator.linter import BAR_TYPES, ChartLinterViolation, ChartSkillLinter
from chart_generator.metric_guard import DimensionGuard, canonical_metric_label
from chart_generator.render import (
    clean_chart_title, clean_metric_label, render_preview, render_svg,
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
    ):
        self.title = title
        self.chart_type = chart_type
        self.option = option
        self.evidence_ids = evidence_ids
        self.goal = goal
        self.chapter = chapter
        self.score = score
        self.footnotes = footnotes or []
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
            called_skills, candidates, suppressed = await self._run_llm_generation(request, record)
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
                repaired_cand, repaired_supp = await self._repair_charts_with_llm(candidates, violations, request, record)
                if repaired_cand:
                    candidates = repaired_cand
                    suppressed.extend(repaired_supp)
                    new_violations = self.linter.lint(candidates, request.report.evidence_index)
                    await record("skill_correction_resolved", passed=not new_violations, remaining_violations=[v.to_dict() for v in new_violations])
                    if new_violations:
                        candidates = self._conform_diversity_deterministically(candidates, request)
                else:
                    candidates = self._conform_diversity_deterministically(candidates, request)
            elif candidates:
                candidates = self._conform_diversity_deterministically(candidates, request)

            if not candidates and has_numeric_or_chain:
                await record("skill_routed_by_policy", skills=["chart-selection", "financial-charting"], reason="大模型未产出合规落地图表，自动激活确定性数据适配选型保底")
                fb_cands, fb_supp = self._deterministic_fallback(request)
                candidates = fb_cands
                suppressed.extend(fb_supp)
                violations = self.linter.lint(candidates, request.report.evidence_index)
                await record("skill_linter_checked", passed=not violations, violations=[v.to_dict() for v in violations])
                if violations:
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
            if len(selected) < request.preferences.max_charts:
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
        for index, item in enumerate(selected, start=1):
            chart_id = f"CHART-{index:02d}-{item.fingerprint[:8].upper()}"
            title = clean_chart_title(item.title)
            svg = render_svg(title, item.chart_type, item.option, item.footnotes)
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

            charts.append(ChartSpec(
                chart_id=chart_id,
                title=title,
                chart_type=item.chart_type,
                option=item.option,
                evidence_ids=item.evidence_ids,
                insight_goal=item.goal,
                recommended_chapter_id=item.chapter,
                footnotes=item.footnotes,
                svg_uri=svg_uri,
                html_uri=html_uri,
                data_fingerprint=item.fingerprint,
            ))
            previews.append((title, svg))
            await record("chart_ready", chart_id=chart_id, chart_type=item.chart_type, title=title)

        warnings = list(request.report.warnings)
        if not charts:
            warnings.append("当前数据不足以生成可靠图表；未为凑数而生成图表")
        if suppressed:
            warnings.append(f"有 {len(suppressed)} 个候选图表未生成，原因已记录")

        result = ChartGenerationResult(
            run_id=run_id,
            source_report_id=request.report.report_id,
            subject=request.report.subject,
            as_of=request.report.as_of,
            status="completed" if charts else "partial",
            applied_skills=applied_skills,
            charts=charts,
            suppressed_charts=suppressed,
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

        # Extract structured overview for LLM
        evidence_payload = [
            {
                "record_id": item.record_id,
                "domain": item.domain,
                "entity": item.entity,
                "metric": item.metric,
                "value": item.value,
                "unit": item.unit,
                "period": item.period.isoformat() if item.period else None,
            }
            for item in evidence_records[:60]
        ]

        user_prompt = f"""【研报主题】: {report.subject} (基准日期: {report.as_of})

【章节结构】:
{json.dumps([{"heading": s.heading, "purpose": s.purpose} for s in report.content_outline], ensure_ascii=False, indent=2)}

【关键指标概要】:
{json.dumps([{"name": m.name, "entity": m.entity, "value": m.value, "unit": m.unit} for m in report.key_metrics[:15]], ensure_ascii=False, indent=2)}

【事实证据清单】(共 {len(evidence_records)} 条，提供前 {len(evidence_payload)} 条):
{json.dumps(evidence_payload, ensure_ascii=False, indent=2)}

【用户配置偏好】:
- 最大图表数: {request.preferences.max_charts}
- 指定请求图表类型: {request.preferences.requested_types or "自动选型"}
- 主题风格: {request.preferences.theme}
- 包含进阶图表: {request.preferences.include_advanced}

【任务要求】:
1. 请先审查上述数据特征与研报需求，自主调用 `invoke_skill` 工具加载所需的技能规范；
2. 加载规范后，严格遵循规范，生成不超过 {request.preferences.max_charts} 张专业金融研报图表；
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
            if table and (not isinstance(option, dict) or not option or self._has_option_defects(option)):
                option = EChartsCompiler.compile(table, chart_type, title)
            elif not isinstance(option, dict) or not option:
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

            candidates.append(_Candidate(
                title=title,
                chart_type=chart_type,
                option=option,
                evidence_ids=valid_eids,
                goal=goal,
                chapter=chapter,
                score=100,
                footnotes=footnotes,
            ))

        return called_skills, candidates, suppressed

    def _has_option_defects(self, option: dict[str, Any]) -> bool:
        """Detects whether an option contains obvious quality defects like raw slugs or duplicate labels."""
        if not isinstance(option, dict) or not option:
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
            if getattr(report, "industry_chain_segments", None):
                nodes = []
                links = []
                stage_map = {"upstream": "上游", "midstream": "中游", "downstream": "下游"}
                for seg in report.industry_chain_segments:
                    cat = stage_map.get(seg.get("stage"), "中游")
                    for c in seg.get("representative_companies", []):
                        if c and c != "宏观" and not any(n["name"] == c for n in nodes):
                            nodes.append({"id": f"N{len(nodes)+1}", "name": str(c)[:14], "category": cat})
                if len(nodes) >= 3:
                    for i in range(len(nodes) - 1):
                        if nodes[i]["category"] != nodes[i + 1]["category"]:
                            links.append({"source": nodes[i]["id"], "target": nodes[i + 1]["id"]})
                    return {
                        "legend": {"data": ["上游", "中游", "下游"]},
                        "series": [{"type": "graph", "layout": "none", "data": nodes, "links": links}],
                    }
            chain = [r for r in records if r.domain == "industry_chain"] or records
            nodes = []
            seen = set()
            for r in chain[:18]:
                label = str(r.entity or r.value or r.metric)[:30]
                if label in seen:
                    continue
                seen.add(label)
                text = f"{r.metric} {r.value}"
                cat = "上游" if "上游" in text else "下游" if "下游" in text else "中游"
                nodes.append({"id": f"N{len(nodes)+1}", "name": label, "category": cat})
            links = [{"source": nodes[i]["id"], "target": nodes[i + 1]["id"]} for i in range(len(nodes) - 1) if nodes[i]["category"] != nodes[i + 1]["category"]]
            return {
                "legend": {"data": ["上游", "中游", "下游"]},
                "series": [{"type": "graph", "layout": "none", "data": nodes, "links": links}],
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
            max_v = max(vals) if vals else 100
            indicators = [{"name": lbl, "max": round(max(max_v * 1.2, 10), 2)} for lbl in labels]
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
                labels = [x.isoformat() for x in periods]
                series = []
                for entity, group in list(usable_series.items())[:5]:
                    mapping = {x.period: float(x.value) for x in group}
                    series.append({"name": entity, "type": "line", "connectNulls": False, "data": [mapping.get(p) for p in periods]})
                option = {"tooltip": {"trigger": "axis"}, "legend": {"data": [s["name"] for s in series]}, "xAxis": {"type": "category", "data": labels}, "yAxis": {"type": "value", "name": unit or ""}, "series": series}
                candidates.append(_Candidate(f"{m_label}趋势", "line", option, ids, f"观察{m_label}的时间变化", "CH-02", 100, footnotes))
                if request.preferences.include_advanced and len(periods) >= 4 and ("area" in req_types or "累计" in metric or "堆叠" in metric):
                    area = json.loads(json.dumps(option))
                    area["series"][0]["areaStyle"] = {}
                    candidates.append(_Candidate(f"{m_label}趋势面积", "area", area, ids, f"突出{m_label}的累计变化轮廓", "CH-02", 55, footnotes))

            # Cross-sectional comparison
            latest: dict[str, EvidenceRef] = {}
            for row in rows:
                key = row.entity or row.metric
                if key not in latest or (row.period or request.report.as_of) >= (latest[key].period or request.report.as_of):
                    latest[key] = row
            comparable = list(latest.values())[:15]
            if len(comparable) >= 2 and len({x.entity for x in comparable if x.entity}) >= 2:
                labels = [x.entity or clean_metric_label(x.metric) for x in comparable]
                vals = [float(x.value) for x in comparable]
                signed = min(vals) < 0 < max(vals)
                chart_type: ChartType = "comparison_bar" if signed else ("horizontal_bar" if any(len(str(l)) > 4 for l in labels) else "bar")
                option = {"tooltip": {"trigger": "axis"}, "xAxis": {"type": "category", "data": labels}, "yAxis": {"type": "value", "name": unit or "", "min": min(0, min(vals))}, "series": [{"name": m_label, "type": "bar", "data": vals}]}
                candidates.append(_Candidate(f"{m_label}横向比较", chart_type, option, [x.record_id for x in comparable], f"比较不同实体的{m_label}", "CH-04", 90, footnotes))
                if signed:
                    candidates.append(_Candidate(f"{m_label}发散对比", "diverging_bar", option, [x.record_id for x in comparable], f"清晰呈现不同实体的{m_label}正负分化", "CH-04", 88, footnotes))
                if all(v > 0 for v in vals) and len(vals) <= 5 and any(k in metric.lower() for k in ("占比", "份额", "构成", "share")):
                    pie = {"tooltip": {"trigger": "item"}, "series": [{"type": "pie", "radius": ["36%", "68%"], "data": [{"name": n, "value": v} for n, v in zip(labels, vals, strict=True)]}]}
                    candidates.append(_Candidate(f"{m_label}构成", "pie", pie, [x.record_id for x in comparable], f"展示{m_label}的结构构成", "CH-04", 95, footnotes))
                    candidates.append(_Candidate(f"{m_label}环形构成", "donut", pie, [x.record_id for x in comparable], f"环形展示{m_label}的结构构成", "CH-04", 94, footnotes))
                if request.preferences.include_advanced and all(v >= 0 for v in vals) and (len(vals) >= 8 or "treemap" in req_types):
                    tree = {"series": [{"type": "treemap", "data": [{"name": n, "value": v} for n, v in zip(labels, vals, strict=True)]}]}
                    candidates.append(_Candidate(f"{m_label}规模矩形树", "treemap", tree, [x.record_id for x in comparable], f"同时观察{m_label}的规模和集中度", "CH-04", 48, footnotes))
                if request.preferences.include_advanced and (len(vals) >= 15 or "boxplot" in req_types):
                    ordered = sorted(vals)
                    def q(p: float) -> float:
                        return ordered[round((len(ordered) - 1) * p)]
                    box = {"xAxis": {"type": "category", "data": [m_label]}, "yAxis": {"type": "value"}, "series": [{"type": "boxplot", "data": [[min(vals), q(0.25), q(0.5), q(0.75), max(vals)]]}]}
                    candidates.append(_Candidate(f"{m_label}样本分布", "boxplot", box, [x.record_id for x in comparable], f"展示{m_label}的样本分布与分位数", "CH-04", 42, footnotes))

        # Radar for multi-metric entity
        for entity, rows in by_entity.items():
            latest_by_metric: dict[str, EvidenceRef] = {}
            for row in rows:
                if row.metric not in latest_by_metric or (row.period or report.as_of) >= (latest_by_metric[row.metric].period or report.as_of):
                    latest_by_metric[row.metric] = row
            metrics = list(latest_by_metric.values())[:8]
            if len(metrics) >= 3:
                vals = [float(x.value) for x in metrics]
                low, high = min(vals), max(vals)
                normalized = [100.0 if high == low else (v - low) / (high - low) * 100 for v in vals]
                radar = {"radar": {"indicator": [{"name": clean_metric_label(x.metric), "max": 100} for x in metrics]}, "series": [{"type": "radar", "data": [{"name": entity, "value": normalized}]}]}
                candidates.append(_Candidate(f"{entity}多指标雷达", "radar", radar, [x.record_id for x in metrics], f"比较{entity}多项指标的相对位置", "CH-05", 70, ["各指标采用样本内0—100归一化"]))

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
                    candidates.append(_Candidate(f"{x_label}与{y_label}定位", kind, option, list(dict.fromkeys(ids)), f"观察实体在{x_label}和{y_label}维度的位置", "CH-04", 60, ["仅展示两个指标均有数据的实体"]))
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
                    candidates.append(_Candidate("多指标横向热力图", "heatmap", option, list(dict.fromkeys(ids)), "以各指标样本内标准化值比较实体位置", "CH-04", 52, ["每行指标独立归一化为0—100"]))

            # Combo
            for entity, rows in by_entity.items():
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
                        candidates.append(_Candidate(f"{entity}{left_label}与{right_label}", "combo", option, ids, f"联合观察{entity}的{left_label}和{right_label}", "CH-05", 58))
                        found = True
                        break
                    if found:
                        break
                if found:
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
                ev_ids.extend(seg.get("evidence_record_ids", []))
                for c in comps:
                    if c and c != "宏观" and not any(n["name"] == c for n in nodes):
                        nodes.append({"id": f"N{len(nodes)+1}", "name": str(c)[:14], "category": cat})
                        if sum(1 for n in nodes if n["category"] == cat) >= 3:
                            break
            if len(nodes) >= 3:
                for i in range(len(nodes) - 1):
                    if nodes[i]["category"] != nodes[i + 1]["category"]:
                        links.append({"source": nodes[i]["id"], "target": nodes[i + 1]["id"]})
                option = {"legend": {"data": ["上游", "中游", "下游"]}, "series": [{"type": "graph", "layout": "none", "data": nodes, "links": links}]}
                candidates.append(_Candidate(
                    "产业链结构",
                    "industry_chain",
                    option,
                    list(dict.fromkeys(ev_ids))[:18] or [x.record_id for x in list(report.evidence_index.values())[:18]],
                    "展示已获证据支持的产业链环节与核心代表企业",
                    "CH-03",
                    110
                ))
        else:
            chain = [x for x in report.evidence_index.values() if x.domain == "industry_chain"]
            if chain:
                nodes = []
                seen_names = set()
                for i, row in enumerate(chain[:18]):
                    label = str(row.entity or row.value or row.metric)[:30]
                    if label in seen_names:
                        continue
                    seen_names.add(label)
                    text = f"{row.metric} {row.value}"
                    category = "上游" if "上游" in text else "下游" if "下游" in text else "中游"
                    nodes.append({"id": f"N{len(nodes)+1}", "name": label, "category": category})
                if nodes:
                    links = [{"source": nodes[i]["id"], "target": nodes[i + 1]["id"]} for i in range(len(nodes) - 1) if nodes[i]["category"] != nodes[i + 1]["category"]]
                    option = {"legend": {"data": ["上游", "中游", "下游"]}, "series": [{"type": "graph", "layout": "none", "data": nodes, "links": links}]}
                    candidates.append(_Candidate("产业链结构", "industry_chain", option, [x.record_id for x in chain[:18]], "展示已获证据支持的产业链环节", "CH-03", 110))

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
                if table and (not isinstance(option, dict) or not option or self._has_option_defects(option)):
                    option = EChartsCompiler.compile(table, chart_type, title)
                elif not isinstance(option, dict) or not option:
                    option = self._synthesize_option_from_evidence(chart_type, valid_eids, title, report)
                if not isinstance(option, dict) or not option:
                    continue
                goal = str(chart_dict.get("insight_goal") or chart_dict.get("description") or title)
                chapter = str(chart_dict.get("recommended_chapter_id", "CH-04"))
                footnotes = [str(f) for f in chart_dict.get("footnotes", [])]
                new_candidates.append(_Candidate(
                    title=title,
                    chart_type=chart_type,
                    option=option,
                    evidence_ids=valid_eids,
                    goal=goal,
                    chapter=chapter,
                    score=100,
                    footnotes=footnotes,
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
        """Filters and orders candidates strictly by Data-Fitness without forcing unnatural chart types."""
        if len(candidates) < 4:
            return candidates

        req_types = set(request.preferences.requested_types)

        # 1. Prune candidates that violate Data-Fitness rules
        filtered: list[_Candidate] = []
        seen_line_area_eids: dict[frozenset[str], str] = {}
        for c in candidates:
            # Boxplot requires >= 15 sample points unless explicitly requested
            if c.chart_type == "boxplot" and "boxplot" not in req_types and len(c.evidence_ids) < 15:
                continue
            # Treemap requires >= 8 items unless explicitly requested
            if c.chart_type == "treemap" and "treemap" not in req_types:
                data_items = c.option.get("series", [{}])[0].get("data", []) if isinstance(c.option, dict) else []
                if len(data_items) < 8:
                    continue
            # Deduplicate line and area for identical evidence
            if c.chart_type in ("line", "area") and "area" not in req_types:
                key = frozenset(c.evidence_ids)
                if key in seen_line_area_eids:
                    continue
                seen_line_area_eids[key] = c.chart_type
            filtered.append(c)

        candidates = filtered or candidates

        max_charts = request.preferences.max_charts
        max_bars = max(1, int(max_charts * 0.60)) if max_charts >= 4 else max_charts

        # Categorize
        bars = [c for c in candidates if c.chart_type in BAR_TYPES]
        non_bars = [c for c in candidates if c.chart_type not in BAR_TYPES]

        # Group non_bars by type to encourage natural diversity where data allows
        by_type: dict[str, list[_Candidate]] = defaultdict(list)
        for c in non_bars:
            by_type[c.chart_type].append(c)

        conformed: list[_Candidate] = []
        # First round: pick 1 from each distinct non-bar type
        for ctype in sorted(by_type.keys(), key=lambda t: (t != "industry_chain", t != "combo", t != "radar", t != "donut", t != "line", t)):
            if by_type[ctype]:
                conformed.append(by_type[ctype].pop(0))

        # Add allowable number of bars
        for b in bars[:max_bars]:
            conformed.append(b)

        # Fill remaining non-bars
        for ctype, items in by_type.items():
            conformed.extend(items)

        # Fill remaining bars
        conformed.extend(bars[max_bars:])

        return conformed
