from __future__ import annotations
import asyncio
import json
import logging
import re
import secrets
from datetime import datetime
from typing import Any

from backend.app.agents.adapters import FiveAgentsAdapter
from backend.app.core.event_hub import event_hub
from backend.app.core.storage import storage
from backend.app.schemas.workflow import (
    STAGE_ORDER,
    ReviewAction,
    ReviewRequest,
    RunCreateRequest,
    StageName,
    StageResult,
    WorkflowState,
)

logger = logging.getLogger("workflow_engine")


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


class WorkflowEngine:
    """行业研究报告五智能体流水线与人机协同状态机引擎"""

    def __init__(self) -> None:
        self._running_tasks: dict[str, asyncio.Task[Any]] = {}

    def get_next_stage(self, current_stage: StageName) -> StageName | None:
        try:
            idx = STAGE_ORDER.index(current_stage)
            if idx + 1 < len(STAGE_ORDER):
                return STAGE_ORDER[idx + 1]
        except ValueError:
            pass
        return None

    async def create_run(self, req: RunCreateRequest) -> WorkflowState:
        run_id = f"run-{datetime.now().strftime('%Y%m%d%H%M%S')}-{datetime.now().microsecond // 1000:03d}"
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

    async def handle_review(self, req: ReviewRequest) -> WorkflowState:
        state = storage.load_state(req.run_id)
        if not state:
            raise ValueError(f"任务不存在: {req.run_id}")

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
                state.stage_results[current_stage].status = "completed"
                state.status = "completed"
                state.updated_at = datetime.now().isoformat()
                storage.save_state(state)

        elif req.action == "direct_edit":
            # 用户就地直接编辑局部数据，无需全量重跑大模型
            rev_dir = run_dir / "revisions"
            rev_dir.mkdir(parents=True, exist_ok=True)
            prev_snapshot = rev_dir / f"{state.revision}.json"
            try:
                prev_snapshot.write_text(state.model_dump_json(indent=2), encoding="utf-8")
            except Exception as e:
                logger.warning(f"保存版本快照失败: {e}")

            if req.edited_data and isinstance(req.edited_data, dict):
                cur_data = state.stage_results[req.stage].data or {}

                # 针对图表阶段：保护图表规格的完整性，合并变更属性（形态、标题、状态、单位等），绝不丢弃原始 ECharts option 与数据
                if req.stage == "chart_generate" and "chart_specs" in req.edited_data:
                    existing_specs = cur_data.get("chart_specs") or cur_data.get("charts") or []
                    existing_map = {
                        s.get("chart_id"): s for s in existing_specs if isinstance(s, dict) and s.get("chart_id")
                    }
                    merged_specs = []
                    for incoming in req.edited_data["chart_specs"]:
                        cid = incoming.get("chart_id")
                        base = dict(existing_map.get(cid, {}))
                        base.update(incoming)
                        if ("option" not in incoming or not incoming.get("option")) and "option" in existing_map.get(cid, {}):
                            base["option"] = existing_map[cid]["option"]

                        # 如果形态类型发生变更且存在 option，自动将 option 转为目标形态
                        target_type = incoming.get("chart_type")
                        if target_type and base.get("option"):
                            base["option"] = morph_echarts_option(base["option"], target_type)

                        merged_specs.append(base)

                    req.edited_data["chart_specs"] = merged_specs

                cur_data.update(req.edited_data)
                state.stage_results[req.stage].data = cur_data

                # 同步更新 artifacts 目录下的持久化资产，确保下游阶段与导出立即生效
                art_dir = run_dir / "artifacts"
                if req.stage == "data_fetch":
                    ds_path = art_dir / "dataset.json"
                    deleted_ids = req.edited_data.get("deleted_record_ids", [])
                    if ds_path.exists() and deleted_ids:
                        try:
                            ds_json = json.loads(ds_path.read_text(encoding="utf-8"))
                            del_set = set(deleted_ids)
                            for list_key, val in ds_json.items():
                                if isinstance(val, list):
                                    ds_json[list_key] = [
                                        item for item in val
                                        if (item.get("record_id") if isinstance(item, dict) else getattr(item, "record_id", "")) not in del_set
                                    ]
                            ds_path.write_text(json.dumps(ds_json, ensure_ascii=False, indent=2), encoding="utf-8")
                        except Exception as e:
                            logger.warning(f"同步清洗 dataset.json 失败: {e}")
                    if deleted_ids and "source_records" in cur_data:
                        del_set = set(deleted_ids)
                        cur_data["source_records"] = [
                            r for r in cur_data["source_records"]
                            if r.get("record_id") not in del_set
                        ]
                    if deleted_ids and "record_count" in cur_data:
                        cur_data["record_count"] = max(0, int(cur_data["record_count"]) - len(deleted_ids))
                elif req.stage == "chapter_write" and "chapters" in req.edited_data:
                    ch_path = art_dir / "chapter_result.json"
                    if ch_path.exists():
                        try:
                            ch_json = json.loads(ch_path.read_text(encoding="utf-8"))
                            ch_json["chapters"] = req.edited_data["chapters"]
                            ch_path.write_text(json.dumps(ch_json, ensure_ascii=False, indent=2), encoding="utf-8")
                        except Exception as e:
                            logger.warning(f"同步更新 chapter_result.json 失败: {e}")
                    if "report_fusion" in state.stage_results and state.stage_results["report_fusion"].status in ("approved", "completed"):
                        state.stage_results["report_fusion"].status = "pending"
                elif req.stage == "chart_generate" and "chart_specs" in req.edited_data:
                    ct_path = art_dir / "chart_result.json"
                    if ct_path.exists():
                        try:
                            ct_json = json.loads(ct_path.read_text(encoding="utf-8"))
                            ct_json["charts"] = req.edited_data["chart_specs"]
                            ct_json["chart_specs"] = req.edited_data["chart_specs"]
                            ct_path.write_text(json.dumps(ct_json, ensure_ascii=False, indent=2), encoding="utf-8")
                        except Exception as e:
                            logger.warning(f"同步更新 chart_result.json 失败: {e}")
                elif req.stage == "data_interpret":
                    ir_path = art_dir / "interpretation_report.json"
                    if ir_path.exists():
                        try:
                            ir_json = json.loads(ir_path.read_text(encoding="utf-8"))
                            ir_json.update(req.edited_data)
                            ir_path.write_text(json.dumps(ir_json, ensure_ascii=False, indent=2), encoding="utf-8")
                        except Exception as e:
                            logger.warning(f"同步更新 interpretation_report.json 失败: {e}")
                elif req.stage == "report_fusion":
                    rf_path = art_dir / "report_view.json"
                    if rf_path.exists():
                        try:
                            rf_json = json.loads(rf_path.read_text(encoding="utf-8"))
                            rf_json.update(req.edited_data)
                            rf_path.write_text(json.dumps(rf_json, ensure_ascii=False, indent=2), encoding="utf-8")
                        except Exception as e:
                            logger.warning(f"同步更新 report_view.json 失败: {e}")

            state.revision += 1
            state.stage_results[req.stage].revision = state.revision
            state.updated_at = datetime.now().isoformat()
            storage.save_state(state)
            event_hub.emit(
                req.run_id, req.stage, "artifact_created",
                f"用户已就地保存第 r{state.revision} 版局部修改内容（未触发全量重算）",
                tool="HumanDirectEdit"
            )
            return state

        elif req.action in ("revise", "customize"):
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

            # 针对性人机协同精准介入分支 1：Stage 1 数据增量补采 / 局部子域重采
            if req.stage == "data_fetch" and req.edited_data and req.edited_data.get("action_type") in ("replenish", "partial_refetch"):
                demand = req.edited_data.get("demand") or {}
                if req.edited_data.get("action_type") == "partial_refetch":
                    selected_domains = req.edited_data.get("domains") or ["financials"]
                    demand = {
                        "domain": selected_domains[0] if selected_domains else "financials",
                        "entities": req.edited_data.get("entities") or [],
                        "query_hint": req.edited_data.get("query_hint") or f"重新采集{'、'.join(selected_domains)}相关核心指标",
                        "reason": req.edited_data.get("reason") or "局部子域重采",
                    }
                logger.info(f"[{req.run_id}] 收到数据采集精准介入需求 ({req.edited_data.get('action_type')}): {demand}")
                try:
                    import backend.app.core.setup_env
                    from data_fetcher.agent import DataFetcherAgent
                    agent = DataFetcherAgent()
                    new_records = await agent.fetch_supplemental(demand)
                except Exception as exc:
                    logger.warning(f"执行增量补采异常: {exc}")
                    new_records = []

                art_dir = run_dir / "artifacts"
                ds_path = art_dir / "dataset.json"
                if ds_path.exists() and new_records:
                    try:
                        ds_json = json.loads(ds_path.read_text(encoding="utf-8"))
                        if "records" not in ds_json or not isinstance(ds_json["records"], list):
                            ds_json["records"] = []
                        new_dicts = [r.model_dump(mode="json") if hasattr(r, "model_dump") else r for r in new_records]
                        ds_json["records"].extend(new_dicts)
                        ds_path.write_text(json.dumps(ds_json, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception as e:
                        logger.warning(f"增量补采写入 dataset.json 失败: {e}")

                cur_data = state.stage_results["data_fetch"].data or {}
                source_records = list(cur_data.get("source_records") or [])
                for r in new_records:
                    rec_dict = {
                        "record_id": getattr(r, "record_id", f"SUPP-{secrets.token_hex(3)}"),
                        "domain": getattr(r.domain, "value", str(r.domain)) if hasattr(r, "domain") else "financials",
                        "metric": getattr(r, "metric", "补充指标"),
                        "value": getattr(r, "value", 0),
                        "unit": getattr(r, "unit", ""),
                        "entity_name": getattr(r, "entity_name", demand.get("entities", [""])[0] if demand.get("entities") else ""),
                        "entity_code": getattr(r, "entity_code", ""),
                        "period": str(getattr(r, "period_end", "") or ""),
                        "query": demand.get("query_hint", ""),
                        "skill_name": "fetch_supplemental",
                    }
                    source_records.insert(0, rec_dict)
                cur_data["source_records"] = source_records[:120]
                cur_data["record_count"] = (cur_data.get("record_count") or 0) + len(new_records)
                state.stage_results["data_fetch"].data = cur_data
                state.revision += 1
                state.stage_results["data_fetch"].revision = state.revision
                state.status = "waiting_review"
                state.stage_results["data_fetch"].status = "waiting_review"
                state.updated_at = datetime.now().isoformat()
                storage.save_state(state)
                event_hub.emit(
                    req.run_id, "data_fetch", "artifact_created",
                    f"精准数据补采完成，新增 {len(new_records)} 条有效金融记录并入数据集 (r{state.revision})",
                    tool="DataReplenisher"
                )
                return state

            # 针对性人机协同精准介入分支 2：Stage 4 指定单章定向重写
            if req.stage == "chapter_write" and req.edited_data and req.edited_data.get("action_type") == "single_chapter_rewrite":
                target_chapter_id = req.edited_data.get("target_chapter_id")
                instruction = req.edited_data.get("instruction") or req.comment or ""
                logger.info(f"[{req.run_id}] 收到章节定向重写需求: {target_chapter_id}, 指令: {instruction}")
                art_dir = run_dir / "artifacts"
                ch_path = art_dir / "chapter_result.json"
                report_path = art_dir / "interpretation_report.json"
                chart_path = art_dir / "chart_result.json"
                if ch_path.exists() and report_path.exists() and target_chapter_id:
                    import backend.app.core.setup_env
                    from chapter_writer.agent import ChapterWriterAgent, DEFAULT_OUTLINE, extract_global_quantitative_anchor, format_global_facts_prompt
                    from chapter_writer.models import ChapterWritingRequest, InterpretationReport, ChartResult, ChapterWritingOptions, ChapterDraft
                    from chapter_writer.retriever import DynamicEvidenceRetriever

                    with open(report_path, "r", encoding="utf-8") as f:
                        report = InterpretationReport.model_validate(json.load(f))
                    chart_res = None
                    if chart_path.exists():
                        with open(chart_path, "r", encoding="utf-8") as f:
                            chart_res = ChartResult.model_validate(json.load(f))

                    writing_options = ChapterWritingOptions(
                        instruction=f"【用户定向重写指令】: {instruction}" if instruction else ""
                    )
                    request = ChapterWritingRequest(
                        report=report,
                        charts=chart_res,
                        options=writing_options,
                    )
                    agent = ChapterWriterAgent()
                    outline_chapter = next((c for c in (request.outline or DEFAULT_OUTLINE) if c.chapter_id == target_chapter_id), None)
                    if outline_chapter:
                        global_facts = extract_global_quantitative_anchor(report)
                        global_facts_prompt = format_global_facts_prompt(global_facts)
                        retriever = DynamicEvidenceRetriever(request)
                        context = retriever.retrieve(outline_chapter.chapter_id, outline_chapter)
                        context["global_facts"] = global_facts
                        context["global_facts_prompt"] = global_facts_prompt
                        planned_skills = await agent._plan_chapter_skills(outline_chapter, context, request)
                        context["skills"] = [{"name": s.name, "instructions": s.instructions} for s, _, _ in planned_skills]

                        chapter_draft = None
                        if agent.llm.is_available:
                            try:
                                payload = {
                                    "outline": outline_chapter.model_dump(mode="json"),
                                    "subject": request.report.subject,
                                    "as_of": request.report.as_of.isoformat(),
                                    "audience": request.options.audience,
                                    "style": request.options.style,
                                    "target_length": request.options.target_length,
                                    "instruction": writing_options.instruction,
                                    "context": context,
                                    "global_facts": global_facts_prompt,
                                }
                                from chapter_writer.agent import SYSTEM_PROMPT
                                raw = await agent.llm.generate_json(SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False, default=str))
                                chapter_draft = ChapterDraft.model_validate(raw)
                            except Exception as e:
                                logger.warning(f"定向重写调用LLM失败，使用兜底: {e}")

                        if chapter_draft is None:
                            ready_charts = {c.chart_id: c for c in (chart_res.charts if chart_res else []) if c.status == "ready"}
                            chapter_draft = agent._fallback_chapter(request, outline_chapter, context, ready_charts, global_facts)

                        ch_json = json.loads(ch_path.read_text(encoding="utf-8"))
                        existing_chapters = ch_json.get("chapters", [])
                        new_chapters = []
                        for ch in existing_chapters:
                            if ch.get("chapter_id") == target_chapter_id:
                                new_chapters.append(chapter_draft.model_dump(mode="json"))
                            else:
                                new_chapters.append(ch)
                        ch_json["chapters"] = new_chapters
                        ch_path.write_text(json.dumps(ch_json, ensure_ascii=False, indent=2), encoding="utf-8")

                        cur_data = state.stage_results["chapter_write"].data or {}
                        cur_data["chapters"] = new_chapters
                        state.stage_results["chapter_write"].data = cur_data
                        state.revision += 1
                        state.stage_results["chapter_write"].revision = state.revision
                        state.status = "waiting_review"
                        state.stage_results["chapter_write"].status = "waiting_review"
                        if "report_fusion" in state.stage_results and state.stage_results["report_fusion"].status in ("approved", "completed"):
                            state.stage_results["report_fusion"].status = "pending"
                        state.updated_at = datetime.now().isoformat()
                        storage.save_state(state)
                        event_hub.emit(
                            req.run_id, "chapter_write", "artifact_created",
                            f"用户触发单章定向重写完成（章节 {target_chapter_id}），其余 6 章节保持稳定不变 (r{state.revision})",
                            tool="SingleChapterRewriter"
                        )
                        return state

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
            running_task = self._running_tasks.pop(req.run_id, None)
            if running_task and not running_task.done():
                logger.info(f"[{req.run_id}] 收到人工审核取消指令，正在中断后台异步任务")
                running_task.cancel()
            state.status = "cancelled"
            state.stage_results[req.stage].status = "cancelled"
            state.updated_at = datetime.now().isoformat()
            storage.save_state(state)

        latest = storage.load_state(req.run_id)
        return latest or state

    async def cancel_run(self, run_id: str) -> WorkflowState:
        """中途强行中断并取消正在执行或等待中的任务"""
        state = storage.load_state(run_id)
        if not state:
            raise ValueError(f"任务不存在: {run_id}")

        logger.info(f"[{run_id}] 收到中途强行取消请求 (当前状态: {state.status}, 阶段: {state.current_stage})")

        # 1. 尝试强行中断后台运行的异步协程 Task
        running_task = self._running_tasks.pop(run_id, None)
        if running_task and not running_task.done():
            logger.info(f"[{run_id}] 正在主动调用 task.cancel() 中断后台执行...")
            running_task.cancel()

        # 2. 将全局状态与当前阶段状态即时置为 cancelled
        state.status = "cancelled"
        if state.current_stage and state.current_stage in state.stage_results:
            state.stage_results[state.current_stage].status = "cancelled"
        state.updated_at = datetime.now().isoformat()
        storage.save_state(state)
        logger.info(f"[{run_id}] 任务已被成功标记为已取消 (cancelled)")
        return state

    async def resume_run(self, run_id: str, from_stage: StageName | None = None) -> WorkflowState:
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

        # 获取行业主题与参数
        industry = "低空经济"
        focus_points = []
        market_scope = ["中国 A 股", "港股", "美股", "中国 B 股"]
        security_types = ["股票", "债券", "基金", "期货", "指数"]
        reporting_currency = "CNY"
        research_as_of = None
        analysis_depth = "standard"
        chart_options = None

        run_dir = storage.get_run_dir(run_id)
        input_file = run_dir / "input_data.json"
        if input_file.exists():
            try:
                req_data = RunCreateRequest.model_validate_json(input_file.read_text(encoding="utf-8"))
                industry = req_data.input_data.industry_topic or industry
                focus_points = req_data.input_data.focus_questions or []
                if req_data.input_data.market_scope:
                    market_scope = req_data.input_data.market_scope
                if req_data.input_data.security_types:
                    security_types = req_data.input_data.security_types
                if req_data.input_data.reporting_currency:
                    reporting_currency = req_data.input_data.reporting_currency
                if req_data.input_data.research_as_of:
                    research_as_of = req_data.input_data.research_as_of
                if req_data.input_data.analysis_depth:
                    analysis_depth = req_data.input_data.analysis_depth
                chart_options = req_data.input_data.chart_generate_options
            except Exception:
                pass

        state.current_stage = stage
        state.status = "running"
        state.stage_results[stage].status = "running"
        state.updated_at = datetime.now().isoformat()
        storage.save_state(state)

        try:
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
                )
            elif stage == "data_interpret":
                result = await FiveAgentsAdapter.run_data_interpreter(
                    run_id=run_id,
                    industry=industry,
                    feedback=feedback,
                    market_scope=market_scope,
                    security_types=security_types,
                    reporting_currency=reporting_currency,
                    research_as_of=research_as_of,
                    analysis_depth=analysis_depth,
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

            # 检查任务是否在中途已被外部取消
            fresh_state = storage.load_state(run_id)
            if fresh_state and fresh_state.status == "cancelled":
                logger.info(f"[{run_id}] 检测到任务已被中途取消，终止写入阶段结果与后续流转")
                return

            # 保持 revision 同步
            result.revision = state.revision
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
                next_stage = self.get_next_stage(stage)
                if next_stage:
                    logger.info(f"[{run_id}] 阶段 {stage} 自动通过，流转至下一阶段: {next_stage}")
                    state.current_stage = next_stage
                    state.status = "running"
                    state.stage_results[next_stage].status = "running"
                    state.updated_at = datetime.now().isoformat()
                    storage.save_state(state)
                    # 递归调用下一阶段
                    await self._execute_stage(run_id, next_stage, review_stages, feedback=None)
                else:
                    # 全流程结束
                    state.status = "completed"
                    state.updated_at = datetime.now().isoformat()
                    storage.save_state(state)
                    logger.info(f"[{run_id}] 全流水线执行圆满完成！(completed)")

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
            logger.exception(f"[{run_id}] 阶段 {stage} 执行出错: {e}")
            state.status = "failed"
            state.stage_results[stage].status = "failed"
            state.stage_results[stage].error = str(e)
            state.updated_at = datetime.now().isoformat()
            storage.save_state(state)
        finally:
            if run_id in self._running_tasks and self._running_tasks[run_id].done():
                self._running_tasks.pop(run_id, None)


engine = WorkflowEngine()
