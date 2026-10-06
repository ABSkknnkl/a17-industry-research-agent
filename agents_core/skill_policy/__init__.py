"""技能选择融合器：把「模型自主选择」与「确定性路由」的结果按并集合并。

## 为什么要有这个模块

五个智能体各自有一份确定性技能路由（`skillhub.select`），它基于技能元数据
（`domains` / `keywords` / `chapters` / `always`）打分，能保证「该用的技能不漏」；
而大模型的自主判断能发现规则没覆盖到的场景（例如报告里出现了冷门分析视角）。

在此之前，两者的关系是**互斥替代**：模型可用就用模型的，模型不可用或失败才回落到
确定性路由。这等于每次运行都丢掉另一半信息——模型漏选的技能没人补，规则能识别但
模型没想到的组合也进不来。

本模块把两者合并为**并集**：模型选的保留，规则认为该有的补齐。

## 合并优先级

1. 强制技能（`always=True`）—— 无论来自哪一侧，必留
2. 模型选中的技能 —— 保持模型给出的顺序
3. 确定性路由补充的技能 —— 追加在末尾

去重按技能名进行；超过 `limit` 时从末尾截断，并在结果里记录被截断的名称。

## provenance 的用途

合并结果会标注每个技能的来源（`model` / `policy` / `both`），并单列出
「模型漏选、被规则补上」的技能清单。这不是调试信息，而是可观测数据：
一轮真实运行下来，可以统计出模型漏选率，作为提示词与规则各自的改进依据。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

# 来源标注取值
SOURCE_MODEL = "model"
SOURCE_POLICY = "policy"
SOURCE_BOTH = "both"

# --- 补入准入 ---------------------------------------------------------------
# 实测教训：某次运行里用户只问了「市场规模、增速」，规则却补进了 ESG 风险技能，
# 其产出最终没有进入报告——技能本身有用，但与本次意图无关，属于白付执行成本。
# 因此把「规则补入」分成两类：
#   1) 通用技能：任何研报都用，无条件补入；
#   2) 条件技能：只在用户意图里出现对应信号时才补入（如 ESG 只在问到环境/治理时才有意义）。

# 显式声明为通用的技能（即便 requires_signal 为真也照常补入）。
# 这类是经实测确认「任何研报都绕不开」的分析维度。
UNIVERSAL_SKILL_NAMES: frozenset[str] = frozenset({
    "financial-statement-analysis",   # 财报分析：所有研报都要看财务
    "tech-hype-vs-fundamentals",      # 估值与基本面对比：估值是研报通用语言
    "quantitative-validation",        # 量化校验：数字可信度的基础
})

# 条件技能允许的额外触发信号（补充技能元数据里的 keywords）。
# 命中这些词即视为「用户确实关心这个维度」，允许补入。
CONDITIONAL_EXTRA_SIGNALS: dict[str, tuple[str, ...]] = {
    "esg-risk-analysis": ("ESG", "环境", "社会责任", "治理", "碳", "排放", "能耗", "可持续", "绿色"),
    "geopolitical-risk-analysis": ("地缘", "关税", "制裁", "出口管制", "脱钩", "供应链", "国产替代", "贸易战", "出海"),
}

# 未在字典中登记的条件技能，只用其自身 keywords 判定
DEFAULT_KEYWORDS: tuple[str, ...] = ()


__all__ = [
    "MergeResult",
    "merge_selection",
    "admit_policy_skill",
    "screen_policy_skills",
    "UNIVERSAL_SKILL_NAMES",
    "CONDITIONAL_EXTRA_SIGNALS",
    "SOURCE_MODEL",
    "SOURCE_POLICY",
    "SOURCE_BOTH",
]


@dataclass(frozen=True)
class MergeResult:
    """并集合并的结果。

    Attributes:
        final: 合并后的技能对象列表（保持原始对象引用，不重建）。
        provenance: 技能名 → 来源标注（model / policy / both）。
        added_by_policy: 模型没选、被确定性路由补上的技能名。
        dropped_by_limit: 因超过 limit 被截断的技能名。
        model_count / policy_count: 合并前两侧各自的技能数。
    """

    final: list[Any]
    provenance: dict[str, str] = field(default_factory=dict)
    added_by_policy: list[str] = field(default_factory=list)
    dropped_by_limit: list[str] = field(default_factory=list)
    screened_out: list[str] = field(default_factory=list)
    model_count: int = 0
    policy_count: int = 0
    policy_screened: int = 0

    @property
    def rescued_count(self) -> int:
        """模型漏选、由规则补上的技能数量。"""
        return len(self.added_by_policy)


def _skill_name(skill: Any, name_of: Callable[[Any], str] | None) -> str:
    """取技能名；默认读取 `name` 属性，缺失时退化为字符串表示。"""
    if name_of is not None:
        return name_of(skill)
    return str(getattr(skill, "name", skill))


def _is_always(skill: Any, is_always: Callable[[Any], bool] | None) -> bool:
    """判断是否强制技能；默认读取 `always` 属性。"""
    if is_always is not None:
        return bool(is_always(skill))
    return bool(getattr(skill, "always", False))


def admit_policy_skill(
    skill: Any,
    intent_text: str | None,
    *,
    name_of: Callable[[Any], str] | None = None,
) -> tuple[bool, str]:
    """判断一个「规则补入」的技能是否准入。

    判定顺序：
      1. 强制技能（always）—— 必准入；
      2. 显式通用技能（UNIVERSAL_SKILL_NAMES）—— 必准入，任何研报都用；
      3. requires_signal 的条件技能 —— 仅当用户意图里出现其触发信号时准入；
      4. 其余技能（requires_signal 为假）—— 视为通用，准入。

    Args:
        skill: 技能对象（需具备 name / always / requires_signal / keywords 中相关字段）。
        intent_text: 用户意图文本（主题 + 关注点 + 数据要求）。为 None 时不做条件裁剪。
        name_of: 自定义取名字段。

    Returns:
        (是否准入, 判定理由) —— 理由用于留痕，便于回溯「为什么补/没补这个技能」。
    """
    name = _skill_name(skill, name_of)

    if _is_always(skill, None):
        return True, "always"

    if name in UNIVERSAL_SKILL_NAMES:
        return True, "universal"

    if not getattr(skill, "requires_signal", False):
        return True, "universal"

    if not intent_text:
        # 没有意图文本可比对时，保持旧行为（不裁剪），避免误杀
        return True, "no-intent-text"

    keywords = tuple(CONDITIONAL_EXTRA_SIGNALS.get(name, ())) + tuple(
        getattr(skill, "keywords", ()) or DEFAULT_KEYWORDS
    )
    lowered = intent_text.casefold()
    for kw in keywords:
        if kw and kw.casefold() in lowered:
            return True, f"signal:{kw}"

    return False, "conditional-without-intent-signal"


def screen_policy_skills(
    skills: Iterable[Any],
    intent_text: str | None,
    *,
    name_of: Callable[[Any], str] | None = None,
) -> tuple[list[Any], list[str]]:
    """按用户意图筛选规则补入的技能。

    Returns:
        (准入的技能列表, 被裁掉的技能名列表)
    """
    kept: list[Any] = []
    dropped: list[str] = []
    for skill in skills or []:
        ok, _reason = admit_policy_skill(skill, intent_text, name_of=name_of)
        if ok:
            kept.append(skill)
        else:
            dropped.append(_skill_name(skill, name_of))
    return kept, dropped


def merge_selection(
    model_skills: Iterable[Any] | None,
    policy_skills: Iterable[Any] | None,
    *,
    limit: int | None = None,
    name_of: Callable[[Any], str] | None = None,
    is_always: Callable[[Any], bool] | None = None,
    intent_text: str | None = None,
    screen: bool = True,
) -> MergeResult:
    """把模型选择与确定性路由的结果合并为并集。

    Args:
        model_skills: 大模型选中的技能（可为 None）。
        policy_skills: 确定性路由给出的技能（可为 None）。
        limit: 合并后允许的最大技能数；None 表示不限制。
        name_of: 自定义取名字段，默认用 `.name`。
        is_always: 自定义强制技能判定，默认用 `.always`。
        intent_text: 用户意图文本（主题 + 关注点 + 数据要求）。提供时会先对
            `policy_skills` 做准入裁剪，避免为与意图无关的条件技能白付执行成本。
        screen: 是否启用上述裁剪；默认 True。`intent_text` 为空时裁剪自动跳过。

    Returns:
        MergeResult: 含最终清单、来源标注、补入、被截断与被裁掉的技能名。

    Raises:
        ValueError: limit 为负数时。
    """
    if limit is not None and limit < 0:
        raise ValueError(f"limit 不能为负数，收到 {limit!r}")

    model_list = list(model_skills or [])
    policy_all = list(policy_skills or [])

    screened_out: list[str] = []
    policy_list = policy_all
    if screen and intent_text:
        policy_list, screened_out = screen_policy_skills(policy_all, intent_text, name_of=name_of)

    model_names = {_skill_name(s, name_of) for s in model_list}
    policy_names = {_skill_name(s, name_of) for s in policy_list}

    # 来源标注：两侧都有记为 both
    provenance: dict[str, str] = {}
    for skill in model_list:
        provenance[_skill_name(skill, name_of)] = SOURCE_MODEL
    for skill in policy_list:
        name = _skill_name(skill, name_of)
        provenance[name] = SOURCE_BOTH if name in model_names else SOURCE_POLICY

    # 组装顺序：强制技能 → 模型选的 → 规则补的
    forced: list[Any] = [s for s in model_list if _is_always(s, is_always)]
    forced += [s for s in policy_list if _is_always(s, is_always) and _skill_name(s, name_of) not in model_names]

    model_rest = [s for s in model_list if not _is_always(s, is_always)]
    policy_rest = [
        s for s in policy_list
        if not _is_always(s, is_always) and _skill_name(s, name_of) not in model_names
    ]

    ordered: list[Any] = []
    seen: set[str] = set()
    for skill in forced + model_rest + policy_rest:
        name = _skill_name(skill, name_of)
        if name in seen:
            continue
        seen.add(name)
        ordered.append(skill)

    dropped: list[str] = []
    if limit is not None and len(ordered) > limit:
        dropped = [_skill_name(s, name_of) for s in ordered[limit:]]
        ordered = ordered[:limit]

    # 按 policy 原始顺序生成，保证结果可复现（早先从 set 迭代，顺序会随哈希变化）。
    # 注意用裁剪后的 policy_list：被准入裁掉的技能不应出现在补入清单里。
    added = [
        _skill_name(skill, name_of)
        for skill in policy_list
        if _skill_name(skill, name_of) not in model_names
    ]

    return MergeResult(
        final=ordered,
        provenance=provenance,
        added_by_policy=added,
        dropped_by_limit=dropped,
        screened_out=screened_out,
        model_count=len(model_list),
        policy_count=len(policy_all),
        policy_screened=len(screened_out),
    )
