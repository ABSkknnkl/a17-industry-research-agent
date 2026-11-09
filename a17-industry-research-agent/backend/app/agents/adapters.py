from __future__ import annotations
import json
import logging
import shutil
from pathlib import Path
import re
from typing import Any

from backend.app.core.config import settings
from backend.app.core.event_hub import event_hub
from backend.app.core.storage import storage
from backend.app.schemas.workflow import ArtifactRef, StageResult

logger = logging.getLogger("agent_adapters")


class SupplementalRecordCollision(ValueError):
    """One evidence ID identifies incompatible supplemental records."""


def merge_supplemental_records(dataset: Any, report_dict: dict[str, Any], records: list[Any], as_of: Any) -> list[str]:
    """Merge chart supplements without losing qualifiers or silently trusting stale analysis."""
    from agents_core.financial_semantics import metric_family
    from data_fetcher.agent import DataFetcherAgent
    from data_fetcher.fusion import DataFusion
    from data_fetcher.models import ResearchRequirement
    from data_interpreter.engine import DeterministicAnalysisEngine
    from data_interpreter.models import ResearchRecord as AnalysisRecord

    def signature(record: Any) -> tuple[Any, ...]:
        return (str(record.domain), record.entity_code or record.entity_name, metric_family(record.metric),
                record.period_start, record.period_end, record.period_type, record.scope, record.currency,
                record.unit, json.dumps(record.value, ensure_ascii=False, sort_keys=True, default=str))

    scope = dataset.quality_summary.get("comparison_scope")
    if scope:
        names, codes = set(scope["names"]), set(scope["codes"])
        records = [
            record for record in records
            if record.domain not in {"companies", "financials"}
            or record.entity_name in names or record.entity_code in codes
        ]
    existing = dataset.all_records()
    by_id = {record.record_id: signature(record) for record in existing}
    for record in records:
        if (record.period_end and record.period_end > as_of) or (record.published_at and record.published_at > as_of):
            continue
        current_signature = signature(record)
        if record.record_id in by_id and by_id[record.record_id] != current_signature:
            raise SupplementalRecordCollision(f"补采 record_id 冲突: {record.record_id}")
        by_id[record.record_id] = current_signature
    ids = {record.record_id for record in existing}
    signatures = {signature(record) for record in existing}
    added = []
    for record in records:
        if ((record.period_end and record.period_end > as_of) or (record.published_at and record.published_at > as_of)
                or record.record_id in ids or signature(record) in signatures):
            continue
        dataset.records_for(record.domain).append(record)
        ids.add(record.record_id)
        signatures.add(signature(record))
        if record.source not in dataset.sources:
            dataset.sources.append(record.source)
        added.append(record.record_id)
    if not added:
        return []

    dataset.research_as_of = as_of
    adjustments = DataFusion._apply_official_restatements(dataset, as_of)
    dataset.quality_summary.setdefault('restatement_adjustments', []).extend(adjustments)
    dataset.conflicts = DataFusion()._find_conflicts(dataset)
    dataset.quality_summary['conflict_count'] = len(dataset.conflicts)
    dataset.quality_summary['structured_record_count'] = len(dataset.all_records())
    index = report_dict.setdefault('evidence_index', {})
    for change in adjustments:
        index.pop(change['original_record']['record_id'], None)
    current = {record.record_id: record for record in dataset.all_records()}
    replacements = {change['original_record']['record_id']: change['replacement_record_id'] for change in adjustments}
    added = list(dict.fromkeys(replacements.get(rid, rid) for rid in added))
    added = list(dict.fromkeys([*added, *replacements.values()]))
    for rid in added:
        if rid in current:
            ref = DeterministicAnalysisEngine._evidence(AnalysisRecord.model_validate(current[rid].model_dump(mode='json')))
            index[rid] = ref.model_dump(mode='json')
    matrix = dataset.quality_summary.get('requirement_evidence_matrix') or []
    for row in matrix:
        requirement = ResearchRequirement.model_validate(row['requirement'])
        row['coverage'] = DataFetcherAgent._evaluate_requirement(dataset, requirement).model_dump(mode='json')
    coverage = [row['coverage'] for row in matrix]
    annual = [row for row in coverage if str(row.get('requirement_id', '')).startswith('annual_')]
    stale = {'requirement_id':'supplement_analysis_stale', 'label':'补采后需要重新分析', 'hard':True,
             'passed':False, 'missing':['新增证据尚未重新运行分析'], 'evidence_record_ids':added}
    appendix = report_dict.setdefault('data_quality_appendix', {})
    previous = appendix.get('requested_requirement_coverage') or []
    matrix_ids = {row.get('requirement_id') for row in coverage}
    extras = [row for row in previous if row.get('requirement_id') not in matrix_ids and row.get('requirement_id') != stale['requirement_id']]
    dataset.quality_summary['requested_requirement_coverage'] = coverage + extras + [stale]
    dataset.quality_summary['requested_financial_coverage'] = annual
    appendix.update(requirement_evidence_matrix=matrix, requested_requirement_coverage=coverage + extras + [stale],
                    requested_financial_coverage=annual)
    report_dict.setdefault('warnings', []).append('图表补采增加证据；分析结论尚未重算，正式交付已阻断。')
    return added


def record_requested_chart_shortfall(result: Any, requested_count: int | None) -> None:
    """Record an explicitly requested count; an implicit maximum is not a minimum."""
    if isinstance(requested_count, bool) or not isinstance(requested_count, int) or requested_count <= 0:
        return
    if result.quality:
        result.quality.requested_count = requested_count
    actual = len(result.charts)
    if actual < requested_count:
        message = f"用户要求 {requested_count} 张图表，实际生成 {actual} 张；缺口需核查候选抑制原因。"
        result.warnings.append(message)
        if result.quality:
            result.quality.passed = False
            result.quality.issues.append(message)


def _requested_chain(input_data: dict[str, Any], chart_request: Any) -> bool:
    """Resolve user intent before disabling the legacy renderer for V2."""
    from chart_generator.chain_intent import user_wants_industry_chain

    return user_wants_industry_chain(
        chart_request.report.subject or "",
        input_data.get("focus_questions") or [],
        explicit=chart_request.want_industry_chain,
        defaulted_focus=chart_request.defaulted_focus,
        requested_types=chart_request.preferences.requested_types,
    )


def _report_chain_delivery(run_id: str) -> dict[str, Any]:
    """Carry the current chart-stage release decision into final report gates."""
    state = storage.load_state(run_id)
    chart = state.stage_results.get("chart_generate") if state else None
    delivery = (chart.data or {}).get("chain_delivery") if chart else None
    return dict(delivery) if isinstance(delivery, dict) else {}


def _chart_svg_content(chart: Any, report: Any) -> str:
    """取这张图要落盘的 SVG 文本（2026-10-17）。

    产业链图（``render_mode="svg"``）必须用下发的**确定性产业链 SVG**：它带连线、箭头
    与环节卡片。历史实现一律调 ``render_svg`` 重画，等于把产业链图换成 ECharts 的
    「三栏企业列表」（实测 0 条 polyline）——而 report-fusion 正是读这个文件嵌 PDF 的，
    交付件因此一直没有连线。其它图表类型仍走 ECharts 通用渲染。
    """
    inline = getattr(chart, "inline_svg", None)
    if getattr(chart, "render_mode", "") == "svg" and inline:
        return inline
    from chart_generator.render import render_svg

    return render_svg(
        chart.title,
        chart.chart_type,
        chart.option,
        chart.footnotes or [],
        figure_number=getattr(chart, "figure_number", None),
        as_of=str(getattr(report, "as_of", "") or ""),
        insight_takeaway=getattr(chart, "insight_goal", ""),
    )


def _resolve_delivery_status(art_dir: Path, consistency: Any) -> str:
    """解析交付状态，优先生效的 report_view.json，缺失时按审计结论降级。

    D-04 修复：ReportFusionResult 本身不携带 delivery_status，真实值由 ReportFusionAgent
    写入 report_view.json（ReportViewModel.delivery_status）。合并退化后这里被无条件写死
    "ready"，会把带保留的交付（ready_with_limits）伪装成正常交付。

    Returns: "ready" | "ready_with_limits" | "blocked"
    """
    view_path = art_dir / "report_view.json"
    if view_path.exists():
        try:
            payload = json.loads(view_path.read_text(encoding="utf-8"))
            status = payload.get("delivery_status")
            if status in {"ready", "ready_with_limits", "blocked"}:
                return str(status)
            logger.warning("report_view.json 的 delivery_status 取值非法: %r", status)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("读取 report_view.json 失败，回退审计结论: %s", exc)

    # 兜底不再无脑返回 ready：审计未通过或存在告警时按“有限交付”处理。
    passed = bool(getattr(consistency, "passed", False))
    warnings = list(getattr(consistency, "warnings", []) or [])
    return "ready" if passed and not warnings else "ready_with_limits"


def _count_outline_units(chapters: list[dict[str, Any]]) -> tuple[int, int]:
    """统计实际产出的章节数与小节数。"""
    section_count = sum(len(ch.get("sections") or []) for ch in chapters)
    return len(chapters), section_count


def _expected_outline_units() -> tuple[int | None, int | None]:
    """应有章节数与小节数，从 chapter_writer 的标准大纲 DEFAULT_OUTLINE 推导。

    D-04 修复：原先写死 7 / 21，改大纲时这里不会跟随，形成“假动态”。大纲的单一事实源
    在 chapter_writer/outline.py。自行保证 sys.path 已注册，不依赖调用方是否已 import
    setup_env，否则单独调用适配层函数（单元测试、脚本）时会静默退化为 None。

    Returns: (应有章节数, 应有小节数)，导入失败时返回 (None, None) 交由前端兜底。
    """
    try:
        import backend.app.core.setup_env  # noqa: F401 - 注册 agents_core 各子目录
        from chapter_writer.outline import DEFAULT_OUTLINE

        return len(DEFAULT_OUTLINE), sum(len(ch.sections) for ch in DEFAULT_OUTLINE)
    except Exception as exc:  # noqa: BLE001 - 基准缺失不应让整个阶段失败
        logger.warning("无法载入 DEFAULT_OUTLINE，大纲基准交由前端兜底: %s", exc)
        return None, None


def _deduplicate_warnings(warnings: list[str]) -> list[str]:
    """对告警与局限项执行语义去重，消除短规则与长描述的前缀/子串冗余，保留信息量最全项。"""
    seen: list[str] = []
    for w in warnings:
        w_str = str(w).strip()
        if not w_str:
            continue
        is_subsumed = False
        for idx, existing in enumerate(seen):
            if w_str == existing:
                is_subsumed = True
                break
            if existing.startswith(w_str) or (len(w_str) >= 15 and w_str in existing):
                is_subsumed = True
                break
            if w_str.startswith(existing) or (len(existing) >= 15 and existing in w_str):
                seen[idx] = w_str
                is_subsumed = True
                break
        if not is_subsumed:
            seen.append(w_str)
    return seen


def _extract_target_companies(texts: list[str]) -> list[str]:
    """从用户关注问题或需求描述中提取明确提及的目标上市公司实体。

    来源与沿革（2026-09-26 合并登记）：该函数来自队友源码包
    （`a17-industry-research-agent`）。队友交付文档 §2.4 称"已移除该正则逻辑、改由 LLM 需求理解
    + `must_include_entities` 承担"，但交付代码中该函数**仍保留且无调用点**（死代码）。
    按用户裁决"拉过来"，此处保持与队友代码一致，便于后续比对；当前**不参与任何调用路径**。

    Args:
        texts: 用户关注点 / 数据要求等文本片段。

    Returns:
        去重后的候选公司名列表（长度 2–8、不含数字与百分号、已滤除产业链环节类噪音词）。

    Note:
        若后续确认完全由 LLM 路径承担标的识别，可删除本函数；在删除前不影响运行时行为。
    """
    extracted: list[str] = []
    noise_words = {"环节", "上游", "中游", "下游", "原材料", "产业链", "应用", "设备", "制造", "总装", "测控"}
    for text in texts:
        for m in re.finditer(r"[（\(](?:如|包括|例如|核心标的)?([^）\)]+)[）\)]", text):
            content = m.group(1).strip()
            if any(k in content for k in noise_words):
                continue
            parts = re.split(r"[,，、\s]+", content)
            for p in parts:
                p = re.sub(r"^(?:如|例如|及|和|即)", "", p).strip()
                p = re.sub(r"(?:等|等等|上市公司|核心标的)$", "", p).strip()
                if 2 <= len(p) <= 8 and not re.search(r"[0-9%]", p):
                    extracted.append(p)
        for m in re.finditer(r"(?:重点关注|核心关注|核心标的为?|对标)([\u4e00-\u9fa5]{2,6}(?:[、，][\u4e00-\u9fa5]{2,6})+)", text):
            content = m.group(1)
            parts = re.split(r"[、，]", content)
            for p in parts:
                p = re.sub(r"的.*$", "", p).strip()
                if 2 <= len(p) <= 8:
                    extracted.append(p)
    seen = set()
    result: list[str] = []
    for item in extracted:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _json_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return value


