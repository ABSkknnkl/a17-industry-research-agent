import json

import pytest

from app.integrations.llm.mock import MockChapterWritingModel


@pytest.mark.asyncio
async def test_mock_chapter_model_preserves_allowed_evidence_and_outline() -> None:
    runtime_prompt = json.dumps(
        {
            "chapter_config": {
                "chapter_id": "CH-04",
                "title": "竞争格局",
                "sections": [
                    {
                        "section_id": f"SEC-04-{index:02d}",
                        "title": f"竞争小节{index}",
                        "purpose": "说明竞争研究边界。",
                    }
                    for index in range(1, 4)
                ],
            },
            "allowed_claims": [
                {
                    "claim_id": "C-001",
                    "text": "样本企业数量为10家。",
                    "evidence_ids": ["E-001"],
                    "uncertainty": "样本待扩充。",
                }
            ],
            "available_charts": [],
            "writing_options": {"instruction": None},
            "audit_feedback": [],
            "revision": 1,
        },
        ensure_ascii=False,
    )

    chapter = await MockChapterWritingModel().generate_chapter(
        system_prompt="ignored in deterministic tests",
        runtime_prompt=runtime_prompt,
    )

    assert chapter.chapter_id == "CH-04"
    assert [section.section_id for section in chapter.sections] == [
        "SEC-04-01",
        "SEC-04-02",
        "SEC-04-03",
    ]
    assert chapter.claim_ids == ["C-001"]
    assert chapter.evidence_ids == ["E-001"]
    assert all(section.paragraphs[0].claim_ids == ["C-001"] for section in chapter.sections)
