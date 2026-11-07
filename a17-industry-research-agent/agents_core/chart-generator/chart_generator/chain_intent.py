"""用户是否**明确需要产业链图**的确定性判断（2026-10-21）。

═════════════════════════════════════════════════════════════════════════════
为什么需要它
═════════════════════════════════════════════════════════════════════════════

当前（改动前）豆包与产业链图的触发条件与用户意图**无关**：

    adapters.py   focus_points 为空时默认注入 ["产业链", ...]
    A1            required_domains 恒等于全部 7 个域（含 industry_chain，LLM 无法移除）
    A3            if web_search_available():  → 只要问财返回了证据就调豆包

结果：用户只问"手机行情/财务"，豆包照样被调用，白吃月度 500 次额度。

用户裁定规则：
  · 未**明确**需要产业链图 → **不出产业链图**，改出别的图（且不调豆包）
  · 明确需要 → 出产业链图，并把用户输入透传给豆包

═════════════════════════════════════════════════════════════════════════════
设计原则
═════════════════════════════════════════════════════════════════════════════

1. **确定性优先**：判断不进 LLM。LLM 判定不可复现、无法回归测试，
   且实测一次调用 28 秒（`build_gap_queries_llm` 已因此默认关闭）。
2. **默认注入不算用户意图**：`focus_points` 走系统默认时不含判断力。
3. **显式开关最高优先**：前端可 100% 覆盖自动判断。
"""

from __future__ import annotations

import os
from typing import Sequence

# ── 关键词表（2026-10-21 扩展）──────────────────────────────────────────────
# 强信号：这些词出现即认为用户明确要看产业链结构。
# （刻意**不含**"环节""全景""生态"这类过宽的词——财务语境里"生产环节""行业全景"
#   很常见，会把只要财务图的用户误判成要产业链图。）
_CHAIN_INTENT_STRONG: tuple[str, ...] = (
    "产业链", "产业链结构", "产业链图谱", "产业链全景", "产业链图",
    "产业图谱", "产业结构", "产业生态",
    "供应链", "供应链结构", "供应链图谱",
    "上中下游", "上下游结构", "价值链",
    "国产化", "国产替代",
    "supply chain", "value chain", "supplychain",
)

# 弱信号：单独命中不足以判定，需要**两个及以上**同时命中。
# 覆盖"帮我梳理一下这个行业有哪些公司"这类口语表达。
_CHAIN_INTENT_WEAK: tuple[str, ...] = (
    "全景图", "图谱", "生态图谱",
    "拆解", "梳理", "有哪些企业", "有哪些公司",
    "供应商", "配套", "龙头名单",
)

_WEAK_THRESHOLD = 2


def user_wants_industry_chain(
    industry: str = "",
    focus_points: Sequence[str] | None = None,
    *,
    explicit: bool | None = None,
    defaulted_focus: bool = False,
    requested_types: Sequence[str] | None = None,
) -> bool:
    """用户是否明确需要产业链图。

    参数
    ----
    industry        用户输入的研究主题（``ResearchRequest.industry``）。
    focus_points    用户**自己填写**的关注点。走系统默认值时传 ``defaulted_focus=True``。
    explicit        前端显式开关，优先级最高（``None`` 表示未指定，走自动判断）。
    defaulted_focus 为 True 时忽略 focus_points——系统默认注入的"产业链"
                    不代表用户意图（``adapters.py`` 的默认值）。
    requested_types 用户显式请求的图表类型；含 ``industry_chain`` 即视为明确要
                    （除显式开关外最强的意图信号）。

    判定顺序：显式开关 → requested_types → 强信号 → 弱信号（≥2 个）。
    """
    if explicit is not None:
        return bool(explicit)
    if requested_types and any(str(t).lower() == "industry_chain" for t in requested_types):
        return True
    # 环境变量兜底：批处理/测试脚本（如 scratch/run_a123.py）无法改前端契约时，
    # 用 CHAIN_INTENT_OVERRIDE=1|0 显式指定。
    _env = str(os.environ.get("CHAIN_INTENT_OVERRIDE", "")).strip().lower()
    if _env in ("1", "true", "yes", "on"):
        return True
    if _env in ("0", "false", "no", "off"):
        return False

    parts = [str(industry or "")]
    if not defaulted_focus:
        parts.extend(str(f) for f in (focus_points or []))
    text = " ".join(parts).lower()

    if any(k in text for k in _CHAIN_INTENT_STRONG):
        return True
    return sum(1 for k in _CHAIN_INTENT_WEAK if k in text) >= _WEAK_THRESHOLD


def intent_keywords() -> tuple[str, ...]:
    """供诊断/文档输出当前生效的关键词表。"""
    return _CHAIN_INTENT_STRONG + _CHAIN_INTENT_WEAK
