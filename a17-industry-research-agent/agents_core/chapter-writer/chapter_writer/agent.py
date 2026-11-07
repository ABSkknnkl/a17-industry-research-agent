"""Bounded generate-audit-repair chapter writing agent."""

from __future__ import annotations
from agents_core.financial_semantics import (
    CLAIM_METRICS,
    QUANTITY_RE,
    measurement_period,
    metric_family,
    quantity_issues,
    retain_supported_claims,
    verified_calculations,
)
from agents_core.context_budget import ContextBudgetExceeded, serialize_context

import asyncio
import httpx
from collections.abc import Awaitable, Callable
from datetime import datetime
import json
from pathlib import Path
import re
import secrets
from typing import Any


from chapter_writer.config import Settings
from chapter_writer.llm import ChapterLLM, OpenAICompatibleLLM
from chapter_writer.models import (
    AppliedSkill, ChapterDraft, ChapterQualityReport, ChapterWritingRequest, ChapterWritingResult,
    ParagraphDraft, SectionDraft,
)
from chapter_writer.outline import DEFAULT_OUTLINE, OUTLINE_VERSION
from chapter_writer.retriever import DynamicEvidenceRetriever
from chapter_writer.skillhub import WritingSkill, WritingSkillHub

try:
    from skill_policy import merge_selection
except ModuleNotFoundError:  # 单包测试或独立运行时 agents_core 不在搜索路径上，按包位置回推
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from skill_policy import merge_selection

from skill_policy.requests import resolve_requested_skills

EventEmitter=Callable[[dict[str,Any]],Awaitable[None]]

def prepare_chapter_context(payload: dict[str, Any], system: str) -> tuple[str, dict[str, Any]]:
    """Drop duplicated and optional chapter context; never truncate required evidence."""
    packet = dict(payload)
    context = dict(packet.get('context') or {})
    packet['context'] = context
    omitted = []
    for key in ('global_facts', 'global_facts_prompt'):
        if key in context:
            context.pop(key)
            omitted.append('context.' + key)
    details = {'omitted_sections': omitted}
    packet['context_packing'] = details
    for key in ('requirement_evidence_matrix.details', 'comps_matrix', 'financial_ratios', 'industry_chain_segments', 'findings', 'outline_hints', 'insights', None):
        try:
            text, size, budget = serialize_context(packet, system=system)
            details.update(bytes=size, budget_bytes=budget)
            text, size, budget = serialize_context(packet, system=system)
            details.update(bytes=size, budget_bytes=budget)
            return text, details
        except ContextBudgetExceeded:
            if key is None:
                raise
            if key == 'requirement_evidence_matrix.details':
                matrix = context.get('requirement_evidence_matrix')
                if isinstance(matrix, list):
                    compacted = []
                    for row in matrix:
                        if not isinstance(row, dict):
                            continue
                        requirement, coverage = row.get('requirement') or {}, row.get('coverage') or {}
                        req_fields = ('requirement_id','label','domain','hard','min_records','expected_metric_groups',
                                      'requires_entity_code','requires_period_end','requires_published_at',
                                      'acceptable_skill_ids','entity_names','period_ends','metric_families')
                        cov_fields = ('requirement_id','label','domain','hard','passed','evidence_count','evidence_record_ids','missing')
                        compacted.append({'requirement':{k:requirement[k] for k in req_fields if k in requirement},
                                          'coverage':{k:coverage[k] for k in cov_fields if k in coverage}})
                    if compacted != matrix:
                        context['requirement_evidence_matrix'] = compacted
                        omitted.append('context.requirement_evidence_matrix.details')
                continue
            if context.get(key):
                context[key] = None if isinstance(context[key], dict) else []
                omitted.append('context.' + key)
    raise AssertionError('unreachable')

NUMBER_RE=re.compile(r"(?<![A-Za-z0-9_-])[-+]?\d+(?:\.\d+)?%?")
YEAR_OR_ORDINAL_RE=re.compile(r"^(?:19\d\d|20\d\d|[1-9]|10)$")

# 单章写作规范的默认预算；强制规范与用户显式选择优先保留。
CHAPTER_SKILL_LIMIT = 10

_NARRATIVE_KINDS = {"analysis", "thesis", "comparison", "chart_readout"}
_READOUT = re.compile(
    r"从.{0,32}(?:到|至).{0,32}(?:上升|下降|持平|回落|提高|扩大|收窄)"
    r"|由于|归因于|不能据此|仅能|不足以判断|仍需核对|仍需结合|无法判断"
)


def _lists_numbers(paragraph: ParagraphDraft) -> bool:
    if paragraph.kind not in _NARRATIVE_KINDS or not paragraph.evidence_ids or _READOUT.search(paragraph.text):
        return False
    clauses = [part.strip() for part in re.split(r"[。；;！!？?\n]", paragraph.text) if part.strip()]
    counts = [sum(bool(unit) for _, unit in QUANTITY_RE.findall(part)) for part in clauses]
    return bool(counts and all(counts) and sum(counts) >= 2)

