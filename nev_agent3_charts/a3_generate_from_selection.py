"""按智能体3 LLM 的选图结论，逐张生成图表（严格不增不减）。

流程
----
1. 读取 llm_selection_result.json 中由 LLM 自主决定的有序清单与 chart_count。
2. 逐张调用 charts.CHARTS 注册表中对应的实现函数，生成 ECharts option。
3. 三重强校验：清单条数 == chart_count == 生成 option 数 == 页面渲染数，
   且每张 chart_id / chart_type 与 LLM 选型逐项一致。
4. 导出 chart_options_selected.json 与统一展示页 index_selected.html。

约束：不改动交接包中任何既有文件；未入选的候选图（C07）不渲染、不补位。
数值全部来自 A1 dataset.json，经 chart_data 证据 ID 校验，不外推、不补缺失值。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import charts
import render_preview as rp

ROOT = Path(__file__).resolve().parent
SELECTION_PATH = ROOT / "llm_selection_result.json"
PLAN_PATH = ROOT / "chart_plan.json"
OPTIONS_OUT = ROOT / "chart_options_selected.json"
HTML_OUT = ROOT / "index_selected.html"
MANIFEST_OUT = ROOT / "generation_manifest.json"
ECHARTS_PATH = ROOT / "echarts.min.js"


def main() -> None:
    record = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    if record.get("validation_errors"):
        raise RuntimeError(f"选图结果未通过校验: {record['validation_errors']}")
    selection = record["selection"]
    chosen: list[dict[str, Any]] = selection["charts"]
    declared_count: int = selection["chart_count"]

    if declared_count != len(chosen):
        raise RuntimeError(f"LLM 声明数量 {declared_count} != 清单长度 {len(chosen)}")

    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    specs_by_id = {s["chart_id"]: s for s in plan["charts"]}
    all_evidence_ids = {eid for s in plan["charts"] for eid in s.get("evidence_ids", [])}

    options: list[dict[str, Any]] = []
    generated: list[dict[str, Any]] = []

    # ---- 逐张生成：清单顺序即为生成顺序，一张不多、一张不少 ----
    for i, item in enumerate(chosen, 1):
        cid = item["chart_id"]
        ctype = item["chart_type"]
        if cid not in specs_by_id:
            raise RuntimeError(f"{cid} 不在候选图卡池")
        spec = specs_by_id[cid]
        if spec["chart_type"] != ctype:
            raise RuntimeError(f"{cid} 选型 {ctype} 与候选卡 {spec['chart_type']} 不一致")
        if cid not in charts.CHARTS:
            raise RuntimeError(f"{cid} 没有对应的图表实现")
        fn, declared_type = charts.CHARTS[cid]
        if declared_type != ctype:
            raise RuntimeError(f"{cid} 实现类型 {declared_type} 与 LLM 选型 {ctype} 不一致")

        option = fn(spec)                      # 单张生成（内部做证据 ID 校验）
        meta = option["chart_meta"]
        if meta["chart_id"] != cid or meta["chart_type"] != ctype:
            raise RuntimeError(f"{cid} chart_meta 与选型不一致")
        bad = [e for e in meta["evidence_ids"] if e not in all_evidence_ids]
        if bad:
            raise RuntimeError(f"{cid} 出现未知证据 ID: {bad}")
        options.append(option)
        generated.append({
            "seq": i,
            "chart_id": cid,
            "chart_type": ctype,
            "title": meta["title"],
            "chapter": meta["recommended_chapter_id"],
            "evidence_count": len(meta["evidence_ids"]),
            "footnote_count": len(meta["footnotes"]),
            "llm_reason": item.get("reason", ""),
        })
        print(f"  [{i:02d}/{declared_count}] {cid} {ctype:<16} {meta['title'][:34]} "
              f"(证据 {len(meta['evidence_ids'])} 条)")

    # ---- 强校验 1：生成数量 == LLM 声明数量 ----
    assert len(options) == declared_count == len(generated), "生成数量与 LLM 选图数量不一致"
    # ---- 强校验 2：无重复、无额外 ----
    assert len({g["chart_id"] for g in generated}) == declared_count, "出现重复 chart_id"
    assert {g["chart_id"] for g in generated} == {c["chart_id"] for c in chosen}, "生成集合与选图集合不一致"

    # ---- 构造只含入选图的展示 plan，抑制项合并 LLM 本轮抑制结论 ----
    llm_suppressed = []
    by_id = {s["chart_id"]: s for s in plan["charts"]}
    for s in selection.get("suppressed", []):
        src = by_id.get(s["chart_id"], {})
        llm_suppressed.append({
            "title": f"[本轮 LLM 抑制] {src.get('title', s['chart_id'])}",
            "requested_type": src.get("chart_type", ""),
            "reason_code": s.get("reason_code", ""),
            "reason": s.get("reason", ""),
            "evidence_ids": [],
        })
    shown_plan = {
        "charts": [specs_by_id[c["chart_id"]] for c in chosen],
        "suppressed_charts": llm_suppressed + plan.get("suppressed_charts", []),
    }

    html = rp.build_html(shown_plan, options)
    # ---- 强校验 3：页面渲染的图表容器数 == 生成数量 ----
    card_count = html.count('<article class="card">')
    div_count = sum(html.count(f'id="chart-{i}"') for i in range(1, len(options) + 1))
    assert card_count == declared_count, f"页面卡片 {card_count} != {declared_count}"
    assert div_count == declared_count, f"页面容器 {div_count} != {declared_count}"

    # ---- 把本轮 LLM 选图结论与数量对账嵌入统一展示页 ----
    rows = "".join(
        f"<tr><td>{g['seq']:02d}</td><td><code>{rp._esc(g['chart_id'])}</code></td>"
        f"<td><code>{rp._esc(g['chart_type'])}</code></td>"
        f"<td>{rp._esc(g['chapter'])}</td><td>{rp._esc(g['title'])}</td>"
        f"<td>{rp._esc(g['llm_reason'])}</td></tr>"
        for g in generated
    )
    supp_rows = "".join(
        f"<li><code>{rp._esc(s['chart_id'])}</code> · {rp._esc(s.get('reason_code',''))}："
        f"{rp._esc(s.get('reason',''))}</li>"
        for s in selection.get("suppressed", [])
    )
    panel = f"""
  <section class="panel">
    <h3>本轮智能体3 LLM 选图结论（数量由其自主决定）</h3>
    <div class="stats">
      <div class="stat"><b>{declared_count}</b><span>LLM 决定图表张数</span></div>
      <div class="stat"><b>{len(options)}</b><span>逐张生成 option</span></div>
      <div class="stat"><b>{card_count}</b><span>本页统一展示</span></div>
      <div class="stat"><b>{len(selection.get('suppressed', []))}</b><span>本轮 LLM 抑制</span></div>
    </div>
    <p style="font-size:13px;line-height:1.9;margin:6px 0 12px;">
      调用模型：<code>{rp._esc(str(record.get('model')))}</code> · 耗时 {record.get('elapsed_seconds')}s ·
      prompt 指纹 <code>{rp._esc(str(record.get('prompt_sha256')))}</code>。<br>
      <b>模型给的数量结论：</b>{rp._esc(str(selection.get('rationale')))}<br>
      <b>数量对账：</b>LLM 声明 {declared_count} 张 = 清单 {len(chosen)} 项 =
      逐张生成 {len(options)} 个 option = 本页 {card_count} 张卡片 / {div_count} 个容器，<b>不增不减</b>。
    </p>
    <table class="supp">
      <thead><tr><th>序</th><th>chart_id</th><th>图型</th><th>章节</th><th>标题</th><th>LLM 选中理由</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    <p style="font-size:12.5px;color:#64748b;margin:12px 0 4px;">本轮 LLM 主动抑制（未出图、不补位）：</p>
    <ul style="font-size:12.5px;line-height:1.9;">{supp_rows}</ul>
  </section>
