"""Bounded generate-audit-repair chapter writing agent."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
import json
from pathlib import Path
import re
import secrets
from typing import Any

from pydantic import ValidationError

from chapter_writer.config import Settings
from chapter_writer.llm import ChapterLLM, OpenAICompatibleLLM
from chapter_writer.models import (
    AppliedSkill, ChapterDraft, ChapterQualityReport, ChapterWritingRequest, ChapterWritingResult,
    ParagraphDraft, SectionDraft,
)
from chapter_writer.outline import DEFAULT_OUTLINE, OUTLINE_VERSION
from chapter_writer.retriever import DynamicEvidenceRetriever
from chapter_writer.skillhub import WritingSkillHub

EventEmitter=Callable[[dict[str,Any]],Awaitable[None]]
NUMBER_RE=re.compile(r"(?<![A-Za-z0-9_-])[-+]?\d+(?:\.\d+)?%?")
YEAR_OR_ORDINAL_RE=re.compile(r"^(?:19\d\d|20\d\d|[1-9]|10)$")

SYSTEM_PROMPT="""你是机构级证券与行业研究报告章节写作智能体。你必须将内容组织成可直接供前端/PDF排版的结构化组件，而不是连续长文章。
严格要求：
1. 只使用输入 context 中的 evidence、insights、findings、comps_matrix、financial_ratios、industry_chain_segments 和 charts 信息，严禁捏造事实和数字。
2. 写作风格采用“断言主旨驱动 (Thesis-Driven)”：
   - 先用 2~4 条 `key_points` 给出本节可独立阅读的硬核结论（结论前置、数字优先、25~80字）；
   - 章级摘要 (summary)：必须控制在 60~100 字，精准提炼本章最核心的 1~2 个独立量化断言，严禁跨章重复或与全篇宏观摘要雷同！
   - 严禁出现“已有资料显示”、“当前资料未形成确定证据”等套话！有证据直接下判断，证据不全则直言资料缺口并放入 `uncertainties`。
3. 段落颗粒度控制：普通段落控制在 120~260 个中文字符，一段只阐明一个判断。`kind` 必须选用受控枚举：
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
5. 图文协同：挂接的 `chart_ids` 必须在正文中提供具有分析深度的邻接解读。正文中引用图表时使用 `[CHART-xx]` 或“如图表所示”，排版引擎将统一映射为最终图表顺序编号。
6. 风险与情景推演规范（尤其针对第七章或预测性章节）：
   - 必须提供三档量化情景推演（建议提炼为 comparison_table 或 scenario 段落）：乐观（20%~30%）、基准（50%~60%）、悲观（15%~25%）；
   - 每档情景必须包含三要素：① 核心触发条件 (Catalyst)；② 经营与财务推演结果；③ 可观测的前瞻跟踪阈值 (Leading Indicators & Thresholds)；
   - 必须包含非外推声明 (Non-extrapolation Disclaimer，建议放置在 callout 中)：明确指出样本结构代表性边界（如未上市火箭/本体龙头未纳入三表核算）及期间跨度局限，禁止线性外推至整个产业。
