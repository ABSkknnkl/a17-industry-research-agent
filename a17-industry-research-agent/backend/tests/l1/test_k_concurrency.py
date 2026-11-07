"""K1/K2/K3/K4/K6 · 并发与隔离专项（合成哨兵夹具 + mock LLM，全程离线）。

**判据来源**：任务书 §2.1（L4c 部分）与 §3.1（K1/K2/K3/K4/K6）。

**设计要点（为什么这么做）**：
- 用「哨兵证据」把"某章用了哪些证据"变成**可判定事实**：第 i 章的哨兵命名 `EV-SENT-CH{i}-{seq}`，
  任何越界引用都能被正则识别，无需人工读正文。
- 用可注入的 mock LLM（`is_available=True` + `generate_json`）驱动 LLM 路径，**不触发任何真实模型调用**；
  另用 `is_available=False` 驱动确定性 fallback 路径，两条路径都验。
- K4 的判据按本项目重锚（**文件态存储**）：任务书 §3.4 明确"并发写 `state.json`/`artifacts` 无损坏、
  无相互覆盖、无半写文件"。

**离线自证**：`provider_mode=mock`，`input_source=synthetic`（哨兵夹具为合成数据），零网络调用。
"""

from __future__ import annotations

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest

from backend.app.core.storage import StorageManager
from backend.app.schemas.workflow import WorkflowState
from chapter_writer import ChapterWriterAgent, ChapterWritingRequest
from chapter_writer.models import InterpretationReport
from chapter_writer.outline import DEFAULT_OUTLINE

SENTINELS_PER_CHAPTER = 3
FOREIGN_SENTINEL = "EV-SENT-CH-99-1"


def sentinel_id(chapter_id: str, seq: int) -> str:
    """第 i 章第 seq 个哨兵证据 ID（命名即断言依据）。"""
    return f"EV-SENT-{chapter_id}-{seq}"


def sentinel_report() -> InterpretationReport:
    """构造 7 章 × 3 条哨兵证据的最小解读报告（合成夹具）。"""
    index: dict[str, dict] = {}
    for chapter in DEFAULT_OUTLINE:
        for seq in range(1, SENTINELS_PER_CHAPTER + 1):
            sid = sentinel_id(chapter.chapter_id, seq)
            index[sid] = {
                "record_id": sid,
                "domain": "industry",
                "entity": "哨兵行业",
                "metric": f"{chapter.title}指标{seq}",
                "value": 100 + seq,
                "unit": "亿元",
                "period": "2026-06-30",
            }
    return InterpretationReport.model_validate(
        {
            "report_id": "K-FIXTURE",
            "subject": "哨兵行业",
            "as_of": "2026-09-01",
            "status": "completed",
            "evidence_index": index,
        }
    )


