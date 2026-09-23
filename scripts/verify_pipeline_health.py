#!/usr/bin/env python3
"""
自动化防回归校验脚本 (Pipeline Health Verifier)
仅依赖 Python 3 标准库，无任何外部额外依赖。

用法:
    python3 scripts/verify_pipeline_health.py --run-id test-silver-01
"""

import argparse
import json
import sys
from pathlib import Path


def verify_run(base_dir: Path, run_id: str) -> bool:
    print(f"==================================================")
    print(f"🚀 开始对运行任务 [{run_id}] 进行全链路防回归健康检查")
    print(f"==================================================")
    
    run_dir = base_dir / "data" / "runs" / run_id
    if not run_dir.exists():
        print(f"❌ 任务目录不存在: {run_dir}")
        return False

    errors: list[str] = []
    warnings: list[str] = []

    # 1. 检查全局状态机 state.json
    state_file = run_dir / "state.json"
    if not state_file.exists():
        errors.append("state.json 不存在")
    else:
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
            status = state_data.get("status")
            print(f"✅ 全局状态机 state.json 读取成功，状态: {status}")
            if status not in ("completed", "waiting_review", "approved", "running"):
                warnings.append(f"全局状态处于非常规状态: {status}")
        except Exception as e:
            errors.append(f"state.json 解析失败: {e}")

    # 2. 检查 5 个阶段的核心 JSON 产物
    art_dir = run_dir / "artifacts"
    expected_jsons = [
        ("dataset.json", 1024 * 100),                # 至少 100KB
        ("interpretation_report.json", 1024 * 50),   # 至少 50KB
        ("chart_result.json", 1024 * 5),             # 至少 5KB
        ("chapter_result.json", 1024 * 50),          # 至少 50KB
    ]

    for fname, min_size in expected_jsons:
        p = art_dir / fname
        if not p.exists():
            errors.append(f"中间产物缺失: {fname}")
        else:
            size = p.stat().st_size
            if size < min_size:
                errors.append(f"产物体积异常过小: {fname} ({size} bytes < {min_size} bytes)")
            else:
                print(f"✅ 核心数据产物完整: {fname} ({size / 1024:.1f} KB)")

    # 3. 检查矢量图表生成质量
    charts_dir = art_dir / "charts"
    if not charts_dir.exists():
        errors.append("图表目录 artifacts/charts 不存在")
    else:
        svg_files = list(charts_dir.glob("*.svg"))
        if not svg_files:
            errors.append("artifacts/charts 中没有找到任何 .svg 矢量图表")
        else:
            print(f"✅ 找到 {len(svg_files)} 个独立 SVG 矢量图表:")
            for svg_file in svg_files:
                content = svg_file.read_text(encoding="utf-8")
                if "图表预览不可用" in content:
                    errors.append(f"图表文件 {svg_file.name} 包含降级占位符 '图表预览不可用'")
                elif not content.strip().startswith("<svg"):
                    errors.append(f"图表文件 {svg_file.name} 不是合法的 SVG 根元素")
                else:
                    print(f"   - {svg_file.name} ({len(content)} 字符, 矢量渲染正常)")

    # 4. 检查最终交付物（HTML, PDF, Markdown）
    deliverables = [
        ("report.md", 1024 * 20),      # 至少 20KB
        ("report.html", 1024 * 100),   # 至少 100KB
        ("report.pdf", 1024 * 500),    # 至少 500KB
    ]

    for fname, min_size in deliverables:
        p = art_dir / fname
        if not p.exists():
            errors.append(f"最终交付物缺失: {fname}")
        else:
            size = p.stat().st_size
            if size < min_size:
                errors.append(f"交付物体积异常: {fname} ({size} bytes < {min_size} bytes)")
            else:
                print(f"✅ 最终交付物合格: {fname} ({size / 1024:.1f} KB)")

    # 5. 关键断言：断言 report.html 中绝无「图表预览不可用」
    html_file = art_dir / "report.html"
    if html_file.exists():
        html_text = html_file.read_text(encoding="utf-8")
        if "图表预览不可用" in html_text:
            errors.append("致命断点：report.html 中仍然残留 '图表预览不可用' 占位文本！")
        else:
            print("✅ 深度内容断言通过：report.html 中 0 个降级占位符，图表全量矢量注入成功！")

        svg_count = html_text.count("<svg")
        if svg_count < 3:
            warnings.append(f"report.html 中的 SVG 图表数量偏少: {svg_count} 个")
        else:
            print(f"✅ report.html 包含 {svg_count} 个内嵌 SVG 矢量图表块")

    print(f"--------------------------------------------------")
    if warnings:
        print(f"⚠️  警告项 ({len(warnings)} 条):")
        for w in warnings:
            print(f"   - {w}")

    if errors:
        print(f"❌ 校验失败！发现 {len(errors)} 个严重问题:")
        for err in errors:
            print(f"   - {err}")
        print(f"==================================================")
        return False
    else:
        print(f"🎉 校验圆满通过！流水线各阶段数据、图表渲染与最终交付物 100% 合规！")
        print(f"==================================================")
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline Health Verifier")
    parser.add_argument("--run-id", default="test-silver-01", help="运行任务ID (例如 test-silver-01)")
    args = parser.parse_args()

    # 工作根目录
    project_root = Path(__file__).resolve().parent.parent
    success = verify_run(project_root, args.run_id)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
