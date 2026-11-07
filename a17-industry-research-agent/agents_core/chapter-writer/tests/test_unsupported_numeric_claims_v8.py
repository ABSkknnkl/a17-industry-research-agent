"""S-01 红测（二）：A4 无依据事实数字不得被通用 assumption_note 洗白。

对应 V8 方案 §4.4 第 5、6、7 行。全部离线：假 LLM + 临时目录，无任何联网。
"""

from __future__ import annotations

import asyncio
import json

from chapter_writer import ChapterWriterAgent, ChapterWritingRequest
from chapter_writer.models import InterpretationReport, OutlineChapter, OutlineSection

OUTLINE = [
    OutlineChapter(
        chapter_id=f"CH-{i:02d}",
        title=f"第{i}章",
        sections=[
            OutlineSection(section_id=f"SEC-{i:02d}-0{j}", title=f"节{j}", purpose="目的")
            for j in range(1, 4)
        ],
    )
    for i in range(1, 8)
]

TARGET_CHAPTER = "CH-01"
TARGET_SECTION = "SEC-01-01"


def _report() -> InterpretationReport:
    return InterpretationReport.model_validate(
        {
            "report_id": "R-S01",
            "subject": "测试行业",
            "as_of": "2026-09-01",
            "status": "completed",
            "insights": [],
            "evidence_index": {
                "R1": {
                    "record_id": "R1",
                    "domain": "industry",
                    "entity": "测试行业",
                    "metric": "市场规模",
                    "value": 100,
                    "unit": "亿元",
                    "period": "2026-06-30",
                }
            },
        }
    )


class _ScriptedLLM:
    """按 outline 里的 chapter_id 逐章返回；只让目标段落承载被测文本。"""

    is_available = True

    def __init__(self, text: str, kind: str = "thesis", evidence_ids: list[str] | None = None) -> None:
        self.text = text
        self.kind = kind
        self.evidence_ids = evidence_ids or []

    async def generate_json(self, _system, user):
        payload = json.loads(user) if isinstance(user, str) else user
        outline = payload["outline"]
        cid = outline["chapter_id"]
        sections = []
        for idx, sec in enumerate(outline["sections"]):
            hit = cid == TARGET_CHAPTER and sec["section_id"] == TARGET_SECTION
            # 纯中文、无阿拉伯数字：避免填充文案自身触发“数字缺证据”检查
            filler = "本节按既有证据梳理行业现状与结构。" + "补充说明" * (idx + 1)
            sections.append(
                {
                    "section_id": sec["section_id"],
                    "title": sec["title"],
                    "purpose": sec.get("purpose", "目的"),
                    "key_points": ["要点"],
                    "paragraphs": [
                        {
                            "paragraph_id": f"P-{cid[-2:]}-{sec['section_id'][-2:]}-01",
                            "kind": self.kind if hit else "analysis",
                            "text": self.text if hit else filler,
                            "evidence_ids": list(self.evidence_ids) if hit else [],
                        }
                    ],
                    "chart_ids": [],
                    "uncertainties": [],
                    "metric_cards": [],
                    "comparison_table": None,
                    "callouts": [],
                    "layout_hint": "text_only",
                }
            )
        return {
            "chapter_id": cid,
            "title": outline["title"],
            "summary": "本章摘要。",
            "sections": sections,
        }


def _run(text: str, kind: str = "thesis", evidence_ids: list[str] | None = None):
    agent = ChapterWriterAgent(llm=_ScriptedLLM(text, kind, evidence_ids))
    return asyncio.run(
        agent.run(ChapterWritingRequest(report=_report(), outline=OUTLINE), save_artifacts=False)
    )


def _target_paragraph(result):
    return next(
        p
        for c in result.chapters
        for s in c.sections
        for p in s.paragraphs
        if p.paragraph_id.startswith("P-01-01")
    )


def test_unsupported_factual_number_is_not_whitelisted_by_assumption_note():
    """空证据段落写“2025年收入增长20%”：不得因自动补 assumption_note 而通过。"""
    result = _run("2025 年公司营业收入同比增长 20%，毛利率提升至 45%。")
    assert not any(p.paragraph_id.startswith("P-01-01")
                   for chapter in result.chapters for section in chapter.sections for p in section.paragraphs)
    isolated = [item for item in result.chapters[0].content_audit if item["disposition"] == "isolated"]
    assert any("20%" in item["original"] for item in isolated)
    assert result.quality.passed is False, result.quality.issues
    assert result.quality.fallback_chapter_ids == [], result.quality.issues
    assert any("段落资料缺口" in issue for issue in result.quality.issues)


def test_pure_year_and_ordinal_are_not_flagged():
    """纯年份/编号不是事实数字，不得误杀。"""
    result = _run("2025 年以来，行业进入第 3 轮产能周期，详见第 2 节。")
    target = _target_paragraph(result)
    assert target.assumption_note is None
    assert result.quality.passed is True, result.quality.issues


def test_supported_factual_number_still_passes():
    """有证据的数字保持合法。"""
    result = _run("行业市场规模达到 100 亿元。", evidence_ids=["R1"])
    target = _target_paragraph(result)
    assert target.evidence_ids == ["R1"]
    assert result.quality.passed is True, result.quality.issues


def test_explicit_scenario_paragraph_keeps_legal_behavior():
    """明确标注的情景假设（kind=scenario）不被当成事实数字拦下。"""
    result = _run("情景假设：设定产能利用率为85%，仅作为敏感性分析的输入参数。", kind="scenario")
    assert result.quality.passed is True, result.quality.issues


def test_quality_report_exposes_real_status_and_fallback():
    """A4 的 status / quality.passed / issues / fallback 必须真实可读。"""
    result = _run("2025 年营业收入同比增长 20%。")
    assert result.quality.passed is False
    assert isinstance(result.quality.issues, list) and result.quality.issues
    assert isinstance(result.quality.fallback_chapter_ids, list)
