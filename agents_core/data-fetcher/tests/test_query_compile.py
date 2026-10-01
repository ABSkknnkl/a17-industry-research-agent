"""A1 query 编译层（P0-2）与空数据集硬风控（P0-1）的回归夹具。

数据来源：docs/A1_query与失败上报_可落地修复方案.md §4.3（10 条真实坏样本 + 6 条正样本）。
验收口径（方案 §4.3 修正版）：编译后需满足 4 条必要条件 ——
  ① 不含标点；② 不含返回字段名；③ 不含说明性文字（_DESC_NOISE 与 等X 通用模式）；
  ④ 长度 ≤40 字符 **或** 词数 ≤7（中文按字符计，替代原"≤20 字"）。
"""
import asyncio
import re
from datetime import date
from pathlib import Path

import pytest

from data_fetcher.agent import (
    _compile_query,
    _DESC_NOISE,
    _FIELD_NAME_NOISE,
    _PUNCT_RE,
    _total_records,
)
from data_fetcher.config import Settings
from data_fetcher.models import (
    Domain,
    ResearchRequest,
    SkillTask,
    StructuredResearchDataset,
)
from data_fetcher.skillhub import SkillHub


_ETC_NOISE_RE = re.compile(r"等[\u4e00-\u9fa5]{0,4}(?=\s|$)")


def _compile_reasons(q: str) -> list[str]:
    """按验收口径返回未通过的判据原因（空列表 = 通过）。"""
    reasons: list[str] = []
    if _PUNCT_RE.search(q):
        reasons.append("含标点")
    if any(f in q for f in _FIELD_NAME_NOISE):
        reasons.append("含返回字段名")
    if any(d in q for d in _DESC_NOISE):
        reasons.append("含说明性文字")
    if _ETC_NOISE_RE.search(q):
        reasons.append("含等X残留")
    if len(q) > 40 and len(q.split()) > 7:
        reasons.append("过长且词数超标")
    return reasons


BAD_SAMPLES = [
    # §4.3 样本 1–10（A1 真实产出的坏 query）
    "海水淡化行业板块估值盈利财务行情等数据包括行业PE PB ROE 营收增速等指标近3年走势",
    "碧水源 300070.SZ 基本信息 证券代码 证券简称 总市值 营业收入 所属行业 所属概念",
    "碧水源 300070.SZ 近5年 2021-2025 营业收入 归母净利润 销售毛利率 销售净利率 ROE 资产负债率 经营活动产生的现金流量净额 研发费用",
    "海水淡化行业研究报告，重点关注2025年吨水成本、技术路线、政策补贴、行业空间等，时间范围2025年。",
    "近5年国内生产总值当季同比及工业增加值季度趋势，用于评估宏观水资源与基建投资环境。",
    "海水淡化行业最新动态，包括重大项目落地、政策发布、技术进步…等，近一年资讯。",
    "筛选A股再生水概念或主营业务涉及污水处理及再生水利用的上市公司按A股总市值从大到小排序取前30家企业",
    "查询再生水行业2025年利用率投资需求行业规模及增速等数据包括近5年行业产值污水处理及再生水利用行业",
    "伟明环保(603568.SH) 2021年至2025年营业收入归母净利润销售毛利率销售净利率 ROE",
    "查询碧水源（300070）的主营业务构成，包括再生水处理、污水处理、膜技术、环保工程等各业务板块的收入",
]

POSITIVE_SAMPLES = [
    # 正样本回归：不得误杀（误杀率 0）
    "海水淡化 行业 政策 项目 成本 2025年 最新动态",
    "碧水源 兴蓉环境 海水淡化 最新新闻 业绩 项目",
    "海水淡化",
    "火工品",
    "光伏逆变器2025年",
    "特种石墨 等静压 供需",
]


@pytest.mark.parametrize("raw", BAD_SAMPLES)
def test_bad_queries_compile_to_clean_keywords(raw: str):
    compiled, extra = _compile_query(raw)
    assert compiled, f"编译后为空: {raw!r}"
    assert not _compile_reasons(compiled), (
        f"编译后未达标: {compiled!r} 原因={_compile_reasons(compiled)} 原始={raw!r}"
    )