SYSTEM_PROMPT="""你是机构级证券与行业研究报告章节写作智能体。你必须将内容组织成可直接供前端/PDF排版的结构化组件，而不是连续长文章。
严格要求：
1. 只使用输入 context 中的 evidence、insights、findings、comps_matrix、financial_ratios、industry_chain_segments 和 charts 信息，严禁捏造事实和数字。
2. 写作风格采用“断言主旨驱动 (Thesis-Driven)”：
   - 先回答本节问题，再选支撑判断的关键数字。把明细、平行指标和重复读数留给表格或指标卡；`key_points` 与摘要只保留读者需要记住的结论。
   - 每段只承担一个判断：给出证据对应的主体、期间和口径，然后说明变化、差异或业务含义。同一段的核心数字共用一次解读，无需逐个数字补一句归因。
   - 有同口径对照时解释方向和差异。有直接披露时注明谁披露了什么，才写成因。只有单期数字时交代该数字能回答什么；若要继续解释，指出具体还缺哪项数据。避免“值得关注”“总体向好”等空句。
   - 摘要概括本章最重要的判断，篇幅随证据和问题决定；无需为了凑字增加背景或重复结论。
3. `kind` 必须选用受控枚举：
   - `thesis`：本节核心判断与影响；
   - `evidence`：直接数据论据与口径引用；
   - `comparison`：横向同业对标或纵向历史周期对比；
   - `chart_readout`：图表邻接解读（图前结论、图中拐点、图后含义三段式）；
   - `risk`：风险、反例与制约因素；
   - `methodology`：口径与测算方法；
   - `transition`：必要的承上启下；
   - `analysis` / `scenario`：综合分析或情景推演。
4. 页面组件抽取（充分利用上下文中的量化资产）：
   - `metric_cards`：若本节涉及关键量化指标（如市值、增速、杜邦ROE、净现比、估值溢价），提炼 1~3 个指标卡：label, value, unit, period, evidence_ids；
   - `comparison_table`：若本节涉及多企业横向对标或三档情景推演，提炼结构化对比表：title, columns, rows, evidence_ids；
   - `callouts`：若本节存在关键风险提示、政策边界或不可外推声明，提炼为 callout：type("risk"|"boundary"|"highlight"), title, text, evidence_ids；
   - `layout_hint`：根据图文关系选择：text_only, chart_right, chart_full, comparison_table, metrics_grid。
5. 图文协同与显式强锚点：挂接的 `chart_ids` 必须在对应小节正文中提供具有分析深度的邻接解读（段落 `kind` 优先选用 `chart_readout`）。【强制约束】正文引用图表时必须显式出现对应图表的完整占位符（如 `[CHART-xx]`），严禁仅写模糊的“如图所示”而遗漏 `[CHART-xx]` 标签！排版引擎将统一映射为最终图表顺序编号。【严禁捏造未挂接图表占位符】：若本小节未挂接图表（`chart_ids` 为空），严禁在正文中插入任何 `[CHART-xx]` 占位符或图表引用！只能引用在上下文 `charts` 中真实存在的图表 ID！
6. 风险与情景推演规范（尤其针对第七章或预测性章节）：
   - 仅在输入提供可核验的测算依据时写量化情景，区分假设与结果；概率和阈值需要来源。
   - 资料只支持定性判断时，写清触发条件、待观察指标和判断边界；情景数量随证据决定。
   - 必须包含非外推声明 (Non-extrapolation Disclaimer，建议放置在 callout 中)：明确指出样本结构代表性边界（如未上市火箭/本体龙头未纳入三表核算）及期间跨度局限，禁止线性外推至整个产业。
7. 全局事实与一致性锚点（强制约束）：严格遵循输入及上下文中的 `global_facts`。凡提及行业/样本总市值，必须统一按照 `global_facts` 给出，严禁在不同章节出现数量级矛盾（如 22.14万亿 与 2.21万亿 的10倍冲突）；凡提及重点企业产业链环节归属，必须与 `global_facts` 保持绝对一致，严禁同一标的在上中下游反复横跳！
8. 非宏观章节套话禁令：除宏观综述或宏观驱动专章外，其余产业、竞争、财务等章节严禁重复展开脱节宏观指标（如社融、工业增加值）的周期无效性免责声明套话！保持对本行业真实财务、业务与竞争态势的专注。
9. 返回严格 JSON 格式（【极其重要规范】：你的输出必须且只能是一个纯合法的 JSON 对象。严禁在输出开头添加任何 Markdown 标题如 "# 标题" 或引言文字；严禁输出任何 ```json 代码块外围文本；正文内部出现的双引号若非 JSON 键值语法边界，一律使用中文双引号“”或转义）：
{
  "chapter_id": "CH-xx",
  "title": "...",
  "summary": "用最短篇幅概括本章有证据的核心判断",
  "sections": [
    {
      "section_id": "SEC-xx-xx",
      "title": "...",
      "purpose": "...",
      "key_points": ["核心要点1", "核心要点2"],
      "paragraphs": [
        {"paragraph_id": "P-xx-xx-01", "kind": "thesis", "text": "...", "evidence_ids": ["..."], "assumption_note": null}
      ],
      "chart_ids": ["..."],
      "uncertainties": ["..."],
      "metric_cards": [{"label": "...", "value": "...", "unit": "...", "period": "...", "evidence_ids": ["..."]}],
      "comparison_table": null,
      "callouts": [],
      "layout_hint": "chart_right"
    }
  ]
}"""


def extract_numbers(text:str)->list[str]:
    return NUMBER_RE.findall(text)


AEROSPACE_CANONICAL_SEGMENTS: dict[str, str] = {
    "中国卫星": "中游卫星研制与系统总装",
    "铖昌科技": "上游相控阵T/R芯片与核心元器件",
    "中兴通讯": "下游/地面系统与终端通信设备",
    "航天电子": "中游航天电子元器件与集成",
    "上海瀚讯": "中游卫星通信载荷与系统集成",
    "航天环宇": "上游/中游地面测控天线与微波部件",
    "移远通信": "下游通信模组与应用终端",
    "中国卫通": "下游卫星运营与综合通信服务",
    "光威复材": "上游碳纤维及复合材料",
    "中材科技": "上游特种纤维与复合材料",
    "国机精工": "上游特种轴承与精密部件",
    "大族激光": "上游激光加工与先进装备",
    "九丰能源": "上游特种气体与推进能源供给",
    "海格通信": "中游北斗导航与卫星通信终端",
}


def extract_global_quantitative_anchor(report: Any) -> dict[str, Any]:
    comps_matrix = getattr(report, "comps_matrix", None)
    if isinstance(comps_matrix, dict):
        comps = comps_matrix.get("entries") or comps_matrix.get("comps") or []
        total_mc = comps_matrix.get("total_market_cap")
        median_pe = comps_matrix.get("median_pe")
        median_pb = comps_matrix.get("median_pb")
        median_gross_margin = comps_matrix.get("median_gross_margin")
    else:
        comps = (getattr(comps_matrix, "entries", None) or getattr(comps_matrix, "comps", [])) if comps_matrix else []
        total_mc = getattr(comps_matrix, "total_market_cap", None) if comps_matrix else None
        median_pe = getattr(comps_matrix, "median_pe", None) if comps_matrix else None
        median_pb = getattr(comps_matrix, "median_pb", None) if comps_matrix else None
        median_gross_margin = getattr(comps_matrix, "median_gross_margin", None) if comps_matrix else None

    if not total_mc and comps:
        mc_list = [
            (c.get("market_cap") if isinstance(c, dict) else getattr(c, "market_cap", 0)) or 0
            for c in comps
        ]
        total_mc = sum(mc_list)

    mc_val = round(total_mc, 2) if total_mc else 0.0
    mc_wan_yi = round(mc_val / 10000.0, 2)
    if mc_val >= 10000:
        mc_str = f"{mc_val:,.2f} 亿元（约 {mc_wan_yi:.2f} 万亿元）"
    elif mc_val > 0:
        mc_str = f"{mc_val:,.2f} 亿元（约 {mc_wan_yi:.2f} 万亿元）"
    else:
        mc_str = "暂无汇总数据"

    total_companies = len(comps) if comps else 0
    profitable_count = sum(
        1 for c in comps
        if (c.get("valuation_tier") if isinstance(c, dict) else getattr(c, "valuation_tier", None)) == "profitable"
    ) if comps else 0
    loss_count = total_companies - profitable_count if total_companies else 0

    # Resolve subject for domain-specific canonical dictionaries
    subj = ""
    meta = getattr(report, "metadata", None)
    if isinstance(meta, dict):
        subj = meta.get("industry") or meta.get("subject") or ""
    elif meta:
        subj = getattr(meta, "industry", "") or getattr(meta, "subject", "") or ""
    if not subj and hasattr(report, "subject"):
        subj = getattr(report, "subject", "") or ""

    is_aerospace = any(k in str(subj) for k in ("航天", "卫星", "低轨"))
    canonical_segments: dict[str, str] = dict(AEROSPACE_CANONICAL_SEGMENTS) if is_aerospace else {}

    # Resolve company canonical segments dynamically
    for seg in getattr(report, "industry_chain_segments", []):
        s_name = getattr(seg, "segment_name", "") or (seg.get("segment_name", "") if isinstance(seg, dict) else "")
        reps = getattr(seg, "representative_companies", []) or (seg.get("representative_companies", []) if isinstance(seg, dict) else [])
        for comp in reps:
            c_str = str(comp).strip()
            if c_str and not re.match(r"^\d{6}\.[A-Z]{2}$", c_str) and not c_str.replace(".", "").isdigit():
                if c_str not in canonical_segments:
                    canonical_segments[c_str] = s_name

    return {
        "market_cap_val": mc_val,
        "market_cap_wan_yi": mc_wan_yi,
        "market_cap_str": mc_str,
        "total_companies": total_companies,
        "profitable_count": profitable_count,
        "loss_count": loss_count,
        "median_pe": median_pe,
        "median_pb": median_pb,
        "median_gross_margin": median_gross_margin,
        "canonical_segments": canonical_segments,
    }


