#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report-style-benchmark / scripts/text_rules.py —— SHIM（转发壳）

词表的**唯一来源**已收敛到：

    skills/report-page-composer/scripts/text_rules.py

本文件只做一件事：按文件路径加载真源并**原样再导出**其符号。
`style_benchmark_audit.py` 仍然 `from text_rules import MACHINE_FIELD_MAP,
PIPELINE_PHRASE_RES`，不需要任何改动。

## 为什么必须收敛（2026-09-18 事故）

收敛前这里是一份"精简自 report-page-composer/text_rules.py"的副本，
靠模块注释里一句「上游更新时同步本文件」维系。它比真源多一条
`report-style-benchmark` 映射，少掉全部 `sanitize_public` 逻辑；
而后端 `html.py` 又持有第三份措辞不同的词表。

结果是：**渲染器清掉的东西审计不知道，审计检查的东西渲染器不清**。
最直接的后果是交付 PDF 里残留了 `competition · partial` 这类内部状态码
与 81 处 3 位以上小数 —— 三者都没接上 `STATUS_CODE_MAP` 与精度规则，
而审计只查 `MACHINE_FIELD_MAP` + `PIPELINE_PHRASE_RES`，查不到。

现在本文件是转发壳，副本已删除，结构上不可能再漂移。

## 加载失败时的行为

真源缺失时抛 `ImportError`。调用方（`style_benchmark_audit.py`）已经用
try/except 兜底为空表 —— 审计会退化为"不检查内部语言"，但不会崩。
这不是理想状态，所以 `RULES_FINGERPRINT` 同时导出，供一致性校验报警。
"""

from __future__ import annotations

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REAL_REL = os.path.join("..", "..", "report-page-composer", "scripts")
_MODULE_NAME = "_canonical_text_rules"


def _resolve_real_dir():
    """返回真源 scripts 目录；找不到返回 None。"""
    candidates = []
    env = os.environ.get("REPORT_PAGE_COMPOSER_SCRIPTS")
    if env:
        candidates.append(os.path.abspath(env))
    candidates.append(os.path.normpath(os.path.join(_HERE, _REAL_REL)))
    for candidate in candidates:
        if os.path.isfile(os.path.join(candidate, "text_rules.py")):
            return candidate
    return None


def _load():
    real_dir = _resolve_real_dir()
    if real_dir is None:
        raise ImportError(
            "找不到 text_rules.py 的真源。期望位置："
            + os.path.normpath(os.path.join(_HERE, _REAL_REL))
            + "；可用环境变量 REPORT_PAGE_COMPOSER_SCRIPTS 覆盖。"
        )
    path = os.path.join(real_dir, "text_rules.py")
    # 真源内部有 `sys.path` 无关的纯标准库依赖，直接按路径加载即可。
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 text_rules 真源：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_real = _load()

# ---- 原样再导出（保持与真源同名同义）----------------------------------------
MACHINE_FIELD_MAP = _real.MACHINE_FIELD_MAP
PIPELINE_PHRASE_RES = _real.PIPELINE_PHRASE_RES
PROSE_RULES = _real.PROSE_RULES
STATUS_CODE_MAP = _real.STATUS_CODE_MAP
STATUS_CHAIN_RE = _real.STATUS_CHAIN_RE
FILLER_RES = _real.FILLER_RES
BARE_CODE_RE = _real.BARE_CODE_RE
PAREN_CODE_RE = _real.PAREN_CODE_RE
HIGH_PRECISION_PCT_RE = _real.HIGH_PRECISION_PCT_RE
YUAN_AMOUNT_RE = _real.YUAN_AMOUNT_RE
BIG_BARE_NUMBER_RE = _real.BIG_BARE_NUMBER_RE
DECIMALS_3PLUS_RE = _real.DECIMALS_3PLUS_RE
RULES_FINGERPRINT = _real.RULES_FINGERPRINT

humanize_status = _real.humanize_status
sanitize_public = _real.sanitize_public
is_filler = _real.is_filler
filler_pattern_index = _real.filler_pattern_index
normalize_text = _real.normalize_text
shingles = _real.shingles
similarity = _real.similarity

__all__ = list(getattr(_real, "__all__", []))
