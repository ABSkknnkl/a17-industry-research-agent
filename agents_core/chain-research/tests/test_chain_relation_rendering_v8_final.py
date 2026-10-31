"""D3 测试：关系边渲染（同列/跨列、箭头、稳定 ID、映射）。

对应 V8 最终方案 §10.6 第 5、6 条：同列/跨列 accepted 关系必须有可核对
边与方向；data ID / 映射保留到消毒后 DOM；背景网格不能满足断言。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agents_core" / "chain-research"))

from chain_research.models import (  # noqa: E402
    BundleManifest,
    ChainAssertion,
    ChainEntity,
    ChainEvidence,
    ChainKnowledgeBundle,
    ChainQualityReport,
    ChainScope,
    Predicate,
    Qualifiers,
    Verification,
)
from chain_research.view import render_bundle  # noqa: E402

# 与前端 ChartGallery.vue INLINE_SVG_WHITELIST 保持一致的消毒口径
FRONTEND_WHITELIST = {
    "svg", "g", "rect", "text", "line", "polyline", "polygon",
    "circle", "ellipse", "defs", "marker", "title",
}


def _evidence(eid: str, quote: str) -> ChainEvidence:
    return ChainEvidence(
        evidence_id=eid, document_id=f"doc-{eid}", url="https://example.org/" + eid,
        title="资料", document_kind="other", published_at=None,
        fetched_at="2026-10-31T00:00:00", content_hash="h-" + eid,
        source_family="official", locator="第1段", quote=quote,
    )


def _claim(aid: str, s: str, o: str, eid: str) -> ChainAssertion:
    return ChainAssertion(
        assertion_id=aid, subject_id=s, predicate=Predicate.PRECEDES, object_id=o,
        evidence_ids=[eid], status="supported",
        verification=Verification(method="source_rule", verifier_version="t1", rationale="已核"),
        qualifiers=Qualifiers(),
    )


@pytest.fixture(scope="module")
def bundle() -> ChainKnowledgeBundle:
    scope = ChainScope(
        scope_id="s1", subject="测试产业链", as_of="2026-10", view_kind="industry",
    )
    entities = [
        ChainEntity(entity_id="A", entity_type="activity", canonical_name="环节A"),
        ChainEntity(entity_id="B", entity_type="activity", canonical_name="环节B"),
        ChainEntity(entity_id="C", entity_type="activity", canonical_name="环节C"),
    ]
    evidence = [_evidence("E1", "A先于B"), _evidence("E2", "A先于C")]
    assertions = [_claim("AS1", "A", "B", "E1"), _claim("AS2", "A", "C", "E2")]
    return ChainKnowledgeBundle(
        run_id="r1", scope=scope, entities=entities, assertions=assertions,
        evidence=evidence,
        structure={
            "structure_id": "st1", "scope_id": "s1",
            "activity_ids": ["A", "B", "C"], "required_activity_ids": ["A", "B", "C"],
            "coverage_basis": "profile_policy", "unresolved": [],
        },
        quality=ChainQualityReport(release_status="partial"),
        manifest=BundleManifest(run_id="r1", scope_subject=scope.subject),
    )


def test_edges_are_rendered_with_stable_ids(bundle):
    """呈现的边必须有稳定 edge/assertion ID，并写入 view_mapping。"""
    svg, mapping = render_bundle(bundle)
    edges = mapping.get("edges") or []
    assert len(edges) == 2, f"边数量不符: {edges}"
    for e in edges:
        assert e["edge_id"].startswith("edge-")
        assert e["assertion_id"].startswith("AS")
        assert e["render_status"] == "rendered"
        assert e["from"] and e["to"]
        assert e["evidence_ids"], "边缺证据引用"
        assert e["edge_id"] in svg, "边 ID 未落到 SVG（无法核对）"


def test_edge_elements_use_frontend_safe_primitives(bundle):
    """边与箭头必须用前后端都支持的图元（line/polygon），不能用 path。"""
    svg, _ = render_bundle(bundle)
    assert "<line" in svg, "未渲染任何边"
    assert "<polygon" in svg, "缺箭头（polygon）"
    assert "<path" not in svg, "使用了 path —— 前端消毒会删除"

    for tag in set(re.findall(r"<([a-zA-Z][\w:-]*)", svg)):
        assert tag.lower() in FRONTEND_WHITELIST, f"含非白名单元素 {tag}（前端会被删）"


def test_edge_has_arrow_marker(bundle):
    svg, _ = render_bundle(bundle)
    assert "marker-end" in svg
    assert 'id="chain-arrow"' in svg, "缺箭头 marker 定义"
    # marker 内的箭头本体必须是 polygon
    marker_block = svg[svg.find('id="chain-arrow"') :][:400]
    assert "<polygon" in marker_block


def test_same_column_edge_is_not_skipped():
    """同列关系：不得因 x 相同被跳过（旧实现直接 continue）。"""
    scope = ChainScope(scope_id="s2", subject="同列测试", as_of="2026-10", view_kind="industry")
    entities = [
        ChainEntity(entity_id="A", entity_type="activity", canonical_name="上游一"),
        ChainEntity(entity_id="B", entity_type="activity", canonical_name="上游二"),
    ]
    evidence = [_evidence("E9", "上游一先于上游二")]
    assertions = [_claim("AS9", "A", "B", "E9")]
    bundle = ChainKnowledgeBundle(
        run_id="r2", scope=scope, entities=entities, assertions=assertions, evidence=evidence,
        structure={
            "structure_id": "st2", "scope_id": "s2", "activity_ids": ["A", "B"],
            "required_activity_ids": ["A", "B"], "coverage_basis": "profile_policy",
            "unresolved": [],
        },
        quality=ChainQualityReport(release_status="partial"),
        manifest=BundleManifest(run_id="r2", scope_subject=scope.subject),
    )
    svg, mapping = render_bundle(bundle)
    edges = mapping.get("edges") or []
    assert edges, "同列边被丢"
    assert edges[0]["same_column"] is True
    # 同列边：x1 == x2（纵向短箭头）
    m = re.search(r'data-edge-id="' + re.escape(edges[0]["edge_id"]) + r'".*?x1="([\d.]+)".*?y1="([\d.]+)".*?x2="([\d.]+)".*?y2="([\d.]+)"', svg)
    assert m, "同列边未落到 SVG"
    x1, y1, x2, y2 = (float(v) for v in m.groups())
    assert abs(x1 - x2) < 0.5, f"同列边不是纵向: x1={x1} x2={x2}"
    assert abs(y1 - y2) > 0, "同列边长度为 0"


def test_no_edge_without_supported_assertion():
    """未受支持的断言不得画成边（不臆造关系）。"""
    scope = ChainScope(scope_id="s3", subject="无证据", as_of="2026-10", view_kind="industry")
    entities = [
        ChainEntity(entity_id="A", entity_type="activity", canonical_name="A"),
        ChainEntity(entity_id="B", entity_type="activity", canonical_name="B"),
    ]
    assertion = _claim("AS3", "A", "B", "E3")
    assertion.status = "unresolved"  # type: ignore[assignment]
    bundle = ChainKnowledgeBundle(
        run_id="r3", scope=scope, entities=entities, assertions=[assertion],
        evidence=[_evidence("E3", "未核")],
        structure={
            "structure_id": "st3", "scope_id": "s3", "activity_ids": ["A", "B"],
            "required_activity_ids": ["A", "B"], "coverage_basis": "profile_policy",
            "unresolved": [],
        },
        quality=ChainQualityReport(release_status="draft"),
        manifest=BundleManifest(run_id="r3", scope_subject=scope.subject),
    )
    svg, mapping = render_bundle(bundle)
    assert not (mapping.get("edges") or []), "未受支持断言被画成关系边"
    assert "<line" not in svg


def test_svg_has_no_dangerous_content(bundle):
    """消毒口径：无脚本/事件属性/href。"""
    svg, _ = render_bundle(bundle)
    lowered = svg.lower()
    for bad in ("<script", "onload=", "onclick=", "javascript:", "xlink:href"):
        assert bad not in lowered, f"SVG 含危险内容 {bad}"
