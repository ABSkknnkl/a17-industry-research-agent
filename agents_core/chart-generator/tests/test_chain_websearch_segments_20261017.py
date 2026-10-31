"""博查补漏必须覆盖「拓扑缺失 → segments 兜底」路径（2026-10-17，B13）。

背景（六主题横向测试）：博查调用点原先挂在 `cg/agent.py` 的
``if isinstance(topo, dict) and topo.get("nodes"):`` **分支内部**。
6 个测试主题 `industry_chain_topology=None`（A2 语义通道被跳过）→ 走 segments 兜底
→ **博查整段被跳过、0 次调用**。而代码注释写的意图恰恰相反：
「问财未收录该主题时，博查升级为整条链的企业名/环节名来源」——最需要它时用不上。

修复：新增 `supplement_segments_with_web()`（websearch.py），把 segments 摊平成
topo-like 结构交给 `fill_chain_gaps`，再把补到的企业名写回 segments。

验收：
- 开关关闭 / client 为 None → 原样返回，段数据零改动（绝不因联网失败破坏已有结构）；
- 命中时企业名必须写回对应 segment，且不得新增节点（红线 C-10）。
"""

from __future__ import annotations

import asyncio

from chart_generator.websearch import supplement_segments_with_web

SEGMENTS = [
    {"segment_name": "上游：基础支撑、核心部件与关键供给", "stage": "upstream",
     "representative_companies": [], "key_products": ["核心零部件与原材料"]},
    {"segment_name": "中游：核心产品研发、系统集成与方案交付", "stage": "midstream",
     "representative_companies": [], "key_products": ["系统集成"]},
    {"segment_name": "下游：场景应用、终端落地与商业化生态", "stage": "downstream",
     "representative_companies": [], "key_products": ["场景化应用"]},
]


class _FakeHit:
    def __init__(self, title: str, snippet: str) -> None:
        self.title = title
        self.snippet = snippet
        self.url = "https://example.com/a"
        self.published_at = "2026-01-01"


class _FakeClient:
    """最小 WebSearchClient 替身：只提供 fill_chain_gaps 需要的接口面。"""

    def __init__(self, hits: list[_FakeHit], *, enabled: bool = True) -> None:
        self._hits = hits
        self.queries: list[str] = []
        self.exhausted = False
        self._config = type("Cfg", (), {"enabled": enabled, "always_search": True})()

    async def search(self, query: str, *, scope: str = "industry_chain", known_companies=(), required_terms=()):  # noqa: ANN001
        self.queries.append(query)
        return list(self._hits)


def test_disabled_client_returns_segments_untouched():
    """开关关闭：原样返回，段数据零改动。"""
    segs = [dict(s) for s in SEGMENTS]
    out, diag = asyncio.run(supplement_segments_with_web(
        segs, subject="创新药", client=_FakeClient([], enabled=False)))
    assert out == SEGMENTS
    assert diag.get("hits", 0) == 0
    assert [s["representative_companies"] for s in out] == [[], [], []]


def test_none_client_returns_segments_untouched():
    """client 为 None（未配置）：不得抛异常，原样返回。"""
    segs = [dict(s) for s in SEGMENTS]
    out, diag = asyncio.run(supplement_segments_with_web(segs, subject="创新药", client=None))
    assert out == SEGMENTS
    assert diag["enabled"] is False


def test_hits_are_written_back_to_segments():
    """命中时企业名必须写回对应 segment（且段数不变 = 不新增节点）。"""
    hits = [
        _FakeHit("创新药产业链上游原料药供应商盘点",
                 "上游原料药代表企业：药明康德、凯莱英、泰格医药"),
        _FakeHit("创新药中游研发与生产", "代表企业：恒瑞医药、百济神州"),
    ]
    segs = [dict(s) for s in SEGMENTS]
    out, diag = asyncio.run(supplement_segments_with_web(
        segs, subject="创新药", client=_FakeClient(hits), evidence_count=0))

    assert len(out) == len(SEGMENTS), "不得新增/删除环节（红线 C-10）"
    assert diag.get("queries"), "应当至少发出一条检索语句"
    got = {s["stage"]: s["representative_companies"] for s in out}
    # 上游段应被写入候选企业（LLM 抽取不可用时退化为正则抽取）
    assert any(got.values()), f"命中的企业名未写回任何 segment：{got}"
    assert all(isinstance(c, str) for c in got["upstream"])
