#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report-style-benchmark / scripts/baseline_schema.py

`samples_baseline.json` 的**唯一模式定义**：阈值名 → (样本提取函数, 脚本默认阈值说明)。

## 为什么必须独立成一个模块

生成端（build_baseline.py）与校验端（style_benchmark_audit.py）原本各自持有一份
"阈值名 → 从样本取哪个字段"的隐式知识。一旦两边漂移，就会出现
「生成时按 A 口径写入、校验时按 B 口径复算」的**假通过**。

2026-09-17 的 samples_baseline.json 双份漂移正是这一类事故：

    report-page-composer/scripts/samples_baseline.json
      samples.R*.basic.header_mark_h_mm  = [16.6, 33.4, 27.4, 16.1, 16.6, 16.6]  ← collect_extended.py 全文档扫描口径
      thresholds.HEADER_MARK_H_MM_MIN.real_samples = [9.5, 8.4, 14.0, 16.1, 9.5, 9.5]  ← 手写的 audit p2 单页口径

    同一文件里，samples 与 thresholds 互相矛盾。而当时的自检只看 thresholds 内部
    是否自洽（declared == derived），于是 16 项全 ✓ 却仍然是错的。

因此本模块把提取逻辑收敛成一份，供三方共用：

    * build_baseline.py         —— 生成时用
    * style_benchmark_audit.py  —— baseline_selfcheck 交叉复算时用
    * report-page-composer      —— 经 shim 间接使用

## 纪律（来自 SKILL.md §阈值校准纪律）

1. 每条阈值都必须来自真实样本实测分布，手写值不合法。
2. baseline 里的实测值必须来自**同一个算法**（见 SKILL.md §阈值校准纪律 #3：
   HEADER_MARK_H_MM_MIN 用 audit 的 p2 单页测法，不是全文档扫描法）。
3. 因此 `thresholds_with_baseline[X].real_samples` 必须能由 `samples` 用本模块的
   提取函数**原样复算出来**；不能复算的条目要么补提取函数，要么显式标注 provenance。