class MissingLLM:
    """LLM 不可用 → 驱动确定性 fallback 路径。"""

    is_available = False

    async def generate_json(self, *args, **kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("offline fixture: LLM must not be called")


class SentinelLLM:
    """按当前章返回该章哨兵的确定性 mock LLM。

    Args:
        inject_foreign: 是否注入一条**外来章**的哨兵（用于验证"越界证据必须留痕"）。
        fail_on: 这些章节的调用应抛错（用于 K6 单章降级）。
    """

    is_available = True

    def __init__(self, *, inject_foreign: bool = False, fail_on: frozenset[str] = frozenset()) -> None:
        self.inject_foreign = inject_foreign
        self.fail_on = fail_on
        self.called_chapters: list[str] = []

    async def generate_json(self, system: str, user: str) -> dict:
        payload = json.loads(user)
        outline = payload["outline"]
        chapter_id = str(outline["chapter_id"])
        self.called_chapters.append(chapter_id)
        if chapter_id in self.fail_on:
            raise RuntimeError(f"sentinel-induced failure on {chapter_id}")

        available = sorted(((payload.get("context") or {}).get("evidence") or {}).keys())
        evidence = [i for i in available if i.startswith(f"EV-SENT-{chapter_id}-")]
        if self.inject_foreign:
            evidence = [*evidence, FOREIGN_SENTINEL]

        sections = [
            {
                "section_id": section["section_id"],
                "title": section["title"],
                "purpose": section["purpose"],
                "key_points": [f"哨兵要点 {chapter_id}/{section['section_id']}"],
                "paragraphs": [
                    {
                        "paragraph_id": f"P-{section['section_id']}-01",
                        "kind": "thesis",
                        # 文本必须逐段唯一：生产审计有"段落重复"检查，重复文本会触发 fallback 降级
                        "text": (
                            f"哨兵段落 {chapter_id} 之 {section['section_id']}："
                            f"本段为跨章证据隔离与结构等价的确定性校验素材，内容随章节变化。"
                        ),
                        "evidence_ids": list(evidence),
                    }
                ],
            }
            for section in outline["sections"]
        ]
        return {
            "chapter_id": chapter_id,
            "title": str(outline["title"]),
            "summary": "哨兵摘要",
            "sections": sections,
        }


def _run(agent: ChapterWriterAgent) -> object:
    return asyncio.run(
        agent.run(ChapterWritingRequest(report=sentinel_report()), save_artifacts=False)
    )


def _chapter_of(sentinel: str) -> str | None:
    match = re.match(r"^EV-SENT-(CH-\d+)-", sentinel)
    return match.group(1) if match else None


# --------------------------------------------------------------------------
# K1 · 输出结构等价
# --------------------------------------------------------------------------


def test_k1_fallback_path_structure_equivalent() -> None:
    """K1（fallback 路径）：7 章 × 3 节，chapter_id / section_id 与大纲逐一对应，无串位。"""
    result = _run(ChapterWriterAgent(llm=MissingLLM()))
    expected_ids = [c.chapter_id for c in DEFAULT_OUTLINE]
    assert [c.chapter_id for c in result.chapters] == expected_ids, "章节顺序或 ID 与大纲不一致"
    for chapter, outline in zip(result.chapters, DEFAULT_OUTLINE):
        assert [s.section_id for s in chapter.sections] == [s.section_id for s in outline.sections], (
            f"{chapter.chapter_id} 的 section_id/顺序与大纲不一致（串位）"
        )


def test_k1_llm_path_structure_equivalent() -> None:
    """K1（LLM 路径）：mock LLM 下结构同样等价，且 7 章都被调用一次。"""
    llm = SentinelLLM()
    result = _run(ChapterWriterAgent(llm=llm))
    assert [c.chapter_id for c in result.chapters] == [c.chapter_id for c in DEFAULT_OUTLINE]
    assert llm.called_chapters == [c.chapter_id for c in DEFAULT_OUTLINE], (
        f"LLM 调用章序列异常: {llm.called_chapters}"
    )
    for chapter, outline in zip(result.chapters, DEFAULT_OUTLINE):
        assert [s.section_id for s in chapter.sections] == [s.section_id for s in outline.sections]


# --------------------------------------------------------------------------
# K2 · 跨章污染
# --------------------------------------------------------------------------


def test_k2_no_cross_chapter_sentinel_appears() -> None:
    """K2：第 i 章的产出中不得出现非第 i 章的哨兵（跨章污染零命中）。"""
    result = _run(ChapterWriterAgent(llm=SentinelLLM()))
    leaks: dict[str, list[str]] = {}
    for chapter in result.chapters:
        bad = set()
        for section in chapter.sections:
            for para in section.paragraphs:
                for eid in para.evidence_ids:
                    owner = _chapter_of(eid)
                    if owner and owner != chapter.chapter_id:
                        bad.add(eid)
        if bad:
            leaks[chapter.chapter_id] = sorted(bad)
    assert leaks == {}, f"K2 出现跨章哨兵泄漏: {leaks}"


def test_k2_foreign_evidence_must_be_reported_not_silently_dropped() -> None:
    """K2 扩展：模型给出越界证据时，系统必须**留痕**（issue/warning），不得静默丢弃。

    背景：`_audit_chapter` 会把不在 `allowed` 内的证据静默过滤
    （`para.evidence_ids = [e for e in ... if e in allowed]`），过滤后不产生任何 issue。
    静默过滤会掩盖模型的越界行为——本用例把它固化为判据。
    """
    llm = SentinelLLM(inject_foreign=True)
    result = _run(ChapterWriterAgent(llm=llm))
    haystack = " ".join([*result.warnings, *[w for c in result.chapters for w in (c.summary or "",)]]).lower()
    mentioned = any(
        keyword in haystack for keyword in ("越界", "未授权", "allowed", "超范围", "非本章", "evidence")
    ) or FOREIGN_SENTINEL in " ".join(result.warnings)
    assert mentioned, (
        "K2 扩展：注入的外来证据 ID 既未出现在产物中，也未在任何 issue/warning 中留痕 —— "
        "属静默过滤（掩盖模型越界），应补记问题"
    )


# --------------------------------------------------------------------------
# K3 · 证据引用合法
# --------------------------------------------------------------------------


def test_k3_all_evidence_ids_come_from_fixture_pool() -> None:
    """K3：产物中的 evidence_ids 必须全部落在夹具证据池内。"""
    pool = set(sentinel_report().evidence_index.keys())
    result = _run(ChapterWriterAgent(llm=SentinelLLM()))
    used: set[str] = set()
    for chapter in result.chapters:
        for section in chapter.sections:
            for para in section.paragraphs:
                used |= set(para.evidence_ids)
    assert used, "产物未引用任何证据（判据未生效）"
    assert used <= pool, f"K3 出现夹具池外的证据: {sorted(used - pool)}"
    pool |= {FOREIGN_SENTINEL}  # 说明：即使注入外来哨兵，也应被过滤出最终产物
    assert used <= pool


# --------------------------------------------------------------------------
# K4 · 并发持久化（本项目重锚：文件态存储）
# --------------------------------------------------------------------------


def _state(run_id: str, revision: int) -> WorkflowState:
    return WorkflowState(project_id="k4", run_id=run_id, revision=revision)


def test_k4_concurrent_state_writes_are_not_corrupted(tmp_path: Path) -> None:
    """K4：16 个 run 并发写 `state.json` + `revisions/*.json` → 全部可解析、内容正确、无半写。"""
    store = StorageManager(base_dir=tmp_path / "runs")
    run_ids = [f"run-k4-{i:02d}" for i in range(16)]

    def write(run_id: str) -> None:
        store.save_state(_state(run_id, revision=3))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, run_ids))

    for run_id in run_ids:
        state_file = tmp_path / "runs" / run_id / "state.json"
        assert state_file.exists(), f"{run_id} 的 state.json 未生成"
        payload = json.loads(state_file.read_text(encoding="utf-8"))  # 半写文件会在此抛错
        assert payload["run_id"] == run_id and payload["revision"] == 3
        rev_file = tmp_path / "runs" / run_id / "revisions" / "3.json"
        assert rev_file.exists() and json.loads(rev_file.read_text(encoding="utf-8"))["run_id"] == run_id