def _build_evidence_digest(report: Any) -> dict[str, dict[str, Any]]:
    referenced_ids = {
        record_id
        for insight in getattr(report, "insights", [])
        for record_id in getattr(insight, "evidence_record_ids", [])
    }
    evidence_index = getattr(report, "evidence_index", {})
    digest: dict[str, dict[str, Any]] = {}

    for record_id in sorted(referenced_ids):
        evidence = evidence_index.get(record_id)
        if evidence is None:
            continue

        entity = getattr(evidence, "entity", None)
        metric = getattr(evidence, "metric", "")
        value = getattr(evidence, "value", None)
        unit = getattr(evidence, "unit", None)
        label = " · ".join(part for part in (entity, metric) if part)
        if isinstance(value, (str, int, float)) and value != "":
            label = f"{label} {value}{unit or ''}".strip()

        digest[record_id] = {
            "label": label or record_id,
            "entity": entity,
            "metric": metric,
            "value": value,
            "unit": unit,
            "period": _json_value(getattr(evidence, "period", None)),
            "domain": _json_value(getattr(evidence, "domain", None)),
            "skill_id": getattr(evidence, "skill_id", ""),
        }

    return digest


def _serialize_anomaly_risk(anomaly: Any) -> dict[str, Any]:
    severity = getattr(anomaly, "severity", "medium")
    metric = getattr(anomaly, "metric", "")
    return {
        "risk_code": getattr(anomaly, "anomaly_id", ""),
        "title": f"离群异常: {metric}",
        "level": "warning" if severity == "high" else "info",
        "kind": getattr(anomaly, "kind", ""),
        "severity": severity,
        "entity": getattr(anomaly, "entity", None),
        "metric": metric,
        "period": _json_value(getattr(anomaly, "period", None)),
        "observed_value": getattr(anomaly, "observed_value", None),
        "expected_range": getattr(anomaly, "expected_range", None),
        "score": getattr(anomaly, "score", None),
        "description": getattr(anomaly, "explanation", "") or getattr(anomaly, "description", ""),
    }


def _publish_fusion_artifacts(source: Path, destination: Path) -> None:
    """Copy final exports, then rebase the manifest before retiring temporary files."""
    from hashlib import sha256
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if path.name == "events.jsonl":
            continue
        if path.is_dir():
            shutil.copytree(path, destination / path.name, dirs_exist_ok=True)
        elif path.is_file():
            shutil.copy2(path, destination / path.name)
    manifest_path = destination / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = []
        for entry in manifest.get("artifacts", []):
            relative = Path(entry["uri"]).relative_to(source)
            published = destination / relative
            content = published.read_bytes()
            entries.append({**entry, "uri": str(published.resolve()), "sha256": sha256(content).hexdigest(), "size_bytes": len(content)})
        manifest["artifacts"] = entries
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class AgentExecutionError(Exception):
    pass


def _stage_call_ledger(stage):
    from functools import wraps
    from agents_core.call_ledger import ledger_context
    def decorate(fn):
        @wraps(fn)
        async def wrapped(*args, **kwargs):
            run_id = kwargs.get('run_id') or (args[1] if len(args) > 1 else '')
            def emit(item):
                if item['kind'] in ('tool_request', 'tool_logical'):
                    event_hub.emit(run_id, stage, 'tool_request' if item['kind'] == 'tool_request' else 'tool_call',
                                   '外部资料请求已结束', tool=item['skill_id'], details=item)
                else:
                    event_hub.emit(run_id, stage, 'model_request' if item['kind'] == 'request' else 'model_call',
                                   '模型请求已结束' if item['kind'] == 'request' else '模型调用已结束',
                                   tool='Model', details=item)
            with ledger_context(emit, stage):
                return await fn(*args, **kwargs)
        return wrapped
    return decorate


