"""生成智能体3 演示用「构成类」数据。

## 为什么需要这个脚本

现有数据源（`data/runs/*/artifacts/interpretation_report.json`）全部是**时序类**
与**横截面数值类**数据，缺少「各部分占比、合计有意义」的**构成类**数据，因此
`pie`（环形占比图）没有可用的输入 —— 实测六图中其余五种均可由现有数据产出，
唯独 pie 不行。

## 数据合规约定（重要）

本脚本产出的是**演示数据**，与真实证据严格区分，避免污染证据链：

1. `record_id` 统一加 `R-DEMO-` 前缀
2. `metric` 名称后缀「（演示数据）」
3. `skill_id` / `trace_id` 标记为 `demo`
4. 写入**独立目录**，不修改任何原始 run 的数据

因此这类数据不得计入真实证据覆盖率，也不应出现在正式交付物中。

用法：
    python scripts/make_agent3_demo_data.py
"""

from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_RUN = PROJECT_ROOT / "data/runs/run-20260922213739-783/artifacts"
OUTPUT_DIR = PROJECT_ROOT / "output/agent3_demo/source"

DEMO_METRIC = "动力电池装机市占率（演示数据）"
DEMO_PERIOD = "2026-06-30"

# 演示用各主体份额（合计 100%），用于验证环形占比图的构成语义
DEMO_SHARES: list[tuple[str, float]] = [
    ("宁德时代", 36.8),
    ("比亚迪", 15.2),
    ("中创新航", 7.4),
    ("国轩高科", 5.1),
    ("亿纬锂能", 4.6),
    ("欣旺达", 3.2),
    ("其他", 27.7),
]


def build() -> Path:
    """在源报告基础上追加构成类演示数据，写入独立目录。

    Returns:
        产出的 interpretation_report.json 路径。

    Raises:
        FileNotFoundError: 源报告不存在。
    """
    source_file = SOURCE_RUN / "interpretation_report.json"
    if not source_file.is_file():
        raise FileNotFoundError(f"源报告不存在：{source_file}")

    report = json.loads(source_file.read_text(encoding="utf-8"))

    evidence_index: dict[str, dict[str, object]] = report.setdefault("evidence_index", {})
    demo_ids: list[str] = []
    for idx, (entity, share) in enumerate(DEMO_SHARES, 1):
        record_id = f"R-DEMO-SHARE-{idx:02d}"
        demo_ids.append(record_id)
        evidence_index[record_id] = {
            "record_id": record_id,
            "domain": "industry",
            "entity": entity,
            "metric": DEMO_METRIC,
            "value": share,
            "unit": "%",
            "period": DEMO_PERIOD,
            "skill_id": "demo",
            "trace_id": "demo",
        }

    top = DEMO_SHARES[0]
    report.setdefault("insights", []).append(
        {
            "insight_id": "I-DEMO-SHARE",
            "title": "动力电池装机份额构成（演示数据）",
            "conclusion": (
                f"{top[0]}以 {top[1]}% 的装机份额居首，"
                f"前六家合计约 {sum(v for _, v in DEMO_SHARES[:-1]):.1f}%，"
                "其余主体占 27.7%，行业集中度较高。"
            ),
            "significance": "用于验证环形占比图（pie）的构成语义与渲染能力，非真实结论。",
            "confidence": "high",
            "evidence_record_ids": demo_ids,
        }
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUTPUT_DIR / "interpretation_report.json"
    out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_file


if __name__ == "__main__":
    path = build()
    total = sum(v for _, v in DEMO_SHARES)
    print(f"已生成演示数据源：{path}")
    print(f"  构成类记录 {len(DEMO_SHARES)} 条，份额合计 {total:.1f}%")
    print(f"  记录 ID 前缀 R-DEMO-SHARE-*，指标名含「（演示数据）」")