def format_global_facts_prompt(facts: dict[str, Any]) -> str:
    lines = [
        "【全篇全局量化基准与事实锚点（强制约束，所有章节必须保持高度一致，严禁互相矛盾）】",
    ]
    if facts.get("total_companies"):
        lines.append(f"- 样本公司总数：{facts['total_companies']} 家（成熟盈利：{facts['profitable_count']} 家，早期/亏损/高估值：{facts['loss_count']} 家）")
    if facts.get("market_cap_str") and facts["market_cap_str"] != "暂无汇总数据":
        lines.append(f"- 样本总市值标准基准：{facts['market_cap_str']}（全篇必须以此为准，严禁在不同章节出现 22.14万亿 vs 2.21万亿 的10倍冲突！）")
    if facts.get("median_pe") is not None:
        lines.append(f"- 估值与盈利中枢：成熟标的 PE(TTM) 中位数 {facts['median_pe']} 倍，PB 中位数 {facts.get('median_pb')} 倍，销售毛利率中枢 {facts.get('median_gross_margin')}%")
    if facts.get("canonical_segments"):
        lines.append("- 核心标的产业链环节锁定字典（严禁同一企业在不同章节环节归属不一致）：")
        for comp, seg in list(facts["canonical_segments"].items())[:12]:
            lines.append(f"  * {comp}: {seg}")
    return "\n".join(lines)


