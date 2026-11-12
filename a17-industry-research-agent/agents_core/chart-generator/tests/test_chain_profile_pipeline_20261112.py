"""2026-11-12 产业链图守门用例（模板复原版）。

用户要求产业链图渲染模块与 GitHub 仓库源码一模一样：
``render_chain_svg`` 只走仓库原版 ``_render_lane_grid``（三列目录式）。
本文件守两件事：① 渲染路径没有被再次分叉；② 审定数据底座仍被 A3 接入，
且内容修订（B1/B3/B6）不丢。``assert_render_fidelity`` 降级为独立诊断工具。
"""

from __future__ import annotations

import sys
from pathlib import Path

_CG_ROOT = Path(__file__).resolve().parents[1]
if str(_CG_ROOT) not in sys.path:
    sys.path.insert(0, str(_CG_ROOT))

from chain_data import load_chain_profile  # noqa: E402
from chart_generator.chain_graph import ChainGraphSpec  # noqa: E402
from chart_generator.chain_lint import assert_graph_fidelity  # noqa: E402
from chart_generator.chain_render import _omitted_edge_labels, render_chain_svg  # noqa: E402
from chart_generator.chain_render_check import assert_render_fidelity  # noqa: E402


def _payload():
    payload = load_chain_profile("新能源汽车")
    assert payload is not None, "新能源汽车审定事实底座必须存在"
    return payload


def _spec():
    return ChainGraphSpec.model_validate(_payload()["spec"])


def test_lane_grid_body_matches_github_source_byte_for_byte():
    """lane_grid 主体（37911 字节）必须与仓库源码逐字节一致。

    合并项只允许追加在末尾；任何对模板主体的改动都会改掉这个 md5。
    """
    import hashlib

    src = (_CG_ROOT / "chart_generator" / "chain_render.py").read_text(encoding="utf-8")
    body = src.split("def _render_reviewed_profile(", 1)[0]
    assert hashlib.md5(body.encode("utf-8")).hexdigest() == "55f87a067c87e2eae7d62ab6faea33d7"
    assert "chain_relation_render" not in src
    assert "reviewed_chain_profile" not in src


def test_default_render_path_is_original_lane_grid():
    """默认路径只有 lane_grid；唯一分流是 11-10 的 A2 审定结构卡合并项。"""
    src = (_CG_ROOT / "chart_generator" / "chain_render.py").read_text(encoding="utf-8")
    body = src.split("def render_chain_svg(", 1)[1]
    assert "return _render_lane_grid(spec, width)" in body
    assert body.count("if spec.source") == 1
    assert 'spec.source == "reviewed_profile"' in body


def test_profile_uses_repo_legal_source_and_renders_lane_grid():
    """数据底座用仓库合法 source，出图走原模板且通过原版事实锁死。"""
    spec = _spec()
    assert spec.source == "merged"
    svg = render_chain_svg(spec)
    assert "上游" in svg and "中游" in svg and "下游" in svg
    assert "环节关系" not in svg, "不得出现自行编写的关系面板"
    assert not assert_graph_fidelity(spec, svg)


def test_edge_labels_omitted_by_design_not_by_accident():
    """原模板卡片零连线：带标签的边必须走 _omitted_edge_labels 同源豁免。"""
    spec = _spec()
    omitted = _omitted_edge_labels(spec)
    labeled = [(e.source, e.target) for e in spec.edges if e.label]
    assert labeled and all(pair in omitted for pair in labeled)


def test_render_fidelity_is_available_as_diagnostic():
    """独立诊断工具仍能抓到「图面被抹字」，只是不再作出图门禁。"""
    payload, spec = _payload(), _spec()
    svg = render_chain_svg(spec)
    # 抹掉一个真实画在图上的节点名，严格回读必须报缺失
    name = spec.nodes[0].name
    broken = svg.replace(name, "已抹除")
    report = assert_render_fidelity(spec, broken, payload["annotations"])
    assert "node_names" in report


def test_unregistered_theme_yields_explicit_gap():
    assert load_chain_profile("白酒") is None
    assert load_chain_profile("光伏") is None
    assert load_chain_profile("新能源汽车产业链") is not None


def test_content_fixes_b1_b3_b6():
    spec = _spec()
    by_name = {n.name: n for n in spec.nodes}
    assert "长安汽车" in by_name["整车研发与品牌"].companies
    assert "赛力斯" in by_name["整车制造与集成"].companies
    assert "拓普集团" not in by_name["整车制造与集成"].companies
    assert "拓普集团" in by_name["底盘与热管理部件"].companies
    assert "锂镍钴矿产资源" in by_name
    assert all(n.phase != "试点中" for n in by_name.values())
