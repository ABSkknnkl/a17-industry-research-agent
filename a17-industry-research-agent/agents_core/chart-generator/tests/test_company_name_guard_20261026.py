"""企业名短语碎片拦截（2026-10-26）。

事故背景
--------
``run-20261026023355-5347eb`` 真跑的笔记本电脑产业链图，上游三个环节被填成：

    [upstream] 处理器与GPU   ['如互联网与软件公司', '影视后期制作公司', '新材料']
    [upstream] 显示面板      ['新能源', '原材料', '联想集团']
    [upstream] 存储器件      ['AI+新能源', '新的材料']

前两条不是公司名，是**从片段里按顿号硬切出来的类别短语**。链路是：
`_web_extract_llm` 调模型失败（端点订阅失效）→ 退回 `extract_company_candidates`
正则兜底 → 该函数按 ``[，。、；：/|（）()\\s·]`` 切词，再用后缀白名单
（公司/集团/股份/…/材料/能源）过滤 → 「如互联网与软件公司」以「公司」结尾、
「新材料」以「材料」结尾、「新能源」以「能源」结尾，**全部放行**。

所以后缀白名单单独用是**不够**的：它只判"结尾像不像"，不判"整体是不是一家公司"。
本文件锁定新加的 ``looks_like_entity_name`` 与它的接入点。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chart_generator.websearch import (  # noqa: E402
    WebHit,
    extract_company_candidates,
    looks_like_entity_name,
)

# ── 实测被误放大上图的那批词 ────────────────────────────────────────────────
JUNK = [
    "如互联网与软件公司",
    "影视后期制作公司",
    "新材料",
    "新能源",
    "原材料",
    "新的材料",
    "AI+新能源",
    "互联网",
    "零部件",
    "供应链",
]

# ── 真实企业名（必须全部放行）──────────────────────────────────────────────
REAL = [
    "立讯精密",
    "联想集团",
    "联想",
    "华勤技术",
    "京东方A",
    "TCL科技",
    "德赛电池",
    "科森科技",
    "华为技术有限公司",
    "立讯精密工业股份有限公司",
    "工业富联",
    "长鑫存储",
    "比亚迪",
    "中国石油和化学工业联合会",
]


@pytest.mark.parametrize("term", JUNK)
def test_category_phrase_is_rejected(term: str) -> None:
    assert looks_like_entity_name(term) is False


@pytest.mark.parametrize("term", REAL)
def test_real_company_is_kept(term: str) -> None:
    """宁放过一个模糊词，也不误杀真公司名。"""
    assert looks_like_entity_name(term) is True


def test_blank_is_not_a_name() -> None:
    assert looks_like_entity_name("") is False
    assert looks_like_entity_name("   ") is False


def test_phrase_prefix_covers_the_usual_suspects() -> None:
    """「如/例如/包括…」开头的并列短语一律不是公司名。"""
    for head in ("如", "例如", "包括", "以及", "主要", "其中", "涵盖", "面向"):
        assert looks_like_entity_name(f"{head}某某科技") is False, head


def test_suffix_alone_does_not_pass() -> None:
    """核心回归：有「公司」后缀 ≠ 是公司名。"""
    assert looks_like_entity_name("影视后期制作公司") is False
    # 但带真实企业名的同后缀必须留
    assert looks_like_entity_name("华为技术有限公司") is True


def _hit(title: str, snippet: str) -> WebHit:
    return WebHit(title=title, url="https://example.com/a", source_org="example.com",
                  snippet=snippet, published_at="", retrieved_at="")


def test_extract_drops_phrase_fragments_end_to_end() -> None:
    """接入点回归：一段真实形态的片段，切完不许再把类别短语当企业。

    注意断言口径——正则兜底是**按顿号硬切**的，句子中段的企业名会带上前后文
    （「整机制造由联想集团」），本来就不该指望它抽出干净名字；抽干净名字是
    LLM 通路（`_web_extract_llm`）的职责。本用例只锁「不再放垃圾上线」。
    """
    snippet = (
        "笔记本电脑产业链覆盖多个环节，服务于多个行业，"
        "如互联网与软件公司、影视后期制作公司、新材料企业均有参与。"
    )
    got = extract_company_candidates([_hit("笔记本电脑产业链梳理", snippet)])
    assert "如互联网与软件公司" not in got
    assert "影视后期制作公司" not in got
    assert "新材料" not in got
    assert got == [] or all("如" not in g for g in got)


def test_hard_split_residue_is_also_blocked() -> None:
    """硬切残句「整机制造由联想集团」含类别词「制造」→ 同样拦掉。"""
    got = extract_company_candidates(
        [_hit("t", "整机制造由联想集团、华勤技术承接，联想集团份额居前。")],
    )
    assert "整机制造由联想集团" not in got


def test_whitelist_still_wins_for_real_names() -> None:
    """干净的顿号列表（真实检索片段的常见形态）里，白名单命中排最前。

    ⚠️ 顺带记录两个既有缺口（不在本次改动范围）：后缀白名单里没有「技术」和
    「电池」，所以「华勤技术」「德赛电池」这类真公司名在**正则兜底通路**里
    永远抽不出来。这条通路本就只是 LLM 失败时的降级壳，别拿它当主抽取器。
    本用例只验证两件事：白名单命中排最前、垃圾词被拦。
    """
    snippet = "代表企业：联想集团、春秋电子、新能源、新材料"
    got = extract_company_candidates(
        [_hit("t", snippet)], whitelist={"联想集团"}, limit=8,
    )
    assert got and got[0] == "联想集团"      # 白名单命中排最前
    assert "春秋电子" in got
    assert "新能源" not in got
    assert "新材料" not in got