@pytest.mark.parametrize(
    "raw, expected_terms",
    [
        ("海水淡化 行业 政策 项目 成本 2025年 最新动态", ["海水淡化", "行业", "政策", "项目", "成本", "2025年"]),
        ("碧水源 兴蓉环境 海水淡化 最新新闻 业绩 项目", ["碧水源", "兴蓉环境", "海水淡化", "项目"]),
        ("海水淡化", ["海水淡化"]),
        ("火工品", ["火工品"]),
        ("光伏逆变器2025年", ["光伏逆变器", "2025年"]),
        ("特种石墨 等静压 供需", ["特种石墨", "等静压", "供需"]),
    ],
)
def test_positive_queries_keep_core_terms(raw: str, expected_terms: list[str]):
    compiled, _ = _compile_query(raw)
    for term in expected_terms:
        assert term in compiled, f"正样本关键词被误删: {term!r} 编译后={compiled!r} 原始={raw!r}"


def test_special_graphics_term_is_protected_from_etc_cleanup():
    # 方案 §4.3 待修项：通用"等X"清理不得吃掉"等静压"等专业技术术语
    compiled, _ = _compile_query("特种石墨 等静压 供需")
    assert "等静压" in compiled


def test_sort_and_limit_semantics_are_transferred():
    # 方案 §4.3 调优 #4：排序/条数语义转移到 sort_by / limit，而不是静默丢弃
    raw = "筛选A股再生水概念或主营业务涉及污水处理及再生水利用的上市公司按A股总市值从大到小排序取前30家企业"
    compiled, extra = _compile_query(raw)
    assert extra["limit"] == 30
    assert "总市值" in extra["sort_by"] and "desc" in extra["sort_by"]
    assert "取前" not in compiled
    assert "从大到小" not in compiled


def test_inline_year_is_split_out_to_avoid_glued_zero_hits():
    # 专项分析 §4.2：无空格连写（"海水淡化2025年吨水成本"）会归零 → 必须拆出空格
    compiled, _ = _compile_query("海水淡化2025年吨水成本")
    assert "海水淡化" in compiled
    assert "2025年" in compiled
    assert "吨水成本" in compiled


def test_validate_tasks_compiles_query_before_signature():
    from data_fetcher.agent import DataFetcherAgent

    class FakeLLM:
        is_available = True

        async def generate_json(self, system_prompt, user_prompt):
            raise AssertionError("should not be called in _validate_tasks")

    agent = DataFetcherAgent(llm=FakeLLM(), skillhub=SkillHub())
    task = SkillTask(
        task_id="a",
        skill_name="industry_data",
        arguments={"query": "碧水源 300070.SZ 基本信息 证券代码 证券简称 总市值 营业收入 所属行业 所属概念"},
        depends_on=[],
        purpose="行业",
    )
    accepted, errors = agent._validate_tasks(
        [task],
        dataset=StructuredResearchDataset(),
        remaining=5,
        used_task_ids=set(),
        completed_signatures=set(),
        successful_task_ids=set(),
    )
    assert accepted
    assert accepted[0].arguments["query"] == "碧水源 300070 SZ"
    assert not errors


class EmptyGateway:
    async def call(self, spec, arguments, *, call_type, trace_id):
        return {"datas": []}


class RepeatingLLM:
    is_available = True

    def __init__(self):
        self.calls = 0

    async def generate_json(self, system_prompt, user_prompt):
        self.calls += 1
        if self.calls == 1:
            return {"required_domains": [domain.value for domain in Domain]}
        return {
            "decision": "continue",
            "assessment": "继续",
            "tasks": [{
                "task_id": f"empty-{self.calls}",
                "skill_name": "industry_data",
                "arguments": {"query": "低空经济"},
                "depends_on": [],
                "purpose": "行业",
            }],
        }


def test_empty_dataset_is_blocked_and_reported():
    from data_fetcher.agent import DataFetcherAgent

    agent = DataFetcherAgent(
        llm=RepeatingLLM(),
        skillhub=SkillHub(gateway=EmptyGateway(), retry_backoff_seconds=0),
    )
    result = asyncio.run(agent.run(
        ResearchRequest(industry="低空经济", max_iterations=6), save_artifacts=False
    ))
    assert result.status == "blocked"
    assert result.stop_reason == "empty_dataset"
    assert _total_records(result.dataset) == 0
    assert any(e.stage == "data_fetch" and e.retryable for e in result.errors)


def test_result_builder_guards_empty_dataset():
    from data_fetcher.agent import DataFetcherAgent

    agent = DataFetcherAgent(llm=RepeatingLLM(), skillhub=SkillHub(gateway=EmptyGateway()))
    result = agent._result(
        "run-test", "completed", "coverage_complete",
        ResearchRequest(industry="低空经济"), [], [], [], Path("output"),
    )
    assert result.status == "blocked"
    assert result.stop_reason == "empty_dataset"
    assert result.errors and result.errors[-1].stage == "data_fetch"