class ChapterWriterAgent:
    def __init__(self,*,settings:Settings|None=None,llm:ChapterLLM|None=None,skillhub:WritingSkillHub|None=None)->None:
        self.settings=settings or Settings.from_env(); self.llm=llm or OpenAICompatibleLLM(self.settings); self.skillhub=skillhub or WritingSkillHub()

    async def _plan_chapter_skills(
        self,
        outline_chapter: Any,
        context: dict[str, Any],
        request: ChapterWritingRequest,
    ) -> list[tuple[WritingSkill, str, str]]:
        # Every applicable writing rule is already included by policy. A model
        # planning round cannot improve that union; avoid one paid call per chapter.
        policy_skills = self.skillhub.select(outline_chapter.chapter_id)
        requested, _ = resolve_requested_skills(
            request.selected_skills, self.skillhub.catalog, stage="writing",
        )
        requested = [s for s in requested
                     if s.always or outline_chapter.chapter_id in s.chapters]
        requested_names = {s.name for s in requested}
        merged = merge_selection(
            [], policy_skills, requested_skills=requested, limit=CHAPTER_SKILL_LIMIT,
        )
        return [
            (skill, "用户显式选择；按适用章节加载" if skill.name in requested_names
             else skill.adaptation or "章节大纲特征匹配",
             "user" if skill.name in requested_names else "policy")
            for skill in merged.final
        ]

    async def run(self,request:ChapterWritingRequest,emit:EventEmitter|None=None,save_artifacts:bool=True)->ChapterWritingResult:
        run_id=f"chapters-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
        artifact_dir=self.settings.output_dir/"runs"/run_id if save_artifacts else None
        events:list[dict[str,Any]]=[]
        async def record(event:str,**details:Any)->None:
            item={"timestamp":datetime.now().astimezone().isoformat(),"event":event,"details":details}; events.append(item)
            if emit:
                try: await emit(item)
                except Exception: pass
        await record("chapter_writing_started",source_report_id=request.report.report_id)
        outline=request.outline or DEFAULT_OUTLINE
        allowed_evidence=set(request.report.evidence_index)
        ready_charts={c.chart_id:c for c in (request.charts.charts if request.charts else []) if c.status=="ready"}
        global_facts=extract_global_quantitative_anchor(request.report)
        global_facts_prompt=format_global_facts_prompt(global_facts)
        retriever = DynamicEvidenceRetriever(request)
        concurrency = getattr(self.settings, "max_concurrency", 7)
        semaphore = asyncio.Semaphore(concurrency)
        if artifact_dir:
            (artifact_dir / "chapters").mkdir(parents=True, exist_ok=True)

        _, unavailable_skills = resolve_requested_skills(
            request.selected_skills, self.skillhub.catalog, stage="writing",
        )
        if unavailable_skills:
            await record("skill_skipped", skills=unavailable_skills,
                         reason="写作阶段没有对应规范，分析技能不一定存在写作映射")
        selected_by_chapter: dict[str, list[WritingSkill]] = {}
        skill_reasons: dict[str, str] = {}
        # D-11：跨章共享的越界证据留痕通道（asyncio 单线程事件循环内 append 安全；
        # _audit_chapter 内为同步调用，无 await 打断）。汇入 result.warnings，不触发重写。
        foreign_drops: list[str] = []

        async def _write_chapter(outline_chapter: Any) -> tuple[ChapterDraft, str | None, str | None]:
            async with semaphore:
                context = retriever.retrieve(outline_chapter.chapter_id, outline_chapter)
                context["global_facts"] = global_facts
                context["global_facts_prompt"] = global_facts_prompt
                planned_skills = await self._plan_chapter_skills(outline_chapter, context, request)
                selected_by_chapter[outline_chapter.chapter_id] = [skill for skill, _, _ in planned_skills]
                for skill, reason, route_type in planned_skills:
                    skill_reasons[skill.name] = reason
                    if route_type == "user":
                        await record("skill_requested", chapter_id=outline_chapter.chapter_id, skill=skill.name, reason=reason)
                    elif route_type == "llm":
                        await record("skill_invoked_by_llm", chapter_id=outline_chapter.chapter_id, skill=skill.name, reason=reason)
                    else:
                        await record("skill_routed_by_policy", chapter_id=outline_chapter.chapter_id, skill=skill.name, route_type="fast_skill_router", reason=reason)
                context["skills"] = [{"name": skill.name, "instructions": skill.instructions} for skill, _, _ in planned_skills]
                await record("skill_loaded", chapter_id=outline_chapter.chapter_id,
                             skills=[s.name for s, _, _ in planned_skills],
                             planner="chapter_policy", model_planning_calls=0)
                chapter, fallback_id, warning = await self._generate_audited_chapter(
                    request, outline_chapter, context, ready_charts, global_facts, record, foreign_drops
                )
                if artifact_dir:
                    (artifact_dir / "chapters" / f"{chapter.chapter_id}.json").write_text(
                        chapter.model_dump_json(indent=2) + "\n", encoding="utf-8"
                    )
                return chapter, fallback_id, warning

        chapter_results = await asyncio.gather(*[_write_chapter(c) for c in outline])
        await record("skills_planned", skills={chapter_id: [skill.name for skill in skills] for chapter_id, skills in selected_by_chapter.items()})
        chapters: list[ChapterDraft] = [item[0] for item in chapter_results]
        fallback_ids = [item[1] for item in chapter_results if item[1] is not None]
        warnings = list(request.report.warnings) + [item[2] for item in chapter_results if item[2] is not None] + list(dict.fromkeys(foreign_drops))
        issues=self._audit_package(chapters,allowed_evidence,ready_charts,global_facts)
        issues.extend(item[2] for item in chapter_results if item[2] and item[2].startswith("段落资料缺口："))
        cited={eid for chapter in chapters for section in chapter.sections for para in section.paragraphs for eid in para.evidence_ids}
        coverage=len(cited)/len(allowed_evidence) if allowed_evidence else 0
        if fallback_ids: issues.append(f"{len(fallback_ids)} 章使用确定性兜底稿")
        status="completed" if not fallback_ids and not issues else "partial"
        quality=ChapterQualityReport(passed=not issues,chapter_count=len(chapters),section_count=sum(len(c.sections) for c in chapters),evidence_coverage=min(coverage,1),issues=issues,fallback_chapter_ids=fallback_ids)
        applied=[]
        for skill in self.skillhub.catalog.values():
            chapters_used=[chapter_id for chapter_id,skills in selected_by_chapter.items() if any(s.name == skill.name for s in skills)]
            if chapters_used:
                adaptation = skill_reasons.get(skill.name, skill.adaptation)
                applied.append(AppliedSkill(name=skill.name,description=skill.description,source=skill.source,adaptation=adaptation,chapters=chapters_used))
        result=ChapterWritingResult(run_id=run_id,source_report_id=request.report.report_id,subject=request.report.subject,as_of=request.report.as_of,status=status,outline_version=OUTLINE_VERSION if request.outline is None else "custom-1",model_name=self.settings.llm_model if self.llm.is_available else "deterministic-fallback",applied_skills=applied,chapters=chapters,quality=quality,warnings=warnings+issues+[f"写作阶段没有对应技能：{name}" for name in unavailable_skills],artifact_dir=str(artifact_dir.resolve()) if artifact_dir else None)
        await record("chapter_writing_completed",status=status,chapters=len(chapters),fallbacks=len(fallback_ids))
        if artifact_dir:
            artifact_dir.mkdir(parents=True,exist_ok=True)
            (artifact_dir/"request.json").write_text(request.model_dump_json(indent=2)+"\n",encoding="utf-8")
            (artifact_dir/"input_report.json").write_text(request.report.model_dump_json(indent=2)+"\n",encoding="utf-8")
            (artifact_dir/"input_charts.json").write_text((request.charts.model_dump_json(indent=2) if request.charts else "{}")+"\n",encoding="utf-8")
            (artifact_dir/"chapter_result.json").write_text(result.model_dump_json(indent=2)+"\n",encoding="utf-8")
            (artifact_dir/"events.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in events),encoding="utf-8")
        return result

    async def _generate_audited_chapter(
        self, request: ChapterWritingRequest, outline_chapter: Any,
        context: dict[str, Any], ready_charts: dict[str, Any],
        global_facts: dict[str, Any], record: Callable[..., Awaitable[None]], drop_log: list[str],
    ) -> tuple[ChapterDraft, str | None, str | None]:
        """Shared generation, repair and evidence audit for full and targeted writing."""
        allowed_evidence = set(request.report.evidence_index)
        global_facts_prompt = context["global_facts_prompt"]
        chapter = None
        errors: list[str] = []
        paragraph_warning = None
        if self.llm.is_available:
            for attempt in range(request.options.max_repairs + 1):
                try:
                    payload = {
                        "outline": outline_chapter.model_dump(mode="json"),
                        "subject": request.report.subject,
                        "as_of": request.report.as_of.isoformat(),
                        "audience": request.options.audience,
                        "style": request.options.style,
                        "target_length": request.options.target_length,
                        "instruction": request.options.instruction,
                        "context": context,
                        "global_facts": global_facts_prompt,
                        "previous_errors": errors,
                    }
                    # The model client owns request retries; do not multiply them here.
                    prompt, packing = prepare_chapter_context(payload, SYSTEM_PROMPT)
                    await record("context_budget_checked", chapter_id=outline_chapter.chapter_id,
                                 **packing)
                    raw = await self.llm.generate_json(SYSTEM_PROMPT, prompt)
                    chapter = ChapterDraft.model_validate(raw)
                    chapter.content_audit = []
                    if any(not section.paragraphs for section in chapter.sections):
                        raise ValueError("生成章节含空节")
                    errors = self._audit_chapter(chapter, outline_chapter, allowed_evidence, ready_charts, context, global_facts, drop_log=drop_log)
                    await record("skill_linter_checked", chapter_id=outline_chapter.chapter_id, passed=not errors, issues=errors)
                    await record("chapter_attempt", chapter_id=outline_chapter.chapter_id, attempt=attempt + 1, issues=errors)
                    quarantined = []
                    for section in chapter.sections:
                        card_errors = [issue for issue in errors if issue.startswith(f"{section.section_id} 指标卡「")
                                       and issue.endswith("数值缺少证据绑定")]
                        for issue in card_errors:
                            label = issue.split("「", 1)[1].split("」", 1)[0]
                            section.metric_cards = [card for card in section.metric_cards if card.label != label]
                        table_error = f"{section.section_id} 对比表数值缺少证据绑定"
                        if table_error in errors:
                            section.comparison_table = None
                        removed = card_errors + ([table_error] if table_error in errors else [])
                        if removed:
                            chapter.content_audit.extend({
                                "code": "chapter_component_isolation", "location": section.section_id,
                                "section_id": section.section_id, "claim": issue, "disposition": "isolated",
                            } for issue in removed)
                            quarantined.extend(removed)
                    if quarantined:
                        errors = self._audit_chapter(chapter, outline_chapter, allowed_evidence,
                            ready_charts, context, global_facts, drop_log=drop_log)
                    if not errors:
                        if quarantined:
                            paragraph_warning = f"段落资料缺口：{chapter.chapter_id} {'；'.join(quarantined)}"
                        if attempt < request.options.max_repairs:
                            await self._add_numeric_readout(
                                chapter, outline_chapter, allowed_evidence, ready_charts, context, global_facts, record,
                            )
                        break
                    positions = {p.paragraph_id: (si, pi) for si, section in enumerate(chapter.sections)
                                 for pi, p in enumerate(section.paragraphs)}
                    failures = {pid: [issue for issue in errors if issue.startswith(pid + " ")]
                                for pid in positions}
                    failures = {pid: issues for pid, issues in failures.items() if issues}
                    if failures and all(any(issue in group for group in failures.values()) for issue in errors):
                        unresolved = list(quarantined)
                        remaining_repairs = request.options.max_repairs - attempt
                        for pid, para_issues in failures.items():
                            si, pi = positions[pid]
                            original = chapter.sections[si].paragraphs[pi]
                            repair_payload = {"subject": request.report.subject,
                                "section_id": chapter.sections[si].section_id,
                                "paragraph": original.model_dump(mode="json"), "issues": para_issues,
                                "evidence": context.get("evidence", {})}
                            await record("paragraph_repair_started", chapter_id=chapter.chapter_id,
                                         section_id=chapter.sections[si].section_id, paragraph_id=pid,
                                         issues=para_issues, evidence_ids=original.evidence_ids)
                            repaired = False
                            reason = "repair_disabled"
                            if remaining_repairs > 0:
                                remaining_repairs -= 1
                                try:
                                    reason = "audit_failed"
                                    repair_system = SYSTEM_PROMPT + "\n只返回修复后的单个段落 JSON，保持 paragraph_id。"
                                    prompt, _, _ = serialize_context(repair_payload, system=repair_system)
                                    raw = await self.llm.generate_json(repair_system, prompt)
                                    replacement = ParagraphDraft.model_validate(raw)
                                    if replacement.paragraph_id != pid:
                                        raise ValueError("paragraph_id 不一致")
                                    trial = chapter.model_copy(deep=True)
                                    trial.sections[si].paragraphs[pi] = replacement
                                    trial_issues = self._audit_chapter(trial, outline_chapter, allowed_evidence,
                                        ready_charts, context, global_facts)
                                    if not any(issue.startswith(pid + " ") for issue in trial_issues) and not (set(trial_issues) - set(errors)):
                                        chapter.sections[si].paragraphs[pi] = trial.sections[si].paragraphs[pi]
                                        repaired = True
                                        reason = "passed"
                                except Exception as exc:
                                    reason = type(exc).__name__
                            disposition = "repaired"
                            if not repaired:
                                evidence = context.get("evidence", {})
                                refs = [evidence[rid] for rid in original.evidence_ids if rid in evidence]
                                refs.extend(verified_calculations(context.get("financial_ratios", []), evidence, original.evidence_ids))
                                retained = retain_supported_claims(original.text, lambda clause: not quantity_issues(
                                    clause, refs, universe=list(evidence.values()),
                                    assumption_note=original.assumption_note, kind=original.kind,
                                ))
                                trial = chapter.model_copy(deep=True)
                                if retained and retained != original.text:
                                    trial.sections[si].paragraphs[pi].text = retained
                                    trial_errors = self._audit_chapter(trial, outline_chapter,
                                        allowed_evidence, ready_charts, context, global_facts)
                                    if any(issue.startswith(pid + " ") for issue in trial_errors):
                                        retained = ""
                                else:
                                    retained = ""
                                chapter.sections[si].paragraphs[pi] = original.model_copy(update={
                                    "text": retained, "evidence_ids": original.evidence_ids if retained else [],
                                })
                                disposition = "partially_retained" if retained else "isolated"
                                unresolved.extend(para_issues)
                            chapter.content_audit.append({
                                "code": "chapter_claim_repair", "location": pid,
                                "section_id": chapter.sections[si].section_id,
                                "original": original.text, "claim": "；".join(para_issues),
                                "evidence_ids": original.evidence_ids, "disposition": disposition,
                                "reason": reason,
                            })
                            await record("paragraph_repair_completed", chapter_id=chapter.chapter_id,
                                         paragraph_id=pid, passed=repaired, reason=reason, issues=para_issues)
                        remaining = self._audit_chapter(chapter, outline_chapter, allowed_evidence,
                            ready_charts, context, global_facts, drop_log=drop_log)
                        for section in chapter.sections:
                            section.paragraphs = [para for para in section.paragraphs if para.text.strip()]
                        if remaining:
                            unresolved.extend(remaining)
                        if unresolved:
                            paragraph_warning = f"段落资料缺口：{chapter.chapter_id} {'；'.join(unresolved)}"
                        break
                    chapter = None
                except Exception as exc:
                    errors = [str(exc)[:500] if isinstance(exc, ContextBudgetExceeded) else type(exc).__name__]
                    await record("chapter_attempt_failed", chapter_id=outline_chapter.chapter_id, attempt=attempt + 1, error=errors[0])
                    if isinstance(exc, (ContextBudgetExceeded, httpx.HTTPError, TimeoutError)):
                        break
        fallback_id = None
        warning = paragraph_warning
        if chapter is None:
            chapter = self._fallback_chapter(request, outline_chapter, context, ready_charts, global_facts)
            fallback_id = outline_chapter.chapter_id
            warning = f"{outline_chapter.chapter_id} 使用确定性兜底稿：{'；'.join(errors) if errors else '未配置模型'}"
            await record("chapter_fallback", chapter_id=outline_chapter.chapter_id)
            fb_errors = self._audit_chapter(chapter, outline_chapter, allowed_evidence, ready_charts, context, global_facts, drop_log=drop_log)
            await record("skill_linter_checked", chapter_id=outline_chapter.chapter_id, passed=not fb_errors, issues=fb_errors)
        return chapter, fallback_id, warning

    async def _add_numeric_readout(
        self, chapter, outline, allowed_evidence, charts, context, global_facts, record,
    ) -> None:
        """Use one remaining repair slot to interpret an otherwise valid numeric list."""
        candidate = next(((si, pi) for si, section in enumerate(chapter.sections)
                          for pi, para in enumerate(section.paragraphs) if _lists_numbers(para)), None)
        if candidate is None:
            return
        si, pi = candidate
        section = chapter.sections[si]
        paragraph = section.paragraphs[pi]
        evidence = context.get("evidence") or {}
        refs = {rid: evidence[rid] for rid in paragraph.evidence_ids if rid in evidence}
        if not refs:
            return
        system = (
            "给通过事实核验的投研段落补一到两句简洁解读。只依据所给记录，说明这些数字"
            "支持的比较或业务判断。解释因果必须有直接披露；如果缺证据，指出具体缺少的科目"
            "或材料。保持原有事实，不重复数字，不新增量化断言，不写套话。"
            '只返回 JSON {"interpretation":"要追加到段末的解读"}。'
        )
        try:
            prompt, _, _ = serialize_context({
                "section_title": section.title, "purpose": section.purpose,
                "paragraph": paragraph.text, "evidence": refs,
            }, system=system)
            raw = await self.llm.generate_json(system, prompt)
            value = raw.get("interpretation")
            explanation = value.strip() if isinstance(value, str) else ""
            accepted = False
            if (explanation and len(explanation) <= 160 and explanation not in paragraph.text
                    and not any(unit for _, unit in QUANTITY_RE.findall(explanation))
                    and _READOUT.search(explanation)):
                trial = chapter.model_copy(deep=True)
                paragraph_trial = trial.sections[si].paragraphs[pi]
                separator = "" if paragraph.text.rstrip().endswith(("。", "！", "？", ".", "!", "?")) else "。"
                paragraph_trial.text = paragraph.text.rstrip() + separator + explanation
                if not self._audit_chapter(trial, outline, allowed_evidence, charts, context, global_facts):
                    section.paragraphs[pi] = paragraph_trial
                    accepted = True
        except Exception as exc:
            await record("numeric_readout_skipped", paragraph_id=paragraph.paragraph_id,
                         reason=type(exc).__name__)
            return
        await record("numeric_readout_checked", paragraph_id=paragraph.paragraph_id, accepted=accepted)

    def _audit_chapter(
        self,
        chapter: ChapterDraft,
        outline: Any,
        allowed: set[str],
        charts: dict[str, Any],
        context: dict[str, Any] | None = None,
        global_facts: dict[str, Any] | None = None,
        drop_log: list[str] | None = None,
    ) -> list[str]:
        issues = []
        # D-11 修复：越界证据被过滤时必须留痕。drop_log 是一条**独立于 issues 的软通道**——
        # issues 非空会触发本章重写/兜底（越界引用不应导致整章作废），而 drop_log 汇入
        # result.warnings，使“模型引用了非本章证据”这一事实可观测、可据以评估提示词质量。
        def _note_dropped(where: str, foreign: set[str]) -> None:
            if drop_log is not None and foreign:
                drop_log.append(
                    f"{chapter.chapter_id} {where}引用了非本章/未授权证据 {sorted(foreign)}，已剔除（越界留痕）"
                )

        if chapter.chapter_id != outline.chapter_id:
            issues.append("chapter_id 与大纲不一致")
        if [s.section_id for s in chapter.sections] != [s.section_id for s in outline.sections]:
            issues.append("section_id 或章节顺序与大纲不一致")
        seen_text = set()
        evidence_dict = (context.get("evidence") or {}) if context else {}
        if context is not None and "evidence" in context:
            allowed = allowed.intersection(evidence_dict)

        # Consistency repair: fix 22.14万亿 vs 2.21万亿 scale anomaly in chapter summary
        if global_facts and global_facts.get("market_cap_wan_yi"):
            cw = global_facts["market_cap_wan_yi"]
            cw_str = f"{cw}万亿元"
            cm_str = f"{cw * 10000:.2f}亿元"
            wrong_pattern = r"2\.21\s*万亿(?:元)?" if cw > 10 else r"22\.14\s*万亿(?:元)?"
            chapter.summary = re.sub(wrong_pattern, cw_str, chapter.summary)
            if cw <= 10:
                chapter.summary = re.sub(r"221411(?:\.07)?\s*亿元", cm_str, chapter.summary)

        for section in chapter.sections:
            expected = next((x for x in outline.sections if x.section_id == section.section_id), None)
            if expected:
                section.title = expected.title
                section.purpose = expected.purpose

            # Consistency repair in section key_points
            if global_facts and global_facts.get("market_cap_wan_yi"):
                cw = global_facts["market_cap_wan_yi"]
                cw_str = f"{cw}万亿元"
                cm_str = f"{cw * 10000:.2f}亿元"
                wrong_pattern = r"2\.21\s*万亿(?:元)?" if cw > 10 else r"22\.14\s*万亿(?:元)?"
                section.key_points = [
                    re.sub(r"221411(?:\.07)?\s*亿元", cm_str, re.sub(wrong_pattern, cw_str, kp)) if cw <= 10 else re.sub(wrong_pattern, cw_str, kp)
                    for kp in section.key_points
                ]

            for para in section.paragraphs:
                unknown = set(para.evidence_ids) - allowed
                if unknown:
                    _note_dropped(f"段落 {para.paragraph_id} ", unknown)
                    para.evidence_ids = [e for e in para.evidence_ids if e in allowed]

                # Consistency repair in paragraph text
                if global_facts and global_facts.get("market_cap_wan_yi"):
                    cw = global_facts["market_cap_wan_yi"]
                    cw_str = f"{cw}万亿元"
                    cm_str = f"{cw * 10000:.2f}亿元"
                    wrong_pattern = r"2\.21\s*万亿(?:元)?" if cw > 10 else r"22\.14\s*万亿(?:元)?"
                    para.text = re.sub(wrong_pattern, cw_str, para.text)
                    if cw <= 10:
                        para.text = re.sub(r"221411(?:\.07)?\s*亿元", cm_str, para.text)

                # Entity chain segment consistency repair
                if "中国卫星等上游" in para.text:
                    para.text = para.text.replace("中国卫星等上游", "中国卫星等中游总装")
                if "中国卫星、铖昌科技等上游" in para.text:
                    para.text = para.text.replace("中国卫星、铖昌科技等上游", "铖昌科技等上游核心部件与中国卫星等中游总装")
                if "铖昌科技、中国卫星等上游核心部件" in para.text:
                    para.text = para.text.replace("铖昌科技、中国卫星等上游核心部件", "铖昌科技等上游核心部件与中国卫星等中游总装")

                # Filter out pure years (19xx, 20xx) and small list ordinals (1-10)
                nums = extract_numbers(para.text)
                substantive_nums = [n for n in nums if not YEAR_OR_ORDINAL_RE.match(n.strip())]

                # R4（V8 最终方案 §7.2）：**假设说明不能为已发生的事实数字提供依据**。
                # 旧实现的 `or para.assumption_note` 让模型自填任意一句"综合测算"
                # 就能豁免缺证据检查。现在只有 kind 维度（scenario/risk/methodology/
                # transition）保留窄通道；assumption_note 一律不构成豁免。
                if substantive_nums and not para.evidence_ids and not (
                    para.kind in ("scenario", "risk", "methodology", "transition")
                    and bool(re.search(r"假设|情景|如果|若|设定|敏感性", para.text))
                ):
                    matched_eids: list[str] = []
                    for eid, rec in evidence_dict.items():
                        if eid not in allowed:
                            continue
                        val_str = str(rec.get("value", "")).strip()
                        metric_str = str(rec.get("metric", "")).strip()
                        entity_str = str(rec.get("entity", "")).strip()
                        if val_str and len(val_str) >= 2 and val_str in para.text:
                            matched_eids.append(eid)
                        elif metric_str and len(metric_str) >= 2 and metric_str in para.text:
                            if entity_str and entity_str in para.text:
                                matched_eids.append(eid)
                    if matched_eids:
                        para.evidence_ids = list(dict.fromkeys(matched_eids))

                # R4：第二道检查与第一道同口径；assumption_note 不再是豁免项。
                if substantive_nums and not para.evidence_ids and not (
                    para.kind in ("scenario", "risk", "methodology", "transition")
                    and bool(re.search(r"假设|情景|如果|若|设定|敏感性", para.text))
                ):
                    issues.append(f"{para.paragraph_id} 数字缺少证据支撑（假设说明不能替代证据）")

                semantic_refs = [evidence_dict[eid] for eid in para.evidence_ids if eid in evidence_dict]
                semantic_refs.extend(verified_calculations((context or {}).get("financial_ratios", []), evidence_dict, para.evidence_ids))
                for sentence in re.split(r"[。；;\n]", para.text):
                    proposition = re.sub(r"“[^”]*”|《[^》]*》", "", sentence)
                    if not re.search(r"由于.+[，,].+|(?:导致|驱动|推动|带动|造成)(?!因素)", proposition):
                        continue
                    if re.search(r"资料缺|数据缺|证据不足|假设|情景", sentence):
                        continue
                    claim = re.sub(r"\s+", "", sentence).strip()
                    supporting_texts = [re.sub(r"\s+", "", str(ref.get("value", "")))
                                        for ref in semantic_refs if isinstance(ref, dict)]
                    if claim and not any(claim in text for text in supporting_texts):
                        issues.append(f"{para.paragraph_id} 因果判断缺少独立依据")
                semantic_issues = quantity_issues(para.text,
                    semantic_refs,
                    universe=list(evidence_dict.values()), assumption_note=para.assumption_note,
                    kind=para.kind, location=para.paragraph_id)
                issues.extend(f"{para.paragraph_id} 数值语义未通过：{item['claim']}（需同实体、指标和期间证据）" for item in semantic_issues)
                normalized = "".join(para.text.split())
                if normalized in seen_text:
                    issues.append(f"{para.paragraph_id} 与其他段落重复")
                seen_text.add(normalized)
                if len(para.text) > 1000:
                    issues.append(f"{para.paragraph_id} 段落过长")

            # Prune charts that do not belong to this chapter
            valid_cids = []
            for cid in section.chart_ids:
                if cid in charts:
                    chart_obj = charts[cid]
                    rec_ch = getattr(chart_obj, "recommended_chapter_id", None) or (
                        chart_obj.get("recommended_chapter_id") if isinstance(chart_obj, dict) else None
                    )
                    if not rec_ch or rec_ch == outline.chapter_id:
                        valid_cids.append(cid)
            section.chart_ids = valid_cids

            # Ground structured UI components & fix metric cards
            if section.metric_cards:
                for mc in section.metric_cards:
                    if getattr(mc, "evidence_ids", None):
                        _note_dropped("指标卡 ", set(mc.evidence_ids) - allowed)
                        mc.evidence_ids = [e for e in mc.evidence_ids if e in allowed]
                    # R4（V8 最终方案 §7.1）：指标卡是证据承载对象——
                    # 承载数值却无任何合法证据绑定，必须计入审计问题，
                    # 不能因为"看起来结构化"就默认可信。
                    mc_value = str(getattr(mc, "value", "") or "")
                    if mc_value and extract_numbers(mc_value) and not getattr(mc, "evidence_ids", None):
                        issues.append(
                            f"{section.section_id} 指标卡「{getattr(mc, 'label', '')}」数值缺少证据绑定"
                        )
                    if global_facts and global_facts.get("market_cap_wan_yi") and "市值" in mc.label:
                        cw = global_facts["market_cap_wan_yi"]
                        if "22.14" in str(mc.value):
                            mc.value = f"{cw}万亿"
                        elif "221411" in str(mc.value):
                            mc.value = f"{cw * 10000:.2f}"
            if section.comparison_table and getattr(section.comparison_table, "evidence_ids", None):
                _note_dropped("对比表 ", set(section.comparison_table.evidence_ids) - allowed)
                section.comparison_table.evidence_ids = [e for e in section.comparison_table.evidence_ids if e in allowed]
            # R4：对比表同样承载数值——行内含实质数字却无证据绑定，记为审计问题
            if section.comparison_table is not None:
                table_rows = getattr(section.comparison_table, "rows", None) or []
                table_eids = getattr(section.comparison_table, "evidence_ids", None) or []
                row_nums: list[str] = []
                for row in table_rows:
                    cells = row if isinstance(row, (list, tuple)) else (
                        list(row.values()) if isinstance(row, dict) else [row]
                    )
                    for cell in cells:
                        row_nums.extend(
                            n for n in extract_numbers(str(cell))
                            if not YEAR_OR_ORDINAL_RE.match(n.strip())
                        )
                if row_nums and not table_eids:
                    issues.append(
                        f"{section.section_id} 对比表数值缺少证据绑定"
                    )
            if section.callouts:
                for co in section.callouts:
                    if getattr(co, "evidence_ids", None):
                        _note_dropped("callout ", set(co.evidence_ids) - allowed)
                        co.evidence_ids = [e for e in co.evidence_ids if e in allowed]

        # Auto-attach any unattached charts designated for this chapter
        attached_cids = {cid for s in chapter.sections for cid in s.chart_ids}
        chapter_charts = [
            cid for cid, c in charts.items()
            if getattr(c, "recommended_chapter_id", None) == outline.chapter_id
        ]
        for cid in chapter_charts:
            if cid not in attached_cids:
                c_eids = set(getattr(charts[cid], "evidence_ids", []))
                best_sec = None
                best_overlap = -1
                for s in chapter.sections:
                    sec_eids = {e for p in s.paragraphs for e in p.evidence_ids}
                    overlap = len(c_eids & sec_eids)
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_sec = s
                if best_sec is not None:
                    best_sec.chart_ids.append(cid)
                    attached_cids.add(cid)

        # Enforce and auto-repair [CHART-xx] placeholders in paragraph text
        for section in chapter.sections:
            for cid in section.chart_ids:
                tag = f"[{cid}]"
                if not any(tag in p.text for p in section.paragraphs):
                    target_p = next((p for p in section.paragraphs if p.kind == "chart_readout"), None)
                    if not target_p and section.paragraphs:
                        target_p = section.paragraphs[0]
                    if target_p:
                        target_p.text = f"如图 {tag} 所示，{target_p.text}"

        chapter.evidence_ids = list(dict.fromkeys(e for s in chapter.sections for p in s.paragraphs for e in p.evidence_ids))
        chapter.chart_ids = list(dict.fromkeys(c for s in chapter.sections for c in s.chart_ids))
        return list(dict.fromkeys(issues))

    def _fallback_chapter(
        self,
        request: ChapterWritingRequest,
        outline: Any,
        context: dict[str, Any],
        charts: dict[str, Any],
        global_facts: dict[str, Any] | None = None,
    ) -> ChapterDraft:
        evidence_by_id = context["evidence"]
        evidence_ids = list(evidence_by_id)
        universe = list(evidence_by_id.values())
        insights = context["insights"]
        chapters = []
        ch_charts = [
            c.chart_id
            for c in charts.values()
            if getattr(c, "recommended_chapter_id", None) == outline.chapter_id
        ]
        for index, section in enumerate(outline.sections):
            possible = [cid for i, cid in enumerate(ch_charts) if i % max(1, len(outline.sections)) == index][:1]
            chart_prefix = f"如图 [{possible[0]}] 所示，" if possible else ""
            chosen: list[str] = []
            base = ""
            if index < len(insights):
                insight = insights[index]
                claim = str(insight.get("conclusion") or insight.get("title") or "").strip()
                ids = insight.get("evidence_record_ids") or []
                if claim and ids and all(rid in evidence_by_id for rid in ids):
                    refs = [evidence_by_id[rid] for rid in ids]
                    if not quantity_issues(claim, refs, universe=universe):
                        base, chosen = claim, list(dict.fromkeys(ids))
            if not chosen:
                for eid in evidence_ids[index::3]:
                    item = evidence_by_id[eid]
                    period = measurement_period(item)
                    entity, unit, value = item.get("entity"), item.get("unit"), item.get("value")
                    if isinstance(value, str) and item.get("domain") in {"news", "reports", "events", "industry_chain"}:
                        excerpt = " ".join(value.split())
                        if excerpt and len(excerpt) <= 240:
                            claim = f"来源记载：{excerpt.rstrip('。')}。"
                            if not quantity_issues(claim, [item], universe=universe):
                                base, chosen = claim, [eid]
                                break
                    metric = metric_family(item.get("metric", ""))
                    label = next((term for term, key in CLAIM_METRICS.items()
                                  if key == metric and re.search(r"[\u4e00-\u9fff]", term)), None)
                    if (not period or not entity or not unit or not label or type(value) not in (int, float)
                            or item.get("scope", "consolidated") != "consolidated"
                            or item.get("currency", "CNY") != "CNY"
                            or any("conflict" in issue for issue in item.get("issues", []))):
                        continue
                    claim = f"{entity}截至{period[1].isoformat()}的{label}为{value}{unit}。"
                    if not quantity_issues(claim, [item], universe=universe):
                        base, chosen = claim + f"该数字是单期观察，判断{label}变化仍需核对同口径的前期数据。", [eid]
                        break
            text = chart_prefix + (base or f"“{section.title}”缺少可用于判断的直接证据。")
            chapters.append(
                SectionDraft(
                    section_id=section.section_id,
                    title=section.title,
                    purpose=section.purpose,
                    key_points=[],
                    paragraphs=[
                        ParagraphDraft(
                            paragraph_id=f"P-{outline.chapter_id[-2:]}-{index+1:02d}-01",
                            kind="chart_readout" if possible else "analysis",
                            text=text,
                            evidence_ids=chosen,
                        )
                    ],
                    chart_ids=possible,
                    uncertainties=[] if chosen else ["缺少与本节直接相关的可验证资料"],
                )
            )
        all_ids = list(dict.fromkeys(e for s in chapters for p in s.paragraphs for e in p.evidence_ids))
        chart_ids = list(dict.fromkeys(c for s in chapters for c in s.chart_ids))
        return ChapterDraft(
            chapter_id=outline.chapter_id,
            title=outline.title,
            summary=f"本章围绕{outline.title}整理现有证据，并明确资料边界。",
            sections=chapters,
            evidence_ids=all_ids,
            chart_ids=chart_ids,
            used_fallback=True,
        )

    def _audit_package(
        self,
        chapters: list[ChapterDraft],
        allowed: set[str],
        charts: dict[str, Any],
        global_facts: dict[str, Any] | None = None,
    ) -> list[str]:
        issues = []
        if len(chapters) != 7:
            issues.append("报告不是7章")
        if sum(len(x.sections) for x in chapters) != 21:
            issues.append("报告不是21节")
        if len({x.chapter_id for x in chapters}) != len(chapters):
            issues.append("章节ID重复")

        # Single-Placement Lock: verify and enforce each chart appears in AT MOST ONE section across the entire report
        seen_cids: dict[str, tuple[str, str]] = {}
        for chapter in chapters:
            for section in chapter.sections:
                for para in section.paragraphs:
                    if set(para.evidence_ids) - allowed:
                        issues.append("存在未知证据引用")

                clean_cids = []
                for cid in section.chart_ids:
                    if cid not in charts:
                        issues.append(f"{section.section_id} 存在未就绪图表引用 {cid}")
                        continue
                    chart_obj = charts[cid]
                    rec_ch = getattr(chart_obj, "recommended_chapter_id", None) or (
                        chart_obj.get("recommended_chapter_id") if isinstance(chart_obj, dict) else None
                    )
                    # If chart was explicitly recommended for another chapter, remove from here
                    if rec_ch and rec_ch != chapter.chapter_id:
                        continue
                    # If chart was already placed elsewhere, enforce single placement
                    if cid in seen_cids:
                        continue
                    seen_cids[cid] = (chapter.chapter_id, section.section_id)
                    clean_cids.append(cid)
                section.chart_ids = clean_cids
            chapter.chart_ids = list(dict.fromkeys(c for s in chapter.sections for c in s.chart_ids))

        # Ensure all ready charts designated for a chapter are placed in that chapter
        for cid, chart_obj in charts.items():
            rec_ch = getattr(chart_obj, "recommended_chapter_id", None) or (
                chart_obj.get("recommended_chapter_id") if isinstance(chart_obj, dict) else None
            )
            if rec_ch and cid not in seen_cids:
                target_ch = next((c for c in chapters if c.chapter_id == rec_ch), None)
                if target_ch and target_ch.sections:
                    target_sec = target_ch.sections[0]
                    target_sec.chart_ids.append(cid)
                    target_ch.chart_ids = list(dict.fromkeys(c for s in target_ch.sections for c in s.chart_ids))
                    seen_cids[cid] = (target_ch.chapter_id, target_sec.section_id)
                    tag = f"[{cid}]"
                    if not any(tag in p.text for p in target_sec.paragraphs):
                        target_p = next((p for p in target_sec.paragraphs if p.kind == "chart_readout"), target_sec.paragraphs[0])
                        target_p.text = f"如图 {tag} 所示，{target_p.text}"

        # Cross-chapter market cap consistency audit
        mc_values = []
        for ch in chapters:
            for sec in ch.sections:
                for p in sec.paragraphs:
                    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*万亿", p.text):
                        val = float(m.group(1))
                        if val > 0.05:
                            mc_values.append((ch.chapter_id, val))
        if mc_values:
            vals = [v for _, v in mc_values]
            if max(vals) > min(vals) * 3.0:
                issues.append(f"跨章节总市值存在量级冲突：最高 {max(vals)} 万亿，最低 {min(vals)} 万亿")

        return list(dict.fromkeys(issues))