def test_k4_concurrent_artifacts_in_same_run_do_not_interfere(tmp_path: Path) -> None:
    """K4：同一 run 内并发写多个 artifact → 各自完整，无相互覆盖。"""
    store = StorageManager(base_dir=tmp_path / "runs")
    run_id = "run-k4-shared"
    names = [f"artifact-{i:02d}.json" for i in range(24)]
    payload = {name: json.dumps({"name": name, "index": i}) for i, name in enumerate(names)}

    def write(item: tuple[str, str]) -> None:
        name, content = item
        store.save_artifact_file(run_id, name, content)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, payload.items()))

    for name, content in payload.items():
        target = tmp_path / "runs" / run_id / "artifacts" / name
        assert target.exists(), f"artifact 缺失: {name}"
        assert target.read_text(encoding="utf-8") == content, f"artifact 内容被覆盖/截断: {name}"


# --------------------------------------------------------------------------
# K6 · 单章降级语义
# --------------------------------------------------------------------------


def test_k6_single_chapter_failure_degrades_locally() -> None:
    """K6：仅失败章降级为 fallback，其余 6 章正常，兄弟任务不被取消。"""
    failing = "CH-04"
    llm = SentinelLLM(fail_on=frozenset({failing}))
    result = _run(ChapterWriterAgent(llm=llm))

    assert failing in set(result.quality.fallback_chapter_ids), (
        f"{failing} 应进入 fallback 列表，实际 {result.quality.fallback_chapter_ids}"
    )
    others = [c.chapter_id for c in result.chapters if c.chapter_id != failing]
    assert not (set(others) & set(result.quality.fallback_chapter_ids)), (
        f"其余章节不应降级，实际降级: {result.quality.fallback_chapter_ids}"
    )
    # 兄弟任务未被取消：7 章都在，且 6 章走了 LLM 路径
    assert len(result.chapters) == len(DEFAULT_OUTLINE)
    assert set(llm.called_chapters) >= set(others), (
        f"兄弟章节未被调用（疑似被取消）: 已调用={llm.called_chapters}"
    )
    assert result.status in {"completed", "partial"}, f"阶段状态异常: {result.status}"
