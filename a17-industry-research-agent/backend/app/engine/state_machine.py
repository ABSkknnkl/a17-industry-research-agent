from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import re
import secrets
import shutil
from contextlib import AsyncExitStack
from datetime import date, datetime
from pathlib import Path
from typing import Any

from backend.app.agents.adapters import FiveAgentsAdapter
from backend.app.core.event_hub import event_hub
from backend.app.core.storage import storage
from backend.app.schemas.workflow import (
    STAGE_ORDER,
    ReviewRequest,
    RunCreateRequest,
    RunExecutionSnapshot,
    StageName,
    StageResult,
    WorkflowState,
)

logger = logging.getLogger("workflow_engine")


class ReviewConflictError(ValueError):
    """A review no longer applies to the stored workflow state."""


class RevisionConflictError(ReviewConflictError):
    """请求携带的 expected_revision 与当前版本不一致（并发冲突）。"""

    def __init__(self, run_id: str, expected: int, actual: int) -> None:
        self.run_id = run_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"版本冲突：期望 revision={expected}，当前 revision={actual}。请刷新后重试。"
        )


# 编辑源 -> 必须失效的下游阶段（V8 方案 §5.3 表格）
DOWNSTREAM_INVALIDATION: dict[str, tuple[str, ...]] = {
    "data_fetch": ("data_interpret", "chart_generate", "chapter_write", "report_fusion"),
    "data_interpret": ("chart_generate", "chapter_write", "report_fusion"),
    "chart_generate": ("chapter_write", "report_fusion"),
    "chapter_write": ("report_fusion",),
    "report_fusion": (),
}


class StageBlockedError(ValueError):
    """阶段处于硬阻塞状态，不允许批准放行或跳过推进。

    继承 ValueError 以便既有 API 层 `except ValueError -> 400` 分支原样复用，
    不新增 HTTP 契约。
    """

    def __init__(self, run_id: str, stage: str, reason: str) -> None:
        self.run_id = run_id
        self.stage = stage
        self.reason = reason
        super().__init__(f"阶段 {stage} 处于硬阻塞状态，不可放行：{reason}")


# 判定为硬阻塞的 agent_status 取值（A1 原生状态机口径）。
_BLOCKING_AGENT_STATUS = frozenset({"failed", "blocked"})

# 允许以“定性证据”继续的领域：事件与产业链断言不依赖数值域。
_QUALITATIVE_DOMAINS = ("events",)
_QUALITATIVE_CHAIN_KEY = "chain_research"


def assess_stage_progression(result: StageResult, stage: str | None = None) -> tuple[bool, str]:
    """判断某阶段结果是否允许推进到下游。

    这是 S-01 的唯一局部判定入口：`_execute_stage`、`handle_review` 与
    `resume_run` 共用，避免三处各写一套条件。

    设计约束（对应 V8 方案 §4.2/§4.3）：
    - 只用结构化字段（status / error / agent_status / domains / chain_research）判断，
      不对 warning 文案做“致命”关键字匹配。
    - 一般 warnings 不视为阻塞。
    - 纯事件或受支持的产业链断言属于合法定性证据路径，不得整体误拦。

    Args:
        result: 阶段的原始结果（尚未被 review_stages 覆盖状态）。

    Returns:
        (allowed, reason)。allowed=False 时 reason 为可读的阻塞原因。
    """
    status = getattr(result, "status", None)
    error = getattr(result, "error", None)
    data = getattr(result, "data", None) or {}

    # 1) 执行失败：原生 failed 一律阻塞，且不得被审核覆盖成 approved/completed。
    if status == "failed":
        return False, error or "阶段执行失败"

    # 2) 适配器显式上报的 agent 原生状态。
    agent_status = str(data.get("agent_status") or "").strip().lower()
    domains = data.get("domains") if isinstance(data.get("domains"), dict) else {}
    quantitative = sum(
        int(domains.get(key) or 0)
        for key in ("industry", "companies", "financials", "macro", "industry_chain", "reports", "news")
    )
    events = int(domains.get("events") or 0)
    total_records = int(data.get("total_records") or 0) or quantitative + events

    # 3) 产业链受支持断言：属于合法定性证据路径。
    chain = data.get(_QUALITATIVE_CHAIN_KEY) if isinstance(data.get(_QUALITATIVE_CHAIN_KEY), dict) else {}
    chain_supported = 0
    if isinstance(chain, dict):
        coverage_values = chain.get("coverage_values") or {}
        if isinstance(coverage_values, dict):
            try:
                chain_supported = int(coverage_values.get("supported_assertions") or 0)
            except (TypeError, ValueError):
                chain_supported = 0
        if chain_supported <= 0 and chain.get("release_status") == "verified":
            chain_supported = 1
    has_qualitative_evidence = events > 0 or chain_supported > 0

    if agent_status in _BLOCKING_AGENT_STATUS:
        # 只有“零有效记录”且无任何定性证据才算硬阻塞；
        # 有事件/受支持产业链断言时按定性路径放行。
        if total_records <= 0 and not has_qualitative_evidence:
            return False, error or f"阶段未产出任何有效记录（agent_status={agent_status}）"
        if quantitative <= 0 and not has_qualitative_evidence:
            return False, error or "阶段无数值域记录且无定性证据支撑"

    # 4) 「零有效记录」只对**取数阶段**成立。
    # 章节/图表等阶段的 error 是质量降级说明（如"6 章使用确定性兜底稿"），
    # 早年实现把它们也按记录数为 0 判阻塞，会把正常降级误停成 awaiting review。
    if stage == "data_fetch" and error and not has_qualitative_evidence and total_records <= 0:
        return False, error

    # 正式报告不能把部分格式/不合格内容包装为完整交付；章节兜底仍允许审阅。
    if stage == "report_fusion":
        if data.get("hard_blocked") or data.get("delivery_blocked"):
            return False, error or "报告存在硬性内容错误"
        if data.get("release_mode") == "draft_with_warnings":
            return True, ""
        quality = data.get("quality") or {}
        delivery = data.get("chain_delivery") or {}
        if (agent_status == "partial" or quality.get("passed") is False
                or data.get("delivery_blocked") is True
                or (delivery.get("requested") and delivery.get("status") != "complete")):
            return False, error or "报告存在未解决的质量或交付缺口"

    # 5) 其他阶段的硬阻塞只看显式结构化标记（status=failed / hard_blocked）。
    if stage not in (None, "data_fetch"):
        if data.get("hard_blocked") is True:
            return False, error or "阶段标记为硬阻塞"
        return True, ""

    return True, ""


def morph_echarts_option(opt: dict, target_type: str) -> dict:
    """智能转换 ECharts option 以适配新的图表形态（如柱状、折线、水平条形、堆叠图、面积图）"""
    if not opt or not isinstance(opt, dict):
        return opt
    import copy
    o = copy.deepcopy(opt)
    series = o.get("series", [])
    if not isinstance(series, list):
        return o

    x_axis = o.get("xAxis", {})
    y_axis = o.get("yAxis", {})

    if target_type == "horizontal_bar":
        for s in series:
            if isinstance(s, dict):
                s["type"] = "bar"
                s.pop("stack", None)
                s.pop("areaStyle", None)
        is_x_cat = (isinstance(x_axis, dict) and x_axis.get("type") == "category") or (
            isinstance(x_axis, dict) and "data" in x_axis and (not isinstance(y_axis, dict) or y_axis.get("type") != "category")
        )
        if is_x_cat:
            new_y = dict(x_axis)
            new_y["type"] = "category"
            new_x = dict(y_axis) if isinstance(y_axis, dict) else {}
            new_x["type"] = "value"
            o["xAxis"] = new_x
            o["yAxis"] = new_y
    elif target_type in ("bar", "line", "stacked_bar", "area"):
        is_y_cat = (
            isinstance(y_axis, dict)
            and y_axis.get("type") == "category"
            and isinstance(x_axis, dict)
            and x_axis.get("type") == "value"
        )
        if is_y_cat:
            new_x = dict(y_axis)
            new_x["type"] = "category"
            new_y = dict(x_axis)
            new_y["type"] = "value"
            o["xAxis"] = new_x
            o["yAxis"] = new_y

        for s in series:
            if not isinstance(s, dict):
                continue
            if target_type == "bar":
                s["type"] = "bar"
                s.pop("stack", None)
                s.pop("areaStyle", None)
            elif target_type == "line":
                s["type"] = "line"
                s.pop("stack", None)
                s.pop("areaStyle", None)
            elif target_type == "stacked_bar":
                s["type"] = "bar"
                s["stack"] = "total"
                s.pop("areaStyle", None)
            elif target_type == "area":
                s["type"] = "line"
                s.pop("stack", None)
                s["areaStyle"] = s.get("areaStyle") or {}

    return o


_SNAPSHOT_FILE = "execution_snapshot.json"


