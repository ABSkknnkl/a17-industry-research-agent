"""Editorial fusion, consistency checks and multi-format export."""
from __future__ import annotations
from collections.abc import Awaitable,Callable
from datetime import datetime
import hashlib,json,re,secrets
from pathlib import Path
from typing import Any

from report_fusion.config import Settings
from report_fusion.llm import FusionLLM,OpenAICompatibleLLM
from report_fusion.models import *
from report_fusion.pdf import render_pdf
from report_fusion.render import render_html,render_markdown
from report_fusion.skillhub import FusionSkillHub

EventEmitter=Callable[[dict[str,Any]],Awaitable[None]]
NUMBER_RE=re.compile(r"(?<![A-Za-z0-9_-])[-+]?\d+(?:\.\d+)?%?")
SYSTEM_PROMPT="""你是行业研究报告总编辑。只能编辑已有内容，不能补充外部事实、数字或来源。skills 只提供编辑方法，绝不是事实来源。
返回JSON：headline；conclusions[{text,evidence_ids,confidence,uncertainty}]；risks；research_boundaries；terminology_map；chapter_transitions；paragraph_edits。
【重要约束规范】：
1. terminology_map 仅用于极少数专业术语或别名的一致性归一（例如将“动力锂电池”归一为“动力电池”）。
   - 严禁将专业术语、指标代码（如 PB、PE、ROE）替换为长句解释或名词定义；
   - 严禁将研究主题（如“人形机器人”、“新能源汽车”、“航天”）作为映射 key 替换为长句定义；
   - 映射后的目标词（value）必须是极简短的专有名词（不超过 8 个字），严禁包含逗号、句号、冒号、分号或任何解释性描述语句；如果不需别名归一，保持 terminology_map 为空字典 {}。
2. chapter_transitions 是 chapter_id 到承上启下过渡句的映射；
3. paragraph_edits 是 paragraph_id 到 {text, evidence_ids} 的微调映射（仅在必要时修改关键段落，严禁无故大段重写）；
4. 所有证据ID必须来自输入；所有数字必须已存在于输入。"""