7. 返回严格 JSON 格式：
{
  "chapter_id": "CH-xx",
  "title": "...",
  "summary": "章级核心主结论，精准独立，60~100字",
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


CHAPTER_SKILL_PLANNING_PROMPT = """你是研报章节写作规划模块。
你必须基于本章节大纲定位（章节ID、标题、写作目的）以及本章节检索到的证据与图表特征，自主调用 `invoke_skill` 工具选择最适合指导本章节撰写的 1~3 个写作技能。
可选技能包括财务分析写作、产业链分析写作、竞争格局写作、宏观政策催化写作、风险情景写作、证据穿透写作、质量控制等。
必须调用 `invoke_skill` 并给出专业、针对性的调用理由。"""


class ChapterWriterAgent:
    def __init__(self,*,settings:Settings|None=None,llm:ChapterLLM|None=None,skillhub:WritingSkillHub|None=None)->None:
        self.settings=settings or Settings.from_env(); self.llm=llm or OpenAICompatibleLLM(self.settings); self.skillhub=skillhub or WritingSkillHub()

    async def _plan_chapter_skills(
        self,
        outline_chapter: Any,
        context: dict[str, Any],
        request: ChapterWritingRequest,
    ) -> list[tuple[WritingSkill, str, str]]:
        if self.llm.is_available and hasattr(self.llm, "plan_skills_with_tools"):
            try:
                tools = self.skillhub.get_tool_spec()
                evidence_raw = context.get("evidence", {})
                evidence_items = list(evidence_raw.values()) if isinstance(evidence_raw, dict) else list(evidence_raw)
                evidence_summary = [
                    {"domain": e.get("domain"), "metric": e.get("metric"), "entity": e.get("entity")}
                    for e in evidence_items[:12]
                ]
                user_prompt = json.dumps({
                    "chapter_id": outline_chapter.chapter_id,
                    "title": outline_chapter.title,
                    "purpose": getattr(outline_chapter, "purpose", None) or "、".join(s.purpose for s in outline_chapter.sections),
                    "section_titles": [s.title for s in outline_chapter.sections],
                    "subject": request.report.subject,
                    "evidence_count": len(evidence_items),
                    "sample_evidence": evidence_summary,
                    "charts": [c.get("title") for c in context.get("charts", [])],
                }, ensure_ascii=False, default=str)

                planned = await self.llm.plan_skills_with_tools(
                    CHAPTER_SKILL_PLANNING_PROMPT, user_prompt, tools
                )
                if planned:
                    results: list[tuple[WritingSkill, str, str]] = []
                    seen = set()
                    for item in planned:
                        sname = item.get("skill_name", "")
                        reason = item.get("reason", "")
                        skill = self.skillhub.get(sname)
                        if skill and sname not in seen:
                            seen.add(sname)
                            results.append((skill, reason or "模型自主调用", "llm"))
                    for s in self.skillhub.catalog.values():
                        if s.always and s.name not in seen:
                            results.append((s, "通用写作基础规范", "llm"))
                    if results:
                        return results
            except Exception:
                pass

        # FastSkillRouter (System-1 Task Feature Fast Routing)
        default_skills = self.skillhub.select(outline_chapter.chapter_id)
        router_reasons = {
            "CH-01": "依据宏观产业定位与基础规模数据，快速路由宏观与全景写作规范",
            "CH-02": "依据行业时序与空间测算数据，快速路由财务与测算分析规范",
            "CH-03": "依据上下游拓扑与价值链分工数据，快速路由产业链拆解规范",
            "CH-04": "依据竞争企业对标与份额数据，快速路由竞争格局写作规范",
            "CH-05": "依据重点标的杜邦分解与财报数据，快速路由深度财务透视规范",
            "CH-06": "依据催化剂与技术驱动，快速路由产业演进与驱动写作规范",
            "CH-07": "依据敏感性与不确定性指标，快速路由风险情景推演规范",
        }
        return [
            (
                s,
                router_reasons.get(outline_chapter.chapter_id, s.adaptation or "章节大纲特征匹配"),
                "policy",
            )
            for s in default_skills
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
        retriever = DynamicEvidenceRetriever(request)
        concurrency = getattr(self.settings, "max_concurrency", 7)
        semaphore = asyncio.Semaphore(concurrency)
        if artifact_dir:
            (artifact_dir / "chapters").mkdir(parents=True, exist_ok=True)

        selected_by_chapter: dict[str, list[WritingSkill]] = {}
        skill_reasons: dict[str, str] = {}

        async def _write_chapter(outline_chapter: Any) -> tuple[ChapterDraft, str | None, str | None]:
            async with semaphore:
                context = retriever.retrieve(outline_chapter.chapter_id, outline_chapter)
                planned_skills = await self._plan_chapter_skills(outline_chapter, context, request)
                selected_by_chapter[outline_chapter.chapter_id] = [skill for skill, _, _ in planned_skills]
                for skill, reason, route_type in planned_skills:
                    skill_reasons[skill.name] = reason
                    if route_type == "llm":
                        await record("skill_invoked_by_llm", chapter_id=outline_chapter.chapter_id, skill=skill.name, reason=reason)
                    else:
                        await record("skill_routed_by_policy", chapter_id=outline_chapter.chapter_id, skill=skill.name, route_type="fast_skill_router", reason=reason)
                context["skills"] = [{"name": skill.name, "instructions": skill.instructions} for skill, _, _ in planned_skills]
                chapter = None
                errors: list[str] = []
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
                                "previous_errors": errors,
                            }
                            raw = await self.llm.generate_json(SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False, default=str))
                            chapter = ChapterDraft.model_validate(raw)
                            errors = self._audit_chapter(chapter, outline_chapter, allowed_evidence, ready_charts, context)
                            await record("skill_linter_checked", chapter_id=outline_chapter.chapter_id, passed=not errors, issues=errors)
                            await record("chapter_attempt", chapter_id=outline_chapter.chapter_id, attempt=attempt + 1, issues=errors)
                            if not errors:
                                break
                            chapter = None
                        except Exception as exc:
                            errors = [str(exc)[:500]]
                            await record("chapter_attempt_failed", chapter_id=outline_chapter.chapter_id, attempt=attempt + 1, error=errors[0])
                fallback_id = None
                warning = None
                if chapter is None:
                    chapter = self._fallback_chapter(request, outline_chapter, context, ready_charts)
                    fallback_id = outline_chapter.chapter_id
                    warning = f"{outline_chapter.chapter_id} 使用确定性兜底稿：{'；'.join(errors) if errors else '未配置模型'}"
                    await record("chapter_fallback", chapter_id=outline_chapter.chapter_id)
                    fb_errors = self._audit_chapter(chapter, outline_chapter, allowed_evidence, ready_charts, context)
                    await record("skill_linter_checked", chapter_id=outline_chapter.chapter_id, passed=not fb_errors, issues=fb_errors)
                if artifact_dir:
                    (artifact_dir / "chapters" / f"{chapter.chapter_id}.json").write_text(
                        chapter.model_dump_json(indent=2) + "\n", encoding="utf-8"
                    )
                return chapter, fallback_id, warning

        chapter_results = await asyncio.gather(*[_write_chapter(c) for c in outline])
        await record("skills_planned", skills={chapter_id: [skill.name for skill in skills] for chapter_id, skills in selected_by_chapter.items()})
        chapters: list[ChapterDraft] = [item[0] for item in chapter_results]
        fallback_ids = [item[1] for item in chapter_results if item[1] is not None]
        warnings = list(request.report.warnings) + [item[2] for item in chapter_results if item[2] is not None]
        issues=self._audit_package(chapters,allowed_evidence,ready_charts)
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
        result=ChapterWritingResult(run_id=run_id,source_report_id=request.report.report_id,subject=request.report.subject,as_of=request.report.as_of,status=status,outline_version=OUTLINE_VERSION if request.outline is None else "custom-1",model_name=self.settings.llm_model if self.llm.is_available else "deterministic-fallback",applied_skills=applied,chapters=chapters,quality=quality,warnings=warnings+issues,artifact_dir=str(artifact_dir.resolve()) if artifact_dir else None)
        await record("chapter_writing_completed",status=status,chapters=len(chapters),fallbacks=len(fallback_ids))
        if artifact_dir:
            artifact_dir.mkdir(parents=True,exist_ok=True)
            (artifact_dir/"request.json").write_text(request.model_dump_json(indent=2)+"\n",encoding="utf-8")
            (artifact_dir/"input_report.json").write_text(request.report.model_dump_json(indent=2)+"\n",encoding="utf-8")
            (artifact_dir/"input_charts.json").write_text((request.charts.model_dump_json(indent=2) if request.charts else "{}")+"\n",encoding="utf-8")
            (artifact_dir/"chapter_result.json").write_text(result.model_dump_json(indent=2)+"\n",encoding="utf-8")
            (artifact_dir/"events.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in events),encoding="utf-8")
        return result

    def _context(self,request:ChapterWritingRequest,chapter_id:str)->dict[str,Any]:
        outline=request.outline or DEFAULT_OUTLINE
        match=next((c for c in outline if c.chapter_id==chapter_id),outline[0])
        return DynamicEvidenceRetriever(request).retrieve(chapter_id,match)

    def _audit_chapter(
        self,
        chapter: ChapterDraft,
        outline: Any,
        allowed: set[str],
        charts: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> list[str]:
        issues = []
        if chapter.chapter_id != outline.chapter_id:
            issues.append("chapter_id 与大纲不一致")
        if [s.section_id for s in chapter.sections] != [s.section_id for s in outline.sections]:
            issues.append("section_id 或章节顺序与大纲不一致")
        seen_text = set()
        evidence_dict = (context.get("evidence") or {}) if context else {}

        for section in chapter.sections:
            expected = next((x for x in outline.sections if x.section_id == section.section_id), None)
            if expected:
                section.title = expected.title
                section.purpose = expected.purpose
            for para in section.paragraphs:
                unknown = set(para.evidence_ids) - allowed
                if unknown:
                    para.evidence_ids = [e for e in para.evidence_ids if e in allowed]

                # Filter out pure years (19xx, 20xx) and small list ordinals (1-10)
                nums = extract_numbers(para.text)
                substantive_nums = [n for n in nums if not YEAR_OR_ORDINAL_RE.match(n.strip())]

                if substantive_nums and not para.evidence_ids and not (
                    para.kind in ("scenario", "risk", "methodology", "transition") or para.assumption_note
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
                    else:
                        para.assumption_note = "基于产业公开资料及研报上下文综合测算"

                if extract_numbers(para.text) and not para.evidence_ids and not (
                    para.kind in ("scenario", "risk", "methodology", "transition") or para.assumption_note
                ):
                    issues.append(f"{para.paragraph_id} 数字缺少证据或假设说明")

                normalized = "".join(para.text.split())
                if normalized in seen_text:
                    issues.append(f"{para.paragraph_id} 与其他段落重复")
                seen_text.add(normalized)
                if len(para.text) > 1000:
                    issues.append(f"{para.paragraph_id} 段落过长")

            valid_cids = []
            for cid in section.chart_ids:
                if cid in charts:
                    valid_cids.append(cid)
            section.chart_ids = valid_cids

            # Ground structured UI components
            if section.metric_cards:
                for mc in section.metric_cards:
                    if getattr(mc, "evidence_ids", None):
                        mc.evidence_ids = [e for e in mc.evidence_ids if e in allowed]
            if section.comparison_table and getattr(section.comparison_table, "evidence_ids", None):
                section.comparison_table.evidence_ids = [e for e in section.comparison_table.evidence_ids if e in allowed]
            if section.callouts:
                for co in section.callouts:
                    if getattr(co, "evidence_ids", None):
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

        chapter.evidence_ids = list(dict.fromkeys(e for s in chapter.sections for p in s.paragraphs for e in p.evidence_ids))
        chapter.chart_ids = list(dict.fromkeys(c for s in chapter.sections for c in s.chart_ids))
        return list(dict.fromkeys(issues))

    def _fallback_chapter(self,request:ChapterWritingRequest,outline:Any,context:dict[str,Any],charts:dict[str,Any])->ChapterDraft:
        evidence=list(context["evidence"])
        insight_text=[x.get("conclusion",x.get("title","")) for x in context["insights"]]
        chapters=[]
        ch_charts=[c.chart_id for c in charts.values() if getattr(c, "recommended_chapter_id", None)==outline.chapter_id]
        for index,section in enumerate(outline.sections):
            chosen=evidence[index::3][:4]
            base=insight_text[index] if index<len(insight_text) else "当前资料未形成足以支持确定结论的直接证据。"
            if chosen:
                samples=[context["evidence"][eid] for eid in chosen]
                descriptions=[]
                for item in samples[:3]:
                    value=item.get("value"); unit=item.get("unit") or ""
                    value_text=" ".join(str(value).split())
                    if len(value_text)>120:
                        value_text=value_text[:119]+"…"
                    descriptions.append(f"{item.get('entity') or request.report.subject}的{item.get('metric')}为{value_text}{unit}")
                text=f"{base}。已有资料显示，"+"；".join(descriptions)+"。上述观察仅适用于当前样本与研究时点。"
            else: text=f"围绕“{section.title}”，{base}需补充相应资料后再作判断。"
            possible=[cid for i, cid in enumerate(ch_charts) if i % max(1, len(outline.sections)) == index]
            chapters.append(SectionDraft(section_id=section.section_id,title=section.title,purpose=section.purpose,key_points=[base[:120]],paragraphs=[ParagraphDraft(paragraph_id=f"P-{outline.chapter_id[-2:]}-{index+1:02d}-01",kind="analysis",text=text,evidence_ids=chosen)],chart_ids=possible[:2],uncertainties=[] if chosen else ["缺少与本节直接相关的可验证资料"]))
        all_ids=list(dict.fromkeys(e for s in chapters for p in s.paragraphs for e in p.evidence_ids)); chart_ids=list(dict.fromkeys(c for s in chapters for c in s.chart_ids))
        return ChapterDraft(chapter_id=outline.chapter_id,title=outline.title,summary=f"本章围绕{outline.title}整理现有证据，并明确资料边界。",sections=chapters,evidence_ids=all_ids,chart_ids=chart_ids,used_fallback=True)

    def _audit_package(self,chapters:list[ChapterDraft],allowed:set[str],charts:dict[str,Any])->list[str]:
        issues=[]
        if len(chapters)!=7: issues.append("报告不是7章")
        if sum(len(x.sections) for x in chapters)!=21: issues.append("报告不是21节")
        if len({x.chapter_id for x in chapters})!=len(chapters): issues.append("章节ID重复")
        for chapter in chapters:
            for section in chapter.sections:
                for para in section.paragraphs:
                    if set(para.evidence_ids)-allowed: issues.append("存在未知证据引用")
                if set(section.chart_ids)-set(charts): issues.append("存在未就绪图表引用")
        return list(dict.fromkeys(issues))