def resolve_execution_snapshot(req: RunCreateRequest) -> RunExecutionSnapshot:
    """创建 run 时**解析一次**执行策略（D3 §10.3）。

    解析内容：链路引擎、研究策略、画像 id/版本、主数据发布版本、源政策版本。
    之后所有阶段与 resume 都读这份快照，不再各自看进程环境——

    旧行为是 A1/A2/A3 各读 `CHAIN_ENGINE`：改一次环境变量会同时改变所有
    历史 run 的后续阶段行为，且无法解释"同一 run 两个引擎"的产物。
    """
    import os

    notes: list[str] = []
    chain_engine = str(os.environ.get("CHAIN_ENGINE") or "").strip()
    strategy = "profile_guided"
    profile_id = None
    if req.input_data.data_fetch_options:
        strategy = req.input_data.data_fetch_options.chain_research_strategy
        profile_id = req.input_data.data_fetch_options.chain_profile_id

    from chart_generator.chain_intent import user_wants_industry_chain

    options = req.input_data.chart_generate_options
    chain_requested = user_wants_industry_chain(
        req.input_data.industry_topic, req.input_data.focus_questions,
        explicit=options.want_industry_chain if options else None,
        defaulted_focus=options.defaulted_focus if options else False,
        requested_types=options.requested_chart_types if options else None,
    )
    profile_version: str | None = None
    prefer_v2 = not chain_engine and chain_requested
    if chain_engine == "evidence_v2" or prefer_v2:
        try:
            import backend.app.core.setup_env  # noqa: F401
            from chain_research.profiles import load_profile, resolve_profile

            resolved = None
            if profile_id:
                resolved = load_profile(profile_id)
            else:
                from chain_research.models import ChainScope

                scope = ChainScope(
                    scope_id=f"snap-{req.project_id}",
                    subject=req.input_data.industry_topic,
                    as_of=(req.input_data.research_as_of or "2026-10-31")[:7],
                )
                resolved = resolve_profile(scope, strategy=strategy)
            if prefer_v2 and (strategy == "explore" or (resolved is not None and resolved.status == "reviewed")):
                chain_engine = "evidence_v2"
            if chain_engine == "evidence_v2":
                if resolved is not None:
                    profile_id = resolved.profile_id
                    profile_version = resolved.version
                    notes.append(f"profile: {profile_id}@{profile_version} status={resolved.status}")
                else:
                    notes.append("未匹配到专用画像：按通用范围执行")
            elif prefer_v2:
                notes.append("缺少已审画像且未启用开放研究，产业链仅按环节分类呈现")
        except Exception as exc:  # 画像缺失不应阻断建 run
            notes.append(f"画像解析失败（按通用范围继续）：{type(exc).__name__}")

    release_id = None
    try:
        pointer = Path(__file__).resolve().parents[3] / "data" / "industry_reference" / "current.json"
        if pointer.exists():
            release_id = json.loads(pointer.read_text(encoding="utf-8")).get("release_id")
            notes.append(f"reference_release={release_id}")
    except Exception:
        notes.append("主数据发布指针不可读")

    from hashlib import sha256
    from urllib.parse import urlsplit, urlunsplit
    from backend.app.core.config import settings as runtime_settings
    provider = urlsplit(runtime_settings.LLM_BASE_URL)
    provider_url = urlunsplit((provider.scheme, provider.hostname or "", provider.path, "", ""))
    project_root = Path(__file__).resolve().parents[3]
    source_digest = sha256()
    for folder in ("agents_core", "backend/app", "frontend/src"):
        for source in sorted((project_root / folder).rglob("*")):
            if source.suffix not in (".py", ".ts", ".vue", ".html", ".css") or "__pycache__" in source.parts:
                continue
            source_digest.update(str(source.relative_to(project_root)).encode())
            source_digest.update(source.read_bytes())
    input_digest = sha256(json.dumps(req.input_data.model_dump(mode="json"), ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return RunExecutionSnapshot(
        model_configuration={"model": runtime_settings.LLM_MODEL, "base_url": provider_url,
            "timeout_seconds": runtime_settings.LLM_TIMEOUT_SECONDS,
            "reasoning_effort": os.environ.get("LLM_REASONING_EFFORT", "low"),
            "thinking": os.environ.get("LLM_THINKING", "disabled")},
        input_sha256=input_digest, source_sha256=source_digest.hexdigest(), validation_version="report-integrity-1",
        engine="five_agents",
        chain_engine=chain_engine,
        chain_requested=chain_requested,
        research_strategy=strategy,
        profile_id=profile_id,
        profile_version=profile_version,
        reference_release_id=release_id,
        source_policy_version="source-policy-v1",
        notes=notes,
    )


def load_execution_snapshot(run_id: str) -> RunExecutionSnapshot:
    """读取 run 的执行快照；旧 run 缺文件时返回 legacy 标记（不换引擎）。"""
    path = storage.get_run_dir(run_id) / _SNAPSHOT_FILE
    if not path.exists():
        return RunExecutionSnapshot(engine="legacy", legacy=True, notes=["旧 run 无执行快照，按创建时环境解释"])
    try:
        return RunExecutionSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return RunExecutionSnapshot(engine="legacy", legacy=True, notes=["执行快照损坏，按 legacy 处理"])


class WorkflowEngine:
    """行业研究报告五智能体流水线与人机协同状态机引擎"""

    def __init__(self) -> None:
        self._running_tasks: dict[str, asyncio.Task[Any]] = {}
        # One lock per run protects reviews, background commits, and deletion.
        self._run_locks: dict[str, asyncio.Lock] = {}
        self._clear_lock = asyncio.Lock()
        self._clearing_runs = False

    @staticmethod
    async def _fetch_supplement_with_audit(run_id, stage, demand, as_of):
        import inspect
        from data_fetcher.agent import DataFetcherAgent
        async def on_request(item):
            safe = {key:item.get(key) for key in ('task_id','skill_id','attempt','request_id','trace_id',
                    'elapsed_ms','http_status','outcome')}
            event_hub.emit(run_id, stage, 'tool_request', '补采请求已结束',
                           tool=safe.get('skill_id'), details=safe)
        async def on_result(item):
            event_hub.emit(run_id, stage, 'tool_result', '补采任务已结束', tool=item.skill_id,
                details={'task_id':item.task_id,'skill_id':item.skill_id,'attempts':item.attempts,
                         'elapsed_ms':item.elapsed_ms,'cache_hit':item.cache_hit,
                         'record_count':len(item.records),'invocation_outcome':item.invocation_outcome,
                         'outcome':'cancelled' if getattr(item, 'error', None) == 'cancelled' else
                                   'success' if item.success else 'failed'})
        fetch = DataFetcherAgent().fetch_supplemental
        parameters = inspect.signature(fetch).parameters
        kwargs = {'as_of':as_of}
        if 'on_result' in parameters:
            kwargs['on_result'] = on_result
        if 'on_request' in parameters:
            kwargs['on_request'] = on_request
        return await fetch(demand, **kwargs)

    @staticmethod
    def _select_chart_supplement_demands(demands: list[dict], matrix: list[dict]) -> list[dict]:
        """Select at most two distinct unmet matrix requirements relevant to chart needs."""
        from agents_core.financial_semantics import metric_family

        selected = []
        for row in matrix:
            requirement, coverage = row.get("requirement") or {}, row.get("coverage") or {}
            if coverage.get("passed") is not False:
                continue
            rid = str(requirement.get("requirement_id") or "")
            if not rid:
                continue
            entities = requirement.get("entity_names") or []
            metrics = requirement.get("metric_families") or []
            domain = str(requirement.get("domain") or "")
            match = next((d for d in demands if str(d.get("domain") or "") == domain
                          and (not entities or not d.get("entities") or set(entities) & set(d["entities"]))
                          and (not metrics or not d.get("metrics") or
                               {metric_family(str(m)) for m in metrics} &
                               {metric_family(str(m)) for m in d["metrics"]})), None)
            if match is None:
                continue
            periods = [str(p) for p in requirement.get("period_ends") or []]
            sources = requirement.get("acceptable_skill_ids") or []
            priority = 0 if rid.startswith(("annual_", "focused_")) else 1 if requirement.get("hard", True) else 2
            selected.append((priority, rid, {**match, "requirement_id": rid,
                "entities": entities or match.get("entities") or [], "metrics": metrics or match.get("metrics") or [],
                "period_ends": periods, "acceptable_skill_ids": sources,
                "query_hint": " ".join([*entities, *periods, *metrics, *sources, str(match.get("query_hint") or "")]).strip()}))
        result, seen = [], set()
        for _, _, demand in sorted(selected, key=lambda item: (item[0], item[1])):
            fingerprint = (str(demand.get("domain", "")).casefold(),
                           tuple(sorted(str(x).strip().casefold() for x in demand["entities"])),
                           tuple(sorted(metric_family(str(x)) for x in demand["metrics"])),
                           tuple(sorted(demand["period_ends"])), tuple(sorted(demand["acceptable_skill_ids"])))
            if fingerprint not in seen:
                seen.add(fingerprint)
                result.append(demand)
            if len(result) == 2:
                break
        return result

    async def _run_chart_supplement(
        self, run_id: str, input_revision: int, result: StageResult, as_of: date,
    ) -> str:
        """Prepare a single bounded round outside the run lock and commit with a revision guard."""
        import hashlib
        import shutil
        from backend.app.agents.adapters import SupplementalRecordCollision, merge_supplemental_records
        from data_fetcher.agent import DataFetcherAgent
        from data_fetcher.models import ResearchRecord, StructuredResearchDataset

        demands = result.data.get("data_demands") or []
        path = storage.get_run_dir(run_id) / "artifacts" / "dataset.json"
        if not demands or not path.exists():
            return "none"
        original_bytes = path.read_bytes()
        original_hash = hashlib.sha256(original_bytes).hexdigest()
        input_path = storage.get_run_dir(run_id) / "input_data.json"
        original_input = input_path.read_bytes() if input_path.exists() else None
        dataset = StructuredResearchDataset.model_validate_json(original_bytes)
        matrix = dataset.quality_summary.get("requirement_evidence_matrix") or []
        selected = self._select_chart_supplement_demands(demands, matrix)
        if not selected:
            return "none"
        async with self._run_lock(run_id):
            fresh = storage.load_state(run_id)
            if not fresh or fresh.status != "running" or fresh.current_stage != "chart_generate" or fresh.revision != input_revision:
                return "discarded"
            fetch_stage = fresh.stage_results.get("data_fetch")
            if fetch_stage is None or (fetch_stage.data.get("automatic_replenishment") or {}).get("round", 0):
                return "none"
            attempts = [{"requirement_id": d["requirement_id"], "fingerprint": hashlib.sha256(
                json.dumps({k: d.get(k) for k in ("domain", "entities", "metrics", "period_ends", "acceptable_skill_ids")},
                           ensure_ascii=False, sort_keys=True).encode()).hexdigest(), "status": "started"} for d in selected]
            fetch_stage.data["automatic_replenishment"] = {"round": 1, "attempts": attempts}
            storage.save_state(fresh)

        fetched = []
        for demand, attempt in zip(selected, attempts):
            try:
                records = await self._fetch_supplement_with_audit(run_id, 'chart_generate', demand, as_of)
                fetched.extend(ResearchRecord.model_validate(record) for record in records)
                attempt["status"] = "returned" if records else "empty"
            except asyncio.CancelledError:
                raise
            except Exception:
                attempt["status"] = "failed"

        before = {row["requirement"]["requirement_id"]: set((row.get("coverage") or {}).get("evidence_record_ids") or [])
                  for row in matrix if row.get("requirement", {}).get("requirement_id")}
        candidate = dataset.model_copy(deep=True)
        try:
            added = merge_supplemental_records(candidate, {}, fetched, as_of) if fetched else []
        except SupplementalRecordCollision:
            added = []
            for attempt in attempts:
                if attempt["status"] == "returned":
                    attempt["status"] = "rejected_collision"
        target_ids = {d["requirement_id"] for d in selected}
        gained = set()
        for row in candidate.quality_summary.get("requirement_evidence_matrix") or []:
            rid = row.get("requirement", {}).get("requirement_id")
            if rid in target_ids:
                gained.update(set((row.get("coverage") or {}).get("evidence_record_ids") or []) - before.get(rid, set()))
        gained.intersection_update(added)
        replacements = {item.get("original_record", {}).get("record_id"): item.get("replacement_record_id")
                        for item in candidate.quality_summary.get("restatement_adjustments", [])}
        eligible = [record for record in fetched if record.record_id in gained or replacements.get(record.record_id) in gained]
        if eligible:
            candidate = dataset.model_copy(deep=True)
            merge_supplemental_records(candidate, {}, eligible, as_of)
            candidate.quality_summary["requested_requirement_coverage"] = [
                row for row in candidate.quality_summary.get("requested_requirement_coverage", [])
                if row.get("requirement_id") != "supplement_analysis_stale"]

        async with self._run_lock(run_id):
            fresh = storage.load_state(run_id)
            if (not fresh or fresh.status != "running" or fresh.current_stage != "chart_generate"
                or fresh.revision != input_revision or not path.exists()
                or hashlib.sha256(path.read_bytes()).hexdigest() != original_hash
                or (input_path.read_bytes() if input_path.exists() else None) != original_input):
                return "discarded"
            fetch_stage = fresh.stage_results["data_fetch"]
            fetch_stage.data["automatic_replenishment"] = {"round": 1, "attempts": attempts,
                "status": "committed" if eligible else "no_qualified_evidence"}
            if not eligible:
                storage.save_state(fresh)
                return "none"
            previous = fresh.model_copy(deep=True)
            run_dir = storage.get_run_dir(run_id)
            archive = run_dir / "revisions" / "artifacts" / f"r{input_revision}"
            archive_created = False
            touched: dict[Path, bytes | None] = {}
            def backup(item: Path) -> None:
                if item not in touched:
                    touched[item] = item.read_bytes() if item.exists() else None
            try:
                if not archive.exists():
                    archive.parent.mkdir(parents=True, exist_ok=True)
                    archive_created = True
                    shutil.copytree(run_dir / "artifacts", archive)
                backup(path)
                path.write_text(candidate.model_dump_json(indent=2), encoding="utf-8")
                fresh.revision += 1
                fetch_stage.revision = fresh.revision
                fetch_stage.data["record_count"] = len(candidate.all_records())
                fetch_stage.data["requirement_evidence_matrix"] = candidate.quality_summary.get("requirement_evidence_matrix", [])
                self._invalidate_following_stages(fresh, "data_fetch")
                fresh.current_stage = "data_interpret"
                fresh.status = "running"
                fresh.stage_results["data_interpret"].status = "running"
                fresh.updated_at = datetime.now().isoformat()
                self._commit_state_with_history(run_dir, fresh, action="auto_replenish", stage="data_fetch",
                    from_revision=input_revision, to_revision=fresh.revision, comment="图表需求触发定向补采",
                    changed_fields=["dataset"], snapshot_state=previous, backup=backup)
            except Exception:
                for item, content in touched.items():
                    if content is None:
                        item.unlink(missing_ok=True)
                    else:
                        item.write_bytes(content)
                if archive_created:
                    shutil.rmtree(archive, ignore_errors=True)
                raise
            return "committed"

    def _ensure_not_clearing(self) -> None:
        if getattr(self, "_clearing_runs", False):
            raise ReviewConflictError("正在清空任务，请等待清理完成")

    def _lock_for(self, run_id: str) -> asyncio.Lock:
        locks = getattr(self, "_run_locks", None)
        if not isinstance(locks, dict):
            locks = {}
            self._run_locks = locks
        return locks.setdefault(run_id, asyncio.Lock())

    def _run_lock(self, run_id: str) -> asyncio.Lock:
        return self._lock_for(run_id)

    async def _stop_task(self, run_id: str) -> None:
        task = self._running_tasks.pop(run_id, None)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def delete_run(self, run_id: str) -> None:
        async with self._run_lock(run_id):
            await self._stop_task(run_id)
            storage.delete_run(run_id)
            event_hub.clear_run(run_id)

    def get_next_stage(self, current_stage: StageName) -> StageName | None:
        try:
            idx = STAGE_ORDER.index(current_stage)
            if idx + 1 < len(STAGE_ORDER):
                return STAGE_ORDER[idx + 1]
        except ValueError:
            pass
        return None

    async def create_run(self, req: RunCreateRequest) -> WorkflowState:
        self._ensure_not_clearing()
        run_id = f"run-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(6)}"
        now_str = datetime.now().isoformat()

        # 初始化五个阶段的 StageResult
        stage_results: dict[StageName, StageResult] = {}
        for s in STAGE_ORDER:
            stage_results[s] = StageResult(stage=s, status="pending", revision=1)

        state = WorkflowState(
            project_id=req.project_id,
            run_id=run_id,
            current_stage="data_fetch",
            status="running",
            revision=1,
            stage_results=stage_results,
            created_at=now_str,
            updated_at=now_str,
        )

        # 保存初始元数据
        run_dir = storage.get_run_dir(run_id)
        input_file = run_dir / "input_data.json"
        input_file.write_text(req.model_dump_json(indent=2), encoding="utf-8")
        # D3：创建时解析一次执行策略并持久化；后续阶段与 resume 共用
        snapshot = resolve_execution_snapshot(req)
        (run_dir / _SNAPSHOT_FILE).write_text(
            snapshot.model_dump_json(indent=2), encoding="utf-8"
        )
        storage.save_state(state)

        # 执行第一阶段：支持异步驱动
        task = asyncio.create_task(
            self._execute_stage(run_id, "data_fetch", req.review_stages, feedback=None)
        )
        self._running_tasks[run_id] = task

        # 等待首阶段执行或超时前返回当前状态（前端有 5 分钟超时，这里等待短时间让前端看到启动）
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=1.5)
        except asyncio.TimeoutError:
            pass

        # 重新读取最新状态
        latest = storage.load_state(run_id)
        return latest or state

    @staticmethod
    def _merge_chart_specs(existing_specs: list[Any], incoming_specs: list[Any]) -> list[dict[str, Any]]:
        """以原图列表为基底，按 chart_id 就地合并用户改动，保持原顺序。

        契约（V8 方案 §5.3 第 4 步）：
        - 未出现在 incoming 中的图原样保留，不当作删除。
        - incoming 里的 chart_id 必须已存在于原列表；未知 ID 与重复 ID 一律拒绝。
        - 只覆盖传入字段；未传 option 不等于清空原 option。
        - 形态变更时按目标类型重写 option，但绝不丢数据。

        Raises:
            ValueError: 出现未知 chart_id 或重复 chart_id。
        """
        if not isinstance(incoming_specs, list):
            raise ValueError("chart_specs 必须是数组")

        existing_map: dict[str, dict[str, Any]] = {}
        for spec in existing_specs:
            if isinstance(spec, dict):
                cid = spec.get("chart_id")
                if isinstance(cid, str) and cid:
                    existing_map[cid] = spec

        patches: dict[str, dict[str, Any]] = {}
        for incoming in incoming_specs:
            if not isinstance(incoming, dict):
                raise ValueError("chart_specs 元素必须是对象")
            cid = incoming.get("chart_id")
            if not isinstance(cid, str) or not cid:
                raise ValueError("chart_specs 元素缺少 chart_id")
            if cid not in existing_map:
                raise ValueError(f"未知 chart_id: {cid}（不允许通过编辑接口新增图表）")
            if cid in patches:
                raise ValueError(f"重复 chart_id: {cid}")
            patches[cid] = incoming

        merged: list[dict[str, Any]] = []
        for spec in existing_specs:
            if not isinstance(spec, dict):
                merged.append(spec)
                continue
            cid = spec.get("chart_id")
            patch = patches.get(cid) if isinstance(cid, str) else None
            if not patch:
                # 未编辑：深拷贝保留全部字段（含 option / evidence / render_mode / chain_graph）
                merged.append(json.loads(json.dumps(spec, ensure_ascii=False, default=str)))
                continue

            base = json.loads(json.dumps(spec, ensure_ascii=False, default=str))
            base.update(patch)
            if not patch.get("option") and spec.get("option"):
                base["option"] = spec["option"]
            target_type = patch.get("chart_type")
            if target_type and base.get("option"):
                base["option"] = morph_echarts_option(base["option"], target_type)
            merged.append(base)
        return merged

    async def _apply_direct_edit(
        self,
        *,
        state: WorkflowState,
        run_dir: Path,
        art_dir: Path,
        req: ReviewRequest,
        edited_chart_ids: set[str],
        backup: Any,
    ) -> None:
        """把编辑内容应用到内存 state 与落盘产物；失败直接抛出（由调用方回滚）。

        所有写文件动作前都先调用 ``backup(path)``，保证异常时能恢复本次影响的旧内容。
        """
        cur_data = state.stage_results[req.stage].data or {}
        edited_data = req.edited_data or {}

        if req.stage == "chart_generate" and "chart_specs" in edited_data:
            existing_specs = cur_data.get("chart_specs") or cur_data.get("charts") or []
            merged_specs = self._merge_chart_specs(existing_specs, edited_data["chart_specs"])
            edited_data = dict(edited_data)
            edited_data["chart_specs"] = merged_specs
            # charts 别名必须与 chart_specs 同源，否则状态与文件再次分叉
            edited_data["charts"] = merged_specs
            req.edited_data = edited_data

        cur_data.update(edited_data)
        state.stage_results[req.stage].data = cur_data

        if req.stage == "data_fetch":
            self._sync_dataset_artifact(art_dir, cur_data, edited_data, backup)
        elif req.stage == "chapter_write" and "chapters" in edited_data:
            ch_path = art_dir / "chapter_result.json"
            if ch_path.exists():
                backup(ch_path)
                ch_json = json.loads(ch_path.read_text(encoding="utf-8"))
                ch_json["chapters"] = edited_data["chapters"]
                ch_path.write_text(json.dumps(ch_json, ensure_ascii=False, indent=2), encoding="utf-8")
        elif req.stage == "chart_generate" and "chart_specs" in edited_data:
            await self._sync_chart_artifacts(
                state=state,
                art_dir=art_dir,
                edited_data=edited_data,
                edited_chart_ids=edited_chart_ids,
                backup=backup,
            )
        elif req.stage == "data_interpret":
            ir_path = art_dir / "interpretation_report.json"
            if ir_path.exists():
                backup(ir_path)
                ir_json = json.loads(ir_path.read_text(encoding="utf-8"))
                ir_json.update(edited_data)
                ir_path.write_text(json.dumps(ir_json, ensure_ascii=False, indent=2), encoding="utf-8")
        elif req.stage == "report_fusion":
            # The canonical view is merged and rendered atomically by the caller.
            backup(art_dir / "report_view.json")

    @staticmethod
    def _sync_dataset_artifact(
        art_dir: Path,
        cur_data: dict[str, Any],
        edited_data: dict[str, Any],
        backup: Any,
    ) -> None:
        ds_path = art_dir / "dataset.json"
        deleted_ids = edited_data.get("deleted_record_ids", [])
        confirmed_scope = edited_data.get("confirmed_scope")
        confirmed_keywords = edited_data.get("confirmed_keywords")
        if ds_path.exists():
            backup(ds_path)
            ds_json = json.loads(ds_path.read_text(encoding="utf-8"))
            if deleted_ids:
                del_set = set(deleted_ids)
                for list_key, val in ds_json.items():
                    if isinstance(val, list):
                        ds_json[list_key] = [
                            item for item in val
                            if (item.get("record_id") if isinstance(item, dict) else getattr(item, "record_id", "")) not in del_set
                        ]
            if confirmed_scope is not None:
                ds_json["confirmed_scope"] = confirmed_scope
            if confirmed_keywords is not None:
                ds_json["confirmed_keywords"] = confirmed_keywords
            ds_path.write_text(json.dumps(ds_json, ensure_ascii=False, indent=2), encoding="utf-8")
        if deleted_ids and "source_records" in cur_data:
            del_set = set(deleted_ids)
            cur_data["source_records"] = [
                r for r in cur_data["source_records"] if r.get("record_id") not in del_set
            ]
        if deleted_ids and "record_count" in cur_data:
            cur_data["record_count"] = max(0, int(cur_data["record_count"]) - len(deleted_ids))

    async def _sync_chart_artifacts(
        self,
        *,
        state: WorkflowState,
        art_dir: Path,
        edited_data: dict[str, Any],
        edited_chart_ids: set[str],
        backup: Any,
    ) -> None:
        """重渲染被编辑的图并同步 chart_result.json；失败向上抛，由调用方回滚。"""
        from chart_generator.render import render_svg

        charts_dir = art_dir / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)
        specs = edited_data["chart_specs"]

        for spec in specs:
            cid = spec.get("chart_id")
            # 只重渲染真正被编辑的图：未编辑图必须保持字节级不变
            if str(cid) not in edited_chart_ids:
                continue
            c_opt = spec.get("option")
            c_type = spec.get("chart_type", "bar")
            c_title = spec.get("title", "")
            c_notes = spec.get("footnotes") or []
            # 产业链图跳过通用渲染（2026-10-17）：`render_svg` 画的是三栏企业列表（0 条连线），
            # 用它覆盖会把刚落盘的确定性产业链 SVG 冲掉。这类图交给下面的专用重建块。
            if spec.get("chain_graph") or spec.get("inline_svg"):
                continue
            if cid and c_opt:
                svg_file = charts_dir / f"{cid}.svg"
                backup(svg_file)
                svg_text = render_svg(c_title, c_type, c_opt, c_notes)
                svg_file.write_text(svg_text, encoding="utf-8")
                spec["svg_uri"] = str(svg_file.resolve())

        # 产业链图一致性重建（R1 §4.3 步骤 6）：
        # 主图（结构校验 / 渲染 / 落盘）失败 → 整个请求失败并回滚，
        # 绝不静默降级成 echarts 后保留上一版 svg_uri 冒充本次成功。
        # 补充位图（HTML 排版版）是可选视图：失败可降级到本次已成功的主 SVG。
        for spec in specs:
            if str(spec.get("chart_id")) not in edited_chart_ids:
                continue
            if spec.get("render_mode") not in ("svg", "generated_image"):
                continue

            # ── 主图：失败直接抛出（由 direct_edit 的 _restore 回滚） ──
            from chart_generator.chain_graph import ChainGraphSpec
            from chart_generator.chain_render import render_chain_svg

            graph = spec.get("chain_graph")
            if not graph:
                raise ValueError(
                    f"产业链图 {spec.get('chart_id')} 无 chain_graph，无法按审核意见重建"
                )
            title_value = spec.get("title")
            chain_spec = ChainGraphSpec.model_validate(graph)
            if isinstance(title_value, str) and title_value:
                chain_spec.title = title_value
            new_svg = render_chain_svg(chain_spec)
            if not new_svg or "<svg" not in new_svg:
                raise ValueError(f"产业链图 {spec.get('chart_id')} 主图渲染产出为空")
            spec["inline_svg"] = new_svg
            spec["data_fingerprint"] = hashlib.sha256(new_svg.encode()).hexdigest()
            svg_file = charts_dir / f"{spec.get('chart_id') or 'CHART-CHAIN'}.svg"
            backup(svg_file)
            svg_file.write_text(new_svg, encoding="utf-8")
            spec["svg_uri"] = str(svg_file.resolve())
            spec["render_mode"] = "svg"
            spec["image_uri"] = None

            # ── 补充视图：可选，失败只降级，不影响主图 ──
            if spec.get("supplement_image_uri"):
                try:
                    from chart_generator.chain_html import generate_chain_html_image
                    from chart_generator.chain_render import _stats_line
                    from chart_generator.config import Settings as _CGSettings

                    _gen = await generate_chain_html_image(
                        chain_spec,
                        settings=_CGSettings.from_env(),
                        artifact_dir=art_dir,
                        chart_id=str(spec.get("chart_id") or "CHART-CHAIN"),
                        stats_line=_stats_line(chain_spec),
                    )
                    if not _gen:
                        raise ValueError("HTML 出图未通过门禁")
                    spec["supplement_image_uri"] = _gen.image_uri
                    spec["supplement_html_uri"] = _gen.html_path
                    spec["supplement_note"] = "LLM 排版版（卡片信息更细，但不画连线与箭头）"
                    spec["generation_prompt"] = _gen.generation_prompt
                    spec["generation_prompt_model"] = _gen.generation_prompt_model
                except Exception as supp_err:
                    # 结构已变，旧补充图属于过期内容：一律作废；主 SVG 保持本次成功产物。
                    logger.warning(
                        "产业链补充视图重建失败，仅作废补充视图（主图不受影响）：chart=%s err=%s",
                        spec.get("chart_id"), supp_err,
                    )
                    spec["supplement_image_uri"] = None
                    spec["supplement_html_uri"] = None

        ct_path = art_dir / "chart_result.json"
        if ct_path.exists():
            backup(ct_path)
            ct_json = json.loads(ct_path.read_text(encoding="utf-8"))
            ct_json["charts"] = specs
            ct_json["chart_specs"] = specs
            ct_path.write_text(json.dumps(ct_json, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _reexport_fusion_artifacts(self, run_id: str) -> dict[str, Path]:
        """从**已编辑的 report_view.json** 重新渲染 MD / HTML / PDF（R1 §4.3 步骤 8）。

        与整段融合重跑不同：不调 LLM、不重建内容，只把已持久化的最终视图
        重新发布为三种格式，使「编辑标题 → 批准」后旧文件不冒充新版。
        重导出失败由调用方按 StageBlockedError 处理，不吞异常。

        Returns:
            各格式实际落盘路径。
        """
        import backend.app.core.setup_env  # noqa: F401  注册 agents_core 子路径
        from report_fusion.models import ReportViewModel
        from report_fusion.pdf import render_pdf
        from report_fusion.render import render_html, render_markdown
        from report_fusion.config import Settings as _FusionSettings

        art_dir = storage.get_run_dir(run_id) / "artifacts"
        view_path = art_dir / "report_view.json"
        if not view_path.exists():
            raise FileNotFoundError("缺少 report_view.json，无法重导出（请使用修订重跑）")

        view = ReportViewModel.model_validate_json(view_path.read_text(encoding="utf-8"))

        outputs: dict[str, Path] = {}
        md_path = art_dir / "report.md"
        md_path.write_text(render_markdown(view), encoding="utf-8")
        outputs["markdown"] = md_path

        html_text = render_html(view)
        html_path = art_dir / "report.html"
        html_path.write_text(html_text, encoding="utf-8")
        outputs["html"] = html_path

        settings = _FusionSettings.from_env()
        pdf_bytes = await render_pdf(html_text, settings.pdf_timeout_seconds)
        pdf_path = art_dir / "report.pdf"
        pdf_path.write_bytes(pdf_bytes)
        outputs["pdf"] = pdf_path

        logger.info(f"[{run_id}] 融合内容重导出完成：{sorted(outputs)}")
        return outputs

    def _commit_state_with_history(
        self,
        run_dir: Path,
        state: WorkflowState,
        *,
        action: str,
        stage: str,
        from_revision: int,
        to_revision: int,
        comment: str | None,
        changed_fields: list[str],
        combined_feedback: str | None = None,
        edited_data: dict[str, Any] | None = None,
        snapshot_state: WorkflowState | None = None,
        backup: Any = None,
    ) -> None:
        """一次性提交：历史记录 + 版本快照 + state，任一失败则回滚本次改动。

        R1 提交顺序：**先 state、后历史**。旧顺序（历史成功 → state 失败）会在
        state 未生效时留下一条"成功历史"，等于伪造审计记录。

        边界声明：保证请求执行期间注入异常的失败回退；进程在任意文件替换
        瞬间崩溃的跨文件全原子性不在承诺范围内（V8 最终方案 §4.3 步骤 5）。

        Raises:
            Exception: 历史或 state 写入失败时向上抛出，调用方据此返回失败。
        """
        history_file = run_dir / "feedback_history.json"
        history: list[Any] = []
        if history_file.exists():
            try:
                history = json.loads(history_file.read_text(encoding="utf-8"))
            except Exception as exc:
                # 损坏的历史不得按空数组覆盖（会抹掉审计记录）
                raise RuntimeError(f"协同历史文件损坏，拒绝覆盖: {exc}") from exc
            if not isinstance(history, list):
                raise RuntimeError("协同历史文件格式非法（非数组），拒绝覆盖")

        history.append(
            {
                "action": action,
                "stage": stage,
                "from_revision": from_revision,
                "to_revision": to_revision,
                "timestamp": datetime.now().isoformat(),
                "comment": comment,
                "changed_fields": changed_fields,
                "combined_feedback": combined_feedback,
                "edited_data": edited_data,
            }
        )

        # 先把新历史写到临时位置；state 成功后再替换历史。
        tmp_history = history_file.with_suffix(".json.tmp")
        tmp_history.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

        if backup is not None:
            backup(history_file)
            backup(run_dir / "state.json")
            backup(run_dir / "revisions" / f"{to_revision}.json")

        # state 先落盘：state 成功才宣告新版本生效
        storage.save_state(state)
        if snapshot_state is not None:
            snap = run_dir / "revisions" / f"{from_revision}.json"
            if backup is not None:
                backup(snap)
            snap.write_text(snapshot_state.model_dump_json(indent=2), encoding="utf-8")

        # state 已生效，最后发布历史
        tmp_history.replace(history_file)

    def _invalidate_downstream(self, state: WorkflowState, stage: str) -> list[str]:
        """把受影响的下游标为待更新；保留旧文件供历史查阅。"""
        invalidated: list[str] = []
        for downstream in DOWNSTREAM_INVALIDATION.get(stage, ()):
            result = state.stage_results.get(downstream)
            if result is None:
                continue
            if result.status in ("approved", "completed", "waiting_review"):
                result.status = "pending"
                invalidated.append(downstream)
        return invalidated

    async def _prepare_supplement(
        self, req: ReviewRequest, original: WorkflowState, run_dir: Path,
    ) -> tuple[dict[Path, str], dict[str, Any], str] | None:
        """Fetch without a run lock; prepare changes without publishing files."""
        from data_fetcher.agent import DataFetcherAgent

        edits = req.edited_data or {}
        demand = edits.get("demand") or {}
        if edits.get("action_type") == "partial_refetch":
            domains = edits.get("domains") or ["financials"]
            demand = {
                "domain": domains[0], "entities": edits.get("entities") or [],
                "query_hint": edits.get("query_hint") or f"重新采集{'、'.join(domains)}相关核心指标",
                "reason": edits.get("reason") or "局部子域重采",
            }
        input_path = run_dir / "input_data.json"
        input_data = json.loads(input_path.read_text(encoding="utf-8")) if input_path.exists() else {}
        as_of_value = (input_data.get("input_data") or {}).get("research_as_of")
        as_of = date.fromisoformat(as_of_value) if as_of_value else date.today()
        if demand.get('source_type') == 'official-disclosure':
            from agents_core.call_ledger import ledger_context
            from data_fetcher.official_filing import fetch_official_chain_record
            topic = str(demand.get('topic') or '').strip()
            requested_topic = str((input_data.get('input_data') or {}).get('industry_topic') or '').strip()
            if (demand.get('domain') != 'industry_chain' or not topic or not requested_topic
                or topic != requested_topic or isinstance(demand.get('page_number'), bool)
                or not isinstance(demand.get('page_number'), int)):
                raise ValueError('公告资料的领域、研究主题或页码不匹配')
            run_id = getattr(req, 'run_id', run_dir.name)
            stage = getattr(req, 'stage', 'data_fetch')
            def emit(item):
                event_hub.emit(run_id, stage, 'tool_request' if item['kind']=='tool_request' else 'tool_call',
                               '公告原文请求已结束', tool='official-disclosure', details=item)
            with ledger_context(emit, stage):
                record = await fetch_official_chain_record(source_url=str(demand.get('source_url') or ''),
                    published_at=date.fromisoformat(str(demand.get('published_at') or '')),as_of=as_of,
                    page_number=demand['page_number'],excerpt=str(demand.get('excerpt') or ''),topic=topic)
            records = [record]
        else:
            records = await self._fetch_supplement_with_audit(getattr(req, 'run_id', run_dir.name),
                                                             getattr(req, 'stage', 'data_fetch'), demand, as_of)
        if not records:
            return None
        path = run_dir / "artifacts" / "dataset.json"
        from backend.app.agents.adapters import merge_supplemental_records
        from data_fetcher.models import ResearchRecord, ResearchRequirement, StructuredResearchDataset

        dataset = StructuredResearchDataset.model_validate_json(path.read_text(encoding="utf-8"))
        records = [ResearchRecord.model_validate(record) for record in records]
        original_chain_gaps = set()
        if demand.get('source_type') == 'official-disclosure':
            for row in dataset.quality_summary.get('requirement_evidence_matrix') or []:
                requirement = ResearchRequirement.model_validate(row['requirement'])
                if requirement.domain.value == 'industry_chain' and not DataFetcherAgent._evaluate_requirement(dataset, requirement).passed:
                    original_chain_gaps.add(requirement.requirement_id)
        added_ids = merge_supplemental_records(dataset, {}, records, as_of)
        if not added_ids:
            return None
        if demand.get('source_type') == 'official-disclosure':
            improved = any(row['requirement']['requirement_id'] in original_chain_gaps
                           and row['coverage'].get('passed')
                           and bool(set(row['coverage'].get('evidence_record_ids') or []) & set(added_ids))
                           for row in dataset.quality_summary.get('requirement_evidence_matrix') or [])
            if not improved:
                return None
        added_set = set(added_ids)
        records = [record for record in dataset.all_records() if record.record_id in added_set]
        data = original.stage_results[req.stage].model_copy(deep=True).data
        sources = list(data.get("source_records") or [])
        valid_domains = {"industry", "companies", "financials", "macro", "industry_chain", "reports", "news", "events"}
        for record in records:
            raw = record.model_dump(mode="json") if hasattr(record, "model_dump") else dict(record)
            domain = raw.get("domain", "financials")
            domain = domain if domain in valid_domains else "financials"
            sources.insert(0, {
                **raw, "domain": domain,
                "period": str(raw.get("period_end") or ""),
                "query": demand.get("query_hint", ""), "skill_name": "fetch_supplemental",
            })
            if isinstance(data.get("domains"), dict):
                data["domains"][domain] = int(data["domains"].get(domain) or 0) + 1
        data["source_records"] = sources[:120]
        data["record_count"] = int(data.get("record_count") or 0) + len(records)
        if "total_records" in data:
            data["total_records"] = int(data["total_records"] or 0) + len(records)
        data["replenishment_status"] = "completed"
        return {path: dataset.model_dump_json(indent=2)}, data, f"精准数据补采完成，新增 {len(records)} 条有效金融记录"

    async def _prepare_chapter_rewrite(
        self, req: ReviewRequest, original: WorkflowState, run_dir: Path,
    ) -> tuple[dict[Path, str], dict[str, Any], str]:
        from chapter_writer.agent import (
            ChapterWriterAgent, DEFAULT_OUTLINE, extract_global_quantitative_anchor,
            format_global_facts_prompt,
        )
        from chapter_writer.models import (
            ChapterDraft, ChapterWritingOptions, ChapterWritingRequest, ChartResult,
            InterpretationReport,
        )
        from chapter_writer.retriever import DynamicEvidenceRetriever

        art = run_dir / "artifacts"
        path = art / "chapter_result.json"
        package = json.loads(path.read_text(encoding="utf-8"))
        report_raw = json.loads((art / "interpretation_report.json").read_text(encoding="utf-8"))
        report = InterpretationReport.model_validate(report_raw)
        charts_path = art / "chart_result.json"
        charts = ChartResult.model_validate_json(charts_path.read_text(encoding="utf-8")) if charts_path.exists() else None
        edits = req.edited_data or {}
        target_id = edits.get("target_chapter_id")
        outline = next((c for c in DEFAULT_OUTLINE if c.chapter_id == target_id), None)
        if outline is None or not any(c.get("chapter_id") == target_id for c in package["chapters"]):
            raise ValueError(f"未找到待重写章节: {target_id}")
        instructions = [str(report_raw.get("expert_background") or ""), str(edits.get("instruction") or req.comment or "")]
        request = ChapterWritingRequest(report=report, charts=charts,
            options=ChapterWritingOptions(instruction="\n".join(x for x in instructions if x)))
        agent = ChapterWriterAgent()
        facts = extract_global_quantitative_anchor(report)
        context = DynamicEvidenceRetriever(request).retrieve(outline.chapter_id, outline)
        context["global_facts"] = facts
        context["global_facts_prompt"] = format_global_facts_prompt(facts)
        skills = await agent._plan_chapter_skills(outline, context, request)
        context["skills"] = [{"name": s.name, "instructions": s.instructions} for s, _, _ in skills]
        ready_charts = {c.chart_id: c for c in (charts.charts if charts else []) if c.status == "ready"}
        drops: list[str] = []

        async def record(event: str, **details: Any) -> None:
            event_hub.emit(req.run_id, req.stage, "info", event, tool="ChapterWriterAgent", details=details)

        chapter, fallback, warning = await agent._generate_audited_chapter(
            request, outline, context, ready_charts, facts, record, drops
        )
        package["chapters"] = [chapter.model_dump(mode="json") if c.get("chapter_id") == target_id else c
                               for c in package["chapters"]]
        # Legacy partial packages remain reviewable, but never retain a stale pass.
        parsed = []
        issues: list[str] = []
        for raw in package["chapters"]:
            try:
                parsed.append(ChapterDraft.model_validate(raw))
            except ValueError:
                issues.append(f"章节 {raw.get('chapter_id')} 结构不完整")
        before_audit = {c.chapter_id: c.model_dump(mode="json") for c in parsed}
        issues.extend(agent._audit_package(parsed, set(report.evidence_index), ready_charts, facts))
        for audited in parsed:
            raw = audited.model_dump(mode="json")
            if audited.chapter_id == target_id:
                package["chapters"] = [raw if c.get("chapter_id") == target_id else c
                                       for c in package["chapters"]]
            elif raw != before_audit[audited.chapter_id]:
                # A targeted rewrite must not silently modify other chapters or
                # certify their unpersisted repairs as having passed inspection.
                issues.append(f"章节 {audited.chapter_id} 的图表归位需全量审校")
        fallback_ids = [c.chapter_id for c in parsed if c.used_fallback]
        if fallback and fallback not in fallback_ids:
            fallback_ids.append(fallback)
        if fallback_ids:
            issues.append(f"{len(fallback_ids)} 章使用确定性兜底稿")
        issues = list(dict.fromkeys(issues))
        cited = {eid for c in parsed for s in c.sections for p in s.paragraphs for eid in p.evidence_ids}
        allowed = set(report.evidence_index)
        quality = {
            "passed": not issues, "chapter_count": len(package["chapters"]),
            "section_count": sum(len(c.get("sections", [])) for c in package["chapters"]),
            "evidence_coverage": len(cited & allowed) / len(allowed) if allowed else 0,
            "issues": issues, "fallback_chapter_ids": fallback_ids,
        }
        package.update(quality=quality, status="partial" if issues else "completed",
                       warnings=list(dict.fromkeys([*report.warnings, *drops, *([warning] if warning else []), *issues])))
        data = original.stage_results[req.stage].model_copy(deep=True).data
        data.update(chapters=package["chapters"], quality=quality, agent_status=package["status"],
                    warnings=package["warnings"])
        return {path: json.dumps(package, ensure_ascii=False, indent=2)}, data, f"单章定向重写完成（章节 {target_id}）"

    @staticmethod
    def _intervention_input_versions(run_dir: Path, stage: str) -> dict[Path, str | None]:
        watched = ([run_dir / 'input_data.json', run_dir / 'artifacts' / 'dataset.json']
                   if stage == 'data_fetch' else [])
        return {path: hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
                for path in watched}

    async def _execute_intervention(self, req: ReviewRequest, original: WorkflowState,
                                    captured_versions: dict[Path, str | None] | None = None) -> None:
        """Use the existing task registry, cancellation and revision guard for local work."""
        run_dir = storage.get_run_dir(req.run_id)
        try:
            versions = captured_versions if captured_versions is not None else self._intervention_input_versions(run_dir, req.stage)
            if req.stage == "data_fetch":
                prepared = await self._prepare_supplement(req, original, run_dir)
            else:
                prepared = await self._prepare_chapter_rewrite(req, original, run_dir)
            async with self._run_lock(req.run_id):
                fresh = storage.load_state(req.run_id)
                if fresh is None or fresh.status == "cancelled" or fresh.revision != original.revision:
                    return
                result = fresh.stage_results[req.stage]
                if fresh.current_stage != req.stage or fresh.status != 'running' or result.status != 'running':
                    return
                if self._intervention_input_versions(run_dir, req.stage) != versions:
                    result.data['replenishment_status'] = 'discarded_stale_input'
                    fresh.status = result.status = 'waiting_review'
                    fresh.updated_at = datetime.now().isoformat()
                    storage.save_state(fresh)
                    event_hub.emit(req.run_id, req.stage, 'info', '输入已变化，已丢弃旧输入上的补采结果', tool='DataReplenisher')
                    return
                if prepared is None:
                    fresh = original.model_copy(deep=True)
                    fresh.stage_results[req.stage].data["replenishment_status"] = "no_new_data"
                    fresh.updated_at = datetime.now().isoformat()
                    storage.save_state(fresh)
                    event_hub.emit(req.run_id, req.stage, "info", "本次补采没有新增数据，保留原版本", tool="DataReplenisher")
                    return
                files, data, message = prepared
                touched: dict[Path, bytes | None] = {}

                def backup(path: Path) -> None:
                    if path not in touched:
                        touched[path] = path.read_bytes() if path.exists() else None

                try:
                    for path, content in files.items():
                        backup(path)
                        path.write_text(content, encoding="utf-8")
                    result.data = data
                    result.error = None
                    fresh.revision += 1
                    result.revision = fresh.revision
                    fresh.status = result.status = "waiting_review"
                    self._invalidate_following_stages(fresh, req.stage)
                    fresh.updated_at = datetime.now().isoformat()
                    self._commit_state_with_history(
                        run_dir, fresh, action=req.action, stage=req.stage,
                        from_revision=original.revision, to_revision=fresh.revision,
                        comment=req.comment, changed_fields=sorted((req.edited_data or {}).keys()),
                        edited_data=req.edited_data, snapshot_state=original, backup=backup,
                    )
                except Exception:
                    for path, contents in touched.items():
                        if contents is None:
                            path.unlink(missing_ok=True)
                        else:
                            path.write_bytes(contents)
                    raise
                event_hub.emit(req.run_id, req.stage, "artifact_created", message,
                    tool="DataReplenisher" if req.stage == "data_fetch" else "SingleChapterRewriter")
        except asyncio.CancelledError:
            # The cancellation owner holds the run lock and persists cancelled state.
            return
        except Exception as exc:
            logger.exception("[%s] 局部修订失败", req.run_id)
            async with self._run_lock(req.run_id):
                fresh = storage.load_state(req.run_id)
                if fresh and fresh.status != "cancelled" and fresh.revision == original.revision:
                    fresh.status = fresh.stage_results[req.stage].status = "failed"
                    fresh.stage_results[req.stage].error = str(exc)
                    fresh.updated_at = datetime.now().isoformat()
                    storage.save_state(fresh)
                    event_hub.emit(req.run_id, req.stage, "error", f"局部修订失败: {exc}", tool="HumanIntervention")
        finally:
            if self._running_tasks.get(req.run_id) is asyncio.current_task():
                self._running_tasks.pop(req.run_id, None)

    async def handle_review(self, req: ReviewRequest) -> WorkflowState:
        self._ensure_not_clearing()
        async with self._run_lock(req.run_id):
            self._ensure_not_clearing()
            result = await self._handle_review_locked(req)
            task = self._running_tasks.get(req.run_id)
        action_type = (req.edited_data or {}).get("action_type")
        intervention = (
            req.action in ("revise", "customize")
            and ((req.stage == "data_fetch" and action_type in ("replenish", "partial_refetch"))
                 or (req.stage == "chapter_write" and action_type == "single_chapter_rewrite"))
        )
        if intervention and task is not None:
            # Waiting outside the run lock lets completion and cancellation acquire it.
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=1.5)
            except asyncio.TimeoutError:
                pass
            result = storage.load_state(req.run_id) or result
        return result

    async def _handle_review_locked(self, req: ReviewRequest) -> WorkflowState:
        state = storage.load_state(req.run_id)
        if not state:
            raise ValueError(f"任务不存在: {req.run_id}")
        self._validate_review(state, req)

        # Validate the entire batch before saving snapshots or editing any data.
        if req.stage == "chart_generate" and req.edited_data:
            for spec in req.edited_data.get("chart_specs", []):
                if not isinstance(spec, dict):
                    raise ValueError("图表规格必须为对象")
                storage._safe_file_name(spec.get("chart_id"))
                charts_dir = storage.get_run_dir(req.run_id) / "artifacts" / "charts"
                target = (charts_dir / f"{spec['chart_id']}.svg").resolve()
                if not target.is_relative_to(charts_dir.resolve()):
                    raise ValueError("图表文件不得写出 charts 目录")

        # S-02：任何写入与任务派发之前，先校验版本、目标阶段与允许动作。
        # 同一版本重复 approve 也要被阶段状态拦住，不能只比较 revision。
        if req.expected_revision is not None and req.expected_revision != state.revision:
            raise RevisionConflictError(req.run_id, req.expected_revision, state.revision)
        running_task = self._running_tasks.get(req.run_id)
        run_busy = (state.status == "running"
                    or any(sr.status == "running" for sr in state.stage_results.values())
                    or (running_task is not None and not running_task.done()))
        if run_busy and req.action != "cancel":
            # 硬阻塞优先给出原有可读原因；其余忙碌状态按并发冲突拒绝。
            candidate = state.stage_results.get(req.stage)
            if candidate is not None and req.action in ("approve", "accept_recommendation", "accept_with_risks"):
                allowed, reason = assess_stage_progression(candidate, req.stage)
                if not allowed:
                    raise StageBlockedError(req.run_id, req.stage, reason)
            # 适配器会写本 run 的共享产物；后台工作时连上游编辑也会改变其输入。
            raise RevisionConflictError(req.run_id, req.expected_revision or state.revision, state.revision)
        target_result = state.stage_results.get(req.stage)
        if target_result is None:
            raise ValueError(f"无效的阶段: {req.stage}")
        if req.action in ("approve", "accept_recommendation", "accept_with_risks", "direct_edit"):
            if req.action == "direct_edit":
                # R1：正在执行中的阶段拒绝就地编辑——后台按输入版本提交结果，
                # 与手工编辑天然冲突；旧实现放行后编辑会被后台写回吞掉。
                if target_result.status == "running":
                    raise RevisionConflictError(
                        req.run_id, req.expected_revision or state.revision, state.revision
                    )
                # 就地编辑允许在 waiting_review / approved 状态保存，但必须先有阶段结果
                if target_result.status == "pending":
                    raise ValueError(f"阶段 {req.stage} 尚未产出结果，无法就地编辑")
            elif target_result.status not in ("waiting_review", "running", "rejected"):
                # 已 approved/completed 的阶段重复批准：拒绝，避免重复派发
                raise RevisionConflictError(req.run_id, req.expected_revision or state.revision, state.revision)

        logger.info(f"[{req.run_id}] 收到人工审核: stage={req.stage}, action={req.action}")

        # 读取任务创建时的 review_stages
        run_dir = storage.get_run_dir(req.run_id)
        input_file = run_dir / "input_data.json"
        review_stages = ["data_fetch", "data_interpret", "chart_generate", "chapter_write", "report_fusion"]
        if input_file.exists():
            try:
                data = RunCreateRequest.model_validate_json(input_file.read_text(encoding="utf-8"))
                review_stages = data.review_stages
            except Exception:
                pass

        if req.action in ("approve", "accept_recommendation", "accept_with_risks"):
            # S-01：三种批准动作共用同一硬阻塞守卫；风险接受不能覆盖硬阻塞。
            target = state.stage_results.get(req.stage)
            if target is not None:
                if req.stage == "report_fusion" and req.release_mode is not None:
                    target.data = {**target.data, "release_mode": req.release_mode}
                allowed, block_reason = assess_stage_progression(target, req.stage)
                if not allowed:
                    logger.warning(
                        f"[{req.run_id}] 拒绝批准硬阻塞阶段 {req.stage}（action={req.action}）：{block_reason}"
                    )
                    raise StageBlockedError(req.run_id, req.stage, block_reason)

            state.revision += 1
            # 批准当前阶段，推进到下一阶段
            current_stage = req.stage
            state.stage_results[current_stage].status = "approved" if current_stage != "report_fusion" else "completed"
            next_stage = self.get_next_stage(current_stage)

            if next_stage:
                state.current_stage = next_stage
                state.status = "running"
                state.stage_results[next_stage].status = "running"
                state.updated_at = datetime.now().isoformat()
                storage.save_state(state)

                # 异步推进下一阶段
                task = asyncio.create_task(
                    self._execute_stage(req.run_id, next_stage, review_stages, feedback=None)
                )
                self._running_tasks[req.run_id] = task
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=1.5)
                except asyncio.TimeoutError:
                    pass
            else:
                # 已经是最后阶段 (report_fusion 获批)
                fusion_result = state.stage_results[current_stage]
                fusion_data = fusion_result.data or {}
                # R1 §4.3 步骤 8：融合内容被就地编辑后，批准前必须先重导出，
                # 否则旧 PDF/MD/HTML 会带着旧标题冒充新版。
                if fusion_data.get("needs_reexport"):
                    try:
                        await self._reexport_fusion_artifacts(req.run_id)
                    except Exception as export_err:
                        raise StageBlockedError(
                            req.run_id,
                            current_stage,
                            f"报告重导出失败，请重试或使用修订重跑：{export_err}",
                        ) from export_err
                    fusion_data["needs_reexport"] = False

                # R1：批准即当前版本——登记构建代次，供下载资格做比较
                fusion_result.data = {**fusion_data, "built_at_revision": state.revision}
                fusion_result.status = "completed"
                state.status = "completed"
                state.updated_at = datetime.now().isoformat()
                storage.save_state(state)

        elif req.action == "direct_edit":
            # 用户就地直接编辑局部数据，无需全量重跑大模型。
            # S-02：整段走「先备份 → 应用 → 一次性提交」，任一步失败都回滚本次影响。
            if not (req.edited_data and isinstance(req.edited_data, dict)):
                raise ValueError("direct_edit 必须提供 edited_data")

            prev_revision = state.revision
            prev_data = json.loads(
                json.dumps(state.stage_results[req.stage].data or {}, ensure_ascii=False, default=str)
            )
            if req.stage == "chart_generate" and "chart_specs" in req.edited_data:
                edited_chart_ids = {
                    str(item.get("chart_id"))
                    for item in req.edited_data["chart_specs"]
                    if isinstance(item, dict) and item.get("chart_id")
                }
            else:
                edited_chart_ids = set()

            art_dir = run_dir / "artifacts"
            touched: dict[Path, bytes | None] = {}

            def _backup(path: Path) -> None:
                if path not in touched:
                    touched[path] = path.read_bytes() if path.exists() else None

            def _restore() -> None:
                for path, original in touched.items():
                    try:
                        if original is None:
                            path.unlink(missing_ok=True)
                        else:
                            path.write_bytes(original)
                    except Exception as restore_err:  # 回滚尽力而为，不掩盖主异常
                        logger.error(f"回滚 {path} 失败: {restore_err}")
                state.stage_results[req.stage].data = prev_data
                state.stage_results[req.stage].revision = prev_revision
                state.revision = prev_revision

            try:
                await self._apply_direct_edit(
                    state=state,
                    run_dir=run_dir,
                    art_dir=art_dir,
                    req=req,
                    edited_chart_ids=edited_chart_ids,
                    backup=_backup,
                )

                changed_fields = sorted(
                    k for k in req.edited_data.keys() if not k.startswith("__")
                )
                invalidated = self._invalidate_downstream(state, req.stage)
                if invalidated:
                    data = state.stage_results[req.stage].data
                    data["downstream_stale"] = True
                    data["invalidated_stages"] = invalidated

                # R1 §4.3 步骤 8：融合内容编辑必须先重导出再批准，
                # 这里打上待重导出标记；approve 分支据此触发 _reexport。
                if req.stage == "report_fusion" and changed_fields:
                    data = state.stage_results[req.stage].data
                    data["needs_reexport"] = True

                # Invalidate old exports and audit results in the same rollback boundary.
                if req.stage == "report_fusion":
                    from backend.app.core.report_exports import refresh_edited_exports
                    for name in ("report_view.json", "report.md", "report.html", "report.pdf", "manifest.json", "consistency_report.json"):
                        _backup(art_dir / name)
                    refresh_edited_exports(state, run_dir, req.edited_data)
                else:
                    self._invalidate_following_stages(state, req.stage)
                state.revision = prev_revision + 1
                state.stage_results[req.stage].revision = state.revision
                state.updated_at = datetime.now().isoformat()
                state.current_stage = req.stage
                state.status = "waiting_review"
                state.stage_results[req.stage].status = "waiting_review"
                # R1：提交（历史 + 快照 + state）也在同一保护段内。
                # 之前 _commit_state_with_history 在 try 之外，历史写成功而
                # state 落盘失败时会留下「假成功历史」。
                self._commit_state_with_history(
                    run_dir,
                    state,
                    action="direct_edit",
                    stage=req.stage,
                    from_revision=prev_revision,
                    to_revision=state.revision,
                    comment=req.comment,
                    changed_fields=changed_fields,
                    edited_data=req.edited_data,
                    backup=_backup,
                )
            except Exception:
                _restore()
                raise

            event_hub.emit(
                req.run_id, req.stage, "artifact_created",
                f"用户已就地保存第 r{state.revision} 版局部修改内容（未触发全量重算）"
                + (f"；下游待更新：{'、'.join(invalidated)}" if invalidated else ""),
                tool="HumanDirectEdit",
                details={"changed_fields": changed_fields, "invalidated_stages": invalidated},
            )
            return state

        elif req.action in ("revise", "customize"):
            action_type = (req.edited_data or {}).get("action_type")
            if ((req.stage == "data_fetch" and action_type in ("replenish", "partial_refetch"))
                    or (req.stage == "chapter_write" and action_type == "single_chapter_rewrite")):
                original = state.model_copy(deep=True)
                captured_versions = self._intervention_input_versions(run_dir, req.stage)
                state.current_stage = req.stage
                state.status = "running"
                state.stage_results[req.stage].status = "running"
                state.updated_at = datetime.now().isoformat()
                storage.save_state(state)
                task = asyncio.create_task(self._execute_intervention(req, original, captured_versions=captured_versions))
                self._running_tasks[req.run_id] = task
                return state
            # 保存前序版本的完整工作流快照供版本对比 (Revision Diff)
            rev_dir = run_dir / "revisions"
            rev_dir.mkdir(parents=True, exist_ok=True)
            prev_snapshot = rev_dir / f"{state.revision}.json"
            try:
                prev_snapshot.write_text(state.model_dump_json(indent=2), encoding="utf-8")
            except Exception as e:
                logger.warning(f"保存版本快照失败: {e}")

            # 整合结构化标注与用户反馈说明
            combined_feedback = req.comment or ""
            if req.edited_data and isinstance(req.edited_data, dict):
                annotations = req.edited_data.get("annotations")
                if annotations and isinstance(annotations, list):
                    annot_lines = []
                    for a in annotations:
                        action_type = a.get("type", "强调")
                        item_title = a.get("title", "")
                        note = a.get("note", "")
                        annot_lines.append(f"- 【{action_type}】{item_title} (备注: {note})" if note else f"- 【{action_type}】{item_title}")
                    if annot_lines:
                        annot_text = "【用户对象级标注要求】:\n" + "\n".join(annot_lines)
                        combined_feedback = f"{annot_text}\n【综合补充指令】: {combined_feedback}" if combined_feedback else annot_text

                if req.stage == "data_fetch":
                    kws = req.edited_data.get("confirmed_keywords")
                    scopes = req.edited_data.get("confirmed_scope")
                    if kws or scopes:
                        kw_line = f"【指定必查核心检索关键词】: {', '.join(kws)}" if kws else ""
                        scope_line = f"【指定重点覆盖领域】: {', '.join(scopes)}" if scopes else ""
                        extra_parts = [p for p in (kw_line, scope_line) if p]
                        if extra_parts:
                            combined_feedback = f"{'；'.join(extra_parts)}\n{combined_feedback}" if combined_feedback else "；".join(extra_parts)

            # 记录协同反馈历史
            history_file = run_dir / "feedback_history.json"
            history = []
            if history_file.exists():
                try:
                    history = json.loads(history_file.read_text(encoding="utf-8"))
                except Exception:
                    history = []
            history.append({
                "from_revision": state.revision,
                "to_revision": state.revision + 1,
                "stage": req.stage,
                "comment": req.comment,
                "edited_data": req.edited_data,
                "combined_feedback": combined_feedback,
                "timestamp": datetime.now().isoformat(),
            })
            history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

            self._invalidate_following_stages(state, req.stage)
            state.current_stage = req.stage

            # 修改重跑：增加 revision 并注入用户反馈
            state.revision += 1
            state.status = "running"
            state.stage_results[req.stage].status = "running"
            state.stage_results[req.stage].revision = state.revision
            state.updated_at = datetime.now().isoformat()
            storage.save_state(state)

            event_hub.emit(
                req.run_id, req.stage, "agent_start",
                f"收到第 r{state.revision} 版协同优化需求: {combined_feedback[:80]}，正在启动定向重构...",
                tool="HumanInTheLoop"
            )

            task = asyncio.create_task(
                self._execute_stage(req.run_id, req.stage, review_stages, feedback=combined_feedback)
            )
            self._running_tasks[req.run_id] = task
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=1.5)
            except asyncio.TimeoutError:
                pass

        elif req.action == "regenerate":
            # 原条件重跑
            self._invalidate_following_stages(state, req.stage)
            state.current_stage = req.stage
            state.revision += 1
            state.status = "running"
            state.stage_results[req.stage].status = "running"
            state.updated_at = datetime.now().isoformat()
            storage.save_state(state)

            task = asyncio.create_task(
                self._execute_stage(req.run_id, req.stage, review_stages, feedback=None)
            )
            self._running_tasks[req.run_id] = task
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=1.5)
            except asyncio.TimeoutError:
                pass

        elif req.action == "cancel":
            await self._stop_task(req.run_id)
            state.status = "cancelled"
            state.stage_results[req.stage].status = "cancelled"
            state.updated_at = datetime.now().isoformat()
            storage.save_state(state)

        latest = storage.load_state(req.run_id)
        return latest or state

    async def cancel_run(self, run_id: str) -> WorkflowState:
        async with self._run_lock(run_id):
            return await self._cancel_run_locked(run_id)

    async def _cancel_run_locked(self, run_id: str) -> WorkflowState:
        """中途强行中断并取消正在执行或等待中的任务"""
        state = storage.load_state(run_id)
        if not state:
            raise ValueError(f"任务不存在: {run_id}")

        logger.info(f"[{run_id}] 收到中途强行取消请求 (当前状态: {state.status}, 阶段: {state.current_stage})")

        # 1. 尝试强行中断后台运行的异步协程 Task
        await self._stop_task(run_id)
        state = storage.load_state(run_id) or state

        # 2. 将全局状态与当前阶段状态即时置为 cancelled
        state.status = "cancelled"
        if state.current_stage and state.current_stage in state.stage_results:
            state.stage_results[state.current_stage].status = "cancelled"
        state.updated_at = datetime.now().isoformat()
        storage.save_state(state)
        logger.info(f"[{run_id}] 任务已被成功标记为已取消 (cancelled)")
        return state

    async def restore_revision(self, run_id: str, revision: int) -> WorkflowState:
        """从历史版本快照回滚并恢复为新的最新修订版本。"""
        async with self._run_lock(run_id):
            await self._stop_task(run_id)
            current = storage.load_state(run_id)
            if not current:
                raise ValueError(f"任务不存在: {run_id}")

            snapshot = storage.load_revision(run_id, revision)
            if not snapshot:
                raise ValueError(f"未找到版本快照: run_id={run_id}, revision={revision}")

            run_dir = storage.get_run_dir(run_id)
            rev_dir = run_dir / "revisions"
            rev_dir.mkdir(parents=True, exist_ok=True)

            # 保障当前版本快照存在
            current_snap = rev_dir / f"{current.revision}.json"
            if not current_snap.exists():
                try:
                    current_snap.write_text(current.model_dump_json(indent=2), encoding="utf-8")
                except Exception as exc:
                    logger.warning(f"保存当前版本快照失败: {exc}")

            new_revision = current.revision + 1

            # 恢复快照并构建新版本
            restored = snapshot.model_copy(deep=True)
            restored.revision = new_revision
            restored.updated_at = datetime.now().isoformat()

            # 若快照原本状态为 running 或 failed，恢复为 waiting_review 便于用户审核
            if restored.status in ("running", "failed"):
                restored.status = "waiting_review"
                if restored.current_stage and restored.current_stage in restored.stage_results:
                    restored.stage_results[restored.current_stage].status = "waiting_review"

            # 尝试恢复产物归档 (若存在)
            archive_dir = rev_dir / "artifacts" / f"r{revision}"
            artifacts_dir = run_dir / "artifacts"
            if archive_dir.exists():
                try:
                    artifacts_dir.mkdir(parents=True, exist_ok=True)
                    for item in archive_dir.glob("*"):
                        dest = artifacts_dir / item.name
                        if item.is_file():
                            shutil.copy2(item, dest)
                        elif item.is_dir():
                            if dest.exists():
                                shutil.rmtree(dest)
                            shutil.copytree(item, dest)
                except Exception as exc:
                    logger.warning(f"[{run_id}] 恢复产物归档时发生非致命警告: {exc}")

            # 提交历史并持久化
            self._commit_state_with_history(
                run_dir,
                restored,
                action="restore_revision",
                stage=restored.current_stage or "data_fetch",
                from_revision=current.revision,
                to_revision=new_revision,
                comment=f"已从历史版本 r{revision} 回滚恢复",
                changed_fields=["*"],
                snapshot_state=current,
            )

            # 保存新版本的快照
            new_snap = rev_dir / f"{new_revision}.json"
            try:
                new_snap.write_text(restored.model_dump_json(indent=2), encoding="utf-8")
            except Exception as exc:
                logger.warning(f"保存恢复后版本快照失败: {exc}")

            # SSE 广播事件
            event_hub.emit(
                run_id,
                restored.current_stage or "data_fetch",
                "state_change",
                f"已从历史版本 r{revision} 回滚恢复，生成新版本 r{new_revision}",
                tool="VersionRestore",
                details={
                    "restored_from_revision": revision,
                    "new_revision": new_revision,
                    "current_stage": restored.current_stage,
                    "status": restored.status,
                },
            )
            logger.info(f"[{run_id}] 成功从 r{revision} 恢复并递增为 r{new_revision}")
            return restored

    @staticmethod
    def _validate_review(state: WorkflowState, req: ReviewRequest) -> None:
        if req.expected_revision != state.revision:
            raise RevisionConflictError(req.run_id, req.expected_revision, state.revision)
        stage_result = state.stage_results.get(req.stage)
        if stage_result is None:
            raise ReviewConflictError("该任务不存在请求的阶段")
        if req.action == "cancel":
            if state.status not in ("running", "waiting_review") or req.stage != state.current_stage:
                raise ReviewConflictError("任务当前不能取消")
            return
        if req.action in ("approve", "accept_recommendation", "accept_with_risks"):
            if req.stage == "report_fusion" and stage_result.data.get("quality_notice"):
                raise StageBlockedError(req.run_id, req.stage, "报告经人工修改，需重新融合并完成质检后定稿")
            candidate = stage_result.model_copy(deep=True)
            if req.stage == "report_fusion" and req.release_mode is not None:
                candidate.data["release_mode"] = req.release_mode
            allowed, reason = assess_stage_progression(candidate, req.stage)
            if not allowed:
                raise StageBlockedError(req.run_id, req.stage, reason)
        if state.status == "running":
            raise ReviewConflictError("任务正在执行，请等待当前阶段结束")
        if req.action in ("approve", "accept_recommendation", "accept_with_risks"):
            if req.stage != state.current_stage or stage_result.status != "waiting_review":
                raise ReviewConflictError("仅能批准当前待审核阶段")
            if stage_result.data.get("exports_stale"):
                raise ReviewConflictError("报告修改后尚未生成当前版本的导出文件")
            for earlier in STAGE_ORDER[:STAGE_ORDER.index(req.stage)]:
                prior = state.stage_results.get(earlier)
                if prior and prior.status not in ("approved", "completed"):
                    raise ReviewConflictError("前序阶段尚未通过审核")
        elif stage_result.status not in ("waiting_review", "approved", "completed", "failed", "cancelled"):
            raise ReviewConflictError("该阶段尚未产生可修改或重试的结果")

    @staticmethod
    def _invalidate_following_stages(state: WorkflowState, stage: StageName) -> None:
        for following in STAGE_ORDER[STAGE_ORDER.index(stage) + 1:]:
            result = state.stage_results.get(following)
            if result:
                result.status = "pending"
                result.data = {"exports_stale": True} if following == "report_fusion" else {}
                result.artifacts = []
                result.error = None

        if stage == "report_fusion" and stage in state.stage_results:
            result = state.stage_results[stage]
            result.data.update(exports_stale=True, formats=[])
            result.artifacts = []

    async def clear_all_runs(self) -> tuple[int, int]:
        """Stop every writer under the same run locks before removing artifacts."""
        async with self._clear_lock:
            self._clearing_runs = True
            try:
                async with AsyncExitStack() as locks:
                    for run_id in sorted(set(self._run_locks) | set(self._running_tasks)):
                        await locks.enter_async_context(self._run_lock(run_id))
                    cancelled_count = sum(not task.done() for task in self._running_tasks.values())
                    for run_id in list(self._running_tasks):
                        await self._stop_task(run_id)
                    deleted_count = storage.clear_all_runs()
                    event_hub.clear_all()
                    return deleted_count, cancelled_count
            finally:
                self._clearing_runs = False

    async def resume_run(self, run_id: str, from_stage: StageName | None = None) -> WorkflowState:
        self._ensure_not_clearing()
        async with self._run_lock(run_id):
            self._ensure_not_clearing()
            running = self._running_tasks.get(run_id)
            if running is not None and not running.done():
                raise ReviewConflictError("该任务已有正在执行的阶段")
            return await self._resume_run_locked(run_id, from_stage)

    async def _resume_run_locked(self, run_id: str, from_stage: StageName | None = None) -> WorkflowState:
        """断点恢复执行：从中断、失败阶段或指定阶段一键继续推进流水线"""
        state = storage.load_state(run_id)
        if not state:
            raise ValueError(f"任务不存在: {run_id}")

        # 1. 若当前任务仍在执行中，直接返回
        running_task = self._running_tasks.get(run_id)
        if running_task and not running_task.done():
            logger.info(f"[{run_id}] 任务正在运行中，无需重复恢复")
            return state

        run_dir = storage.get_run_dir(run_id)
        art_dir = run_dir / "artifacts"

        stage_prereqs: dict[StageName, list[str]] = {
            "data_fetch": [],
            "data_interpret": ["dataset.json"],
            "chart_generate": ["interpretation_report.json"],
            "chapter_write": ["interpretation_report.json", "chart_result.json"],
            "report_fusion": ["interpretation_report.json", "chart_result.json", "chapter_result.json"],
        }

        # 2. 定位需要恢复推进的目标阶段
        target_stage: StageName | None = None
        if from_stage:
            if from_stage not in STAGE_ORDER:
                raise ValueError(f"无效的目标阶段: {from_stage}")
            target_stage = from_stage
        else:
            # 自动定位：寻找第一个未完成 (不是 approved/completed) 的阶段
            for s in STAGE_ORDER:
                sr = state.stage_results.get(s)
                if not sr or sr.status not in ("approved", "completed"):
                    target_stage = s
                    break

        if not target_stage:
            logger.info(f"[{run_id}] 全阶段均已完成，无需恢复")
            state.status = "completed"
            storage.save_state(state)
            return state

        # 校验前序产物是否存在；若缺失则前溯至最早缺失产物的阶段
        idx = STAGE_ORDER.index(target_stage)
        while idx > 0:
            current_check = STAGE_ORDER[idx]
            prereqs = stage_prereqs.get(current_check, [])
            missing = [f for f in prereqs if not (art_dir / f).exists()]
            if missing:
                prev_stage = STAGE_ORDER[idx - 1]
                logger.warning(f"[{run_id}] 阶段 {current_check} 缺失必要前序产物 {missing}，回溯至上一阶段 {prev_stage}")
                idx -= 1
                target_stage = prev_stage
            else:
                break

        # S-01：文件存在不等于内容有效。任一上游阶段处于硬阻塞时，禁止从其下游开始，
        # 必须回到最早的真实阻塞阶段重试（或拒绝恢复）。
        for earlier_stage in STAGE_ORDER[: STAGE_ORDER.index(target_stage)]:
            earlier = state.stage_results.get(earlier_stage)
            if earlier is None:
                continue
            allowed, block_reason = assess_stage_progression(earlier, earlier_stage)
            if not allowed:
                logger.warning(
                    f"[{run_id}] 上游阶段 {earlier_stage} 处于硬阻塞（{block_reason}），"
                    f"不能从 {target_stage} 开始恢复，回退至 {earlier_stage}"
                )
                target_stage = earlier_stage
                break

        # 3. 读取任务配置与人工审核阶段策略
        run_dir = storage.get_run_dir(run_id)
        review_stages = ["data_fetch", "data_interpret", "chart_generate", "chapter_write", "report_fusion"]
        input_file = run_dir / "input_data.json"
        if input_file.exists():
            try:
                req_data = RunCreateRequest.model_validate_json(input_file.read_text(encoding="utf-8"))
                review_stages = req_data.review_stages
            except Exception:
                pass

        logger.info(f"[{run_id}] 从断点阶段 [{target_stage}] 恢复流水线推进...")

        # 4. 重置后续阶段状态并更新当前阶段
        state.current_stage = target_stage
        state.status = "running"
        self._invalidate_following_stages(state, target_stage)
        target_idx = STAGE_ORDER.index(target_stage)
        for i, s in enumerate(STAGE_ORDER):
            if s not in state.stage_results:
                state.stage_results[s] = StageResult(stage=s, status="pending", revision=state.revision)
            if i == target_idx:
                state.stage_results[s].status = "running"
                state.stage_results[s].error = None
            elif i > target_idx:
                state.stage_results[s].status = "pending"
                state.stage_results[s].error = None

        state.updated_at = datetime.now().isoformat()
        storage.save_state(state)

        # 5. 启动异步推进
        task = asyncio.create_task(
            self._execute_stage(run_id, target_stage, review_stages, feedback=None)
        )
        self._running_tasks[run_id] = task
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=1.5)
        except asyncio.TimeoutError:
            pass

        latest = storage.load_state(run_id)
        return latest or state

    async def _execute_stage(
        self,
        run_id: str,
        stage: StageName,
        review_stages: list[StageName],
        feedback: str | None = None,
    ) -> None:
        state = storage.load_state(run_id)
        if not state:
            return

        state.current_stage = stage
        state.status = "running"
        state.stage_results[stage].status = "running"
        state.updated_at = datetime.now().isoformat()
        # R1：记录本阶段执行的输入版本。耗时调用返回后以此为基准做 CAS——
        # 若期间用户保存了编辑（revision 前进），结果合并进**新版本**，而不是
        # 把整个旧快照写回去吞掉编辑。
        input_revision = state.revision
        storage.save_state(state)

        try:
            input_file = storage.get_run_dir(run_id) / "input_data.json"
            try:
                req_data = RunCreateRequest.model_validate_json(input_file.read_text(encoding="utf-8"))
                if not req_data.input_data.industry_topic.strip():
                    raise ValueError("研究主题不能为空")
            except (OSError, ValueError) as exc:
                raise ValueError(f"任务输入缺失或损坏，无法执行阶段 {stage}: {exc}") from exc
            inputs = req_data.input_data
            industry = inputs.industry_topic
            focus_points = inputs.focus_questions
            market_scope = inputs.market_scope
            security_types = inputs.security_types
            reporting_currency = inputs.reporting_currency
            research_as_of = inputs.research_as_of
            analysis_depth = inputs.analysis_depth
            selected_skills = inputs.selected_skills
            chain_research_strategy = (
                inputs.data_fetch_options.chain_research_strategy
                if inputs.data_fetch_options else "profile_guided"
            )
            chain_profile_id = inputs.data_fetch_options.chain_profile_id if inputs.data_fetch_options else None
            logger.info(f"[{run_id}] 开始执行阶段: {stage}")
            result: StageResult
            if stage == "data_fetch":
                result = await FiveAgentsAdapter.run_data_fetcher(
                    run_id=run_id,
                    industry=industry,
                    focus_points=focus_points,
                    feedback=feedback,
                    market_scope=market_scope,
                    security_types=security_types,
                    research_as_of=research_as_of,
                    analysis_depth=analysis_depth,
                    chain_research_strategy=chain_research_strategy,
                    chain_profile_id=chain_profile_id,
                    focus_companies=inputs.research_brief.focus_companies if inputs.research_brief else None,
                )
            elif stage == "data_interpret":
                # v3：A1 模型生成的指标验收需求随阶段产物透传给解读层
                fetch_stage = state.stage_results.get("data_fetch")
                metric_requirements = (
                    (fetch_stage.data or {}).get("metric_requirements")
                    if fetch_stage and isinstance(fetch_stage.data, dict)
                    else None
                )
                result = await FiveAgentsAdapter.run_data_interpreter(
                    run_id=run_id,
                    industry=industry,
                    feedback=feedback,
                    market_scope=market_scope,
                    security_types=security_types,
                    reporting_currency=reporting_currency,
                    research_as_of=research_as_of,
                    analysis_depth=analysis_depth,
                    # 用户原始问询必须透传给解读层：其技能路由靠它做关键词匹配
                    user_questions=focus_points,
                    selected_skills=selected_skills,
                    metric_requirements=metric_requirements,
                    sensitivity_scenarios=inputs.sensitivity_scenarios,
                )
            elif stage == "chart_generate":
                result = await FiveAgentsAdapter.run_chart_generator(
                    run_id=run_id,
                    feedback=feedback,
                )
            elif stage == "chapter_write":
                result = await FiveAgentsAdapter.run_chapter_writer(
                    run_id=run_id,
                    feedback=feedback,
                    selected_skills=selected_skills,
                )
            elif stage == "report_fusion":
                result = await FiveAgentsAdapter.run_report_fusion(
                    run_id=run_id,
                    industry=industry,
                    feedback=feedback,
                    market_scope=market_scope,
                    security_types=security_types,
                    reporting_currency=reporting_currency,
                    research_as_of=research_as_of,
                )
            else:
                raise ValueError(f"未知阶段: {stage}")

            if stage == "chart_generate" and result.data.get("data_demands"):
                supplement_status = await self._run_chart_supplement(
                    run_id, input_revision, result, date.fromisoformat(research_as_of)
                )
                if supplement_status == "committed":
                    await self._execute_stage(run_id, "data_interpret", review_stages, feedback=None)
                    return
                if supplement_status == "discarded":
                    return

            # ── R1：结果提交段（持锁 + CAS 合并）──────────────────────────────
            # 耗时调用已结束；从这里开始进入互斥保护区。以**最新落盘状态**为基底
            # 合并本阶段结果，绝不把整个旧快照写回（旧实现的写入会吞掉执行期间
            # 保存的人工编辑，并把 revision 写回旧值）。
            next_stage = self.get_next_stage(stage)
            lock = self._lock_for(run_id)
            async with lock:
                fresh = storage.load_state(run_id)
                if fresh is None:
                    logger.warning(f"[{run_id}] 阶段 {stage} 完成但任务不存在，丢弃结果")
                    return
                if fresh.status == "cancelled":
                    logger.info(f"[{run_id}] 检测到任务已被中途取消，终止写入阶段结果与后续流转")
                    return

                if fresh.revision != input_revision:
                    logger.info(
                        f"[{run_id}] 丢弃阶段 {stage} 的旧输入结果："
                        f"r{input_revision} != 当前 r{fresh.revision}"
                    )
                    return
                state = fresh  # 后续流转全部基于最新状态
                result.revision = state.revision
                state.stage_results[stage] = result

                # A sanitized limited export is built from this CAS-checked revision
                # even when its content correctly blocks formal progression.
                if (stage == "report_fusion" and result.data.get("draft_available")
                        and result.data.get("draft_sanitized") and result.artifacts):
                    result.data = {**result.data, "built_at_revision": state.revision}

                # S-01：流转前统一识别终止性失败/硬阻塞。
                # 必须在 review_stages 覆盖状态**之前**判定，否则 failed 会被改写成 approved。
                allowed, block_reason = assess_stage_progression(result, stage)
                if not allowed:
                    result.status = "failed" if result.status == "failed" else "waiting_review"
                    result.error = result.error or block_reason
                    result.data = {**(result.data or {}), "block_reason": block_reason, "blocked": True}
                    state.status = "waiting_review" if result.status != "failed" else "failed"
                    state.stage_results[stage] = result
                    state.updated_at = datetime.now().isoformat()
                    storage.save_state(state)
                    event_hub.emit(
                        run_id, stage, "error",
                        f"阶段 {stage} 硬阻塞，已阻止下游生成：{block_reason}",
                        tool="StageGate",
                        details={"block_reason": block_reason, "stage": stage},
                    )
                    logger.warning(f"[{run_id}] 阶段 {stage} 硬阻塞，停止流转: {block_reason}")
                    return

                # R1：融合阶段成功时登记「构建版本」——下载资格据此做代次比较，
                # 替代旧的永久 downstream_stale 布尔（重建后永远不会被消费）。
                if stage == "report_fusion":
                    result.data = {**(result.data or {}), "built_at_revision": state.revision}
                    state.stage_results[stage] = result

                # 判断下一步流转策略：
                # 若该阶段在 review_stages 中，则进入 waiting_review 等待人工审核！
                if stage in review_stages:
                    result.status = "waiting_review"
                    state.status = "waiting_review"
                    state.updated_at = datetime.now().isoformat()
                    storage.save_state(state)
                    logger.info(f"[{run_id}] 阶段 {stage} 完成，暂停等待人工审核 (waiting_review)")
                else:
                    # 自动通过并进入下一阶段
                    result.status = "approved" if stage != "report_fusion" else "completed"
                    if next_stage:
                        logger.info(f"[{run_id}] 阶段 {stage} 自动通过，流转至下一阶段: {next_stage}")
                        state.current_stage = next_stage
                        state.status = "running"
                        state.stage_results[next_stage].status = "running"
                        state.updated_at = datetime.now().isoformat()
                        storage.save_state(state)
                    else:
                        # 全流程结束
                        state.status = "completed"
                        state.updated_at = datetime.now().isoformat()
                        storage.save_state(state)
                        logger.info(f"[{run_id}] 全流水线执行圆满完成！(completed)")
            # 互斥保护区结束；递归推进在锁外执行，避免长时间占锁
            if stage not in review_stages and next_stage is not None and state.status == "running":
                await self._execute_stage(run_id, next_stage, review_stages, feedback=None)

        except asyncio.CancelledError:
            logger.info(f"[{run_id}] 阶段 {stage} 收到中止信号并安全退出 (CancelledError)")
            cur_state = storage.load_state(run_id) or state
            cur_state.status = "cancelled"
            if stage in cur_state.stage_results:
                cur_state.stage_results[stage].status = "cancelled"
            cur_state.updated_at = datetime.now().isoformat()
            storage.save_state(cur_state)
            return
        except Exception as e:
            from agents_core.call_ledger import safe_error
            error_label = safe_error(e)
            logger.error("[%s] 阶段 %s 执行出错: %s", run_id, stage, error_label)
            # R1：失败标记也必须合并进最新状态，不得用旧快照覆盖人工编辑
            lock = self._lock_for(run_id)
            async with lock:
                cur = storage.load_state(run_id) or state
                if cur.status == "cancelled" or cur.revision != input_revision:
                    return
                cur.status = "failed"
                cur.stage_results[stage].status = "failed"
                cur.stage_results[stage].error = error_label
                cur.updated_at = datetime.now().isoformat()
                storage.save_state(cur)
        finally:
            if self._running_tasks.get(run_id) is asyncio.current_task():
                self._running_tasks.pop(run_id, None)


engine = WorkflowEngine()
