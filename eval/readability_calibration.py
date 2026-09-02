"""评审器校准跑批脚本（红蓝对抗方案 §7 阶段二交付物）。

一键执行：
    cd 项目根
    backend/.venv/bin/python -m eval.readability_calibration --round R0

功能：
  1. 加载回归库（19 正例 + 16 负例，人工策展真值）与独立考卷
     （eval/calibration/exam_set_v1.json，proposed_label 仅为建议标签）；
  2. 对每个样本跑 ReadabilityLinter（确定性）+ judge 软分；
  3. 按方案 §4.2 五项门禁出判定；考卷上画阈值曲线（L3 杠杆）；
  4. 落盘 JSON 报告 + 控制台摘要。

judge 分数来源（默认）：eval/calibration/surrogate_scores_v1.json
——人工代打评审器（与线上 judge 同款模型的代理评分），零真实模型调用。
--judge real 切换为真实 LLM_JUDGE_MODEL（仅运营期换模型回归时使用）。
红蓝对抗轮次用 --redteam 追加对抗样本文件（JSON 数组，同回归库字段）。

防作弊（§6）：考卷 proposed_label 不参与真值门禁；真值仅回归库 35 条；
校准集标注样本永不进入 judge few-shot（few-shot 为合成示例）。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.agents.chapter_writer.readability_linter import lint_paragraph  # noqa: E402

REGRESSION_SAMPLES_PATH = BACKEND / "tests/agents/chapter_writer/redteam_readability_samples.py"
EXAM_PATH = ROOT / "eval/calibration/exam_set_v1.json"
SURROGATE_PATH = ROOT / "eval/calibration/surrogate_scores_v1.json"
REPORT_DIR = ROOT / "eval/calibration/reports"

THRESHOLD = 0.6
THRESHOLD_CURVE = (0.50, 0.55, 0.60, 0.65, 0.70)


def load_regression() -> tuple[list[dict], list[dict]]:
    spec = importlib.util.spec_from_file_location("redteam_samples", REGRESSION_SAMPLES_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return list(module.NEGATIVE_SAMPLES), list(module.POSITIVE_SAMPLES)


def load_surrogate_scores() -> dict[str, float]:
    bundle = json.loads(SURROGATE_PATH.read_text(encoding="utf-8"))
    return {sample_id: item["score"] for sample_id, item in bundle["scores"].items()}


def cohen_kappa_binary(pairs: list[tuple[bool, bool]]) -> float:
    """Cohen's kappa（二分类）。真值-判分一致率的机遇校正。"""

    n = len(pairs)
    if n == 0:
        return float("nan")
    po = sum(1 for a, b in pairs if a == b) / n
    p_a1 = sum(1 for a, _ in pairs if a) / n
    p_b1 = sum(1 for _, b in pairs if b) / n
    pe = p_a1 * p_b1 + (1 - p_a1) * (1 - p_b1)
    if pe == 1.0:
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / (1 - pe)


def judge_score_for(sample_id: str, text: str, kind: str, *, real_judge, surrogate: dict[str, float]) -> float:
    if real_judge is not None:
        import asyncio

        report = asyncio.run(real_judge.review_paragraph(paragraph_text=text, kind=kind))
        return float(report.score)
    if sample_id in surrogate:
        return surrogate[sample_id]
    raise KeyError(f"样本 {sample_id} 无代打分值（--judge real 或补 surrogate_scores）")