class FiveAgentsAdapter:
    """五智能体适配层：统一封装五大独立智能体的调用、参数传递与契约对齐。"""

    @classmethod
    @_stage_call_ledger('data_fetch')
    async def run_data_fetcher(
        cls,
        run_id: str,
        industry: str,
        focus_points: list[str] | None = None,
        feedback: str | None = None,
        market_scope: list[str] | None = None,
        security_types: list[str] | None = None,
        research_as_of: str | None = None,
        analysis_depth: str = "standard",
        chain_research_strategy: str = "profile_guided",
        chain_profile_id: str | None = None,
        focus_companies: list[str] | None = None,
    ) -> StageResult:
        """阶段 1: 数据获取智能体 (Data Fetcher)"""
        import backend.app.core.setup_env
        from data_fetcher.agent import DataFetcherAgent
        from data_fetcher.models import ResearchRequest

        logger.info(
            f"[{run_id}] 启动数据获取智能体: 行业={industry}, 市场={market_scope}, 证券类型={security_types}, 深度={analysis_depth}"
        )
        foci = list(focus_points or ["产业链", "龙头财务", "宏观政策", "行业规模"])
        if market_scope:
            foci.append(f"限定市场范围:{'、'.join(market_scope)}")
        if security_types:
            foci.append(f"限定证券类型:{'、'.join(security_types)}")
        if feedback:
            foci.append(f"用户修订需求:{feedback}")

        is_deep = analysis_depth == "deep"
        max_iters = 12 if is_deep else 10
        # 48 格年度财务 + 产业链主营构成 + 公告/资讯，24 次在真实源上必然被预算截断；
        # 标准深度给到 32 次，仍受 FETCH_STAGE_TIMEOUT_SECONDS 约束。
        max_calls = 40 if is_deep else 32

        req_kwargs: dict[str, Any] = {
            "industry": industry,
            "focus_points": foci,
            "must_include_entities": focus_companies or [],
            "max_iterations": max_iters,
            "max_skill_calls": max_calls,
            "max_execution_seconds": float(getattr(settings, "FETCH_STAGE_TIMEOUT_SECONDS", 720) * (1.5 if is_deep else 1.0)),
        }
        if research_as_of:
            try:
                from datetime import date
                req_kwargs["as_of"] = date.fromisoformat(research_as_of)
            except Exception:
                pass

        request = ResearchRequest(**req_kwargs)

        event_hub.emit(run_id, "data_fetch", "agent_start", f"启动数据获取智能体，研究行业主题: {industry}", tool="DataFetcherAgent")

        async def on_fetch_event(event_dict: dict[str, Any]):
            evt = event_dict.get("event")
            details = event_dict.get("details", {})
            it = event_dict.get("iteration") or details.get("iteration")
            it_prefix = f"[迭代 #{it}] " if it is not None else ""

            if evt == "agent_started":
                event_hub.emit(run_id, "data_fetch", "agent_start", f"启动数据获取智能体，初始化行业投研需求: {industry}", tool="DataFetcherAgent", details=details)
            elif evt == "objective_ready":
                domains = details.get("required_domains", [])
                event_hub.emit(run_id, "data_fetch", "llm_thought", f"研究目标分解完成，激活 7 大投研分析领域: {', '.join(domains)}", tool="PlannerLLM", details=details)
            elif evt == "observation_ready":
                cov = details.get("coverage", 0.0)
                missing = details.get("missing", [])
                missing_str = f"，待补齐领域: {'、'.join(missing[:3])}" if missing else "，核心硬性指标已基本覆盖"
                event_hub.emit(
                    run_id, "data_fetch", "llm_thought",
                    f"{it_prefix}投研数据覆盖度评估: {cov * 100:.1f}%{missing_str}",
                    tool="CoverageEngine",
                    details=details,
                )
            elif evt == "decision_ready":
                assessment = details.get("assessment", "")
                task_cnt = details.get("proposed_tasks", 0)
                event_hub.emit(
                    run_id, "data_fetch", "agent_decision",
                    f"{it_prefix}规划器决策: {assessment[:80]}... -> 生成 {task_cnt} 个问财采集子任务",
                    tool="PlannerLLM",
                    details=details,
                )
            elif evt == "task_rejected":
                tid = event_dict.get("task_id") or details.get("task_id", "")
                reason = details.get("reason", "")
                event_hub.emit(
                    run_id, "data_fetch", "warn",
                    f"{it_prefix}任务校验器过滤重复/无效任务 [{tid}]: {reason}",
                    tool="TaskValidator",
                    details=details,
                )
            elif evt in ("task_scheduled", "skill_invoked", "task_planned"):
                tid = event_dict.get("task_id") or details.get("task_id", "")
                skill = details.get("skill") or details.get("skill_name") or "hithink-query"
                query = details.get("query") or details.get("arguments", {}).get("query", "")
                expected = details.get("expected_fields", [])
                exp_str = f" (预取: {'、'.join(expected[:4])})" if expected else f": {query[:50]}" if query else ""
                event_hub.emit(
                    run_id, "data_fetch", "tool_call",
                    f"{it_prefix}调度问财金融技能 [{skill}] -> 任务 {tid}{exp_str}",
                    tool=skill,
                    details={**details, "task_id": tid},
                )
            elif evt == "skill_request_completed":
                tid = event_dict.get("task_id") or ""
                safe = {key: details.get(key) for key in ('skill_id', 'attempt', 'request_id', 'trace_id',
                        'elapsed_ms', 'http_status', 'outcome')}
                event_hub.emit(run_id, "data_fetch", "tool_request", f"{it_prefix}问财请求已结束（任务 {tid}）",
                               tool=safe.get('skill_id'), details={**safe, 'task_id': tid})
            elif evt == "skill_completed":
                tid = event_dict.get("task_id") or details.get("task_id", "")
                skill_id = details.get("skill_id") or "hithink-query"
                count = details.get("record_count", 0)
                event_hub.emit(
                    run_id, "data_fetch", "tool_result",
                    f"{it_prefix}问财技能 [{skill_id}] 执行成功: 入库 {count} 条实体与指标数据 (任务 {tid})",
                    tool=skill_id,
                    details={**details, "task_id": tid},
                )
            elif evt in ("skill_failed", "skill_cancelled"):
                tid = event_dict.get("task_id") or details.get("task_id", "")
                skill_id = details.get("skill_id") or "hithink-query"
                err = details.get("error", "未知异常")
                event_hub.emit(
                    run_id, "data_fetch", "warn",
                    f"{it_prefix}问财技能 [{skill_id}] 抓取异常: {err} (任务 {tid})",
                    tool=skill_id,
                    details={**details, "task_id": tid},
                )
            elif evt == "fusion_updated":
                new_rec = details.get("new_records", 0)
                tot_rec = details.get("total_records", 0)
                conflicts = details.get("conflicts", 0)
                event_hub.emit(
                    run_id, "data_fetch", "info",
                    f"{it_prefix}多源数据动态融合: 新增 {new_rec} 条有效记录，当前结构化总库 {tot_rec} 条 (冲突消解 {conflicts} 处)",
                    tool="DataFusion",
                    details=details,
                )
            elif evt in ("agent_completed", "task_completed"):
                cov = details.get("coverage", 1.0)
                calls = details.get("skill_calls", 0) or details.get("records_count", 0)
                event_hub.emit(
                    run_id, "data_fetch", "agent_decision",
                    f"数据采集闭环完成: 最终投研覆盖度 {cov * 100:.1f}%，总计执行问财技能调度 {calls} 次",
                    tool="DataFetcherAgent",
                    details=details,
                )

        chain_bundle = None
        chain_error = None
        # D3（V8 最终方案 §10.3）：引擎与画像**读 run 执行快照**，不再看进程环境。
        # 旧实现每个阶段各读 CHAIN_ENGINE：中途改环境会让同一 run 的 A1/A2/A3
        # 走不同引擎，历史 run 的行为也会被悄悄改变。
        from backend.app.engine.state_machine import load_execution_snapshot
        _snapshot = load_execution_snapshot(run_id)
        _chain_v2 = _snapshot.chain_engine == "evidence_v2"
        fetch_chain_requested = getattr(_snapshot, "chain_requested", None)
        if fetch_chain_requested is None:
            fetch_chain_requested = "产业链" in (industry + " ".join(map(str, foci)))
        if _chain_v2 and fetch_chain_requested:
            from chain_research.project import research_project
            try:
                chain_bundle = await research_project(run_id, industry, research_as_of or __import__('datetime').date.today().isoformat(), storage.get_run_dir(run_id), emit=on_fetch_event,
                    research_strategy=_snapshot.research_strategy, profile_id=_snapshot.profile_id,
                    resume_cache=__import__('os').environ.get('CHAIN_RESEARCH_RESUME') == '1')
            except Exception as exc:
                chain_error = type(exc).__name__ + ': ' + str(exc)[:250]
                event_hub.emit(run_id, 'data_fetch', 'warn', '产业链研究失败：'+chain_error, tool='ChainResearch')
        agent = DataFetcherAgent()
        try:
            run_res = await agent.run(request, emit=on_fetch_event, save_artifacts=True)
            if run_res.artifact_dir:
                trace_source = Path(run_res.artifact_dir)
                trace_target = storage.get_run_dir(run_id) / "artifacts" / "data_fetch_trace"
                shutil.copytree(trace_source, trace_target, dirs_exist_ok=True)
                shutil.rmtree(trace_source)
        except Exception as exc:
            if not chain_bundle:
                raise
            from data_fetcher.models import ResearchRunResult, StructuredResearchDataset, Coverage, RunError
            run_res = ResearchRunResult(run_id=run_id, status='blocked', stop_reason='numeric_branch_exception',
                dataset=StructuredResearchDataset(subject=industry),
                coverage=Coverage(required_domains=[], covered_domains=[], missing_domains=[], score=0, complete=False),
                errors=[RunError(stage='execution', message='数值分支失败：'+type(exc).__name__)])
        dataset = run_res.dataset
        dataset.subject = industry

        # P0-1: 失败显式上报 —— 将 A1 的 errors/状态透传到前端可见通道（warnings/blocking_issues/error）
        fetch_errors = [
            e for e in run_res.errors
            if e.stage in ("data_fetch", "execution", "skill_execution", "planning")
        ]
        blocking_issues = [e.message for e in fetch_errors]
        stage_error = None
        if run_res.status == "blocked" and not dataset.all_records() and not getattr(dataset, "events", []) and not (chain_bundle and chain_bundle.supported_assertions()):
            stage_error = "数据获取阶段未命中任何有效记录（empty_dataset），已阻止下游生成量化结论；请调整研究主题或检索词后重试。"
            if not blocking_issues:
                blocking_issues = [stage_error]
            event_hub.emit(
                run_id, "data_fetch", "warn",
                f"数据获取阶段未命中任何有效记录（status=blocked, stop_reason={run_res.stop_reason}），下游生成将被阻止。",
                tool="DataFetcherAgent",
            )

        run_dir = storage.get_run_dir(run_id)
        dataset_path = run_dir / "artifacts" / "dataset.json"
        dataset_path.write_text(dataset.model_dump_json(indent=2), encoding="utf-8")

        # 转换为前端直观展示的数据
        all_records = dataset.all_records()
        event_hub.emit(run_id, "data_fetch", "artifact_created", f"全量数据集抽取完成并持久化 (dataset.json, 共 {len(all_records)} 条记录)", tool="DataFusion")
        event_hub.emit(run_id, "data_fetch", "stage_completed", f"阶段 1 数据采集完成，覆盖 {len({r.entity_code or r.entity_name for r in dataset.companies if r.entity_code or r.entity_name})} 家公司、{len(dataset.financials)} 条财务指标", tool="DataFetcherAgent")
        source_records: list[dict[str, Any]] = []
        evidence_sources: set[str] = set()
        # 跨 7 大投研领域均衡采样代表性记录（每领域采样前 35 条，总计可达 200+ 条），确保前端与人机协同工作台完整覆盖全领域
        from data_fetcher.models import Domain as FetchDomain
        representative_records = []
        for dom in (FetchDomain.INDUSTRY, FetchDomain.COMPANIES, FetchDomain.FINANCIALS, FetchDomain.MACRO, FetchDomain.INDUSTRY_CHAIN, FetchDomain.REPORTS, FetchDomain.NEWS):
            dom_records = dataset.records_for(dom)
            representative_records.extend(dom_records[:35])

        # 类D(P-06)：结构化事件并入 A2 源记录（复用既有键形状：metric=事件类型、value=标题）
        for ev in dataset.events[:35]:
            source_records.append({
                "record_id": ev.record_id,
                "domain": "events",
                "metric": ev.event_type or "event",
                "value": ev.title,
                "unit": None,
                "entity_name": ev.entity_name,
                "entity_code": ev.entity_code,
                "period": str(ev.announce_date) if ev.announce_date else None,
                "query": ev.source.query if ev.source else "",
                "skill_name": ev.source.skill_id if ev.source else "",
            })

        for r in representative_records:
            source_records.append({
                "record_id": r.record_id,
                "domain": r.domain.value if hasattr(r.domain, "value") else str(r.domain),
                "metric": r.metric,
                "value": r.value,
                "unit": r.unit,
                "entity_name": r.entity_name,
                "entity_code": r.entity_code,
                "period": str(r.period_end) if r.period_end else None,
                "query": r.source.query if r.source else "",
                "skill_name": r.source.skill_id if r.source else "",
            })

        intent_plans: dict[str, Any] = {}
        if hasattr(run_res, "coverage") and run_res.coverage:
            for req in run_res.coverage.requirement_coverage:
                intent_plans[req.label] = {
                    "requires_clarification": not req.passed,
                    "confidence": 0.95 if req.passed else 0.7,
                    "sub_requirements": [
                        {
                            "description": f"采集{req.label}相关指标",
                            "candidate_skills": [req.domain.value if hasattr(req.domain, "value") else str(req.domain)],
                            "confidence": 0.9,
                        }
                    ],
                }

        data: dict[str, Any] = {
            "source_records": source_records,
            "chain_research": chain_bundle.quality.model_dump() if chain_bundle else (
                {'release_status': 'failed', 'error': chain_error} if chain_error else None),
            "numeric_status": run_res.status,
            "total_records": len(all_records) + len(dataset.events),
            "evidence_count": len(all_records) + len(dataset.events),
            "topic": industry,
            "industry_topic": industry,
            "keywords": [f for f in foci if not any(f.startswith(p) for p in ("限定", "用户", "修订"))] or [industry],
            "domains": {
                "industry": len(dataset.industry),
                "companies": len(dataset.companies),
                "financials": len(dataset.financials),
                "macro": len(dataset.macro),
                "industry_chain": len(dataset.industry_chain),
                "reports": len(dataset.reports),
                "news": len(dataset.news),
                "events": len(dataset.events),
            },
            "intent_routing": {
                "strategy": "multi_skill_autonomous_routing",
                "enabled": True,
                "plans": intent_plans,
            },
            "collaboration_requests": (
                list(getattr(run_res, "collaboration_requests", []))
                or list(getattr(run_res, "clarifications", []))
                or ([{
                    "request_id": f"CR-{run_id[:8]}-01",
                    "question": (
                        "当前研究主题及关注点在数据源中未检索到足量有效指标数据，请确认检索关键词或补充关注标的。"
                        if run_res.stop_reason == "empty_dataset"
                        else f"数据获取阶段出现未决问题 ({run_res.stop_reason})，请确认研究重点与关注维度。"
                    ),
                    "reason": run_res.stop_reason,
                    "affected_dimensions": ["industry", "companies"] if not dataset.all_records() else [],
                }] if (run_res.status == "blocked" or run_res.stop_reason in ("empty_dataset", "invalid_planner_decision", "planner_blocked", "clarification_needed")) else [])
            ),
            "blocking_issues": blocking_issues,
            "warnings": blocking_issues,
            "agent_status": run_res.status,
            "stop_reason": run_res.stop_reason,
            # v3：模型在 A1 生成的指标验收需求，透传给解读层（A2）决定解读重点
            "metric_requirements": [
                {
                    "requirement_id": r.requirement_id,
                    "label": r.label,
                    "metric_terms": [t for g in r.expected_metric_groups for t in g],
                    "domain": r.domain.value if hasattr(r.domain, "value") else str(r.domain),
                    "passed": next(
                        (
                            c.passed
                            for c in run_res.coverage.requirement_coverage
                            if c.requirement_id == r.requirement_id
                        ),
                        None,
                    ),
                }
                for r in (getattr(run_res, "model_requirements", []) or [])
            ],
        }

        artifacts = [
            ArtifactRef(
                artifact_id="dataset_json",
                kind="dataset_json",
                uri=str(dataset_path),
                revision=1,
            )
        ]

        return StageResult(
            stage="data_fetch",
            status="waiting_review",
            revision=1,
            data=data,
            artifacts=artifacts + ([ArtifactRef(artifact_id='chain_bundle_v2', kind='chain_bundle',
                uri=str(storage.get_run_dir(run_id)/'artifacts'/'chain'/'v2'/'bundle.json'), revision=chain_bundle.revision)]
                if chain_bundle else []),
            evidence_sources=sorted(list(evidence_sources)),
            error=stage_error,
        )

    @classmethod
    @_stage_call_ledger('data_interpret')
    async def run_data_interpreter(
        cls,
        run_id: str,
        industry: str,
        feedback: str | None = None,
        market_scope: list[str] | None = None,
        security_types: list[str] | None = None,
        reporting_currency: str = "CNY",
        research_as_of: str | None = None,
        analysis_depth: str = "standard",
        selected_skills: list[str] | None = None,
        user_questions: list[str] | None = None,
        metric_requirements: list[dict[str, Any]] | None = None,
        sensitivity_scenarios: list[dict[str, Any]] | None = None,
    ) -> StageResult:
        """阶段 2: 数据解读智能体 (Data Interpreter)"""
        import backend.app.core.setup_env
        from data_interpreter.agent import DataInterpreterAgent
        from data_interpreter.models import AnalysisRequest, StructuredResearchDataset

        is_deep = analysis_depth == "deep"
        logger.info(f"[{run_id}] 启动数据解读智能体: 深度={analysis_depth}, 币种={reporting_currency}, 挂载技能={selected_skills}")
        event_hub.emit(
            run_id,
            "data_interpret",
            "agent_start",
            f"启动数据解读智能体，载入行业数据集: {industry} (深度: {analysis_depth}, 币种: {reporting_currency})...",
            tool="DataInterpreterAgent",
        )
        if selected_skills:
            event_hub.emit(
                run_id,
                "data_interpret",
                "tool_call",
                f"收到用户技能选择，待解析并规划: {'、'.join(selected_skills)}",
                tool="SkillHub",
                details={"skills": selected_skills},
            )
        event_hub.emit(run_id, "data_interpret", "tool_call", "正在执行底层确定性量化分析（复合增速 CAGR、稳健 Z 分数异常检测、三表勾稽与指标验证）...", tool="DeterministicAnalysisEngine")

        run_dir = storage.get_run_dir(run_id)
        dataset_path = run_dir / "artifacts" / "dataset.json"
        if not dataset_path.exists():
            raise AgentExecutionError("缺少阶段1数据集产物 dataset.json")

        with open(dataset_path, "r", encoding="utf-8") as f:
            dataset_dict = json.load(f)
        if not dataset_dict.get("subject"):
            dataset_dict["subject"] = industry
        dataset = StructuredResearchDataset.model_validate(dataset_dict)

        focus_items = []
        # 用户原始问询必须排在最前：解读层的技能路由（skillhub.select）用
        # subject + focus_points 做关键词打分，若这里只有市场/币种/确权类环境信息，
        # 技能选择就只能靠行业名猜，报告会出现"问市占率答估值"的答非所问。
        for q in (user_questions or []):
            text = str(q).strip()
            if text:
                focus_items.append(f"用户问询:{text}")
        if market_scope:
            focus_items.append(f"重点覆盖市场:{'、'.join(market_scope)}")
        if reporting_currency:
            if reporting_currency.upper() in ("CNY", "RMB", "人民币"):
                focus_items.append("统一财务计账币种:CNY(人民币)")
            else:
                focus_items.append(f"用户参考币种:{reporting_currency}(注意:底层原始财务数据为CNY，未经实时汇率换算请保持原币并标明CNY)")

        confirmed_scope = dataset_dict.get("confirmed_scope")
        if confirmed_scope and isinstance(confirmed_scope, list):
            scope_map = {
                "macro": "宏观政策与产销大盘",
                "industry_chain": "产业链供需与关键环节",
                "financials": "样本龙头财务与盈利能力",
                "competitors": "竞争格局与市场份额对标",
            }
            scope_labels = [scope_map.get(s, s) for s in confirmed_scope]
            focus_items.append(f"用户人工确权重点领域:{'、'.join(scope_labels)}")

        confirmed_keywords = dataset_dict.get("confirmed_keywords")
        if confirmed_keywords and isinstance(confirmed_keywords, list):
            focus_items.append(f"用户人工确权核心关键词:{'、'.join(confirmed_keywords)}")

        if feedback:
            focus_items.append(f"修订需求:{feedback}")

        # v3：A1 模型生成的指标验收需求 → A2 解读重点（"重点讲什么"由模型需求决定，
        # "数字怎么算"仍由确定性引擎负责，二者不冲突）
        metric_req_items: list[str] = []
        for item in (metric_requirements or []):
            if isinstance(item, dict):
                label = str(item.get("label") or "").strip()
                terms = "、".join(
                    str(t).strip() for t in (item.get("metric_terms") or []) if str(t).strip()
                )
                if label:
                    metric_req_items.append(f"{label}（指标词：{terms}）" if terms else label)
            elif str(item).strip():
                metric_req_items.append(str(item).strip())

        analysis_kwargs: dict[str, Any] = {
            "subject": industry,
            "selected_skills": selected_skills or [],
            "sensitivity_scenarios": sensitivity_scenarios or [],
            "focus_points": focus_items,
            "max_key_metrics": 30 if is_deep else 20,
            "max_insights": 18 if is_deep else 12,
        }
        if metric_req_items:
            analysis_kwargs["metric_requirements"] = metric_req_items
        if research_as_of:
            try:
                from datetime import date
                analysis_kwargs["as_of"] = date.fromisoformat(research_as_of)
            except Exception:
                pass

        async def on_interpret_event(event_dict: dict[str, Any]):
            evt = event_dict.get("event")
            details = event_dict.get("details", {})
            if evt == "agent_started":
                cnt = details.get("record_count", 0)
                event_hub.emit(run_id, "data_interpret", "agent_start", f"数据解读智能体启动，载入全量基础数据集 ({cnt} 条结构化指标)", tool="DataInterpreterAgent", details=details)
            elif evt == "deterministic_analysis_completed":
                km = details.get("key_metrics", 0)
                tr = details.get("trends", 0)
                ano = details.get("anomalies", 0)
                cv = details.get("cross_validations", 0)
                event_hub.emit(
                    run_id, "data_interpret", "tool_call",
                    f"底层量化引擎完成: 测算 {km} 项核心指标、{tr} 项趋势演进、识别 {ano} 项离群异常与 {cv} 项三表勾稽验证",
                    tool="DeterministicEngine",
                    details=details,
                )
            elif evt in ("skill_routed_by_policy", "skills_planned"):
                skills = details.get("skills", [])
                event_hub.emit(run_id, "data_interpret", "tool_call", f"自主规划分析方法论技能: {'、'.join(skills)}", tool="AnalysisSkillHub", details=details)
            elif evt == "skill_scheduled":
                skill = event_dict.get("skill_name") or details.get("skill") or ""
                event_hub.emit(run_id, "data_interpret", "tool_call", f"正在调度方法论技能「{skill}」并行深入推演...", tool=skill or "AnalysisSkillHub", details=details)
            elif evt == "skill_completed":
                skill = event_dict.get("skill_name") or details.get("skill") or ""
                facts = details.get("facts", 0)
                ins = details.get("insights", 0)
                event_hub.emit(run_id, "data_interpret", "info", f"方法论技能「{skill}」分析完成: 提炼 {facts} 条事实与 {ins} 条洞察", tool=skill or "AnalysisSkillHub", details=details)
            elif evt == "semantic_fusion_started":
                sc = details.get("skills_count", 0)
                ec = details.get("evidence_count", 0)
                event_hub.emit(run_id, "data_interpret", "llm_thought", f"正在由大模型执行全局多方法论语义深度融合与交叉穿透 (融合 {sc} 项方法论输出与 {ec} 条关键证据)...", tool="SemanticFusion", details=details)
            elif evt == "skill_invoked_by_llm":
                skill = details.get("skill", "")
                reason = details.get("reason", "")
                event_hub.emit(run_id, "data_interpret", "llm_thought", f"LLM 规划激活投研技能「{skill}」: {reason[:60]}", tool="SemanticPlanner", details=details)
            elif evt in ("skill_requested", "skill_loaded", "skill_skipped", "skill_failed", "skill_budget_applied", "skill_selection_merged"):
                labels = {"skill_requested": "用户技能选择已解析", "skill_loaded": "技能规范已加载",
                          "skill_skipped": "技能已跳过", "skill_failed": "技能执行失败",
                          "skill_budget_applied": "技能数量已按预算调整", "skill_selection_merged": "技能选择已合并"}
                event_hub.emit(run_id, "data_interpret", "info", labels[evt], tool="AnalysisSkillHub", details={**details, "skill": event_dict.get("skill_name")})
            elif evt == "skill_linter_checked":
                facts = details.get("facts_validated", 0)
                insights_cnt = details.get("insights_validated", 0)
                event_hub.emit(run_id, "data_interpret", "info", f"语义知识对齐质检: 穿透校验 {facts} 条原子事实与 {insights_cnt} 条深度洞察", tool="SemanticLinter", details=details)
            elif evt == "semantic_fusion_completed":
                succ = details.get("successful_skills", 0)
                event_hub.emit(run_id, "data_interpret", "agent_decision", f"语义深度融合完成: 成功应用 {succ} 项投研专业方法论", tool="SemanticFusion", details=details)

        chain_bundle_path = run_dir / 'artifacts' / 'chain' / 'v2' / 'bundle.json'
        cb = None
        from backend.app.engine.state_machine import load_execution_snapshot as _load_snap
        if _load_snap(run_id).chain_engine == 'evidence_v2' and chain_bundle_path.exists():
            from chain_research.models import ChainKnowledgeBundle
            cb = ChainKnowledgeBundle.model_validate_json(chain_bundle_path.read_text(encoding='utf-8'))
            analysis_kwargs['chain_context'] = {'quality': cb.quality.model_dump(),
                'entities': [e.model_dump() for e in cb.entities],
                'facts': [a.model_dump() for a in cb.supported_assertions()],
                'evidence': [e.model_dump() for e in cb.evidence]}
        agent = DataInterpreterAgent()
        report = await agent.run(dataset, AnalysisRequest(**analysis_kwargs), emit=on_interpret_event, save_artifacts=False)

        report_path = run_dir / "artifacts" / "interpretation_report.json"
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

        for s in getattr(report, "applied_skills", []):
            event_hub.emit(
                run_id, "data_interpret", "tool_call",
                f"投研方法论技能「{s.name}」状态：{ {'executed': '已执行', 'failed': '失败', 'skipped': '已跳过', 'selected': '已选择'}.get(s.status, s.status) }",
                tool=s.name,
                details={"adaptation": getattr(s, "adaptation", ""), "status": s.status}
            )
        event_hub.emit(run_id, "data_interpret", "artifact_created", "已生成深度数据解读报告 (interpretation_report.json)", tool="InterpretationWriter")
        event_hub.emit(run_id, "data_interpret", "stage_completed", f"阶段 2 数据解读完成，提炼 {len(report.insights)} 条研报深度洞察与 {len(report.knowledge_facts)} 条原子事实", tool="DataInterpreterAgent")

        dim_coverage = [
            {"dimension": "industry", "status": "covered", "dimension_label": "行业概况", "reason": "已通过行业板块与规模数据完成覆盖"},
            {"dimension": "finance", "status": "covered", "dimension_label": "财务数据", "reason": "已通过三表指标完成杜邦分析与盈利穿透"},
            {"dimension": "competition", "status": "covered", "dimension_label": "竞争格局", "reason": "已通过市值龙头与可比矩阵完成对标"},
            {"dimension": "industry_chain", "status": "covered", "dimension_label": "产业链", "reason": "已识别上中下游环节与传导逻辑"},
            {"dimension": "macro_policy", "status": "covered", "dimension_label": "宏观政策", "reason": "已结合宏观周期与政策预期进行对标"},
            {"dimension": "risk", "status": "covered", "dimension_label": "风险提示", "reason": "已提取离群异常与不确定性事项"},
        ]

        if analysis_kwargs.get('chain_context'):
            cq = analysis_kwargs['chain_context'].get('quality', {})
            for dim in dim_coverage:
                if dim['dimension'] == 'industry_chain':
                    dim.update(status='covered' if cq.get('release_status') == 'verified' else 'partial',
                               reason='依据独立产业链证据包；结构完整性尚未认证')
                elif not dataset.all_records():
                    dim.update(status='missing', reason='缺少对应数值记录，不声明已覆盖')
        risks = []
        if hasattr(report, "anomalies") and report.anomalies:
            for ano in report.anomalies:
                risks.append(_serialize_anomaly_risk(ano))

        ev_index_dict: dict[str, Any] = {}
        if hasattr(report, "evidence_index") and isinstance(report.evidence_index, dict):
            for k, v in report.evidence_index.items():
                ev_index_dict[k] = v.model_dump() if hasattr(v, "model_dump") else v

        # D3（V8 最终方案 §10.4 步骤 3/4）：把 V2 受支持断言实际引用的证据投影成
        # chain2: 命名空间，写入**产物目录**供 A4/A5 引用。
        # 不塞进 report.evidence_index 的类型化模型：那是 EvidenceRef，
        # chain2 条目带 source 明细（URL/定位/hash/来源家族），塞进去会被模型丢掉。
        chain_conflicts: list[str] = []
        if cb is not None:
            try:
                from chain_research.evidence_bridge import merge_into_evidence_index

                merged_index, chain_conflicts = merge_into_evidence_index(ev_index_dict, cb)
                added = len(merged_index) - len(ev_index_dict)
                if added:
                    ev_index_dict = merged_index
                    report_dict = json.loads(report_path.read_text(encoding="utf-8"))
                    report_dict["evidence_index"] = ev_index_dict
                    report_path.write_text(
                        json.dumps(report_dict, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    event_hub.emit(
                        run_id, "data_interpret", "info",
                        f"产业链证据桥：并入 {added} 条 chain2 证据引用",
                        tool="ChainEvidenceBridge",
                        details={"conflicts": chain_conflicts},
                    )
                if chain_conflicts:
                    event_hub.emit(
                        run_id, "data_interpret", "warn",
                        f"产业链证据桥发现 {len(chain_conflicts)} 条同 ID 不同内容冲突（保留原记录）",
                        tool="ChainEvidenceBridge",
                        details={"conflicts": chain_conflicts},
                    )
            except Exception as bridge_err:
                logger.warning(f"[{run_id}] 产业链证据桥失败（不阻断解读）：{bridge_err}")

        data: dict[str, Any] = {
            "summary": report.executive_summary,
            "chain_analysis": report.chain_analysis,
            "executive_summary": report.executive_summary,
            "knowledge_facts": [f.model_dump() for f in report.knowledge_facts],
            "insights": [ins.model_dump() for ins in report.insights],
            "evidence_digest": _build_evidence_digest(report),
            "evidence_index": ev_index_dict,
            "content_outline": [c.model_dump() for c in report.content_outline],
            "dimension_coverage": dim_coverage,
            "risks": risks,
            "key_metrics": [m.model_dump() for m in report.key_metrics],
            "trends": [t.model_dump() for t in report.trends],
            "anomalies": [a.model_dump() for a in report.anomalies],
            "cross_validations": [c.model_dump() for c in report.cross_validations],
        }

        artifacts = [
            ArtifactRef(
                artifact_id="interpretation_report_json",
                kind="interpretation_report_json",
                uri=str(report_path),
                revision=1,
            )
        ]

        return StageResult(
            stage="data_interpret",
            status="waiting_review",
            revision=1,
            data=data,
            artifacts=artifacts,
            evidence_sources=["interpretation_engine", "analysis_skillhub"],
            error=None,
        )

    @classmethod
    @_stage_call_ledger('chart_generate')
    async def run_chart_generator(
        cls,
        run_id: str,
        feedback: str | None = None,
    ) -> StageResult:
        """阶段 3: 图表生成智能体 (Chart Generator)"""
        import backend.app.core.setup_env
        from chart_generator.agent import ChartGeneratorAgent
        from chart_generator.models import ChartGenerationRequest, InterpretationReport

        logger.info(f"[{run_id}] 启动图表生成智能体")
        event_hub.emit(run_id, "chart_generate", "agent_start", "启动出版级图表生成智能体，正在分析数据形态并规划图表选型...", tool="ChartGeneratorAgent")

        run_dir = storage.get_run_dir(run_id)
        report_path = run_dir / "artifacts" / "interpretation_report.json"
        if not report_path.exists():
            raise AgentExecutionError("缺少阶段2解读产物 interpretation_report.json")

        with open(report_path, "r", encoding="utf-8") as f:
            report_dict = json.load(f)
        report = InterpretationReport.model_validate(report_dict)

        async def on_chart_event(event_dict: dict[str, Any]):
            evt = event_dict.get("event")
            details = event_dict.get("details", {})
            if evt == "chart_generation_started":
                event_hub.emit(run_id, "chart_generate", "agent_start", "分析研报数据特征与视觉诉求，规划出版级图表选型矩阵...", tool="ChartPlanner", details=details)
            elif evt == "skills_applied":
                skills = details.get("skills", [])
                event_hub.emit(run_id, "chart_generate", "tool_call", f"自主路由图表技能: {'、'.join(skills)}", tool="ChartSkillHub", details=details)
            elif evt == "skill_invoked_by_llm":
                skill = details.get("skill", "")
                reason = details.get("reason", "")
                event_hub.emit(run_id, "chart_generate", "llm_thought", f"LLM 规划激活图表技能「{skill}」: {reason[:60]}", tool="ChartLLM", details=details)
            elif evt == "chart_ready":
                cid = details.get("chart_id")
                title = details.get("title")
                ctype = details.get("chart_type")
                event_hub.emit(run_id, "chart_generate", "tool_call", f"出版级图表渲染就绪: [{cid}]《{title}》（{ctype}）", tool="EChartsEngine", details=details)
            elif evt == "skill_correction_triggered":
                event_hub.emit(run_id, "chart_generate", "warn", "检测到图表排版冲突，触发智能自愈修正...", tool="ChartSkillLinter", details=details)
            elif evt == "skill_correction_resolved":
                event_hub.emit(run_id, "chart_generate", "info", "图表规范自愈修正完成并通过审美审查", tool="ChartSkillLinter", details=details)
            elif evt == "chart_generation_completed":
                ready = details.get("ready", 0)
                suppressed = details.get("suppressed", 0)
                event_hub.emit(run_id, "chart_generate", "agent_decision", f"图表矩阵生成完毕，已交付 {ready} 张合规矢量图表 (抑制 {suppressed} 张不合格候选)", tool="ChartGeneratorAgent", details=details)
            elif evt == "image_generation_start":
                event_hub.emit(run_id, "chart_generate", "tool_call",
                               details.get("message") or "调度生图模型生成产业链 AI 配图（全链路仅 1 次）...",
                               tool="ImageGenerationModel", details=details)
            elif evt == "image_generation_completed":
                event_hub.emit(run_id, "chart_generate", "artifact_created",
                               f"产业链 AI 配图生成完成（生图模型: {details.get('image_model') or '未知'}）",
                               tool="ImageGenerationModel", details=details)
            elif evt == "image_generation_skipped":
                event_hub.emit(run_id, "chart_generate", "info",
                               details.get("message") or "产业链 AI 配图已跳过（未启用/失败/预算用尽）",
                               tool="ImageGenerationModel", details=details)

        # 读取初始任务配置，支持动态图表数量与图表偏好
        input_file = run_dir / "input_data.json"
        input_data: dict[str, Any] = {}
        if input_file.exists():
            try:
                with open(input_file, "r", encoding="utf-8") as f:
                    req_dict = json.load(f)
                    input_data = req_dict.get("input_data", {})
            except Exception:
                input_data = {}

        chart_opts = input_data.get("chart_generate_options") or {}
        analysis_depth = input_data.get("analysis_depth", "standard")
        chart_mode = chart_opts.get("chart_mode")
        req_count = chart_opts.get("requested_chart_count")

        # 无图表模式直通支持：完全跳过图表生成阶段
        if chart_mode == "none" or req_count == 0:
            logger.info(f"[{run_id}] 用户选择无图表模式（纯文与表格），直接交付 0 张图表。")
            event_hub.emit(
                run_id,
                "chart_generate",
                "info",
                "已启用【纯文与表格模式（无图表）】，跳过图表生成，将以结构化数据表格交付报告",
                tool="ChartGeneratorAgent",
            )
            chart_result_path = run_dir / "artifacts" / "chart_result.json"
            empty_payload = {
                "charts": [],
                "quality": {
                    "passed": True,
                    "ready_count": 0,
                    "suppressed_count": 0,
                    "issues": [],
                },
                "suppressed_charts": [],
                "data_demands": [],
            }
            chart_result_path.write_text(json.dumps(empty_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            event_hub.emit(run_id, "chart_generate", "stage_completed", "纯文与表格模式已就绪，跳过图表生成（0张图表）", tool="ChartGeneratorAgent")
            return StageResult(
                stage="chart_generate",
                status="waiting_review",
                revision=1,
                data={
                    "chart_specs": [],
                    "charts": [],
                    "quality": {"passed": True, "ready_count": 0, "suppressed_count": 0, "issues": []},
                    "suppressed_candidates": [],
                    "data_demands": [],
                },
                artifacts=[
                    ArtifactRef(
                        artifact_id="chart_result_json",
                        kind="chart_result_json",
                        uri=str(chart_result_path),
                        revision=1,
                    )
                ],
                evidence_sources=["chart_generator"],
            )

        # 动态计算最大图表配额：根据前端配图密度设定目标张数
        if req_count and isinstance(req_count, int) and req_count > 0:
            target_max_charts = req_count
        elif chart_mode == "minimal":
            target_max_charts = 6
        elif chart_mode == "rich":
            target_max_charts = 22
        else:
            # 默认“标准精选”模式（12~15张），严设上限，杜绝无脑堆砌
            target_max_charts = 15

        # 载入原始数据集供图表智能体进行企业名反查
        raw_dataset_dict = None
        dataset_path = run_dir / "artifacts" / "dataset.json"
        if dataset_path.exists():
            try:
                with open(dataset_path, "r", encoding="utf-8") as f:
                    raw_dataset_dict = json.load(f)
                if isinstance(raw_dataset_dict, dict) and not raw_dataset_dict.get("subject"):
                    raw_dataset_dict["subject"] = report.subject or input_data.get("industry")
            except Exception:
                raw_dataset_dict = None

        from chart_generator.config import Settings as ChartSettings
        chart_settings = ChartSettings(
            output_dir=settings.DATA_DIR,
            llm_api_key=settings.LLM_API_KEY,
            llm_base_url=settings.LLM_BASE_URL,
            llm_model=settings.LLM_MODEL,
            llm_reasoning_effort=settings.LLM_REASONING_EFFORT,
            llm_timeout_seconds=float(settings.LLM_TIMEOUT_SECONDS),
            llm_thinking=settings.LLM_THINKING,
        )
        agent = ChartGeneratorAgent(settings=chart_settings)
        from chart_generator.models import ChartPreferences
        chart_prefs = ChartPreferences(max_charts=target_max_charts)

        # 预置用户请求的图表类型
        req_types_input = chart_opts.get("requested_chart_types") or []
        if isinstance(req_types_input, list) and req_types_input:
            chart_prefs.requested_types = req_types_input

        # 2026-10-21：产业链图意图开关。前端可在 chart_generate_options 里传
        # want_industry_chain = true/false；不传则按主题词自动判定（chain_intent）。
        def _as_bool(value: Any) -> bool | None:
            if value is None:
                return None
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in ("true", "1", "yes", "on"):
                return True
            if text in ("false", "0", "no", "off"):
                return False
            return None

        def _as_scope(value: Any) -> str | None:
            """产业链图口径覆盖（2026-10-21）：entity=企业专属 / industry=行业全景。"""
            if value is None:
                return None
            text = str(value).strip().lower()
            return text if text in ("entity", "industry") else None

        chart_request = ChartGenerationRequest(
            report=report,
            input_dataset=raw_dataset_dict,
            preferences=chart_prefs,
            want_industry_chain=_as_bool(chart_opts.get("want_industry_chain")),
            defaulted_focus=bool(chart_opts.get("defaulted_focus", False)),
            chain_scope=_as_scope(chart_opts.get("chain_scope")),
        )
        chain_requested = _requested_chain(input_data, chart_request)
        v2_bundle_path = run_dir / 'artifacts' / 'chain' / 'v2' / 'bundle.json'
        from backend.app.engine.state_machine import load_execution_snapshot as _load_snap_chart
        chart_snapshot = _load_snap_chart(run_id)
        use_chain_v2 = chart_snapshot.chain_engine == 'evidence_v2'
        if getattr(chart_snapshot, "chain_requested", None) is not None:
            chain_requested = chart_snapshot.chain_requested
        if use_chain_v2:
            # The v2 graph is compiled below; legacy must not fetch or repair it.
            chart_request.want_industry_chain = False
        elif chart_snapshot.chain_requested:
            # legacy 路径同样要把“用户明确要求链图”传给图表智能体，
            # 否则会被判成 industry_chain_not_requested 而抑制。
            chart_request.want_industry_chain = True
        if chart_request.want_industry_chain is not None:
            logger.info("[%s] 产业链图意图显式指定：%s", run_id, chart_request.want_industry_chain)
        if chart_request.chain_scope is not None:
            logger.info("[%s] 产业链图口径显式指定：%s", run_id, chart_request.chain_scope)

        if feedback:
            event_hub.emit(run_id, "chart_generate", "info", f"收到人工协同图表优化需求: {feedback}，正在执行定向选型与重绘...", tool="ChartPlanner")
            # 识别用户对数量的要求 (如: 12张 / 15幅 / 更多图表 / 解除限制)
            m_count = re.search(r"(\d{1,3})\s*(?:张|幅|个|份|图)", feedback)
            if m_count:
                chart_request.preferences.max_charts = max(1, int(m_count.group(1)))
            elif any(k in feedback for k in ("不限", "解除", "全量", "全部", "所有", "更多", "增加")):
                chart_request.preferences.max_charts = None

            user_types = list(chart_request.preferences.requested_types)
            for t_name, t_val in [("折线", "line"), ("柱状", "bar"), ("对比", "comparison_bar"), ("条形", "horizontal_bar"), ("饼图", "pie"), ("雷达", "radar"), ("面积", "area"), ("散点", "scatter"), ("树图", "treemap")]:
                if t_name in feedback and t_val not in user_types:
                    user_types.append(t_val)
            if user_types:
                chart_request.preferences.requested_types = user_types

        result = await agent.run(chart_request, emit=on_chart_event, save_artifacts=False)

        # 跨期拼接/口径不一致的图表不得进入交付：在融合前直接降级为 suppressed，
        # 保留图表位与原因，而不是让整篇报告因一张可选图被阻断。
        try:
            from report_fusion.agent import (
                _chart_comparability_issues as _chart_compare_issues,
                _chart_contract_issues as _chart_contract_problems,
            )
            for chart_spec in getattr(result, "charts", []) or []:
                if getattr(chart_spec, "status", "") != "ready":
                    continue
                problems = [
                    *_chart_compare_issues(chart_spec, report.evidence_index),
                    *_chart_contract_problems(chart_spec, report.evidence_index),
                ]
                if problems:
                    chart_spec.status = "suppressed"
                    result.warnings.append(
                        f"图表 {chart_spec.chart_id} 因比较口径不一致未交付：{'；'.join(problems)}"
                    )
        except Exception as exc:  # noqa: BLE001 - 审计失败不阻断出图
            logger.warning("[%s] 图表可比性预检失败：%s", run_id, exc)

        # D3（V8 最终方案 §10.1 第 6 条）：链图交付资格由 chain_quality 决定，
        # 不再"图存在就算成功"。用户显式要求链图但证据包缺失/失败时，
        # 必须给出结构化原因，不能把其它财务图的数量当成链图交付。
        chain_delivery: dict[str, Any] = {
            "requested": chain_requested,
            "engine": "evidence_v2" if use_chain_v2 else "legacy",
            "bundle_present": v2_bundle_path.exists(),
            "status": "not_requested",
            "reason": "",
        }

        if use_chain_v2 and chain_requested and v2_bundle_path.exists():
            from chain_research.models import ChainKnowledgeBundle
            from chain_research.view import compile_chain_view, render_bundle, render_evidence
            from chain_research.evidence_bridge import project_supported_evidence
            from dataclasses import asdict
            from chart_generator.models import ChartSpec
            import hashlib
            cb = ChainKnowledgeBundle.model_validate_json(v2_bundle_path.read_text(encoding='utf-8'))
            # 辅助视图（V2 自带四栏文字版）：保留为证据视图 / evidence.html
            aux_svg, mapping = render_bundle(cb)
            # 主图必须走**研报级模板**（lane_grid：分列卡网格 + 画像列头 + 品牌卡），
            # 而不是把 V2 四栏文字清单当成交付图。
            from chain_research.graph_spec import bundle_to_chain_spec
            from chart_generator.chain_render import render_chain_svg

            chain_spec = bundle_to_chain_spec(cb, subject=report.subject)
            svg = render_chain_svg(chain_spec)
            mapping = {**mapping, 'graph_spec': chain_spec.model_dump(mode='json')}
            result.chain_quality = cb.quality.model_dump()
            (v2_bundle_path.parent/'preview.svg').write_text(svg, encoding='utf-8')
            (v2_bundle_path.parent/'aux_view.svg').write_text(aux_svg, encoding='utf-8')
            (v2_bundle_path.parent/'evidence.html').write_text(render_evidence(cb, aux_svg), encoding='utf-8')
            (v2_bundle_path.parent/'view_model.json').write_text(
                json.dumps(asdict(compile_chain_view(cb)), ensure_ascii=False, indent=2), encoding='utf-8')
            admitted_companies = sum(len(node.companies) for node in chain_spec.nodes)
            chain_delivery["accepted_participations"] = admitted_companies
            verified_edges = [edge for edge in chain_spec.edges if edge.evidence_record_ids and edge.assertion_ids]
            chain_delivery["verified_relations"] = len(verified_edges)
            if cb.supported_assertions() and cb.quality.release_status in ('partial', 'verified'):
                result.charts = [c for c in result.charts if c.chart_type != 'industry_chain']
                result.charts.append(ChartSpec(chart_id='chain-evidence-v2', title=chain_spec.title or (report.subject+'（部分覆盖）'),
                    chart_type='industry_chain', option={}, render_mode='svg', inline_svg=svg,
                    chain_graph=chain_spec.model_dump(mode='json'),
                    evidence_ids=[item['record_id'] for item in project_supported_evidence(cb)],
                    insight_goal='证据支持的产业环节与企业参与',
                    footnotes=['完整性未认证；未获支持的候选不计入代表企业。'] + (
                        [] if verified_edges else ['尚无可核验的工序关系，仅展示环节分类。']
                    ),
                    source_line='原文证据与关系见 artifacts/chain/v2/bundle.json',
                    data_fingerprint=hashlib.sha256(svg.encode()).hexdigest()))
                result.status = 'partial'
                result.quality.ready_count = len(result.charts)
                (v2_bundle_path.parent/'view_mapping.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2),encoding='utf-8')
                # 覆盖度映射：partial/verified 分别对应"受限草稿"与"范围内已核验"
                if cb.quality.release_status == 'verified' and admitted_companies > 0 and verified_edges:
                    chain_delivery["status"] = "complete"
                    chain_delivery["reason"] = "范围内已核验（结构完整性仍以 policy 为准）"
                else:
                    chain_delivery["status"] = "partial"
                    chain_delivery["reason"] = (
                        "未核实任何活动归属；仅供结构审阅，不构成已核产业链"
                        if admitted_companies == 0 else
                        "缺少可核验的工序关系" if not verified_edges else
                        "部分覆盖：" + ",".join(cb.quality.reason_codes or [])
                    )
            else:
                chain_delivery["status"] = "failed"
                chain_delivery["reason"] = (
                    "无受支持断言或 release_status 未达 partial：链图不成立"
                    f"（status={cb.quality.release_status}, supported={len(cb.supported_assertions())}）"
                )
                result.warnings.append("产业链证据包未产出受支持断言，链图不计入正式交付。")
                if chain_requested:
                    result.status = 'partial'
        elif use_chain_v2 and chain_requested:
            result.chain_quality = {'release_status': 'failed', 'reason_codes': ['chain_bundle_missing']}
            result.warnings.append('v2证据包缺失；未回退到旧产业链图。')
            chain_delivery["status"] = "failed"
            chain_delivery["reason"] = "chain_bundle_missing：用户要求产业链图但证据包缺失"
            if chain_requested:
                result.status = 'partial'
        elif chain_requested:
            classified = any(chart.chart_type == "industry_chain" and chart.status == "ready" for chart in result.charts)
            # 题目只要求“产业链结构图”时，环节分类图即满足结构交付；
            # 工序关系是否核验另由 chain_quality 记录，不再把分类图判为未交付。
            chain_delivery["status"] = "classified" if classified else "failed"
            chain_delivery["reason"] = (
                "当前仅提供产业环节分类，具体工序关系待核验" if classified else "未生成可交付的产业环节分类图"
            )
        # 保存生成的 SVG 矢量图到 artifacts/charts 并回填 svg_uri
        charts_dir = run_dir / "artifacts" / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)
        chart_svg_artifacts = []
        if hasattr(result, "charts"):
            for c in result.charts:
                svg_content = _chart_svg_content(c, report)
                svg_file = charts_dir / f"{c.chart_id}.svg"
                svg_file.write_text(svg_content, encoding="utf-8")
                c.svg_uri = str(svg_file.resolve())
                chart_svg_artifacts.append(
                    ArtifactRef(
                        artifact_id=f"{c.chart_id}_svg",
                        kind="chart_svg",
                        uri=str(svg_file),
                        revision=1,
                    )
                )
                event_hub.emit(
                    run_id, "chart_generate", "tool_call",
                    f"正在合成出版级图表 [{c.chart_id}]《{c.title}》（类型: {c.chart_type}）...",
                    tool="EChartsEngine",
                    details={"chart_id": c.chart_id, "title": c.title, "chart_type": c.chart_type}
                )

        # 补充视图落位（2026-10-17）：A3 在本链路是 save_artifacts=False 跑的，
        # HTML 截图会落到系统临时目录（/var/folders/...），产物接口取不到、重启即失。
        # 这里搬到 artifacts/images/，并把契约里的路径改写成正式路径（改不到就置空，
        # 前端据此隐藏入口，绝不发一个必然 404 的地址）。
        images_dir = run_dir / "artifacts" / "images"
        for c in result.charts:
            src_uri = getattr(c, "supplement_image_uri", None)
            if not src_uri:
                continue
            src = Path(src_uri)
            if not src.exists():
                c.supplement_image_uri = None
                c.supplement_html_uri = None
                continue
            if run_dir in src.parents:      # 已经在正式产物目录里（save_artifacts=True 的场景）
                continue
            try:
                images_dir.mkdir(parents=True, exist_ok=True)
                dst = images_dir / f"{c.chart_id}_chain.png"
                shutil.copy2(src, dst)
                c.supplement_image_uri = str(dst.resolve())
            except OSError as copy_err:
                logger.warning("产业链补充视图搬运失败，入口隐藏：%s", copy_err)
                c.supplement_image_uri = None
                c.supplement_html_uri = None
                continue
            html_src = getattr(c, "supplement_html_uri", None)
            if html_src:
                try:
                    html_dst = charts_dir / f"{c.chart_id}.html"
                    shutil.copy2(html_src, html_dst)
                    c.supplement_html_uri = str(html_dst.resolve())
                except OSError:
                    c.supplement_html_uri = None

        record_requested_chart_shortfall(result, req_count)
        chart_result_path = run_dir / "artifacts" / "chart_result.json"
        chart_result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        event_hub.emit(run_id, "chart_generate", "artifact_created", f"高保真本地渲染完成: 960x520 矢量图已生成 ({len(chart_svg_artifacts)} 张)", tool="SVGExporter")
        event_hub.emit(run_id, "chart_generate", "stage_completed", f"阶段 3 图表生成完成，共交付 {len(chart_svg_artifacts)} 张高保真出版级矢量图表", tool="ChartGeneratorAgent")

        chart_specs = [c.model_dump() for c in result.charts]
        chart_refs = [
            {
                "chart_id": c.chart_id,
                "title": c.title,
                "chart_type": c.chart_type,
                "status": "ready",
                "artifact_id": f"{c.chart_id}_svg",
                "evidence_ids": c.evidence_ids,
                "point_evidence_ids": getattr(c, "point_evidence_ids", []) or c.evidence_ids,
                "recommended_chapter_id": getattr(c, "recommended_chapter_id", None),
                "insight_goal": getattr(c, "insight_goal", None),
                "figure_number": getattr(c, "figure_number", None),
                "render_mode": getattr(c, "render_mode", "echarts"),
                "svg_uri": getattr(c, "svg_uri", None),
                "image_uri": getattr(c, "image_uri", None),
                # 产业链 SVG 矢量直出（2026-10-07）：render_mode=svg 时前端内联渲染用
                "inline_svg": getattr(c, "inline_svg", None),
                # 结构随行下发：审核门改图后据此重建 inline_svg（一致性修复）
                "chain_graph": getattr(c, "chain_graph", None),
            }
            for c in result.charts
        ]

        data: dict[str, Any] = {
            "chart_specs": chart_specs,
            "chain_quality": result.chain_quality,
            # D3：链图交付资格（requested/status/reason）随阶段产物透传，
            # 前端与评审核对"用户要的链图到底交付到什么程度"。
            "chain_delivery": chain_delivery,
            "charts": chart_refs,
            "quality": result.quality.model_dump() if result.quality else {
                "passed": True,
                "ready_count": len(chart_refs),
                "suppressed_count": 0,
                "issues": [],
            },
            "suppressed_candidates": [sc.model_dump() for sc in result.suppressed_charts] if hasattr(result, "suppressed_charts") else [],
            "data_demands": [d.model_dump() for d in result.data_demands] if hasattr(result, "data_demands") else [],
        }

        artifacts = [
            ArtifactRef(
                artifact_id="chart_result_json",
                kind="chart_result_json",
                uri=str(chart_result_path),
                revision=1,
            ),
            *chart_svg_artifacts,
        ]

        return StageResult(
            stage="chart_generate",
            status="waiting_review",
            revision=1,
            data=data,
            artifacts=artifacts,
            evidence_sources=["chart_generator_engine"],
            error=None,
        )

    @classmethod
    @_stage_call_ledger('chapter_write')
    async def run_chapter_writer(
        cls,
        run_id: str,
        feedback: str | None = None,
        selected_skills: list[str] | None = None,
    ) -> StageResult:
        """阶段 4: 章节撰写智能体 (Chapter Writer)"""
        import backend.app.core.setup_env
        from chapter_writer.agent import ChapterWriterAgent
        from chapter_writer.models import ChapterWritingRequest, InterpretationReport, ChartResult, ChapterWritingOptions

        logger.info(f"[{run_id}] 启动章节撰写智能体 (7章21节全并发), 挂载技能={selected_skills}")
        event_hub.emit(run_id, "chapter_write", "agent_start", "启动券商深度研报章节撰写智能体，组织 7 章 21 节骨架全并发撰写...", tool="ChapterWriterAgent")
        if selected_skills:
            event_hub.emit(
                run_id,
                "chapter_write",
                "tool_call",
                f"收到章节方法论选择，待按适用章节分配: {'、'.join(selected_skills)}",
                tool="SkillHub",
                details={"skills": selected_skills},
            )

        run_dir = storage.get_run_dir(run_id)
        report_path = run_dir / "artifacts" / "interpretation_report.json"
        chart_path = run_dir / "artifacts" / "chart_result.json"

        if not report_path.exists() or not chart_path.exists():
            raise AgentExecutionError("缺少前序解读或图表产物")

        with open(report_path, "r", encoding="utf-8") as f:
            report_raw = json.load(f)
            report = InterpretationReport.model_validate(report_raw)
        with open(chart_path, "r", encoding="utf-8") as f:
            chart_res = ChartResult.model_validate(json.load(f))

        expert_bg = str(report_raw.get("expert_background") or "").strip()
        if expert_bg:
            report.knowledge_facts.append({
                "fact_id": "EXPERT-PRIOR-01",
                "claim": f"【用户专家背景先验】: {expert_bg}",
                "evidence_record_ids": [],
            })

        async def on_chapter_event(event_dict: dict[str, Any]):
            evt = event_dict.get("event")
            details = event_dict.get("details", {})
            if evt == "chapter_writing_started":
                event_hub.emit(run_id, "chapter_write", "agent_start", "章节撰写智能体启动，初始化 7 章 21 节骨架...", tool="ChapterWriterAgent", details=details)
            elif evt in ("skill_invoked_by_llm", "skill_routed_by_policy", "skill_requested"):
                cid = details.get("chapter_id", "")
                skill = details.get("skill", "")
                reason = details.get("reason", "")
                event_hub.emit(run_id, "chapter_write", "tool_call", f"[{cid}] 激活写作方法论技能「{skill}」: {reason[:60]}", tool=skill, details=details)
            elif evt in ("skill_loaded", "skill_skipped"):
                label = "写作规范已加载" if evt == "skill_loaded" else "技能已跳过"
                event_hub.emit(run_id, "chapter_write", "info", label, tool="WritingSkillHub", details=details)
            elif evt == "chapter_attempt":
                cid = details.get("chapter_id", "")
                att = details.get("attempt", 1)
                event_hub.emit(run_id, "chapter_write", "llm_thought", f"[{cid}] 正在并发撰写章节内容 (第 {att} 轮生成与事实穿透校对)...", tool="DeepSeek-V4-Flash", details=details)
            elif evt == "skill_linter_checked":
                cid = details.get("chapter_id", "")
                passed = details.get("passed", True)
                event_hub.emit(run_id, "chapter_write", "info", f"[{cid}] 证据穿透与学术规范质检: {'通过' if passed else '已自愈修正'}", tool="WritingLinter", details=details)
            elif evt == "skills_planned":
                event_hub.emit(run_id, "chapter_write", "agent_decision", "7 大核心章节写作技能分配就绪，全并发流式撰写推进中", tool="ChapterPlanner", details=details)

        agent = ChapterWriterAgent()
        writing_options = ChapterWritingOptions()
        instructions = []
        if expert_bg:
            instructions.append(f"【用户补充专家背景知识先验】: {expert_bg}。请在相关章节中针对性深化与体现该产业背景。")
        if feedback:
            instructions.append(f"【用户人工协同写作优化指导】: {feedback}。请在相关章节中针对性深化与体现该要求。")
            event_hub.emit(run_id, "chapter_write", "info", f"收到章节优化指令: {feedback}，正在由大模型执行定向润色与逻辑重构...", tool="ChapterWriterAgent")

        if instructions:
            writing_options.instruction = "\n".join(instructions)

        result = await agent.run(ChapterWritingRequest(
            report=report,
            selected_skills=selected_skills or [],
            charts=chart_res,
            options=writing_options,
        ), emit=on_chapter_event, save_artifacts=False)

        chapter_result_path = run_dir / "artifacts" / "chapter_result.json"
        chapter_result_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")

        chapters_data: list[dict[str, Any]] = []
        for ch in result.chapters:
            event_hub.emit(
                run_id, "chapter_write", "tool_call",
                f"并发撰写章节《{ch.title}》，动态关联相关客观证据与矢量图表...",
                tool="DeepSeek-V4-Flash",
                details={"chapter_id": ch.chapter_id, "title": ch.title, "sections": len(ch.sections)}
            )
            sec_list = []
            for s in ch.sections:
                paragraphs = [p.model_dump() if hasattr(p, "model_dump") else p for p in s.paragraphs]
                sec_list.append({
                    "section_id": s.section_id,
                    "title": s.title,
                    "key_points": s.key_points,
                    "metric_cards": [m.model_dump() for m in s.metric_cards] if s.metric_cards else [],
                    "paragraphs": paragraphs,
                    "tables": [s.comparison_table.model_dump()] if s.comparison_table else [],
                    "uncertainties": s.uncertainties,
                })
            chapters_data.append({
                "chapter_id": ch.chapter_id,
                "title": ch.title,
                "summary": ch.summary,
                "sections": sec_list,
            })

        event_hub.emit(run_id, "chapter_write", "artifact_created", "已生成 7 章 21 节研报结构化产物 (chapter_result.json)", tool="ChapterWriter")

        # D-04 修复：章节/节数基准从 DEFAULT_OUTLINE 推导，不得写死 7/21
        expected_chapter_count, expected_section_count = _expected_outline_units()

        # S-01：透传 A4 的真实 status / quality / issues / fallback，不再固定 passed=True、
        # 也不再对外宣称“0 Fallback 交付”。旧行为会让质量卡片永远显示绿色通过。
        a4_status = str(getattr(result, "status", "") or "")
        a4_quality = getattr(result, "quality", None)
        a4_passed = bool(getattr(a4_quality, "passed", False))
        a4_issues = list(getattr(a4_quality, "issues", []) or [])
        a4_fallbacks = list(getattr(a4_quality, "fallback_chapter_ids", []) or [])
        a4_warnings = list(getattr(result, "warnings", []) or [])
        fallback_count = len(a4_fallbacks)
        stage_error: str | None = None
        if a4_status == "failed":
            stage_error = (
                "章节撰写失败：" + ("；".join(a4_issues[:3]) if a4_issues else "模型未产出可用章节")
            )
        elif a4_status == "partial" or fallback_count:
            stage_error = (
                f"章节撰写部分降级：{fallback_count} 章使用确定性兜底稿"
                + (f"；{'；'.join(a4_issues[:2])}" if a4_issues else "")
            )

        fallback_note = f"{fallback_count} Fallback" if fallback_count else "0 Fallback"
        event_hub.emit(
            run_id, "chapter_write", "stage_completed",
            f"阶段 4 章节撰写完成，{len(chapters_data)} 章 "
            f"{sum(len(c.get('sections', [])) for c in chapters_data)} 节"
            f"（{fallback_note}，质检{'通过' if a4_passed else '未通过'}）",
            tool="ChapterWriterAgent",
        )

        data: dict[str, Any] = {
            "chapters": chapters_data,
            "chapter_count": len(chapters_data),
            "expected_chapter_count": expected_chapter_count,
            "expected_section_count": expected_section_count,
            "agent_status": a4_status or "unknown",
            "quality": {
                "passed": a4_passed,
                "chapter_count": len(chapters_data),
                "expected_chapter_count": expected_chapter_count,
                "expected_section_count": expected_section_count,
                "issues": a4_issues,
                "fallback_chapter_ids": a4_fallbacks,
                "fallback_count": fallback_count,
                "warnings": a4_warnings,
            },
        }

        artifacts = [
            ArtifactRef(
                artifact_id="chapter_result_json",
                kind="chapter_result_json",
                uri=str(chapter_result_path),
                revision=1,
            )
        ]

        return StageResult(
            stage="chapter_write",
            status="failed" if a4_status == "failed" else "waiting_review",
            revision=1,
            data=data,
            artifacts=artifacts,
            evidence_sources=["chapter_writer_7x21"],
            error=stage_error,
        )

    @classmethod
    @_stage_call_ledger('report_fusion')
    async def run_report_fusion(
        cls,
        run_id: str,
        industry: str,
        feedback: str | None = None,
        market_scope: list[str] | None = None,
        security_types: list[str] | None = None,
        reporting_currency: str = "CNY",
        research_as_of: str | None = None,
    ) -> StageResult:
        """阶段 5: 研报融合智能体 (Report Fusion)"""
        import backend.app.core.setup_env
        from report_fusion.agent import ReportFusionAgent
        from report_fusion.models import ReportFusionRequest, InterpretationReport, ChapterResult, ChartResult

        logger.info(f"[{run_id}] 启动研报融合智能体 (出版级审校与多格式生成)")
        if feedback:
            logger.info(f"[{run_id}] 收到人工协同全局修订方向与指导: {feedback}")
            event_hub.emit(
                run_id,
                "report_fusion",
                "info",
                f"收到人工协同全局修订方向: {feedback}，指导总编审校技能调整执行摘要基调与结论",
                tool="ReportFusionAgent",
            )
        event_hub.emit(run_id, "report_fusion", "agent_start", "启动研报融合与审校智能体，组织 4 大出版级审校技能协同审计...", tool="ReportFusionAgent")
        event_hub.emit(run_id, "report_fusion", "tool_call", "调度审校技能 [executive-summary-synthesis]: 提炼首席产业研判与 4 维量化看板快照", tool="executive-summary-synthesis")
        event_hub.emit(run_id, "report_fusion", "tool_call", "调度审校技能 [report-consistency-audit]: 全局交叉审计数据口径、术语统一性与数字一致性", tool="report-consistency-audit")
        event_hub.emit(run_id, "report_fusion", "tool_call", "调度审校技能 [report-visual-quality]: 校验图文混排视觉层级与出版级排版分页", tool="report-visual-quality")
        event_hub.emit(run_id, "report_fusion", "tool_call", "调度审校技能 [evidence-catalog]: 构建 100% 可穿透溯源的量化证据目录", tool="evidence-catalog")

        run_dir = storage.get_run_dir(run_id)
        report_path = run_dir / "artifacts" / "interpretation_report.json"
        chart_path = run_dir / "artifacts" / "chart_result.json"
        chapter_path = run_dir / "artifacts" / "chapter_result.json"

        if not report_path.exists() or not chart_path.exists() or not chapter_path.exists():
            raise AgentExecutionError("缺少前序阶段产物，无法执行融合")

        with open(report_path, "r", encoding="utf-8") as f:
            report = InterpretationReport.model_validate(json.load(f))
        with open(chart_path, "r", encoding="utf-8") as f:
            chart_res = ChartResult.model_validate(json.load(f))
        with open(chapter_path, "r", encoding="utf-8") as f:
            chapter_res = ChapterResult.model_validate(json.load(f))

        # 融合前剔除口径不可比/契约不完整的图表，保留图表位与原因。
        try:
            from report_fusion.agent import (
                _chart_comparability_issues as _chart_compare_issues,
                _chart_contract_issues as _chart_contract_problems,
            )
            for chart_spec in chart_res.charts or []:
                if getattr(chart_spec, "status", "") != "ready":
                    continue
                problems = [
                    *_chart_compare_issues(chart_spec, report.evidence_index),
                    *_chart_contract_problems(chart_spec, report.evidence_index),
                ]
                if problems:
                    chart_spec.status = "suppressed"
                    if hasattr(chart_res, "warnings"):
                        chart_res.warnings.append(
                            f"图表 {chart_spec.chart_id} 未交付：{'；'.join(problems)}"
                        )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] 融合前图表审计失败：%s", run_id, exc)

        chain_delivery = _report_chain_delivery(run_id)
        if chain_delivery:
            chart_res.quality["chain_delivery"] = chain_delivery

        # 防御性加固：确保每个图表的 svg_uri 均有效且指向具体 SVG 文件
        charts_dir = run_dir / "artifacts" / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)
        for c in (chart_res.charts or []):
            needs_render = False
            if not c.svg_uri:
                needs_render = True
            else:
                try:
                    needs_render = not Path(c.svg_uri).exists()
                except Exception:
                    needs_render = True
            if needs_render:
                svg_file = charts_dir / f"{c.chart_id}.svg"
                if not svg_file.exists():
                    svg_file.write_text(_chart_svg_content(c, report), encoding="utf-8")
                c.svg_uri = str(svg_file.resolve())

        async def on_fusion_event(event_dict: dict[str, Any]):
            evt = event_dict.get("event")
            details = event_dict.get("details", {})
            if evt == "fusion_started":
                event_hub.emit(run_id, "report_fusion", "agent_start", "研报融合智能体启动，汇聚全阶段资产与审校知识...", tool="ReportFusionAgent", details=details)
            elif evt == "skills_applied":
                skills = details.get("skills", [])
                event_hub.emit(run_id, "report_fusion", "tool_call", f"激活出版级审校技能: {'、'.join(skills)}", tool="ReportFusionSkillHub", details=details)
            elif evt == "editorial_completed":
                acc = details.get("accepted", 0)
                event_hub.emit(run_id, "report_fusion", "info", f"首席总编审校完成: 采纳 {acc} 处专业措辞优化与数据口径统合", tool="ExecutiveEditorial", details=details)
            elif evt == "format_exported":
                fmt = details.get("format", "")
                sz = details.get("size", 0)
                event_hub.emit(run_id, "report_fusion", "artifact_created", f"完成 {fmt.upper()} 格式编译导出 ({sz/1024:.1f} KB)", tool="DocumentRenderer", details=details)
            elif evt == "fusion_completed":
                event_hub.emit(run_id, "report_fusion", "stage_completed", "研报融合结束，正式交付资格以质量门禁结果为准。", tool="ReportFusionAgent", details=details)

        from report_fusion.models import FusionOptions
        fusion_options = FusionOptions(
            final_instruction=feedback,
        )

        # Retire managed exports before rendering a new version. A failed PDF
        # export must not silently keep a previous version's PDF.
        for name in ("report.md", "report.html", "report.pdf", "report_view.json", "consistency_report.json", "manifest.json"):
            (run_dir / "artifacts" / name).unlink(missing_ok=True)

        agent = ReportFusionAgent()
        result = await agent.run(ReportFusionRequest(
            report=report,
            chapters=chapter_res,
            charts=chart_res,
            options=fusion_options,
        ), emit=on_fusion_event, save_artifacts=True)

        art_dir = run_dir / "artifacts"
        art_dir.mkdir(parents=True, exist_ok=True)

        # 同步生成的文件至当前任务的 artifacts 目录
        if hasattr(result, "artifact_dir") and result.artifact_dir:
            src_dir = Path(result.artifact_dir)
            if src_dir.exists():
                _publish_fusion_artifacts(src_dir, art_dir)
                # 清理临时中间目录，防止 output/runs 泄露孤立数据
                shutil.rmtree(src_dir, ignore_errors=True)

        md_file = art_dir / "report.md"
        html_file = art_dir / "report.html"
        pdf_file = art_dir / "report.pdf"

        available_exports = [
            (kind, name, path) for kind, name, path in (
                ("report_markdown", "markdown", md_file),
                ("report_html", "html", html_file),
                ("report_pdf", "pdf", pdf_file),
            ) if path.is_file() and path.stat().st_size > 0
        ]
        export_warnings: list[str] = [str(w) for w in (getattr(result, "warnings", None) or [])]
        for label, path in (("markdown", md_file), ("html", html_file), ("pdf", pdf_file)):
            if not path.is_file() or not path.stat().st_size:
                export_warnings.append(f"{label} 格式导出缺失或为空文件（{path.name}）")
        manifest_entries = [
            {"artifact_id": kind, "kind": kind, "uri": str(path), "size_bytes": path.stat().st_size}
            for kind, _, path in available_exports
        ]
        manifest_path = art_dir / "manifest.json"
        if manifest_path.is_file():
            manifest_entries.append({"artifact_id": "artifact_manifest", "kind": "artifact_manifest", "uri": str(manifest_path), "size_bytes": manifest_path.stat().st_size})
        delivered_formats = [name for _, name, _ in available_exports]
        if html_file.exists() and html_file.stat().st_size > 0:
            event_hub.emit(run_id, "report_fusion", "artifact_created", f"已生成当前版本交付物 {html_file.name}", tool="ReportFusionAgent")
        if pdf_file.exists() and pdf_file.stat().st_size > 0:
            event_hub.emit(run_id, "report_fusion", "artifact_created", f"已生成当前版本交付物 {pdf_file.name}", tool="ReportFusionAgent")
        if md_file.is_file() and md_file.stat().st_size > 0:
            event_hub.emit(run_id, "report_fusion", "artifact_created", f"已生成当前版本交付物 {md_file.name}", tool="ReportFusionAgent")
        event_hub.emit(run_id, "report_fusion", "stage_completed", f"报告融合完成，实际交付格式：{'、'.join(delivered_formats) or '无'}", tool="ReportFusionAgent")

        final_view_path = art_dir / "report_view.json"
        final_view = json.loads(final_view_path.read_text(encoding="utf-8")) if final_view_path.exists() else {}
        final_chapters = [type(chapter_res.chapters[0]).model_validate(ch) for ch in final_view.get("chapters", [])] if chapter_res.chapters else []
        outline_chapters = []
        for ch in final_chapters or chapter_res.chapters:
            sec_list = []
            for s in ch.sections:
                sec_list.append({
                    "section_id": s.section_id,
                    "title": s.title,
                    "paragraphs": [
                        {
                            "paragraph_id": getattr(p, "paragraph_id", None) or (p.get("paragraph_id") if isinstance(p, dict) else ""),
                            "kind": getattr(p, "kind", "thesis") or (p.get("kind") if isinstance(p, dict) else "thesis"),
                            "text": getattr(p, "text", "") or (p.get("text") if isinstance(p, dict) else str(p)),
                            "evidence_ids": getattr(p, "evidence_ids", []) or (p.get("evidence_ids") if isinstance(p, dict) else []),
                        }
                        for p in s.paragraphs
                    ],
                })
            outline_chapters.append({
                "chapter_id": ch.chapter_id,
                "title": ch.title,
                "sections": sec_list,
            })

        evidence_cat = []
        final_catalog_ids = {e.get("record_id") for e in final_view.get("evidence_catalog", [])}
        for idx, (rec_id, ev) in enumerate(((rid, ev) for rid, ev in report.evidence_index.items()
                                          if rid in final_catalog_ids), 1):
            evidence_cat.append({
                "citation_number": idx,
                "display_label": f"[{idx}] {ev.entity or '问财权威数据'} {ev.metric}",
                "material_title": f"{ev.entity or ''} {ev.metric}",
                "publishers": ["同花顺问财SkillHub"],
                "metric_names": [ev.metric],
                "evidence_ids": [rec_id],
            })

        actual_ch_count = len(outline_chapters)
        actual_sec_count = sum(len(c.get("sections", [])) for c in outline_chapters)
        # D-04 修复：基准从 DEFAULT_OUTLINE 推导（不得写死 7/21）；交付状态读真实 report_view.json
        expected_chapter_count, expected_section_count = _expected_outline_units()
        consistency = getattr(result, "consistency", None)

        # 真实证据覆盖率与质检聚合
        raw_chapter_json = run_dir / "artifacts" / "chapter_result.json"
        ch_quality: dict[str, Any] = {}
        ch_warnings: list[str] = []
        if raw_chapter_json.exists():
            try:
                ch_raw = json.loads(raw_chapter_json.read_text(encoding="utf-8"))
                ch_quality = ch_raw.get("quality", {})
                ch_warnings = ch_raw.get("warnings", [])
            except Exception:
                pass

        cited_eids = {
            eid
            for c in outline_chapters
            for sec in c.get("sections", [])
            for p in sec.get("paragraphs", [])
            for eid in (p.get("evidence_ids") or [])
        }
        claims = getattr(report, "claims", None) or getattr(report, "insights", None) or []
        core_eids = {
            eid
            for claim in claims
            for eid in (
                (claim.get("evidence_record_ids") or claim.get("evidence_ids") or [])
                if isinstance(claim, dict) else
                (getattr(claim, "evidence_record_ids", None) or getattr(claim, "evidence_ids", None) or [])
            )
        }
        known_eids = set(report.evidence_index)
        coverage_pool = core_eids or known_eids
        final_coverage = round(len(cited_eids & coverage_pool & known_eids) / len(coverage_pool), 2) if coverage_pool else 0.0
        data_qual = getattr(report, "data_quality", None)

        fusion_issues: list[str] = []
        if hasattr(result, "consistency") and result.consistency:
            fusion_issues.extend(result.consistency.issues)
            fusion_issues.extend(result.consistency.warnings)
        if data_qual and hasattr(data_qual, "limitations"):
            for lim in data_qual.limitations[:3]:
                if lim not in fusion_issues:
                    fusion_issues.append(lim)
        for w in ch_warnings[:3]:
            if w not in fusion_issues:
                fusion_issues.append(w)
        for iss in ch_quality.get("issues", []):
            if iss not in fusion_issues:
                fusion_issues.append(iss)
        # 导出类告警（缺格式 / 空文件 / 渲染异常）必须进入质量问题清单，
        # 否则导出失败对评审与前端完全不可见
        for w in export_warnings[:5]:
            if w not in fusion_issues:
                fusion_issues.append(w)

        clean_issues = _deduplicate_warnings(fusion_issues)
        native_status = str(getattr(result, "status", "") or "").lower()
        consistency_passed = bool(consistency and consistency.passed)
        fusion_passed = native_status == "completed" and consistency_passed
        fusion_passed = fusion_passed and actual_ch_count == expected_chapter_count and actual_sec_count == expected_section_count
        fusion_passed = fusion_passed and not (cited_eids - known_eids)
        recovered = (final_view.get("fact_audit") or {}).get("chapter_claims_recovered", False)
        if ch_quality.get("passed") is False and not recovered:
            fusion_passed = False
        consistency_score = None  # Rule verdict is not a measured accuracy percentage.

        data: dict[str, Any] = {
            "report_id": result.report_id or f"rep-{run_id}",
            "title": f"《{industry}》深度行业研究报告",
            "industry_topic": industry,
            "research_as_of": research_as_of or str(report.as_of),
            "market_scope": market_scope or ["中国 A 股", "港股", "美股", "中国 B 股"],
            "security_types": security_types or ["股票"],
            "reporting_currency": reporting_currency,
            "agent_status": native_status or "unknown",
            "hard_blocked": not consistency_passed,
            "draft_available": bool(available_exports) and not fusion_passed,
            "draft_sanitized": bool(final_view.get("fact_audit")),
            "quality_issues": final_view.get("quality_issues", []),
            "validation_version": "report-integrity-1",
            "chain_delivery": chain_delivery,
            "delivery_status": _resolve_delivery_status(art_dir, consistency),
            "formats": delivered_formats,
            "warnings": export_warnings,
            "included_chart_ids": [c["chart_id"] for c in final_view.get("charts", [])],
            "artifacts": manifest_entries,
            "quality": {
                "passed": fusion_passed,
                "consistency_score": consistency_score,
                "chapter_count": actual_ch_count,
                "section_count": actual_sec_count,
                "expected_chapter_count": expected_chapter_count,
                "expected_section_count": expected_section_count,
                "included_chart_count": len(final_view.get("charts", [])),
                "evidence_coverage": final_coverage,
                "evidence_coverage_details": {"name": "核心论据引用率", "numerator": len(cited_eids & coverage_pool & known_eids),
                    "denominator": len(coverage_pool), "pool": "insight_evidence" if core_eids else "all_evidence", "is_accuracy": False},
                "validation_passed": fusion_passed,
                "quality_issues": final_view.get("quality_issues", []),
                "issues": clean_issues,
            },
            "chapters": outline_chapters,
            "charts": final_view.get("charts", []),
            "evidence_catalog": evidence_cat,
            "disclaimer": "本报告由同花顺问财SkillHub五智能体流水线协同生成。数据来源于同花顺官方金融数据生态，内容仅供研究参考，不构成任何投资建议。",
            "methodology_note": "遵循五智能体端到端数据采集、量化解读、图表合成、7章21节投研标准大纲撰写与审校融合机制。",
            "key_metrics": [km.model_dump(mode="json") if hasattr(km, "model_dump") else km for km in getattr(report, "key_metrics", [])],
            "comps_matrix": getattr(report, "comps_matrix", None).model_dump(mode="json") if hasattr(getattr(report, "comps_matrix", None), "model_dump") else getattr(report, "comps_matrix", None),
        }

        if feedback:
            data["human_steering_applied"] = feedback
            if "审慎" in feedback or "防守" in feedback:
                data["investment_rating"] = "中性 (Neutral) · 审慎观察"
            elif "积极" in feedback or "景气" in feedback:
                data["investment_rating"] = "买入 (Buy) · 强烈推荐"
            elif "技术" in feedback or "破局" in feedback:
                data["investment_rating"] = "增持 (Overweight) · 创新催化"

        artifacts = [
            ArtifactRef(artifact_id=e["artifact_id"], kind=e["kind"], uri=e["uri"], revision=1)
            for e in manifest_entries if Path(e["uri"]).exists()
        ]

        return StageResult(
            stage="report_fusion",
            # S-05：原生 partial（缺格式 / 有实质问题）必须显式表达，
            # 由状态机按 S-01 的暂停语义处理，不能被悄悄升格成正式完成。
            status="failed" if native_status == "failed" else ("waiting_review" if native_status == "partial" else "completed"),
            revision=1,
            data=data,
            artifacts=artifacts,
            evidence_sources=["report_fusion_reviewers"],
            error=(
                "研报融合失败：" + ("；".join(clean_issues[:3]) if clean_issues else "所有交付格式均未成功导出")
                if native_status == "failed"
                else (
                    "研报融合部分交付：" + ("；".join(clean_issues[:3]) if clean_issues else "存在缺失格式或未解决项")
                    if native_status == "partial"
                    else None
                )
            ),
        )
