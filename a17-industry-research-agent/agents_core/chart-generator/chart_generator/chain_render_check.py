"""产业链图「产物回读」校验：spec 里的事实必须真的出现在最终 SVG 文本里。

为什么需要（2026-11-12 诊断 D 类）：
主项目 ``eval_report.json`` 给新能源汽车打了 1.0 满分，命中项包含
「三行卡片（企业/细分行）」「连线流线语义正确」，但对照产物：
细分品类整层没画、21 条关系边一条都没画。原因是评分器直接拿 **spec JSON**
判的（edges 非空、items 存在即算通过），从未回读渲染后的 SVG。

本模块把校验对象从 spec 换成 **SVG 文本**。2026-11-12 二次修订：产业链图
渲染模块按用户要求复原为 GitHub 源码原版 lane_grid（卡片零连线、企业行优先），
因此本工具**降级为独立诊断**，不再作为 A3 出图门禁；生产门禁仍用仓库原版
``assert_graph_fidelity``（由 ``_omitted_edge_labels`` 同源豁免边标签）。
调用方可打印诊断清单定位「spec 有 / 图面无」，但不应据此拒绝发布原模板图。
"""

from __future__ import annotations

import html
import re
from typing import Any, Iterable

from chart_generator.chain_graph import ChainGraphSpec

_TEXT_RE = re.compile(r"<text\b[^>]*>(.*?)</text>", re.S)


def _norm(text: Any) -> str:
    return re.sub(r"\s+", "", html.unescape(str(text or "")))


def svg_plain_text(svg: str) -> str:
    """把所有 <text> 内容按出现顺序拼成连续串（换行只是排版，不算丢字）。"""
    return _norm("".join(m.group(1) for m in _TEXT_RE.finditer(svg or "")))


def _missing(values: Iterable[Any], plain: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _norm(value)
        if key and key not in plain and key not in seen:
            seen.add(key)
            out.append(str(value))
    return out


def assert_render_fidelity(
    spec: ChainGraphSpec,
    svg: str,
    annotations: dict[str, Any] | None = None,
) -> dict[str, list[str]]:
    """回读 SVG，返回各类「spec 有、图面无」的缺失项；空 dict 表示通过。

    检查项：
      - 节点名 / 细分品类 items / 企业名 / 描述全文（A2、A3）
      - 每条边的标签（A1）
      - 证据来源编号 R1–R8（C1）
      - 结构：箭头 marker 定义、关系行数量（A1）
    """
    plain = svg_plain_text(svg)
    report: dict[str, list[str]] = {}
    ann = annotations or {}

    checks = {
        "node_names": (n.name for n in spec.nodes),
        "items": (i for n in spec.nodes for i in n.items),
        "companies": (c for n in spec.nodes for c in n.companies),
        "descriptions": (n.description for n in spec.nodes),
        "edge_labels": (e.label for e in spec.edges),
        "evidence_ids": (r for n in spec.nodes for r in n.evidence_record_ids),
        # 图例里写的是「R1：xxx」，编号与说明分别命中即可（拼接串带全角冒号会假阴性）
        "source_labels": (desc for _rid, desc in (ann.get("sources") or {}).items()),
    }
    for key, values in checks.items():
        miss = _missing(values, plain)
        if miss:
            report[key] = miss

    # 结构级：每条边至少对应一个箭头元素；四类 flow 各需一个 marker 定义
    arrows = svg.count("<polyline") + svg.count("<path") + svg.count("<line")
    markers = svg.count("<marker")
    structural: list[str] = []
    if markers < 4:
        structural.append(f"flow 箭头 marker 定义 {markers} 个（应 >= 4）")
    if arrows < len(spec.edges):
        structural.append(f"箭头几何元素 {arrows} 个 < 关系边 {len(spec.edges)} 条")
    if structural:
        report["structure"] = structural
    return report


def fidelity_ok(report: dict[str, list[str]]) -> bool:
    return not any(report.values())


def format_report(report: dict[str, list[str]]) -> str:
    if fidelity_ok(report):
        return "产物回读通过：边标签 / 细分品类 / 企业 / 描述 / 证据编号全部命中 SVG"
    lines = ["产物回读未通过（spec 有、图面无）："]
    for key, values in report.items():
        lines.append(f"  {key}: {len(values)} 项，例如 {values[:3]}")
    return "\n".join(lines)