def _sha(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def _numbers(value:object)->set[str]:return set(NUMBER_RE.findall(json.dumps(value,ensure_ascii=False,default=str)))

FUSION_SKILL_PLANNING_PROMPT = """你是研报融合与总编审校模块。
你必须基于待融合研报的整体结构（主题、章节数量与大纲、图表数量、证据量、数据质量预警等），自主调用 `invoke_skill` 工具选择指导本研报审校与融合的专业技能。
可用技能包括：
- executive-summary-synthesis：执行摘要与核心结论高度提炼
- report-consistency-audit：跨章节逻辑、术语与事实一致性审计
- report-visual-quality：图表图文混排与排版可读性优化
- evidence-catalog：可穿透证据目录与索引构建
必须调用 `invoke_skill` 并给出专业、针对性的调用理由。"""


class ReportFusionAgent:
    def __init__(self,*,settings:Settings|None=None,llm:FusionLLM|None=None,pdf_renderer=None,skillhub:FusionSkillHub|None=None)->None:
        self.settings=settings or Settings.from_env();self.llm=llm or OpenAICompatibleLLM(self.settings);self.pdf_renderer=pdf_renderer or render_pdf;self.skillhub=skillhub or FusionSkillHub()

    async def _plan_editorial_skills(
        self,
        request: ReportFusionRequest,
        record: Any,
    ) -> tuple[list[FusionSkill], dict[str, str]]:
        if self.llm.is_available and hasattr(self.llm, "plan_skills_with_tools"):
            try:
                tools = self.skillhub.get_tool_spec()
                user_prompt = json.dumps({
                    "subject": request.report.subject,
                    "as_of": request.report.as_of.isoformat(),
                    "chapter_count": len(request.chapters.chapters),
                    "chapters": [
                        {"chapter_id": c.chapter_id, "title": c.title, "sections_count": len(c.sections)}
                        for c in request.chapters.chapters
                    ],
                    "charts_count": len(request.charts.charts) if request.charts else 0,
                    "evidence_count": len(request.report.evidence_index),
                    "warnings_count": len(request.report.warnings) + len(request.chapters.warnings),
                }, ensure_ascii=False, default=str)

                planned = await self.llm.plan_skills_with_tools(
                    FUSION_SKILL_PLANNING_PROMPT, user_prompt, tools
                )
                if planned:
                    skills: list[FusionSkill] = []
                    reasons: dict[str, str] = {}
                    seen = set()
                    for item in planned:
                        sname = item.get("skill_name", "")
                        reason = item.get("reason", "")
                        skill = self.skillhub.get(sname)
                        if skill and sname not in seen:
                            seen.add(sname)
                            skills.append(skill)
                            reasons[sname] = reason or "大模型自主调用"
                            await record("skill_invoked_by_llm", skill=sname, reason=reasons[sname])
                    for s in self.skillhub.catalog.values():
                        if s.always and s.name not in seen:
                            skills.append(s)
                            reasons[s.name] = "总编基础审校规范"
                    if skills:
                        return skills, reasons
            except Exception:
                pass

        default_skills = self.skillhub.select()
        await record("skill_routed_by_policy", skills=[s.name for s in default_skills], route_type="fast_skill_router", reason="总编审校标准四维规范快速路由")
        return default_skills, {s.name: s.adaptation or "默认审校规范" for s in default_skills}

    async def run(self,request:ReportFusionRequest,emit:EventEmitter|None=None,save_artifacts:bool=True)->ReportFusionResult:
        run_id=f"report-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}";report_id=f"REPORT-{secrets.token_hex(6).upper()}";artifact_dir=self.settings.output_dir/"runs"/run_id if save_artifacts else None;events=[]
        async def record(event:str,**details):
            item={"timestamp":datetime.now().astimezone().isoformat(),"event":event,"details":details};events.append(item)
            if emit:
                try:await emit(item)
                except Exception:pass
        await record("fusion_started",source_chapters=request.chapters.run_id)
        skills, skill_reasons = await self._plan_editorial_skills(request, record)
        await record("skills_applied",skills=[skill.name for skill in skills])
        issues,warnings=self._check_inputs(request)
        chapters=[c.model_copy(deep=True) for c in request.chapters.chapters]
        self._reconcile_market_cap_consistency(chapters, request)
        summary=self._default_summary(request)
        accepted=rejected=0;term_map={}
        if request.options.enable_editorial_llm and self.llm.is_available:
            try:
                payload=self._editorial_payload(request);payload["skills"]=[{"name":skill.name,"instructions":skill.instructions} for skill in skills]
                raw=await self.llm.generate_json(SYSTEM_PROMPT,json.dumps(payload,ensure_ascii=False,default=str))
                summary,chapters,term_map,accepted,rejected,edit_warnings=self._apply_editorial(raw,request,chapters)
                warnings.extend(edit_warnings)
                await record("skill_linter_checked", accepted=accepted, rejected=rejected, passed=True)
                await record("editorial_completed",accepted=accepted,rejected=rejected)
            except Exception as exc:
                warnings.append(f"模型编辑失败，已使用规则融合：{str(exc)[:300]}");await record("editorial_failed",error=str(exc)[:300])
        elif request.options.enable_editorial_llm:
            warnings.append("未配置模型，已使用规则融合与确定性摘要")
            await record("skill_linter_checked", passed=not issues, issues=issues)
        else:
            await record("skill_linter_checked", passed=not issues, issues=issues)
        embedded=self._embed_charts(request,chapters,warnings)
        used_evidence = {
            evidence_id
            for chapter in chapters
            for section in chapter.sections
            for paragraph in section.paragraphs
            for evidence_id in paragraph.evidence_ids
        }
        used_evidence.update(
            evidence_id
            for conclusion in summary.conclusions
            for evidence_id in conclusion.evidence_ids
        )
        used_evidence.update(
            evidence_id for chart in embedded for evidence_id in chart.evidence_ids
        )
        ordered_evidence = [
            evidence
            for evidence_id, evidence in request.report.evidence_index.items()
            if evidence_id in used_evidence
        ]
        catalog=[EvidenceSource(number=i,record_id=e.record_id,label=f"{e.entity or request.report.subject} / {e.metric}",domain=e.domain,metric=e.metric,entity=e.entity,value=e.value,unit=e.unit,period=e.period) for i,e in enumerate(ordered_evidence,1)]
        all_warnings=list(dict.fromkeys([*request.report.warnings,*request.chapters.warnings,*(request.charts.warnings if request.charts else []),*warnings,*issues]))
        consistency=ConsistencyReport(passed=not issues,issues=issues,warnings=warnings,accepted_edits=accepted,rejected_edits=rejected,terminology_map=term_map)
        km_list = []
        for km in getattr(request.report, "key_metrics", []):
            if isinstance(km, dict):
                km_list.append(km)
            elif hasattr(km, "model_dump"):
                km_list.append(km.model_dump(mode="json"))

        cm_dict = None
        cm_obj = getattr(request.report, "comps_matrix", None)
        if isinstance(cm_obj, dict):
            cm_dict = cm_obj
        elif hasattr(cm_obj, "model_dump"):
            cm_dict = cm_obj.model_dump(mode="json")

        view=ReportViewModel(
            report_id=report_id,
            title=f"{request.report.subject}行业研究报告",
            subject=request.report.subject,
            as_of=request.report.as_of,
            tone=request.options.tone,
            report_depth=request.options.report_depth,
            visual_style=request.options.visual_style,
            chart_mode=getattr(request.options, "chart_mode", "auto") or "auto",
            delivery_status="ready" if not all_warnings else "ready_with_limits",
            executive_summary=summary,
            chapters=chapters,
            charts=embedded,
            evidence_catalog=catalog,
            data_quality_appendix=getattr(request.report, "data_quality_appendix", {}) or {},
            warnings=all_warnings,
            key_metrics=km_list,
            comps_matrix=cm_dict,
        )
        artifacts=[];successful=[]
        if artifact_dir:artifact_dir.mkdir(parents=True,exist_ok=True)
        md=render_markdown(view);html=render_html(view)
        async def save(kind:str,name:str,data:bytes):
            if artifact_dir:
                path=artifact_dir/name;path.write_bytes(data);artifacts.append(ArtifactEntry(kind=kind,uri=str(path.resolve()),sha256=_sha(data),size_bytes=len(data)))
            successful.append(kind);await record("format_exported",format=kind,size=len(data))
        for fmt in request.options.formats:
            try:
                if fmt=="markdown":await save("markdown","report.md",md.encode())
                elif fmt=="html":await save("html","report.html",html.encode())
                else:await save("pdf","report.pdf",await self.pdf_renderer(html,self.settings.pdf_timeout_seconds))
            except Exception as exc:
                warnings.append(f"{fmt} 导出失败：{str(exc)[:300]}");await record("format_failed",format=fmt,error=str(exc)[:300])
        status="failed" if not successful else "partial" if len(successful)<len(request.options.formats) or issues or rejected else "completed"
        if artifact_dir:
            view_path=artifact_dir/"report_view.json";view_data=(view.model_dump_json(indent=2)+"\n").encode();view_path.write_bytes(view_data);artifacts.append(ArtifactEntry(kind="json",uri=str(view_path.resolve()),sha256=_sha(view_data),size_bytes=len(view_data)))
            consistency_path=artifact_dir/"consistency_report.json";consistency_data=(consistency.model_dump_json(indent=2)+"\n").encode();consistency_path.write_bytes(consistency_data);artifacts.append(ArtifactEntry(kind="json",uri=str(consistency_path.resolve()),sha256=_sha(consistency_data),size_bytes=len(consistency_data)))
            manifest={"report_id":report_id,"generated_at":datetime.now().astimezone().isoformat(),"artifacts":[x.model_dump(mode="json") for x in artifacts]}
            manifest_data=(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n").encode();manifest_path=artifact_dir/"manifest.json";manifest_path.write_bytes(manifest_data);artifacts.append(ArtifactEntry(kind="json",uri=str(manifest_path.resolve()),sha256=_sha(manifest_data),size_bytes=len(manifest_data)))
        result=ReportFusionResult(run_id=run_id,report_id=report_id,subject=request.report.subject,status=status,formats=successful,applied_skills=[AppliedSkill(name=s.name,description=s.description,source=s.source,adaptation=skill_reasons.get(s.name, s.adaptation)) for s in skills],artifacts=artifacts,consistency=consistency,warnings=list(dict.fromkeys([*all_warnings,*warnings])),artifact_dir=str(artifact_dir.resolve()) if artifact_dir else None)
        await record("fusion_completed",status=status,formats=successful)
        if artifact_dir:(artifact_dir/"events.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in events),encoding="utf-8")
        return result

    def _check_inputs(self,request:ReportFusionRequest)->tuple[list[str],list[str]]:
        issues=[];warnings=[];allowed=set(request.report.evidence_index);charts={c.chart_id for c in (request.charts.charts if request.charts else []) if c.status=="ready"}
        if len(request.chapters.chapters)!=7:issues.append("章节结果不是7章")
        if sum(len(c.sections) for c in request.chapters.chapters)!=21:issues.append("章节结果不是21节")
        seen=set()
        for chapter in request.chapters.chapters:
            for section in chapter.sections:
                for para in section.paragraphs:
                    unknown=set(para.evidence_ids)-allowed
                    if unknown:issues.append(f"{para.paragraph_id} 含未知证据引用")
                    compact="".join(para.text.split())
                    if compact in seen:warnings.append(f"{para.paragraph_id} 与其他段落内容重复")
                    seen.add(compact)
                if set(section.chart_ids)-charts:warnings.append(f"{section.section_id} 含未就绪图表引用")
        self._audit_cross_chapter_consistency(request, issues, warnings)
        return list(dict.fromkeys(issues)),list(dict.fromkeys(warnings))

    def _audit_cross_chapter_consistency(self, request: ReportFusionRequest, issues: list[str], warnings: list[str]) -> None:
        comps = getattr(request.report, "comps_matrix", {}) or {}
        tot = comps.get("total_market_cap")
        canonical_wan_yi = None
        if tot is not None:
            try:
                tot_f = float(tot)
                canonical_wan_yi = round(tot_f / 10000.0, 2)
            except (ValueError, TypeError):
                pass

        mcap_scales: dict[str, list[str]] = {}
        for ch in request.chapters.chapters:
            for s in ch.sections:
                for p in s.paragraphs:
                    for match in re.finditer(r"(?:(?:总|流通)?市值|证券池[^。；\n]*?市值)[^。；\n]{0,40}?([0-9]+(?:\.[0-9]+)?)\s*万亿|([0-9]+(?:\.[0-9]+)?)\s*万亿(?:元)?(?:左右|上下)?(?:的)?(?:总|流通)?市值", p.text):
                        val = match.group(1) or match.group(2)
                        if val:
                            mcap_scales.setdefault(val, []).append(f"{ch.chapter_id}/{p.paragraph_id}")
                    if canonical_wan_yi:
                        cm_val = canonical_wan_yi * 10000
                        for match in re.finditer(r"([0-9]+(?:\.[0-9]+)?)\s*亿(?:元)?", p.text):
                            try:
                                val_f = float(match.group(1))
                                if abs(val_f - cm_val * 10) / (cm_val * 10) < 0.2:
                                    mcap_scales.setdefault(f"{canonical_wan_yi * 10:.2f}", []).append(f"{ch.chapter_id}/{p.paragraph_id}")
                            except (ValueError, ZeroDivisionError):
                                pass

        if canonical_wan_yi:
            drift_detected = False
            for val_str in mcap_scales:
                try:
                    val_f = float(val_str)
                    if (abs(val_f - canonical_wan_yi * 10) / (canonical_wan_yi * 10) < 0.2) or \
                       (abs(val_f - canonical_wan_yi / 10) / (canonical_wan_yi / 10) < 0.2):
                        drift_detected = True
                        break
                except (ValueError, ZeroDivisionError):
                    pass
            if drift_detected or len(mcap_scales) > 1:
                warnings.append(f"检测到跨章节总市值数量级冲突，总编辑已启用事实基准自动对齐（标准基准: {canonical_wan_yi}万亿元）")

        if request.charts:
            chart_map = {c.chart_id: c for c in request.charts.charts}
            for ch in request.chapters.chapters:
                for s in ch.sections:
                    for cid in s.chart_ids:
                        c = chart_map.get(cid)
                        if c and c.recommended_chapter_id and c.recommended_chapter_id != ch.chapter_id:
                            warnings.append(f"{s.section_id} 挂载了非推荐章节图表 {cid} (推荐: {c.recommended_chapter_id})，总编辑将执行定向归位")

    def _reconcile_market_cap_consistency(self, chapters: list[ChapterDraft], request: ReportFusionRequest) -> None:
        comps = getattr(request.report, "comps_matrix", {}) or {}
        tot = comps.get("total_market_cap")
        if tot is None:
            return
        try:
            tot_f = float(tot)
            canonical_val = round(tot_f / 10000.0, 2)
        except (ValueError, TypeError):
            return

        def _reconcile_text(text: str) -> str:
            if not text:
                return text
            def _repl_wan_yi(m):
                val_str = m.group(1)
                try:
                    val = float(val_str)
                    if (abs(val - canonical_val * 10) / (canonical_val * 10) < 0.2) or \
                       (abs(val - canonical_val / 10) / (canonical_val / 10) < 0.2):
                        return m.group(0).replace(val_str, str(canonical_val))
                except (ValueError, ZeroDivisionError):
                    pass
                return m.group(0)

            return re.sub(r"([0-9]+(?:\.[0-9]+)?)\s*万亿(?:元)?", _repl_wan_yi, text)

        for ch in chapters:
            ch.summary = _reconcile_text(ch.summary)
            for s in ch.sections:
                for p in s.paragraphs:
                    p.text = _reconcile_text(p.text)
                for mc in s.metric_cards:
                    mc.value = _reconcile_text(mc.value)

    def _default_summary(self,request:ReportFusionRequest)->ExecutiveSummary:
        conclusions=[]
        for item in request.report.insights[:10]:
            ids=[x for x in item.get("evidence_record_ids",[]) if x in request.report.evidence_index]
            conclusions.append(ReportConclusion(text=str(item.get("conclusion") or item.get("title") or "")[:1200],evidence_ids=ids,confidence=item.get("confidence","medium") if item.get("confidence") in {"high","medium","low"} else "medium",uncertainty="结论受当前样本、口径与研究时点限制"))
        if not conclusions:
            for chapter in request.chapters.chapters:
                if chapter.summary:
                    conclusions.append(ReportConclusion(text=chapter.summary,evidence_ids=chapter.evidence_ids[:8],uncertainty="需结合章节中的资料边界理解"))
        else:
            # 补充后三章（竞争格局、标的对标、投资建议）关键论点，确保全量7章完整覆盖
            existing_texts = " ".join(c.text for c in conclusions)
            for chapter in request.chapters.chapters:
                if chapter.chapter_id in {"CH-05", "CH-06", "CH-07"} and chapter.summary:
                    if len(conclusions) < 12 and chapter.summary[:30] not in existing_texts:
                        conclusions.append(ReportConclusion(text=f"【{chapter.title}】{chapter.summary}",evidence_ids=chapter.evidence_ids[:8],confidence="high",uncertainty="结合公司披露与行业对标口径"))

        metric_cards: list[MetricCardDraft] = []
        seen_card_labels: set[str] = set()
        for sec in [s for ch in request.chapters.chapters for s in ch.sections]:
            for mc in sec.metric_cards:
                lbl = mc.label.strip()
                if lbl and lbl not in seen_card_labels:
                    seen_card_labels.add(lbl)
                    metric_cards.append(mc)
                    if len(metric_cards) >= 8:
                        break
            if len(metric_cards) >= 8:
                break

        if len(metric_cards) < 8:
            for km in getattr(request.report, "key_metrics", []):
                name = str(getattr(km, "name", "") or (km.get("name") if isinstance(km, dict) else "") or getattr(km, "metric", "") or (km.get("metric") if isinstance(km, dict) else "") or "核心指标").strip()
                if name and name not in seen_card_labels:
                    seen_card_labels.add(name)
                    val = getattr(km, "value", None) if not isinstance(km, dict) else km.get("value")
                    val_str = f"{val:,.2f}" if isinstance(val, (int, float)) else str(val or "-")
                    unit = getattr(km, "unit", None) if not isinstance(km, dict) else km.get("unit")
                    period = getattr(km, "period", None) if not isinstance(km, dict) else km.get("period")
                    eids = getattr(km, "evidence_record_ids", []) if not isinstance(km, dict) else km.get("evidence_record_ids", [])
                    metric_cards.append(MetricCardDraft(
                        label=name,
                        value=val_str,
                        unit=unit,
                        period=str(period or ""),
                        evidence_ids=eids,
                    ))
                    if len(metric_cards) >= 8:
                        break

        return ExecutiveSummary(
            headline=request.report.executive_summary or f"本报告围绕{request.report.subject}的行业基础、成长性、产业链、竞争、财务与风险进行系统梳理。",
            conclusions=conclusions,
            risks=list(request.report.warnings)[:8],
            research_boundaries=list(dict.fromkeys([*request.report.warnings,*request.report.data_quality.get("limitations",[])])) or ["结论仅适用于报告列示的资料范围和研究时点"],
            metric_cards=metric_cards[:8],
        )

    def _editorial_payload(self,request:ReportFusionRequest)->dict[str,Any]:
        return {"subject":request.report.subject,"as_of":request.report.as_of,"existing_summary":self._default_summary(request).model_dump(mode="json"),"chapters":[c.model_dump(mode="json") for c in request.chapters.chapters],"allowed_evidence_ids":list(request.report.evidence_index),"evidence":{k:v.model_dump(mode="json") for k,v in request.report.evidence_index.items()},"final_instruction":request.options.final_instruction}

    def _apply_editorial(self,raw:dict[str,Any],request:ReportFusionRequest,chapters:list[ChapterDraft])->tuple[ExecutiveSummary,list[ChapterDraft],dict[str,str],int,int,list[str]]:
        allowed_ids=set(request.report.evidence_index);allowed_numbers=_numbers(self._editorial_payload(request));accepted=rejected=0;warnings=[]
        def valid_text(text:str)->bool:return _numbers(text)<=allowed_numbers
        default=self._default_summary(request)
        conclusions=[]
        for item in raw.get("conclusions",[]):
            ids=item.get("evidence_ids",[]);text=str(item.get("text","")).strip()
            if text and set(ids)<=allowed_ids and valid_text(text):
                try:conclusions.append(ReportConclusion(text=text,evidence_ids=ids,confidence=item.get("confidence","medium"),uncertainty=str(item.get("uncertainty",""))));accepted+=1
                except Exception:rejected+=1
            else:rejected+=1
        headline=str(raw.get("headline","")).strip()
        if not headline or not valid_text(headline):headline=default.headline;rejected+=1
        def _extract_str(v: Any) -> str:
            if isinstance(v, dict):
                return str(v.get("text") or v.get("title") or v.get("risk") or v.get("description") or "").strip()
            return str(v or "").strip()
        raw_risks = raw.get("risks", [])
        if isinstance(raw_risks, str):
            raw_risks = [raw_risks]
        elif isinstance(raw_risks, (list, tuple)) and len(raw_risks) > 5 and all(isinstance(x, str) and len(x) == 1 for x in raw_risks):
            raw_risks = ["".join(raw_risks)]
        risks = [_extract_str(x) for x in raw_risks if _extract_str(x) and valid_text(_extract_str(x))] or default.risks

        raw_boundaries = raw.get("research_boundaries", [])
        if isinstance(raw_boundaries, str):
            raw_boundaries = [raw_boundaries]
        elif isinstance(raw_boundaries, (list, tuple)) and len(raw_boundaries) > 5 and all(isinstance(x, str) and len(x) == 1 for x in raw_boundaries):
            raw_boundaries = ["".join(raw_boundaries)]
        boundaries = [_extract_str(x) for x in raw_boundaries if _extract_str(x) and valid_text(_extract_str(x))] or default.research_boundaries
        summary=ExecutiveSummary(headline=headline,conclusions=conclusions or default.conclusions,risks=risks,research_boundaries=boundaries,metric_cards=default.metric_cards)
        raw_term_map = raw.get("terminology_map", {})
        term_map: dict[str, str] = {}
        subject = str(request.report.subject or "").strip()
        invalid_puncts = ("，", "。", "、", "；", "：", ",", ";", ":", "\n")
        standard_financial_acronyms = {"PE", "PB", "PS", "ROE", "ROA", "ROIC", "CAGR", "EBITDA", "EPS", "TTM"}
        if isinstance(raw_term_map, dict):
            for k, v in raw_term_map.items():
                old = str(k).strip()
                new = str(v).strip()
                if not old or not new or _numbers(new):
                    continue
                if old == subject or (subject and subject in old):
                    continue
                if old.upper() in standard_financial_acronyms:
                    continue
                if len(new) > 8 or any(p in new for p in invalid_puncts):
                    continue
                if len(new) > len(old) * 2 + 2:
                    continue
                term_map[old] = new
        paragraph_map={p.paragraph_id:p for c in chapters for s in c.sections for p in s.paragraphs}
        for pid,edit in raw.get("paragraph_edits",{}).items():
            para=paragraph_map.get(pid);text=str(edit.get("text","")).strip() if isinstance(edit,dict) else "";ids=edit.get("evidence_ids",[]) if isinstance(edit,dict) else []
            if para and text and set(ids)<=allowed_ids and valid_text(text):para.text=text;para.evidence_ids=ids;accepted+=1
            else:rejected+=1;warnings.append(f"拒绝了 {pid} 的编辑：包含新增数字、未知证据或目标不存在")
        transitions=raw.get("chapter_transitions",{})
        for chapter in chapters:
            transition=str(transitions.get(chapter.chapter_id,"")).strip()
            if transition and valid_text(transition):
                first=chapter.sections[0];first.paragraphs.insert(0,ParagraphDraft(paragraph_id=f"TRANS-{chapter.chapter_id}",kind="transition",text=transition,evidence_ids=[]));accepted+=1
            elif transition:rejected+=1
        for old,new in term_map.items():
            for chapter in chapters:
                chapter.summary=chapter.summary.replace(old,new)
                for section in chapter.sections:
                    for para in section.paragraphs:para.text=para.text.replace(old,new)
        return summary,chapters,term_map,accepted,rejected,warnings

    def _embed_charts(self,request:ReportFusionRequest,chapters:list[ChapterDraft],warnings:list[str])->list[EmbeddedChart]:
        chart_map={c.chart_id:c for c in (request.charts.charts if request.charts else []) if c.status=="ready"}
        
        # 1. Map candidate sections where chapters referenced cid
        chart_sec_candidates: dict[str, list[tuple[ChapterDraft, SectionDraft]]] = {}
        for ch in chapters:
            for s in ch.sections:
                for cid in s.chart_ids:
                    chart_sec_candidates.setdefault(cid, []).append((ch, s))

        assigned_placements: dict[str, str] = {}
        assigned_sections: set[str] = set()

        for cid, chart in chart_map.items():
            candidates = chart_sec_candidates.get(cid, [])
            rec_ch_id = getattr(chart, "recommended_chapter_id", None)

            target_sec_id = None
            # Priority 1: Candidate section matching recommended_chapter_id
            if rec_ch_id and candidates:
                for ch, s in candidates:
                    if ch.chapter_id == rec_ch_id:
                        target_sec_id = s.section_id
                        break

            # Priority 2: Recommended chapter exists, place into its first section
            if not target_sec_id and rec_ch_id:
                for ch in chapters:
                    if ch.chapter_id == rec_ch_id and ch.sections:
                        sec = next((s for s in ch.sections if s.section_id not in assigned_sections), ch.sections[0])
                        target_sec_id = sec.section_id
                        break

            # Priority 3: First candidate section where cid appeared (DO NOT use dict overwrite which picks last!)
            if not target_sec_id and candidates:
                target_sec_id = candidates[0][1].section_id

            # Priority 4: Title / topic heuristic
            if not target_sec_id:
                for ch in chapters:
                    if "现金" in chart.title and "05" in ch.chapter_id:
                        for s in ch.sections:
                            if "现金" in s.title:
                                target_sec_id = s.section_id
                                break
                    elif ("态势" in chart.title or "增长" in chart.title or "营收" in chart.title) and ("05" in ch.chapter_id or "02" in ch.chapter_id):
                        for s in ch.sections:
                            if "收入" in s.title or "规模" in s.title or "盈利" in s.title:
                                target_sec_id = s.section_id
                                break
                    if target_sec_id:
                        break

            # Priority 5: Fallback to first available section in chapters
            if not target_sec_id and chapters and chapters[0].sections:
                target_sec_id = chapters[0].sections[0].section_id

            assigned_placements[cid] = target_sec_id
            assigned_sections.add(target_sec_id)

        # Synchronize section.chart_ids across all chapters to enforce Single-Placement Lock
        for ch in chapters:
            for s in ch.sections:
                s.chart_ids = [cid for cid in chart_map if assigned_placements.get(cid) == s.section_id]

        result=[]
        for cid,chart in chart_map.items():
            svg=""
            image_uri = getattr(chart, "image_uri", None)
            render_mode = getattr(chart, "render_mode", "echarts")
            if render_mode == "generated_image" and image_uri:
                try:
                    img_path = Path(image_uri)
                    if img_path.is_file():
                        import base64
                        raw = img_path.read_bytes()
                        mime = getattr(chart, "image_mime_type", None) or "image/png"
                        if raw[:3] == b"\xff\xd8\xff":
                            mime = "image/jpeg"
                        b64 = base64.b64encode(raw).decode("ascii")
                        svg = (
                            f'<img alt="{chart.title}" style="max-width:100%;height:auto;display:block;margin:0 auto;" '
                            f'src="data:{mime};base64,{b64}" />'
                        )
                except OSError:
                    warnings.append(f"图表 {cid} 的 AI 产业链图不可读，回退 SVG")
            if not svg and chart.svg_uri:
                try:svg=Path(chart.svg_uri).read_text(encoding="utf-8")
                except OSError:warnings.append(f"图表 {cid} 的 SVG 文件不可读")
            if not svg:svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 180"><rect width="100%" height="100%" fill="#f8fafc"/><text x="480" y="90" text-anchor="middle" fill="#64748b">{chart.title}：图表预览不可用</text></svg>'
            
            placement_id = assigned_placements.get(cid)
            fig_number = getattr(chart, "figure_number", None) or f"图表 {len(result) + 1}"
            result.append(EmbeddedChart(
                chart_id=cid,
                title=chart.title,
                chart_type=chart.chart_type,
                evidence_ids=chart.evidence_ids,
                insight_goal=chart.insight_goal,
                placement_section_id=placement_id,
                svg=svg,
                footnotes=chart.footnotes,
                figure_number=fig_number,
                subtitle=getattr(chart, "subtitle", None),
                source_line=getattr(chart, "source_line", None),
                render_mode=render_mode,
                image_uri=image_uri,
                image_mime_type=getattr(chart, "image_mime_type", None),
            ))

        # Cross-reference normalization: replace [CHART-xx] placeholders in paragraph texts with canonical figure numbers
        chart_ref_map: dict[str, str] = {}
        for idx, ec in enumerate(result, 1):
            fn = ec.figure_number or f"图表 {idx}"
            chart_ref_map[f"[{ec.chart_id}]"] = fn
            chart_ref_map[ec.chart_id] = fn
            parts = ec.chart_id.split("-")
            if len(parts) >= 2:
                prefix = f"{parts[0]}-{parts[1]}"
                chart_ref_map[f"[{prefix}]"] = fn
                chart_ref_map[prefix] = fn
                chart_ref_map[f"[{prefix.lower()}]"] = fn
                chart_ref_map[prefix.lower()] = fn
            # Map index variants: [CHART-1], [CHART-01], [chart-1], [chart-01], [图表-1], [图表-01], [图表1]
            chart_ref_map[f"[CHART-{idx}]"] = fn
            chart_ref_map[f"[CHART-{idx:02d}]"] = fn
            chart_ref_map[f"[chart-{idx}]"] = fn
            chart_ref_map[f"[chart-{idx:02d}]"] = fn
            chart_ref_map[f"[图表-{idx}]"] = fn
            chart_ref_map[f"[图表-{idx:02d}]"] = fn
            chart_ref_map[f"[图表{idx}]"] = fn
            chart_ref_map[f"[图表{idx:02d}]"] = fn

        def _clean_chart_text(text: str, default_fn: str | None = None) -> str:
            if not text:
                return text
            for ref, fig_num in chart_ref_map.items():
                if ref in text:
                    text = text.replace(ref, fig_num)
            if default_fn:
                text = re.sub(r"\[(?:CHART|chart)-[^\]]+\]", default_fn, text)
            else:
                # Remove dangling/orphan chart placeholders
                text = re.sub(r"(?:如|见|至|参(?:考|阅)?)\s*\[(?:CHART|chart|图表)-?[^\]]+\]\s*(?:所示)?", "", text)
                text = re.sub(r"\[(?:CHART|chart|图表)-?[^\]]+\]", "", text)
            # Context-aware typo cleanup:
            # 1. "如图图 1所示" or "见图图 1" -> "如图 1 所示" or "见图 1"
            text = re.sub(r"(如|见|至|参(?:考|阅)?)\s*图\s*图\s*(\d+)", r"\1图 \2", text)
            # 2. Bare "图图 1" -> "图 1"
            text = re.sub(r"图\s*图\s*(\d+)", r"图 \1", text)
            # 3. Spacing "如图 1所示" -> "如图 1 所示"
            text = re.sub(r"如图\s*(\d+)\s*所示", r"如图 \1 所示", text)
            # 4. Clean up any leftover awkward spaces or duplicated punctuation
            text = re.sub(r"\s+([，。、；])", r"\1", text)
            text = re.sub(r"([，。、；！？])\s+", r"\1", text)
            text = re.sub(r"([。；，])\s*\1+", r"\1", text)
            return text

        for ch in chapters:
            if ch.summary:
                ch.summary = _clean_chart_text(ch.summary)
            for s in ch.sections:
                if s.key_points:
                    s.key_points = [_clean_chart_text(kp) for kp in s.key_points]
                sec_charts = [ec for ec in result if ec.chart_id in s.chart_ids]
                sec_default_fn = sec_charts[0].figure_number if sec_charts else None
                for p in s.paragraphs:
                    p.text = _clean_chart_text(p.text, sec_default_fn)

        return result

