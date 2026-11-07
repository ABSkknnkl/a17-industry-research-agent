"""产业链 AI 生图开关的回归测试。

背景
----
产业链结构本来就有**两条**产出路径：

1. 本地确定性 ECharts 渲染的「产业链结构」图（上中下游三栏 + 代表企业 + 证据注）——
   零外部依赖、节点可被 report_fusion 逐点校验；
2. ``image_gen.generate_industry_chain_image`` 调的 **AI 生图**——额外请求外部模型，
   单次可达数分钟，曾造成阶段三长时间无响应，且位图无法逐点校验。

2026-10-05 起第 2 条改为**默认关闭**，由 ``Settings.enable_industry_chain_image``
（环境变量 ``ENABLE_INDUSTRY_CHAIN_IMAGE``）显式控制，默认只保留第 1 条。

本文件锁住三件事：
- 开关的解析语义（``"0"`` / ``"false"`` 必须判为 False）；
- 默认值必须是 False；
- agent 在关闭时**不得**产出 ``generated_image``，且必须留痕说明跳过原因。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from chart_generator.agent import ChartGeneratorAgent
from chart_generator.config import Settings, _env_flag
from chart_generator.models import ChartGenerationRequest, InterpretationReport


# --------------------------------------------------------------------------- #
# 1. 开关解析语义
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("yes", True),
        ("on", True),
        (" 1 ", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("off", False),
        ("", False),
        (None, False),
    ],
)
def test_env_flag_parsing(monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: bool) -> None:
    """``_env_flag`` 必须把 ``"0"`` / ``"false"`` 判为 False。

    直接用 ``bool(os.getenv(...))`` 会把字符串 ``"0"`` 也判成 True —— 这是开关类配置
    最常见的坑，所以这里逐个钉住。
    """
    if raw is None:
        monkeypatch.delenv("TEST_SWITCH_FLAG", raising=False)
    else:
        monkeypatch.setenv("TEST_SWITCH_FLAG", raw)
    assert _env_flag("TEST_SWITCH_FLAG") is expected


def test_settings_default_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """不设环境变量时，``Settings()`` 与 ``Settings.from_env()`` 都必须是关闭。"""
    monkeypatch.delenv("ENABLE_INDUSTRY_CHAIN_IMAGE", raising=False)
    assert Settings().enable_industry_chain_image is False
    assert Settings.from_env().enable_industry_chain_image is False


def test_settings_from_env_can_enable(monkeypatch: pytest.MonkeyPatch) -> None:
    """置 ``ENABLE_INDUSTRY_CHAIN_IMAGE=1`` 时可以被显式打开（保留回退能力）。"""
    monkeypatch.setenv("ENABLE_INDUSTRY_CHAIN_IMAGE", "1")
    assert Settings.from_env().enable_industry_chain_image is True


# --------------------------------------------------------------------------- #
# 2. agent 行为
# --------------------------------------------------------------------------- #


def _report_with_chain_segments() -> InterpretationReport:
    """构造带 ``industry_chain_segments`` 的解读报告 —— 这是触发 AI 生图的唯一前置条件。"""
    evidence: dict[str, dict[str, object]] = {}
    for idx, (entity, value) in enumerate((("甲", 10), ("乙", -3), ("丙", 8)), start=1):
        evidence[f"R{idx}"] = {
            "record_id": f"R{idx}",
            "domain": "financials",
            "entity": entity,
            "metric": "利润增长率",
            "value": value,
            "unit": "%",
            "period": "2026-06-30",
        }
    for idx, value in enumerate((10, 13, 16), start=4):
        evidence[f"R{idx}"] = {
            "record_id": f"R{idx}",
            "domain": "industry",
            "entity": "行业",
            "metric": "市场规模",
            "value": value,
            "unit": "亿元",
            "period": f"202{idx - 3}-12-31",
        }
    return InterpretationReport.model_validate(
        {
            "report_id": "CHAIN-SWITCH",
            "subject": "测试行业",
            "as_of": "2026-09-01",
            "status": "completed",
            "evidence_index": evidence,
            "industry_chain_segments": [
                {"stage": "upstream", "label": "上游材料", "companies": ["甲公司"], "evidence_ids": ["R1"]},
                {"stage": "midstream", "label": "中游制造", "companies": ["乙公司"], "evidence_ids": ["R2"]},
                {"stage": "downstream", "label": "下游应用", "companies": ["丙公司"], "evidence_ids": ["R3"]},
            ],
        }
    )


def _run(tmp_path: Path, *, enable: bool) -> tuple[object, list[dict[str, object]]]:
    """跑一次 chart agent，返回 ``(result, events)``。

    Args:
        tmp_path: pytest 给的临时目录，作为 agent 的 output_dir。
        enable: 是否打开产业链 AI 生图开关。

    Returns:
        ``(ChartGenerationResult, events.jsonl 解析后的列表)``。
    """
    agent = ChartGeneratorAgent()
    agent.settings = type(agent.settings)(  # 复用原 Settings 类型，只覆盖需要的两个字段
        output_dir=tmp_path,
        enable_industry_chain_image=enable,
    )
    result = asyncio.run(agent.run(ChartGenerationRequest(report=_report_with_chain_segments())))
    events_path = tmp_path / "runs" / result.run_id / "events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return result, events


def test_ai_image_disabled_by_default(tmp_path: Path) -> None:
    """默认关闭：不得产出 ``generated_image``，且必须留痕说明跳过原因。"""
    result, events = _run(tmp_path, enable=False)

    generated = [c for c in result.charts if c.render_mode == "generated_image"]
    assert generated == [], f"默认关闭状态下不应出现 AI 生图产物，实际有 {len(generated)} 张"

    assert not [e for e in events if e.get("event") == "image_generation_start"], \
        "关闭时不应触发 image_generation_start"

    skipped = [e for e in events if e.get("event") == "image_generation_skipped"]
    assert skipped, "关闭时必须记 image_generation_skipped，否则「为什么没有产业链图」会变成排查黑洞"


def test_ai_image_path_opens_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """显式打开开关后必须进入 AI 生图分支（用 stub 拦掉真实网络调用）。"""
    calls: list[dict[str, object]] = []

    async def _stub(**kwargs: object) -> None:
        """替身：记录调用并返回 None，模拟「未配置 / 失败」但不产生任何网络请求。"""
        calls.append(kwargs)
        return None

    monkeypatch.setattr("chart_generator.agent.generate_industry_chain_image", _stub)

    _, events = _run(tmp_path, enable=True)

    assert len(calls) == 1, "开关打开后应恰好调用一次生图入口"
    assert [e for e in events if e.get("event") == "image_generation_start"], \
        "打开开关后应记 image_generation_start"
    assert not [e for e in events if e.get("event") == "image_generation_skipped"] or all(
        e.get("details", {}).get("chart_id") for e in events if e.get("event") == "image_generation_skipped"
    ), "开关打开后的 skipped 必须来自生图分支（带 chart_id），而不是开关关闭那条"
