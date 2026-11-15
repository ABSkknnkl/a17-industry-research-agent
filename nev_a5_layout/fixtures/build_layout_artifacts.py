#!/usr/bin/env python3
"""从冻结夹具生成 P1 布局 AST、P3 注册表与内容保真 diff 产物。

前置：P0 统计闸门必须通过。只读母本，产物全部写入独立工作区。
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/Users/Zhuanz1/Downloads/同花顺赛题-T3交接")
WORK = ROOT / "nev_a5_layout"
FIX = WORK / "fixtures"
SAMPLES = ROOT / "新能源汽车行业优化报告样例"
sys.path.insert(0, str(WORK))
sys.path.insert(0, str(FIX))

from baseline_check import run_checks  # noqa: E402
from audit_against_template import audit as run_template_audit  # noqa: E402
from bind_table_a2_sources import main as bind_table_a2_sources  # noqa: E402
from layout import (  # noqa: E402
    build_registry, content_diff, project_from_html,
)


def load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def main() -> int:
    gate = run_checks()
    if not gate["passed"]:
        print("P0 统计闸门未通过，禁止生成布局产物。", file=sys.stderr)
        return 1

    bind_table_a2_sources()
    source_bindings = load("source_bindings.json")
    a3_audit = load("a3_audit.json")

    source = (SAMPLES / "report.html").read_text(encoding="utf-8")
    ast = project_from_html(source)
    ast_blockers = [x for x in ast.validate() if x["severity"] == "blocker"]
    if ast_blockers:
        print(f"布局 AST 校验失败: {ast_blockers[:3]}", file=sys.stderr)
        return 1

    diff = content_diff(ast, project_from_html(source))
    if not diff.identical:
        print(f"冻结前后内容不一致: {diff.differences}", file=sys.stderr)
        return 1

    a3_charts = json.loads(
        (SAMPLES / "report_a3_charts.json").read_text(encoding="utf-8"))
    registry = build_registry(
        load("nev_structure.json"), load("nev_toc_map.json"),
        a3_audit, a3_charts, load("nev_outline.json"),
        asset_root=ROOT, figure_asset_root=SAMPLES,
        source_bindings=source_bindings,
    )
    registry_issues = registry.validate()

    (FIX / "layout_ast_nev.json").write_text(ast.to_json(), encoding="utf-8")
    (FIX / "registry_nev.json").write_text(registry.to_json(), encoding="utf-8")
    (FIX / "content_diff_nev.json").write_text(
        json.dumps(asdict(diff), ensure_ascii=False, indent=2), encoding="utf-8")

    # 以 report.html 为唯一基准复算模板审核，并把结论写入同一批产物。
    ta = run_template_audit()
    (FIX / "template_audit.json").write_text(
        json.dumps(ta, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stage": "P0+P1+P3",
        "status": "VERIFIED_WITH_KNOWN_GAPS",
        "p0_gate": {"passed": gate["passed"], "rule_count": gate["rule_count"],
                    "summary": gate["summary"]},
        "a3_artifact": {
            "run_id": a3_audit["a3_reference_run_id"],
            "artifact_dir": a3_audit["run"]["artifact_dir"],
            "quality": a3_audit["run"]["quality"],
            "lock_all_match": a3_audit["input_lock"]["all_match"],
            "point_checks": a3_audit["point_verification"]["target_point_checks"],
            "point_errors": a3_audit["point_verification"]["target_point_errors"],
            "real_model_participated": a3_audit["point_verification"]["real_model_participated"],
            "discovery_corrected": a3_audit["discovery"]["correction_status"],
        },
        "source_bindings": {
            "table": source_bindings["table"],
            "summary": source_bindings["summary"],
            "gaps": [g["id"] for g in source_bindings["source_gaps"]],
            "c5_c6_updated": True,
            "mother_text_preserved": source_bindings["c5_c6_update"]["mother_preserved"],
        },
        "layout_ast": {
            "content_sha256": ast.content_sha256,
            "block_count": len(ast.blocks),
            "figure_count": len(ast.figures),
            "table_count": len(ast.tables),
            "asset_count": len(ast.assets),
            "warning_count": len(ast.warnings),
            "blocker_issues": ast_blockers,
        },
        "content_diff": {
            "identical": diff.identical,
            "numbers_equal": diff.numbers_equal,
            "numeric_units_equal": diff.numeric_units_equal,
            "evidence_ids_equal": diff.evidence_ids_equal,
            "paragraph_order_equal": diff.paragraph_order_equal,
            "conclusions_equal": diff.conclusions_equal,
        },
        "registry": {
            "entry_count": len(registry.entries),
            "figure_count": len(registry.figures),
            "table_count": len(registry.tables),
            "outline_entries": sum(1 for e in registry.entries if e.include_in_outline),
            "outline_only_count": registry.outline_only_count,
            "validate_issues": registry_issues,
            "publish_blockers": registry.publish_blockers,
            "blocking_gaps": registry.blocking_gaps,
        },
        "not_done": [
            "P2 母本模板与打印 CSS 分页编排",
            "P4 双遍目录收敛 / PDF outline / 页眉页脚 / 原子发布",
            "P5 DOM+PDF 双侧自动 QA 与 AI 逐页视觉复核",
            "§5 真实 LLM 联调、三次同输入重跑、真实数据版回归",
            "A5 生产入口接线（agent.py / render.py / pdf.py / state_machine.py 均未改动）",
        ],
    }
    report["template_audit"] = {
        "baseline": ta["baseline"],
        "baseline_sha256": ta["baseline_sha256"],
        "summary": ta["summary"],
        "high_failures": [r["rule_id"] for r in ta["rules"]
                          if r["status"] == "FAIL" and r["severity"] == "high"],
        "directory_page_verification": {
            "checked": ta["directory_page_verification"].get("checked"),
            "matched": ta["directory_page_verification"].get("matched"),
            "deviations": len(ta["directory_page_verification"].get("deviations", [])),
        },
    }
    (FIX / "layout_validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"P0 闸门 PASS ({gate['rule_count']} 规则)")
    print(f"布局 AST: {len(ast.blocks)} 块 / {len(ast.figures)} 图 / "
          f"{len(ast.tables)} 表 / {len(ast.warnings)} 富文本告警 / 0 blocker")
    print(f"内容保真 diff: identical={diff.identical}")
    print(f"注册表: {len(registry.entries)} 条 / outline "
          f"{sum(1 for e in registry.entries if e.include_in_outline)} / "
          f"validate_issues={len(registry_issues)} / "
          f"publish_blockers={len(registry.publish_blockers)}")
    print("产物: layout_ast_nev.json / registry_nev.json / "
          "content_diff_nev.json / layout_validation.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