"""
    marker = '  <section class="panel">\n    <h3>交付概览</h3>'
    if marker not in html:
        raise RuntimeError("展示页结构变化，无法插入选图结论面板")
    html = html.replace(marker, panel + marker, 1)

    # 内联本地 echarts，保证单文件离线可渲染（不发起任何网络请求）
    tag = '<script src="echarts.min.js"></script>'
    if tag not in html:
        raise RuntimeError("展示页结构变化，无法内联 echarts")
    echarts_js = ECHARTS_PATH.read_text(encoding="utf-8").replace("</script>", "<\\/script>")
    html = html.replace(tag, "<script>\n" + echarts_js + "\n</script>", 1)
    assert 'src="echarts.min.js"' not in html, "echarts 未成功内联"

    OPTIONS_OUT.write_text(
        json.dumps(options, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    HTML_OUT.write_text(html, encoding="utf-8")

    manifest = {
        "stage": "A3_GENERATE_FROM_LLM_SELECTION",
        "input": {
            "a1_dataset": "a17-industry-research-agent/output/a1_five_industry_probe/新能源汽车/runs/run-20261110013520-220857d7/dataset.json",
            "a2_report": "a17-industry-research-agent/output/a2_industry_review/runs/a2-review-220857d7/artifacts/interpretation_report.json",
            "llm_selection": SELECTION_PATH.name,
            "prompt_sha256": record.get("prompt_sha256"),
        },
        "llm": {
            "model": record.get("model"),
            "elapsed_seconds": record.get("elapsed_seconds"),
            "usage": record.get("usage"),
            "rationale": selection.get("rationale"),
        },
        "count_reconciliation": {
            "llm_chart_count": declared_count,
            "llm_charts_array_length": len(chosen),
            "generated_options": len(options),
            "rendered_cards": card_count,
            "rendered_containers": div_count,
            "suppressed_by_llm": len(selection.get("suppressed", [])),
            "consistent": True,
        },
        "generated_charts": generated,
        "outputs": [OPTIONS_OUT.name, HTML_OUT.name, MANIFEST_OUT.name],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[对账] LLM 决定 {declared_count} 张 -> 逐张生成 {len(options)} 张 "
          f"-> 页面卡片 {card_count} 张 / 容器 {div_count} 个：完全一致，不增不减")
    print(f"[输出] {OPTIONS_OUT.name} / {HTML_OUT.name} / {MANIFEST_OUT.name}")


if __name__ == "__main__":
    main()
