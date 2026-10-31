"""产业链图「LLM 排 HTML → chromium 截图」路径回归（2026-10-17）。

覆盖：提示词构造 / 可见文本抽取 / 结构层与文本层门禁 / 失败与回退分支。
门禁必须与 SVG 路径**同口径**（同一套 lint_chain_texts + assert_text_fidelity）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chart_generator.chain_graph import ChainEdge, ChainGraphSpec, ChainNode, ChainStage
from chart_generator.chain_html import (
    CANVAS_WIDTH,
    _body_of,
    _div_block_spans,
    assert_html_fidelity,
    build_chain_html_payload,
    build_chain_html_prompt,
    ensure_edge_labels,
    html_texts,
    lint_chain_html,
    strip_code_fence,
    structural_issues,
    wrap_chain_html,
)
from chart_generator.chain_lint import lint_chain_svg
from chart_generator.chain_render import _stats_line, render_chain_svg
from chart_generator.config import Settings


def _spec() -> ChainGraphSpec:
    return ChainGraphSpec(
        title="低空经济产业链全景图",
        subtitle="上游核心零部件 → 中游设计研发与制造 → 下游场景落地",
        core_product="eVTOL/低空飞行器",
        stages=[
            ChainStage(stage_id="upstream", title="上游：核心供给"),
            ChainStage(stage_id="midstream", title="中游：设计与制造"),
            ChainStage(stage_id="downstream", title="下游：场景落地"),
            ChainStage(stage_id="support", title="配套：服务与回收"),
        ],
        nodes=[
            ChainNode(
                node_id="n1", name="动力电池", stage="upstream", bottleneck=True,
                companies=["宁德时代", "亿纬锂能"], items=["高能量密度电池"],
                description="提供续航能量，决定飞行器航程", evidence_record_ids=["R1"],
            ),
            ChainNode(
                node_id="n2", name="整机厂", stage="midstream", is_core=True,
                companies=["纵横股份", "绿能慧充", "万丰奥威", "沃飞长空"],
                items=["eVTOL"], description="核心产品本体设计与总装",
                evidence_record_ids=["R1"],
            ),
            ChainNode(
                node_id="n3", name="电力巡检", stage="downstream",
                companies=["国电南瑞"], items=["巡检无人机"], phase="已落地",
                buyer="电网企业", description="电网与设施巡检",
                evidence_record_ids=["R1"],
            ),
            ChainNode(
                node_id="n4", name="运维回收", stage="support", inferred=True,
                companies=["中信海直"], items=["维修"],
                description="整机维护与电池回收", evidence_record_ids=[],
            ),
        ],
        edges=[
            ChainEdge(source="n1", target="n2", label="电池包", flow="material"),
            ChainEdge(source="n2", target="n3", label="整机交付", flow="material"),
            ChainEdge(source="n4", target="n2", label="维护回收", flow="recycle"),
        ],
    )


# ── 模拟模型输出：只写 body 片段，样式靠系统注入的 class ─────────────────────
def _card_html(n) -> str:
    if n.is_core or n.stage == "core":
        cls = "card card-core"
    elif n.stage == "upstream":
        cls = "card card-up"
    elif n.stage == "midstream":
        cls = "card card-mid"
    else:
        cls = "card card-down"
    if n.bottleneck:
        cls += " bottleneck"
    if n.inferred:
        cls += " inferred"
    extra = ""
    if n.bottleneck:
        extra += '<span class="badge badge-hot">瓶颈</span>'
    if n.inferred:
        extra += '<span class="badge">推断</span>'
    if n.is_core or n.stage == "core":
        brands = "".join(f'<div class="brand">{c}</div>' for c in n.companies)
        inner = (f'<div class="name">{n.name}{extra}</div>'
                 f'<div class="desc">{n.description}</div>'
                 f'<div class="brandlist">{brands}</div>')
    else:
        inner = (f'<div class="name">{n.name}{extra}</div>'
                 f'<div class="comp">{" · ".join(n.companies)}</div>'
                 f'<div class="desc">{n.description}</div>')
    if n.phase:
        inner += f'<span class="badge badge-phase">{n.phase}</span>'
    if n.buyer:
        inner += f'<div class="buyer">采购方：{n.buyer}</div>'
    return f'<div class="{cls}">{inner}</div>'


def _body_fragment(spec: ChainGraphSpec, *, stats: str = "") -> str:
    order = ["upstream", "midstream", "core", "downstream"]
    parts: list[str] = []
    for stage in order:
        if stage == "core":
            nodes = [n for n in spec.nodes if n.is_core or n.stage == "core"]
        else:
            nodes = [n for n in spec.nodes if n.stage == stage and not n.is_core]
        pill = {"upstream": "pill-up", "midstream": "pill-mid",
                "core": "pill-core", "downstream": "pill-down"}[stage]
        cards = "".join(_card_html(n) for n in nodes)
        parts.append(f'<div class="lane"><span class="pill {pill}">{stage}</span>{cards}</div>')
        if stage != order[-1]:
            tags = "".join(f'<span class="flowtag">{e.label}</span>' for e in spec.edges)
            parts.append(f'<div class="gutter">{tags}</div>')
    supports = ""
    sup_nodes = [n for n in spec.nodes if n.stage == "support"]

    def _sup_card(n) -> str:
        mark = '<span class="badge">推断</span>' if n.inferred else ""
        cls = "sup inferred" if n.inferred else "sup"
        return (
            f'<div class="{cls}"><div class="sup-title">{n.name}{mark}</div>'
            f'<div class="sup-body">{n.description}</div>'
            f'<div class="sup-body">{" · ".join(n.companies)}</div></div>'
        )

    if sup_nodes:
        cards = "".join(_sup_card(n) for n in sup_nodes)
        supports = ('<div class="support"><div class="support-title">'
                    "配套 · 服务、软件与渠道（虚线挂接）</div>" + cards + "</div>")
    return (
        '<div class="page">'
        f'<h1 class="title">{spec.title}</h1>'
        f'<p class="subtitle">{spec.subtitle}</p>'
        f'<p class="stats">{stats}</p>'
        f'<div class="diagram">{"".join(parts)}</div>'
        + supports
        + '<p class="legend">实线 = 物料 / 零部件流　虚线 = 数据 / 算法 / 服务流'
          "　橙框 = 卡脖子瓶颈环节</p>"
        "</div>"
    )


def _good_html(spec: ChainGraphSpec, *, stats: str = "") -> str:
    """合规产物 = 系统外壳 + 模型片段（ wrap_chain_html 负责注入样式表）。"""
    return wrap_chain_html(_body_fragment(spec, stats=stats))


def test_prompt_locks_stylesheet_and_forbids_extra_markup():
    system, user = build_chain_html_prompt(_spec(), stats_line="上游 1 环节")
    # 样式表在我们手里：提示词必须明确禁止模型自带 <style>/<html>/<script>
    assert "<style>" in system or "不要输出" in system
    for ban in ("<html>", "<script>", "Markdown"):
        assert ban in system or "不要输出" in system
    assert "flowtag" in system and "diagram" in system and "七列" in system
    payload = build_chain_html_payload(_spec())
    for token in ("动力电池", "宁德时代", "整机交付", "中信海直", "采购方"):
        assert token in payload


def test_html_texts_and_structural_gate():
    doc = wrap_chain_html(
        '<div class="page"><h1 class="title">t</h1><script>bad()</script>'
        '<div class="diagram"><div class="lane"><div class="card"><div class="name">动力电池'
        '</div></div></div></div></div>')
    texts = html_texts(doc)
    assert "动力电池" in texts
    assert not any("bad()" in t for t in texts), "script 内容不得进入可见文本"
    issues = structural_issues(_body_of(doc))
    assert any("script" in m for m in issues)
    assert any("外部资源" in m for m in structural_issues('<link href="https://x.com/a.css">'))
    assert any("体量过小" in m for m in structural_issues("<div>hi</div>"))
    assert any("diagram" in m for m in structural_issues("<div>no skeleton</div>"))


def test_strip_code_fence():
    assert strip_code_fence("```html\n<div class=\"page\"></div>\n```") == '<div class="page"></div>'
    assert strip_code_fence('<div class="page"></div>') == '<div class="page"></div>'
    assert strip_code_fence("```\n<div>\n```") == "<div>"


def test_lint_accepts_complete_html_and_rejects_missing_content():
    spec = _spec()
    # 统计行必须用渲染器算出的原串：模型擅自另写一条会被数值体检抓住
    good = _good_html(spec, stats=_stats_line(spec))
    errors = [i for i in lint_chain_html(spec, good) if i["level"] == "error"]
    assert errors == [], f"合规 HTML 被误判：{errors}"
    assert assert_html_fidelity(spec, good) == []

    partial = good.replace("电力巡检", "")
    assert any("电力巡检" in m for m in assert_html_fidelity(spec, partial))

    numeric = good.replace("电网与设施巡检", "市占率约 37%")
    issues = [i for i in lint_chain_html(spec, numeric) if i["level"] == "error"]
    assert any(i["code"] == "numeric_in_chart" for i in issues), issues

    hand_written = _good_html(spec, stats="上游 1 环节 · 中游 1 环节 · 自己加的 9 处")
    issues2 = [i for i in lint_chain_html(spec, hand_written) if i["level"] == "error"]
    assert any(i["code"] == "numeric_in_chart" for i in issues2), issues2


def test_html_and_svg_gates_share_the_same_rules():
    spec = _spec()
    svg = render_chain_svg(spec)
    good = _good_html(spec, stats=_stats_line(spec))
    svg_err = {i["code"] for i in lint_chain_svg(spec, svg) if i["level"] == "error"}
    html_err = {i["code"] for i in lint_chain_html(spec, good) if i["level"] == "error"}
    assert svg_err == html_err == set(), (svg_err, html_err)


def test_switch_defaults():
    """开关与既有 AI 生图开关互不干扰。"""
    assert Settings().enable_industry_chain_html is True
    assert Settings().enable_industry_chain_image is False
    s = Settings(enable_industry_chain_html=False)
    assert s.enable_industry_chain_html is False
    assert s.enable_industry_chain_image is False


def test_generate_returns_none_without_llm_credentials():
    """LLM 未配置时必须安静回退（由调用方用确定性 SVG 顶上），不能抛异常炸掉阶段三。"""
    import asyncio

    from chart_generator.chain_html import generate_chain_html_image

    got = asyncio.run(
        generate_chain_html_image(
            _spec(),
            settings=Settings(llm_api_key="", llm_model=""),
            artifact_dir=None,
            chart_id="CHART-01",
        )
    )
    assert got is None


def test_render_html_to_png_roundtrip(tmp_path: Path):
    """截图链路真跑一遍 chromium（CI 无浏览器时跳过，不用 skip 掩盖失败）。"""
    import asyncio

    from chart_generator.chain_html import render_html_to_png

    pytest.importorskip("playwright")
    try:
        size = asyncio.run(
            render_html_to_png(_good_html(_spec(), stats=_stats_line(_spec())),
                               tmp_path / "t.png", timeout_seconds=45.0))
    except Exception as exc:  # 环境无 chromium → 明确跳过
        pytest.skip(f"chromium 不可用，截图往返未验证：{type(exc).__name__}")
    assert size > 20_000, f"截图产物异常偏小：{size} bytes"
    assert (tmp_path / "t.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_thinking_is_disabled_by_default():
    """2026-10-17：默认关掉思考。该端点开启思考后生成慢一个量级，实测同等任务
    10.4s → 5.8s（关闭后）；长任务差距更大。置 LLM_THINKING=auto/enabled 可恢复。"""
    from chart_generator.chain_html import build_html_llm_payload

    assert Settings().llm_thinking == "disabled"
    payload = build_html_llm_payload(
        system_prompt="sys", user_prompt="usr", model="m")
    assert payload["thinking"] == {"type": "disabled"}
    assert payload.get("reasoning_effort") is None, "thinking 生效时不应再发 reasoning_effort"

    # 可显式恢复；关闭开关（空串）则完全不带思考参数
    assert build_html_llm_payload(system_prompt="s", user_prompt="u", model="m",
                                  thinking="enabled")["thinking"] == {"type": "enabled"}
    assert "thinking" not in build_html_llm_payload(
        system_prompt="s", user_prompt="u", model="m", thinking="")


def test_prompt_lists_every_edge_label_for_counting():
    """连线标签清点表：模型不看 edges 长度，配套带边稳定漏排，清单让它照着数。"""
    spec = _spec()
    _, user = build_chain_html_prompt(spec, stats_line="")
    assert "连线标签清点表" in user
    for e in spec.edges:
        assert f"「{e.label}」" in user


def test_missing_support_edge_label_is_patched_by_code():
    """配套带边（实测「维护回收」两次重试都漏）→ 代码补到起点配套卡里。"""
    spec = _spec()
    body = _body_fragment(spec, stats=_stats_line(spec))
    body = body.replace('<span class="flowtag">维护回收</span>', "")
    assert assert_html_fidelity(spec, wrap_chain_html(body)) == ["连线「维护回收」"]

    patched, injected = ensure_edge_labels(body, spec)
    assert injected == ["维护回收"]
    doc = wrap_chain_html(patched)
    assert assert_html_fidelity(spec, doc) == []
    assert not [i for i in lint_chain_html(spec, doc) if i["level"] == "error"]
    # 落点必须在底部的配套区（而不是混进主带 gutter）
    assert patched.index('class="support"') < patched.index("维护回收")


def test_missing_main_band_edge_label_goes_to_the_right_gutter():
    """主带边按起点/终点泳道落进相邻 gutter：上游→中游 落在第 1 条 gutter。"""
    spec = _spec()
    body = _body_fragment(spec, stats=_stats_line(spec))
    body = body.replace('<span class="flowtag">电池包</span>', "")
    assert assert_html_fidelity(spec, wrap_chain_html(body)) == ["连线「电池包」"]

    patched, injected = ensure_edge_labels(body, spec)
    assert injected == ["电池包"]
    assert assert_html_fidelity(spec, wrap_chain_html(patched)) == []
    gutters = _div_block_spans(patched, "gutter")
    first = patched[gutters[0][0]: gutters[0][1]]
    assert "电池包" in first, "上游→中游 的边应补进第一条 gutter"


def test_ensure_edge_labels_is_a_noop_when_nothing_is_missing():
    spec = _spec()
    body = _body_fragment(spec, stats=_stats_line(spec))
    patched, injected = ensure_edge_labels(body, spec)
    assert injected == [] and patched == body


def test_literal_phase_placeholder_is_rejected():
    """2026-10-17 实测：关掉思考后模型把提示词示例里的「阶段」当字面量抄进徽标，
    落地阶段等于没上图。这类"照抄占位符"必须由代码拦住。"""
    body = _body_fragment(_spec(), stats=_stats_line(_spec()))
    bad = body.replace('<span class="badge badge-phase">已落地</span>',
                       '<span class="badge badge-phase">阶段</span>')
    assert any("字面量「阶段」" in m for m in structural_issues(bad))
    assert structural_issues(body) == []
