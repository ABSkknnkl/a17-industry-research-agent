"""报告质量评分器 · 真实 LLM 辅助测试（方案 §2 Q6 / §4 golden 校准小样本冒烟）。

约定：
- 生产 100 分仍是确定性代码的唯一权威，LLM **不写入** production quality 分数。
- 本文件用真实 LLM（backend/.env 的 Ark 端点）做两件事：
  1) 可读性软评契约：ReadabilityReport score∈[0,1]（对应生产 L2 表达维输入）；
  2) golden 冒烟：对 5 条合成报告质量摘要盲评 0-100，与 high/mid/low 档位做
     Spearman 秩相关（样本少，仅方向性校准，不作为正式 30 条门禁）。

显式跑法：
  backend/.venv/bin/python -m pytest eval/tests/test_report_quality_llm.py -v
"""

from __future__ import annotations

import asyncio
import json
import math
import statistics
from pathlib import Path
from typing import Any, Literal

import pytest
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.integrations.llm.factory import create_readability_model


def _live_settings() -> Settings:
    env_file = Path(__file__).resolve().parents[2] / "backend" / ".env"
    return Settings(
        _env_file=str(env_file),
        ENVIRONMENT="development",
        LLM_USE_MOCK=False,
        SKILLHUB_USE_MOCK=True,
    )


def _live_llm_available() -> bool:
    try:
        env = _live_settings()
    except Exception:
        return False
    return bool(env.LLM_API_KEY) and bool(env.LLM_BASE_URL) and env.LLM_USE_MOCK is False


pytestmark = pytest.mark.skipif(
    not _live_llm_available(),
    reason="真实 LLM 未配置（需 backend/.env: LLM_API_KEY + LLM_BASE_URL + LLM_USE_MOCK=false）",
)


class QualityBlindScore(BaseModel):
    """LLM 盲评报告质量的结构化输出（评测层参考分，不进生产）。"""

    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0, le=100, description="报告综合质量 0-100")
    band: Literal["high", "mid", "low"]
    reason: str = Field(default="", description="一句话依据")


def _synthetic_reports() -> list[dict[str, Any]]:
    return [
        {
            "id": "S-HIGH",
            "brief": "完整7章21节；证据全覆盖；引用干净；维度全supported；风险全披露；图表5张均被引用。",
            "expect_band": "high",
        },
        {
            "id": "S-MID",
            "brief": "7章21节；证据覆盖80%；1类未知引用；维度覆盖partial；风险披露一半；图表2张。",
            "expect_band": "mid",
        },
        {
            "id": "S-LOW",
            "brief": "仅3章9节；证据used为空；3类未知引用；dimension_coverage缺失；风险未披露；无图表。",
            "expect_band": "low",
        },
        {
            "id": "S-LOW2",
            "brief": "7章21节但全部结论被驳回；无可用证据；维度insufficient；图表引用未就绪ID；风险未披露。",
            "expect_band": "low",
        },
        {
            "id": "S-MID2",
            "brief": "结构完整；证据覆盖50%；图表与规格不一致；维度2 supported 3 partial；风险全披露。",
            "expect_band": "mid",
        },
    ]


_BAND_ORDER = {"low": 0, "mid": 1, "high": 2}


def _spearman(xs: list[float], ys: list[float]) -> float:
    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        for rank, idx in enumerate(order, start=1):
            r[idx] = float(rank)
        return r

    rx, ry = ranks(xs), ranks(ys)
    mean_x = statistics.mean(rx)
    mean_y = statistics.mean(ry)
    num = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry))
    den = math.sqrt(
        sum((a - mean_x) ** 2 for a in rx) * sum((b - mean_y) ** 2 for b in ry)
    )
    return num / den if den else 0.0


