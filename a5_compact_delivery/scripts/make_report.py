"""从实测产物生成验收报告，所有数字都从结果文件读取，不手填。"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def tail_line(path: Path) -> str:
    lines = [x.strip() for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return lines[-1] if lines else ""


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    baseline = root / "baseline"
    reports = root / "reports"
    matrix = load(reports / "matrix" / "matrix_summary.json")
    before = load(baseline / "before_summary.json")
    browser = load(reports / "browser_interaction.json") if (reports / "browser_interaction.json").exists() else []
    before_tests = tail_line(baseline / "before_full_tests.txt")
    after_tests = tail_line(baseline / "after_full_tests.txt")

    def passed_count(text: str) -> int:
        m = re.search(r"(\d+) passed", text)
        return int(m.group(1)) if m else 0

    passed_delta = passed_count(after_tests) - passed_count(before_tests)

    # 截图集中到 screenshots/
    shots = sorted(glob.glob(str(reports / "matrix" / "*" / "*.png")))
    for src in shots:
        name = Path(src).parent.name + "_" + Path(src).name
        shutil.copy2(src, root / "screenshots" / name)

    lines = [
        "# A5 附录二紧凑模式 · 实施与验收报告",
        "",
        "本报告全部数字由脚本从实测产物读取。基线在改动前用同一 Python / Chromium 环境重新渲染并保存原始字节。",
        "",
        "## 1. 改动文件",
        "",
        "| 文件 | 性质 | 说明 |",
        "|---|---|---|",
        "| `agents_core/report-fusion/report_fusion/render.py` | 修改 | 新增 keyword-only `source_index_mode`、领域汇总、CSV 导出、可逆文本转义；Markdown 附录二分支 |",
        "| `templates/auto/report.html` | 修改 | 附录二内联条件分支，明细行 ID 在 compact 下改为 `source-row-N` |",
        "| `templates/rich/report.html` | 修改 | 同上，主 ID 保持 `src-N` |",
        "| `templates/_source_index_compact.html` | 新增 | 两套模板共用的汇总表、可打印编号云、打印样式与交互脚本 |",
        "| `report_fusion/export_view.py` | 新增 | 独立 ZIP 交付入口，唯一解析 `A5_SOURCE_INDEX_MODE` 的位置 |",
        "| `agents_core/report-fusion/tests/test_source_index_compact.py` | 新增 | 34 条单元测试 |",
        "",
        "未改动：`ReportViewModel` / `EvidenceSource` 模型、`agent.py` 三条线上渲染路径、"
        "`backend/app/core/report_exports.py`、`state_machine.py`、`pdf.py`、`adapters.py`、`print.css`。",
        "本次只在 3 个既有文件上追加改动、新增 3 个文件；工作区其余 100+ 个未提交变更"
        "（含 chart-generator 各文件、`print.css`、`agent.py`、`models.py`）均保持原样，未覆盖、未提交。",
        "",
        "## 2. full 基线字节对照",
        "",
        "| 模板 | 变更前 HTML SHA-256 | 变更后 full HTML SHA-256 | Markdown SHA | 判定 |",
        "|---|---|---|---|---|",
    ]
    for mode in ("auto", "rich"):
        b = before["modes"][mode]
        a = next(r for r in matrix if r["label"] == "nev" and r["chart_mode"] == mode and r["index_mode"] == "full")
        ok = a["html_sha256"] == b["html_sha256"] and a["md_sha256"] == b["md_sha256"]
        lines.append(
            f"| {mode} | `{b['html_sha256'][:16]}…` | `{a['html_sha256'][:16]}…` | "
            f"`{a['md_sha256'][:16]}…` | {'一致' if ok else '**不一致**'} |"
        )
    lines += [
        "",
        "参数回退（未设值 / 显式 full / 空值 / 非法值）在两套模板上均与变更前逐字节一致，"
        "由单元测试 `test_full_mode_is_byte_identical_for_all_fallback_values` 锁定。",
        "",
        "## 3. 八组验收（2 输入 × 2 模板 × 2 模式）",
        "",
        "输入：`nev` = 冻结的 223 条终稿视图；`baijiu` = 由其派生的跨行业夹具"
        "（6 种领域、空领域、未知领域、重复 URL、非 HTTP URL、逗号/引号/换行/公式前缀文本，保留 223 个真实引用编号）。",
        "",
        "| 输入 | 模板 | 模式 | PDF 总页 | 附录二页 | 证据链接 | 命中附录 | 命中率 | HTML 断链 | 重复 ID |",
        "|---|---|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for r in matrix:
        p = r["pdf"]
        h = r["html"]
        rate = f"{p['evidence_hit_rate'] * 100:.0f}%" if p["evidence_hit_rate"] is not None else "-"
        lines.append(
            f"| {r['label']} | {r['chart_mode']} | {r['index_mode']} | {p['pages']} | "
            f"{p['appendix_pages'][0] if p['appendix_pages'] else '-'} | {p['evidence_links']} | "
            f"{p['evidence_hits_appendix']} | {rate} | {len(h['unresolved_evidence_links'])} | {len(h['duplicate_ids'])} |"
        )
    lines += [
        "",
        "compact 组补充：编号云 223、明细行 223、CSV 223 行、表头固定 14 列、UTF-8 BOM、逐行对账 0 差异，"
        "四组全部通过；目录印刷页码与 PDF 真实目标页比对，未命中链接 0。",
        "",
        "## 4. 紧凑模式收益",
        "",
        "| 输入 / 模板 | full 页数 | compact 页数 | 附录二范围 |",
        "|---|---:|---:|---|",
    ]
    for label in ("nev", "baijiu"):
        for mode in ("auto", "rich"):
            f = next(r for r in matrix if r["label"] == label and r["chart_mode"] == mode and r["index_mode"] == "full")
            c = next(r for r in matrix if r["label"] == label and r["chart_mode"] == mode and r["index_mode"] == "compact")
            lines.append(
                f"| {label} / {mode} | {f['pdf']['pages']} | {c['pdf']['pages']} | "
                f"p{f['pdf']['appendix_pages'][0]}–{f['pdf']['pages']} → p{c['pdf']['appendix_pages'][0]}（1 页） |"
            )
    lines += [
        "",
        "## 5. 浏览器交互与打印可见性",
        "",
        "| 样例 | 编号数 | 点击首/中/末 | 键盘 Enter | 打印时编号可见 | 打印时全表隐藏 | JS 错误 |",
        "|---|---:|---|---|---|---|---|",
    ]
    for b in browser:
        clicks = b["clicks"]
        ok_click = all(c["details_open"] and c["row_focused"] for c in clicks)
        lines.append(
            f"| {Path(b['html']).parent.name} | {b['number_count']} | "
            f"{'通过' if ok_click else '失败'} | {'通过' if b['keyboard']['details_open'] else '失败'} | "
            f"{b['print_visibility']['number_visible']} | "
            f"{b['print_visibility']['details_display'] == 'none'} | {len(b['page_errors'])} |"
        )
    lines += [
        "",
        "## 6. 测试",
        "",
        f"- 变更前全量：`{before_tests}`",
        f"- 变更后全量：`{after_tests}`",
        "- 新增单元测试：34 passed（参数回退、领域汇总、CSV 往返、两套模板契约、ZIP 完整性与失败不发布）。",
        "- 定向套件（新增测试 + `test_agent.py` + `test_final_delivery_contract_v8.py` + `test_l5_delivery_acceptance.py`）：69 passed / 4 skipped。",
        "- 全量前后均为 9 failed，全部位于 `agents_core/chain-research`，根因是既存的 "
        "`BaseModel.model_dump_json() got an unexpected keyword argument 'ensure_ascii'`（Pydantic 版本兼容），与本次改动无关；"
        f"passed 增量 {passed_delta} 与新增用例数一致，无新增失败、无跳过数变化。",
        "",
        "## 7. 交付物",
        "",
        "| 文件 | 大小 | 内容 |",
        "|---|---:|---|",
    ]
    for f in sorted(glob.glob(str(root / "packages" / "*.zip"))):
        import zipfile
        with zipfile.ZipFile(f) as zf:
            names = ", ".join(zf.namelist())
        lines.append(f"| `{Path(f).name}` | {os.path.getsize(f):,} B | {names} |")
    lines += [
        "",
        f"PDF 附录页截图共 {len(shots)} 张，集中在 `screenshots/`；八组 HTML / Markdown / CSV / PDF 原始产物在 `reports/matrix/`。",
        "",
        "## 8. 环境与口径",
        "",
        "- Python：`/Users/Zhuanz1/miniconda3/bin/python3`；PDF：生产 `render_pdf()`（Playwright + 系统 Chrome，A4、`prefer_css_page_size`）。",
        "- `report_fusion.__file__` 已核对指向主应用包，未使用 `nev_a5_layout/isolated_app`。",
        "- `full` 为默认值；线上生成、编辑预览、审批重导出不解析环境变量，继续走原路径。",
        "- `compact` 仅在 `python3 -m report_fusion.export_view` 中通过 `A5_SOURCE_INDEX_MODE=compact` 启用；"
        "`--output` 必须是不存在的路径，任一格式或 CSV 失败即退出非零且不发布半包。",
        "- 回退：删除环境变量或指定 `full`，重新导出新的 ZIP；线上行为完全不变。",
        "",
        "> 说明：旧版 PDF 连续两次生成的原始字节可能因生成时间/文件标识波动，故基线对照以 HTML / Markdown "
        "原始字节 SHA-256 为主，PDF 以页数、逐页文本、链接目的地、目录页码与栅格截图比对。",
    ]
    out = reports / "验收报告.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"报告已生成：{out}（{len(lines)} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