纯标准库实现，无第三方依赖。
"""

from __future__ import annotations

# --------------------------------------------------------------- 脚本默认阈值说明
# 与 style_benchmark_audit.py 顶部的常量一一对应，写在这里是为了让 baseline 能自解释
# 「这条阈值的脚本侧取值是多少」。改 audit 常量时必须同步本表。
SCRIPT_DEFAULTS = {
    "TYPE3_FONT_OBJECTS_MAX": "TYPE3_MAX = 0",
    "NAMED_FONT_OBJECTS_MIN": ">=1 by inspection",
    "BODY_SIZE_DISTINCT_AT_LEAST_2PAGES_MAX": "BODY_SIZE_DISTINCT_MAX = 2",
    "CAPTION_SIZE_MINUS_BODY_PT_ABS_MAX": "CAPTION_SIZE_TOL_PT = 0.8",
    "COVER_WHITE_RATIO_MIN": "COVER_WHITE_MIN = 0.50",
    "COVER_LINES_NONEMPTY_MIN": "COVER_LINES_MIN = 50",
    "HEADER_MARK_H_MM_MIN": "HEADER_MARK_MIN_H_MM = 6.0",
    "FOOTER_DIST_MM_MED_MIN": "FOOTER_GAP_MAJOR_MM = 8.5",
    "ACCENT_COLOR_COUNT_MAX": "ACCENT_COUNT_MAX = 2",
}


# --------------------------------------------------------------- 样本提取函数
# 每个函数从**单个样本**的 {"basic": {...}, "extended": {...}} 取出该阈值的实测值。
# 返回 None 表示该样本缺此字段，build_baseline 会跳过它（而不是记 0）。
THRESHOLD_EXTRACTORS = {
    "TYPE3_FONT_OBJECTS_MAX": lambda s: s["basic"].get("type3_font_objects"),
    "NAMED_FONT_OBJECTS_MIN": lambda s: s["basic"].get("named_font_objects"),
    "BODY_SIZE_DISTINCT_AT_LEAST_2PAGES_MAX": lambda s: s["basic"].get("body_size_count_at_least_2pages"),
    "BODY_SIZE_TOP_PT": lambda s: s["basic"].get("body_size_top"),
    "LINEHEIGHT_MED": lambda s: s["basic"].get("lineheight_med"),
    "ACCENT_COLOR_COUNT_MAX": lambda s: len(s["basic"].get("accent_colors_top", [])),
    "FOOTER_DIST_MM_MED_MIN": lambda s: s["basic"].get("footer_dist_mm"),
    "COVER_WHITE_RATIO_MIN": lambda s: s["basic"].get("cover_white_ratio"),
    "COVER_LINES_NONEMPTY_MIN": lambda s: s["basic"].get("cover_lines_nonempty"),
    "COVER_MAX_SIZE_PT_MAX": lambda s: s["basic"].get("cover_max_size_pt"),
    "HEADER_MARK_H_MM_MIN": lambda s: s["basic"].get("header_mark_h_mm"),
    "LEFT_MARGIN_MM_MODE": lambda s: s["basic"].get("left_margin_mm_mode"),
    "BOLD_SHARE_MIN": lambda s: s["extended"].get("bold_char_share"),
    "TOC_LEADER_DOTS_MIN_LINES": lambda s: s["extended"].get("toc_leader_styles", {}).get("dots", 0),
    "CHART_HEIGHT_RATIO_MED": lambda s: s["extended"].get("chart_height_ratio_med"),
    "PARAGRAPH_ALIGN_HAS_LEFT_OR_INDENT": lambda s: (
        s["extended"].get("paragraph_align_dominant") in ("left", "indent")
    ),
}

# 无提取函数、且承认无法由 samples 复算的条目：必须在 baseline 里显式标注
# provenance="manual_inspection"，否则 cross_check 会报 no_extractor。
KNOWN_MANUAL = {
    "CAPTION_SIZE_MINUS_BODY_PT_ABS_MAX": (
        "题注与正文字号偏差需逐页比对题注行，采集脚本尚未固化该字段；"
        "取值来自 audit 侧对 R1–R6 的人工复核（0.0/0.0/0.6/0.0/0.0/0.0），"
        "与 style_benchmark_audit.py 的 CAPTION_SIZE_TOL_PT 注释一致。"
    ),
}


# --------------------------------------------------------------- 口径（caliber）
# baseline 里存在**两套测量实现**，数值不可互换（SKILL.md §阈值校准纪律 #3）：
#
#   collect_metrics.py::analyze_basics()   —— 全量指标采集，写进 samples 块
#   style_benchmark_audit.py::collect()    —— 审计自身的测量，baseline_diff 用它
#
# 因此每条阈值必须声明自己用的是哪一套：
#
#   caliber = "collect_metrics"（默认）—— real_samples 由 samples 复算
#   caliber = "audit_collect"          —— real_samples 由 audit_samples 复算
#
# 为什么必须区分：baseline_diff 拿 audit 口径的实测值去比 baseline 的 min/max。
# 如果那条 min/max 来自 collect_metrics 口径，就是在跨口径比较 —— 2026-09-18
# 发现 COVER_WHITE_RATIO_MIN 正是如此（collect_metrics 口径下界 0.557，
# audit 口径下界 0.5876，前者偏宽松 5%，会放行过淡封面）。
#
# audit_samples 块的取值可由 `style_benchmark_audit.py --verify-samples <样本目录>`
# 从真实 PDF 重新推导（样本 PDF 不在仓库内，故该验证是显式可选步骤）。
CALIBER_COLLECT_METRICS = "collect_metrics"
CALIBER_AUDIT_COLLECT = "audit_collect"

# baseline_diff() 实际消费的 7 个维度 —— 它们必须用 audit 口径。
BASELINE_DIFF_DIMENSIONS = (
    "TYPE3_FONT_OBJECTS_MAX",
    "NAMED_FONT_OBJECTS_MIN",
    "BODY_SIZE_DISTINCT_AT_LEAST_2PAGES_MAX",
    "COVER_WHITE_RATIO_MIN",
    "COVER_LINES_NONEMPTY_MIN",
    "HEADER_MARK_H_MM_MIN",
    "FOOTER_DIST_MM_MED_MIN",
)


def extract_series(samples, extractor):
    """按 samples 的插入顺序（= R1..R6）逐样本取值，None 跳过。

    与 build_baseline.py 的历史行为逐字一致：只跳过 None，不跳过 0/False。
    """
    vals = []
    for s in samples.values():
        try:
            v = extractor(s)
        except Exception:
            v = None
        if v is not None:
            vals.append(v)
    return vals


def derive(baseline):
    """由 baseline["samples"] 复算出 {阈值名: 实测序列}，只含能复算的条目。"""
    samples = baseline.get("samples") or {}
    out = {}
    for name, extractor in THRESHOLD_EXTRACTORS.items():
        if name in samples:
            continue
        vals = extract_series(samples, extractor)
        if vals:
            out[name] = vals
    return out


def cross_check(baseline):
    """交叉复算：thresholds_with_baseline[X].real_samples 是否等于其声明口径下的复算值。

    这是 baseline_selfcheck 的**第二层**，专门堵住 2026-09-17 那类事故：
    thresholds 内部自洽，但与 samples 互相矛盾。

    按 `info["caliber"]` 选择复算来源：
      * "collect_metrics"（默认）—— 用 THRESHOLD_EXTRACTORS 从 `samples` 复算
      * "audit_collect"           —— 从 `audit_samples` 块读取（该块由
        `style_benchmark_audit.py --verify-samples <目录>` 从真实 PDF 推导）

    verdict ∈ pass / mismatch / skip，skip 一定带 reason：
      * no_samples_block       —— baseline 里没有 samples，无法交叉
      * no_audit_samples_block —— 声明了 audit 口径但没有 audit_samples 块
      * no_extractor           —— 该阈值没有提取函数（需在 KNOWN_MANUAL 里登记）
      * no_real_samples        —— thresholds 里没写 real_samples
      * empty_derived          —— 提取函数在全部样本上都返回 None
      * manual_provenance      —— 已显式标注为人工复核，不参与复算
    """
    samples = baseline.get("samples") or {}
    audit_samples = baseline.get("audit_samples") or {}
    tb = baseline.get("thresholds_with_baseline") or {}
    out = {}

    for name, info in tb.items():
        if not isinstance(info, dict):
            out[name] = {"verdict": "skip", "reason": "malformed_entry"}
            continue

        provenance = info.get("provenance")
        if provenance == "manual_inspection":
            out[name] = {
                "verdict": "skip",
                "reason": "manual_provenance",
                "note": info.get("provenance_note") or KNOWN_MANUAL.get(name, ""),
            }
            continue

        declared = info.get("real_samples")
        if not isinstance(declared, list) or not declared:
            out[name] = {"verdict": "skip", "reason": "no_real_samples"}
            continue

        caliber = info.get("caliber") or CALIBER_COLLECT_METRICS

        if caliber == CALIBER_AUDIT_COLLECT:
            if not audit_samples:
                out[name] = {"verdict": "skip", "reason": "no_audit_samples_block"}
                continue
            derived = [audit_samples[n].get(name) for n in sorted(audit_samples)
                       if isinstance(audit_samples[n], dict) and audit_samples[n].get(name) is not None]
            if not derived:
                out[name] = {"verdict": "skip", "reason": "empty_audit_derived"}
                continue
            source = "audit_samples"
        else:
            if not samples:
                out[name] = {"verdict": "skip", "reason": "no_samples_block"}
                continue
            extractor = THRESHOLD_EXTRACTORS.get(name)
            if extractor is None:
                out[name] = {
                    "verdict": "skip",
                    "reason": "no_extractor",
                    "hint": KNOWN_MANUAL.get(name, "请补 THRESHOLD_EXTRACTORS 或标注 provenance=manual_inspection"),
                }
                continue
            derived = extract_series(samples, extractor)
            if not derived:
                out[name] = {"verdict": "skip", "reason": "empty_derived"}
                continue
            source = "samples"

        if derived == declared:
            out[name] = {
                "verdict": "pass",
                "caliber": caliber,
                "source": source,
                "declared": declared,
                "derived": derived,
                "sample_count": len(derived),
            }
        else:
            out[name] = {
                "verdict": "mismatch",
                "caliber": caliber,
                "source": source,
                "declared": declared,
                "derived": derived,
                "declared_range": [min(declared), max(declared)],
                "derived_range": [min(derived), max(derived)],
                "note": "thresholds 与声明口径下的复算值不一致（历史事故：全文档扫描 vs p2 单页）",
            }
    return out