@pytest.mark.asyncio
async def test_real_llm_readability_contract() -> None:
    """真实 LLM 对糟糕中文分析段落返回契约对象（score∈[0,1]）。"""
    live = _live_settings()
    model = create_readability_model(live)
    report = await model.review_paragraph(
        paragraph_text=(
            "由于原材料价格波动使其行业景气度与利润池的护城河与议价权在正极电解液"
            "界面阻抗层面持续承压，本报告深入剖析并系统重构了产业链价值分配。"
        ),
        kind="analysis",
    )
    assert 0.0 <= report.score <= 1.0
    assert hasattr(report, "findings")
    for finding in report.findings:
        assert finding.dimension in {"通顺度", "通俗度", "连贯性", "客观性"}
    assert isinstance(report.needs_human_review, bool)
    # LLM 软分不得写入 production quality —— 生产 total 仍由 quality.py 确定性计算
    assert report.score <= 1.0


@pytest.mark.asyncio
async def test_real_llm_golden_band_alignment_smoke() -> None:
    """小样本 golden 冒烟：LLM 盲评 0-100 与质量档位秩相关（Spearman ≥ 0.6）。

    生产确定性分数不在此路径计算；此测试验证「LLM 参考评分能否分出质量档」，
    为后续正式 golden 校准（30-50 条 + 人工标签，κ≥0.6 / Spearman≥0.7）铺路。
    """
    live = _live_settings()
    chat = ChatOpenAI(
        model=live.LLM_MODEL,
        api_key=live.LLM_API_KEY.get_secret_value() if live.LLM_API_KEY else None,
        base_url=live.LLM_BASE_URL,
        temperature=0,
        timeout=60,
        max_retries=2,
        extra_body={"thinking": {"type": "disabled"}},
    )
    structured = chat.with_structured_output(QualityBlindScore, method="json_schema")
    samples = _synthetic_reports()
    system = (
        "你是行业研报质量盲评员。只依据给定的「质量摘要」判断报告整体质量，"
        "不引入外部事实。质量要点：结构完整、证据可追溯、引用一致、维度覆盖、"
        "图表可用、风险披露充分。返回 score(0-100)、band(high/mid/low)、reason。"
    )

    async def score_one(sample: dict[str, Any]) -> QualityBlindScore:
        msg = f"质量摘要：{sample['brief']}\n请盲评该报告质量。"
        return await asyncio.to_thread(
            lambda: structured.invoke(
                [
                    ("system", system),
                    ("human", msg),
                ]
            )
        )

    reports = [await score_one(s) for s in samples]
    llm_scores = [float(r.score) for r in reports]
    expect_ranks = [_BAND_ORDER[s["expect_band"]] for s in samples]
    rho = _spearman(llm_scores, [float(x) for x in expect_ranks])

    out_dir = (
        Path(__file__).resolve().parents[1]
        / "calibration"
        / "report_quality"
        / "reports"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "llm_smoke_latest.json"
    out_path.write_text(
        json.dumps(
            {
                "n": len(samples),
                "spearman": rho,
                "pairs": [
                    {
                        "id": samples[i]["id"],
                        "llm_score": llm_scores[i],
                        "llm_band": reports[i].band,
                        "expect_band": samples[i]["expect_band"],
                        "reason": reports[i].reason,
                    }
                    for i in range(len(samples))
                ],
                "note": "LLM 仅作参考分；生产 total_score 由确定性 quality.py 产出",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    assert rho >= 0.6, f"LLM 盲评与质量档位秩相关过低: rho={rho:.3f}, scores={llm_scores}"
    # 高/低档位至少应能被 LLM 分数拉开（方向性）
    low_scores = [
        llm_scores[i] for i, s in enumerate(samples) if s["expect_band"] == "low"
    ]
    high_scores = [
        llm_scores[i] for i, s in enumerate(samples) if s["expect_band"] == "high"
    ]
    assert high_scores and low_scores
    assert max(low_scores) <= min(high_scores) + 5, (
        f"高档未明显高于低档: high={high_scores}, low={low_scores}"
    )
