"""三种情景的结构化呈现：分段、关键读数、语气配色。

**纯确定性文本处理，不合成、不改写、不推断任何数值**（Agent 5 硬约束 #1）。

Agent 4 输出的情景是整段中文散文（2026-09-18 实测 345–507 字 / 条），直接排成
`<ul>` 会得到一坨密不透风的文字 —— 交付反馈是「字数都比较多，密密麻麻的，
感觉很杂」。本模块把它拆成三样东西：

1. **分段**：情景文本用 ` / ` 分隔、每段以「前提：」「传导路径：」等标签开头，
   拆成带标签的段落，读者可以按标签跳读而不是从头读到尾；
2. **关键读数**：从「前提」「触发条件」里抽出**带单位的数值表达式**
   （`41.6%-45.2%` / `174.10亿元` / `12.44%`），连同它前面的中文短语一起放大展示。
   保留前导短语是关键 —— 这正是「数字脱离原本应该存在的位置」的修法：
   放大后的数字仍然带着口径（`归母净利润 7.03亿元`，而不是孤零零的 `7.03亿元`）；
3. **语气**：按情景名判定 中性 / 积极 / 谨慎，映射到品牌色 / 语义绿 / 语义红。

正则匹配不到时的降级路径：整条情景作为**一个无标签段落**输出，且**不产出读数**
（宁可少放大几个数字，也不能把数字放错位置）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape

from markupsafe import Markup

# 段落分隔。实测文本的层级是 **两级**：
#   `前提：A / B / C；传导路径：…；触发条件：D / E / F；反证条件：…；跟踪指标：G / H / I`
# 即 `；` 分隔「前提 / 传导路径 / 触发条件 / 反证条件 / 跟踪指标」五个段落，
# 而 ` / ` 只是**段落内部**的并列子句。2026-09-18 首版按 ` / ` 切分，于是
# 得到 9 个无标签碎片（前提被切成三段、标签全丢），必须先按 `；` 切。
_CLAUSE_SPLIT_RE = re.compile(r"\s*[；;]\s*")
# 兜底分隔符**必须要求斜杠两侧有空白**。2026-09-18 实测：用 `\s*/\s*` 时，
# 一段没有 `；` 的情景会被正文里的裸斜杠切碎 —— `</b>`、`2026/06`、
# `零部件/电池` 都会断开，制造出无标签的碎片段落。真实文本里的分隔符写作
# ` / `（两侧有空格），而裸 `/` 只出现在日期、路径、HTML 结束标签里。
_SEGMENT_SPLIT_RE = re.compile(r"\s+/\s+")
# 段首标签："前提：" / "触发条件:" —— 限长避免把正文里的冒号误当标签。
_SEGMENT_LABEL_RE = re.compile(r"^([^：:]{2,8})[：:]\s*")

# 带单位的数值表达式。区间优先（`41.6%-45.2%`），单位按长度降序排列，
# 否则 `亿元` 会被 `亿` 抢先匹配掉一个字符。
_UNIT = r"(?:%|％|个百分点|亿元|万元|亿|万|倍|元)"
_NUMBER_RE = re.compile(
    rf"\d[\d,]*(?:\.\d+)?\s*{_UNIT}"
    rf"(?:\s*[-–—~至]\s*\d[\d,]*(?:\.\d+)?\s*{_UNIT})?"
)

# 读数标签的清洗：先取数值前面的中文短语，再反复剥掉量词与谓语动词，
# 留下名词性短语（`营业收入` / `毛利率` / `增速` / `低点`）。
#
# 2026-09-18 实测：不剥谓语就会得到 `速重新`（源自「同比增速重新回升至50%」）
# 和 `份毛利率跌破` 这类读不通的标签。剥完仍有 ≥2 字才剥，否则保留原样 ——
# `低于`/`超过` 本身就是完整的语境短语（`低于 15%`）。
_TRAILING_CJK_RE = re.compile(r"([\u4e00-\u9fff]{1,10})$")
_LABEL_STRIP_CHARS = " \t（(【[:：、，,"
_LABEL_LEADING_NOISE = "年月日个份"
# 长的必须排在短的前面：`回升至` 先于 `至`，`环比提升` 先于 `提升`。
_LABEL_TRAILING_NOISE = (
    "环比提升",
    "环比下降",
    "回升至",
    "维持在",
    "达到",
    "重新",
    "提升",
    "回升",
    "下降",
    "增长",
    "跌破",
    "超过",
    "高于",
    "低于",
    "至",
    "约",
    "达",
    "到",
    "在",
    "为",
)
_READING_LABEL_MAX = 6
# 指标名词：标签超长时从这里往回截，得到 `富奥股份毛利率` → `毛利率`、
# `动力电池销量当月同比增速` → `增速`。纯排版启发式，不含任何事实。
_METRIC_NOUNS = (
    "毛利率",
    "净利率",
    "市盈率",
    "市销率",
    "增速",
    "占比",
    "区间",
    "水平",
    "规模",
    "收入",
    "利润",
    "成本",
    "低点",
    "高点",
    "销量",
)
_MAX_READINGS = 3

# 读数优先级：先取「前提」（情景的定义性假设），不足再取「触发条件」，
# 最后才回落到其余段落。
_PREFERRED_SEGMENTS = ("前提", "触发条件", "反证条件", "传导路径", "跟踪指标")

_TONE_RULES = (
    ("positive", ("乐观", "积极", "上行", "好转")),
    ("negative", ("悲观", "谨慎", "下行", "恶化")),
)
_TONE_LABELS = {"neutral": "中性", "positive": "积极", "negative": "谨慎"}


@dataclass(frozen=True, slots=True)
class Reading:
    """一条放大展示的关键读数：数值 + 它原本的语境短语。"""

    value: str
    label: str


@dataclass(frozen=True, slots=True)
class Segment:
    """一个带标签的情景段落，正文里的数值已就地放大。"""

    label: str
    text: Markup


@dataclass(frozen=True, slots=True)
class ScenarioCard:
    """一张情景卡：名称 + 语气 + 关键读数 + 分段正文。"""

    name: str
    tone: str
    tone_label: str
    readings: list[Reading] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    raw: str = ""


def _emphasise(text: str) -> Markup:
    """把段落里的带单位数值就地包成强调标签。

    就地强调而不是把数字搬到别处：数字必须留在它原本的句子里，
    否则又会变成「脱离原本应该存在的位置」。
    """

    parts: list[str] = []
    cursor = 0
    for match in _NUMBER_RE.finditer(text):
        parts.append(escape(text[cursor : match.start()]))
        parts.append(f'<span class="seg-num">{escape(match.group(0))}</span>')
        cursor = match.end()
    parts.append(escape(text[cursor:]))
    return Markup("".join(parts))


def _reading_label(prefix: str) -> str:
    """取数值前最近的名词性中文短语作为读数标签，取不到时返回空串。"""

    candidate = prefix.rstrip(_LABEL_STRIP_CHARS)
    match = _TRAILING_CJK_RE.search(candidate)
    if match is None:
        return ""
    label = match.group(1).lstrip(_LABEL_LEADING_NOISE)
    # 反复剥谓语，直到剥不动为止（`毛利率环比提升超过` → `毛利率`）。
    changed = True
    while changed:
        changed = False
        for noise in _LABEL_TRAILING_NOISE:
            if label.endswith(noise) and len(label) - len(noise) >= 2:
                label = label[: -len(noise)]
                changed = True
                break
    return _trim_label(label)


def _trim_label(label: str) -> str:
    """标签过长时从最近的指标名词往回截，保证读数标签短且读得通。"""

    if len(label) <= _READING_LABEL_MAX:
        return label
    best = -1
    for noun in _METRIC_NOUNS:
        index = label.rfind(noun)
        if index > best and len(label) - index >= 2:
            best = index
    if best > 0:
        return label[best:]
    return label[-_READING_LABEL_MAX:]


def _strip_labels(chunk: str) -> tuple[list[str], str]:
    """剥掉段首的连续标签，返回 `(标签列表, 剩余正文)`。

    第一段带两个标签（`基准情景：前提：…`），其余段带一个。
    """

    labels: list[str] = []
    while True:
        match = _SEGMENT_LABEL_RE.match(chunk)
        if match is None:
            return labels, chunk
        labels.append(match.group(1).strip())
        chunk = chunk[match.end() :].strip()


def _split_segments(text: str) -> list[tuple[list[str], str]]:
    """把情景正文拆成 `(标签列表, 正文)`。

    先按 `；` 切段；没有 `；` 时（上游换了分隔符）退回按 ` / ` 切，
    保证任何写法都能得到可读的分段，而不是整条丢进一个段落。
    """

    chunks = [chunk for chunk in _CLAUSE_SPLIT_RE.split(text) if chunk.strip()]
    if len(chunks) < 2:
        chunks = [chunk for chunk in _SEGMENT_SPLIT_RE.split(text) if chunk.strip()]
    return [_strip_labels(chunk.strip()) for chunk in chunks if chunk.strip()]


def _segment_label(labels: list[str]) -> str:
    """段落的有效标签是**最后一个**标签（`基准情景：前提：` → `前提`）。"""

    return labels[-1] if labels else ""


def _collect_readings(segments: list[tuple[list[str], str]]) -> list[Reading]:
    """按「前提 → 触发条件 → 其余」的顺序收集最多 ``_MAX_READINGS`` 条读数。"""

    ordered: list[tuple[list[str], str]] = []
    for preferred in _PREFERRED_SEGMENTS:
        ordered.extend(item for item in segments if _segment_label(item[0]) == preferred)
    ordered.extend(
        item for item in segments if _segment_label(item[0]) not in _PREFERRED_SEGMENTS
    )

    readings: list[Reading] = []
    seen: set[str] = set()
    for labels, body in ordered:
        for match in _NUMBER_RE.finditer(body):
            value = match.group(0).strip()
            key = value.replace(" ", "")
            if key in seen:
                continue
            seen.add(key)
            readings.append(
                Reading(
                    value=value,
                    label=_reading_label(body[: match.start()]) or _segment_label(labels),
                )
            )
            if len(readings) >= _MAX_READINGS:
                return readings
    return readings


def _tone_of(name: str) -> str:
    for tone, keywords in _TONE_RULES:
        if any(keyword in name for keyword in keywords):
            return tone
    return "neutral"


def build_scenario_card(text: str, *, sanitize) -> ScenarioCard | None:
    """把一条情景散文转成 `ScenarioCard`。

    `sanitize` 是渲染层的对外文本净化入口（`sanitize_for_render`），
    在这里传入而不是 import，避免 `reporting` 包与 `text_rules_loader`
    形成循环依赖，也保证净化顺序与正文其余部分完全一致：
    **先净化整条文本，再切分** —— 词表规则有跨词边界（状态码 lookaround），
    先切分会让同一段文字在情景卡与正文里得到不同结果。
    """

    cleaned = sanitize(text).strip()
    if not cleaned:
        return None
    raw_segments = _split_segments(cleaned)
    if not raw_segments:
        return None

    first_labels, _ = raw_segments[0]
    name = (first_labels[0] if first_labels else "") or "情景"
    # 首段的第一个标签就是情景名（`基准情景：`），其余标签（`前提：`）才是段落标签。
    body_segments = [
        (labels[1:] if index == 0 else labels, body)
        for index, (labels, body) in enumerate(raw_segments)
    ]
    body_segments = [item for item in body_segments if item[1]]

    return ScenarioCard(
        name=name,
        tone=_tone_of(name),
        tone_label=_TONE_LABELS[_tone_of(name)],
        readings=_collect_readings(body_segments),
        segments=[
            Segment(label=_segment_label(labels), text=_emphasise(body))
            for labels, body in body_segments
        ],
        raw=cleaned,
    )


def build_scenario_cards(scenarios: list[str], *, sanitize) -> list[ScenarioCard]:
    """批量转换；单条失败只丢那一条，不影响其余（硬约束 #3）。"""

    cards: list[ScenarioCard] = []
    for item in scenarios:
        if not isinstance(item, str):
            continue
        try:
            card = build_scenario_card(item, sanitize=sanitize)
        except Exception:  # noqa: BLE001 - 渲染层不得因单条情景阻断整份导出
            card = None
        if card is not None:
            cards.append(card)
    return cards