def run(args: argparse.Namespace) -> int:
    negatives, positives = load_regression()
    surrogate = load_surrogate_scores()
    exam = json.loads(EXAM_PATH.read_text(encoding="utf-8"))

    adversarial: list[dict] = []
    if args.redteam:
        adversarial = json.loads(Path(args.redteam).read_text(encoding="utf-8"))

    real_judge = None
    if args.judge == "real":
        from app.core.config import settings
        from app.integrations.llm.factory import create_readability_model

        real_judge = create_readability_model(settings)
        print("[calibration] judge=real（真实模型回归模式，消耗配额）")
    else:
        print("[calibration] judge=surrogate（人工代打评分，零模型调用）")

    # ---- G1：Linter 对确定性类负样本抓取率（必须 100%）----
    deterministic_negatives = [s for s in negatives if s.get("linter_expected")]
    g1_hits, g1_detail = 0, []
    for sample in deterministic_negatives:
        findings = lint_paragraph(sample["text"])
        hit = any(f.rule_id == sample["linter_expected"] for f in findings)
        g1_hits += int(hit)
        if not hit:
            g1_detail.append(sample["id"])
    g1_rate = g1_hits / len(deterministic_negatives) if deterministic_negatives else 1.0

    # ---- G2：judge 对软判负样本（②③类）score<阈值 占比（≥90%）----
    soft_negatives = [s for s in negatives if not s.get("linter_expected")] + adversarial
    g2_caught, g2_detail = 0, []
    for sample in soft_negatives:
        score = judge_score_for(sample["id"], sample["text"], "analysis", real_judge=real_judge, surrogate=surrogate)
        if score < THRESHOLD:
            g2_caught += 1
        else:
            g2_detail.append({"id": sample["id"], "score": score})
    g2_rate = g2_caught / len(soft_negatives) if soft_negatives else 1.0

    # ---- G3：judge 对正样本 score≥阈值 占比（≥95%）与均分（≥0.75）----
    pos_scores = [
        judge_score_for(s["id"], s["text"], "analysis", real_judge=real_judge, surrogate=surrogate)
        for s in positives
    ]
    g3_pass_rate = sum(1 for s in pos_scores if s >= THRESHOLD) / len(pos_scores)
    g3_mean = sum(pos_scores) / len(pos_scores)

    # ---- G4：judge-真值一致率 Cohen's kappa（回归库二分类：≥阈值=可读）----
    pairs: list[tuple[bool, bool]] = []
    for s in positives:
        score = judge_score_for(s["id"], s["text"], "analysis", real_judge=real_judge, surrogate=surrogate)
        pairs.append((True, score >= THRESHOLD))
    for s in negatives:
        score = judge_score_for(s["id"], s["text"], "analysis", real_judge=real_judge, surrogate=surrogate)
        pairs.append((False, score >= THRESHOLD))
    kappa = cohen_kappa_binary(pairs)
    agreement = sum(1 for a, b in pairs if a == b) / len(pairs)

    # ---- G5：误杀率（正样本被判低于阈值，<5%）----
    false_kills = sum(1 for s in pos_scores if s < THRESHOLD)
    g5_rate = false_kills / len(pos_scores)

    # ---- 考卷：阈值曲线与分布（proposed 标签，仅供参考，非真值门禁）----
    curve = {}
    exam_scores = []
    for e in exam:
        score = judge_score_for(e["sample_id"], e["text"], "analysis", real_judge=real_judge, surrogate=surrogate)
        exam_scores.append((e["sample_id"], score, e.get("proposed_label")))
    for t in THRESHOLD_CURVE:
        agree = sum(
            1
            for _, score, label in exam_scores
            if label is not None
            and ((score >= t) == (label == "readable"))
        )
        labeled = sum(1 for _, _, label in exam_scores if label is not None)
        curve[str(t)] = round(agree / labeled, 4) if labeled else None

    gates = {
        "G1_linter_确定性负样本抓取率": {"value": round(g1_rate, 4), "gate": "==1.0", "passed": g1_rate == 1.0, "misses": g1_detail},
        "G2_judge_软判负样本低于阈值占比": {"value": round(g2_rate, 4), "gate": ">=0.90", "passed": g2_rate >= 0.90, "escapes": g2_detail, "n": len(soft_negatives)},
        "G3_judge_正样本达标率": {"value": round(g3_pass_rate, 4), "gate": ">=0.95", "passed": g3_pass_rate >= 0.95, "mean": round(g3_mean, 4), "mean_gate": ">=0.75", "mean_passed": g3_mean >= 0.75},
        "G4_kappa_一致率": {"value": round(kappa, 4), "gate": ">=0.9优 / 0.8-0.9观察 / <0.8触发仲裁", "passed": kappa >= 0.8, "raw_agreement": round(agreement, 4)},
        "G5_误杀率": {"value": round(g5_rate, 4), "gate": "<0.05", "passed": g5_rate < 0.05, "false_kills": false_kills},
    }
    all_passed = all(
        g["passed"] for g in gates.values()
    ) and gates["G3_judge_正样本达标率"]["mean_passed"]

    report = {
        "round": args.round,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "judge_mode": "real" if real_judge else "surrogate",
        "threshold": THRESHOLD,
        "samples": {
            "regression_positive": len(positives),
            "regression_negative": len(negatives),
            "adversarial": len(adversarial),
            "exam": len(exam),
        },
        "gates": gates,
        "all_gates_passed": all_passed,
        "exam_threshold_curve_readable_vs_rest": curve,
        "exam_score_distribution": {
            "min": round(min(s for _, s, _ in exam_scores), 3),
            "median": round(sorted(s for _, s, _ in exam_scores)[len(exam_scores) // 2], 3),
            "max": round(max(s for _, s, _ in exam_scores), 3),
            "below_threshold": sum(1 for _, s, _ in exam_scores if s < THRESHOLD),
        },
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / f"calibration_{args.round}_{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n===== 校准跑批 [{args.round}] 门禁结果 =====")
    for name, g in gates.items():
        mark = "✅" if g["passed"] else "❌"
        extra = f" misses={g['misses']}" if g.get("misses") else (f" escapes={g['escapes']}" if g.get("escapes") else "")
        print(f"{mark} {name}: {g['value']} （门禁 {g['gate']}）{extra}")
    print(f"{'✅' if gates['G3_judge_正样本达标率']['mean_passed'] else '❌'} G3b 正样本均分: {round(g3_mean, 4)} （门禁 >=0.75）")
    print(f"\n考卷阈值曲线（readable vs 其余，proposed 标签，仅参考）: {curve}")
    print(f"综合门禁: {'全部达标 🎉' if all_passed else '存在未达标项 ⚠️'}")
    print(f"报告: {out_path}")
    return 0 if all_passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="评审器校准跑批（红蓝对抗方案 §7）")
    parser.add_argument("--round", default="R0", help="轮次标识（R0 基线 / R1 红攻 / R2 蓝防 / FINAL）")
    parser.add_argument("--redteam", default=None, help="对抗样本 JSON 文件路径（R1/R2 轮次使用）")
    parser.add_argument("--judge", choices=["surrogate", "real"], default="surrogate", help="judge 分数来源")
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
