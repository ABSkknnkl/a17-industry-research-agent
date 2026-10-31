"""R4 红测：事实护栏与最终交付一致性。

对应 V8 最终方案 §7.4。离线：假 LLM + 临时目录。
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

import pytest

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


def _report() -> InterpretationReport:
    return InterpretationReport.model_validate(
        {
            "report_id": "R-R4",
            "subject": "测试行业",
            "as_of": "2026-09-01",
            "status": "completed",
            "insights": [],
            "evidence_index": {
                "R1": {
                    "record_id": "R1", "domain": "industry", "entity": "测试行业",
                    "metric": "市场规模", "value": 100, "unit": "亿元", "period": "2026-06-30",
                }
            },
        }
    )


class _ScriptedLLM:
    is_available = True

    def __init__(self, text, kind="thesis", assumption_note=None, metric_card=None, with_evidence=False):
        self.text = text
        self.kind = kind
        self.assumption_note = assumption_note
        self.metric_card = metric_card
        self.with_evidence = with_evidence

    async def generate_json(self, _system, user):
        payload = json.loads(user) if isinstance(user, str) else user
        outline = payload["outline"]
        cid = outline["chapter_id"]
        sections = []
        for idx, sec in enumerate(outline["sections"]):
            hit = cid == "CH-01" and sec["section_id"] == "SEC-01-01"
            filler = "本节按既有证据梳理行业现状与结构。" + "补充说明" * (idx + 1)
            para = {
                "paragraph_id": f"P-{cid[-2:]}-{sec['section_id'][-2:]}-01",
                "kind": self.kind if hit else "analysis",
                "text": self.text if hit else filler,
                "evidence_ids": ["R1"] if (hit and self.with_evidence) else [],
            }
            if hit and self.assumption_note:
                para["assumption_note"] = self.assumption_note
            sections.append(
                {
                    "section_id": sec["section_id"],
                    "title": sec["title"],
                    "purpose": sec.get("purpose", "目的"),
                    "key_points": ["要点"],
                    "paragraphs": [para],
                    "chart_ids": [],
                    "uncertainties": [],
                    "metric_cards": [self.metric_card] if (hit and self.metric_card) else [],
                    "comparison_table": None,
                    "callouts": [],
                    "layout_hint": "text_only",
                }
            )
        return {"chapter_id": cid, "title": outline["title"], "summary": "本章摘要。", "sections": sections}


def _run(text, kind="thesis", assumption_note=None, metric_card=None, with_evidence=False):
    agent = ChapterWriterAgent(
        llm=_ScriptedLLM(text, kind, assumption_note, metric_card, with_evidence)
    )
    return asyncio.run(
        agent.run(ChapterWritingRequest(report=_report(), outline=OUTLINE), save_artifacts=False)
    )


def _diagnostics(result) -> str:
    """审计明细可能落在 quality.issues 或 warnings（兜底后汇总）。"""
    return " ".join([*result.quality.issues, *(result.warnings or [])])


def test_model_provided_assumption_note_does_not_whitelist_facts():
    """模型自填任意 assumption_note 不得让无证据事实数字通过（R4 核心）。"""
    result = _run(
        "2025 年公司营业收入同比增长 20%，毛利率提升至 45%。",
        assumption_note="以上数据基于行业公开资料综合测算",  # 模型自填的通用说明
    )
    assert result.quality.passed is False, result.quality.issues
    assert result.quality.fallback_chapter_ids == ["CH-01"], result.quality.issues
    assert "数字缺少证据" in _diagnostics(result), _diagnostics(result)


def test_metric_card_without_evidence_is_flagged():
    """指标卡承载数值却无证据绑定：必须被审计拦下。"""
    result = _run(
        "本节引用指标卡数据。",
        metric_card={"label": "营业收入", "value": "1200", "unit": "亿元", "period": "2025", "evidence_ids": []},
    )
    assert result.quality.passed is False, result.quality.issues
    assert "指标卡" in _diagnostics(result), _diagnostics(result)


def test_metric_card_with_evidence_passes():
    """指标卡带合法证据：不误杀。"""
    result = _run(
        "本节引用指标卡数据。",
        metric_card={"label": "市场规模", "value": "100", "unit": "亿元", "period": "2026-06-30", "evidence_ids": ["R1"]},
    )
    assert result.quality.passed is True, result.quality.issues


def test_scenario_kind_still_legal():
    """明确情景（kind=scenario）仍走窄通道，不被误拦。"""
    result = _run("情景假设：若产能利用率提升至 85%，则收入增长 20%。", kind="scenario")
    assert result.quality.passed is True, result.quality.issues


@pytest.mark.parametrize("kind", ["scenario", "risk", "methodology", "transition"])
def test_kind_label_does_not_whitelist_historical_facts(kind):
    result = _run("2025 年公司营业收入同比增长 20%，毛利率提升至 45%。", kind=kind)
    assert result.quality.passed is False
    assert "数字缺少证据" in _diagnostics(result)
