"""环节命名本体（2026-10-25，方案 P1「禁 generic 槽位」）。

## 为什么不是"用 KB 生成环节"

方案初稿设想 `chain_ontology` 用 ChainKnowledgeGraph 直接生成环节名
（`industry_upstreams(行业)` / `product_upstreams(核心产品)`）。实测两条都不成立：

① `industry_up` 的"上游行业"是**企业多元化经营的共现**，不是产业链上游——
   「白酒Ⅲ」的上游是「电机Ⅲ／地面兵装Ⅲ／钾肥」，「锂电池」的上游是「果蔬加工／氮肥」；
   全部上游边只有 10.1% 落在同一申万一级门类内 → 已在 `chain_kb` 弃用。
② 改用"同行业企业的主营产品词"反推上游品类，实测输出是报表科目和收入分项：
   笔记本电脑 → 平衡项目／配件／贸易／硬盘；半导体设备 → 销售专用设备／设备维护；
   工业机器人 → 变频器类／注塑机／数控系统（混进了下游客户的产品）。
   「平衡项目」是财务报表里的对账科目、「销售专用设备」是收入分项，都不是产业环节。
   → 拿它当环节名会把图做得比泛词更差，所以**不接进提示词**。

## 本模块真正做的三层

① **禁泛词**：定义"什么名字不算环节"（核心部件／关键材料／基础器件／专用设备／检测仪器…）。
   这些词是模板占位符，不是产业环节：同一张图上出现「核心部件」，读者不知道它指什么，
   也无法判断该环节的企业填得对不对。
② **具体化**：模型自己给出的 `key_products` 就是具体品类（笔记本实测：结构件／软包电池／
   玻璃盖板／存储芯片／电源管理芯片）。用它们把泛词环节名重命名——有数据、确定性、
   不靠猜。这解决了「A2 明明知道品类，却被要求用泛词当标题」这个具体缺陷。
③ **校验**：KB 只回答"这个词是不是真实存在的品类／行业词"，不生成环节。

## 与其他层的关系

- 环节**数量与 stage 分布**仍由 `chain_structure` 的结构骨架定（版式职责）；
- 环节**名字**由模型按具体品类给（内容职责），本模块负责拦截泛词并在修复阶段补正；
- 环节**该不该有企业**由角色（`role_for_label`）定，`in_house` 能力卡不检索企业（P2）。
"""
from __future__ import annotations

import re
from typing import Any

# 模板占位符式环节名：出现即视为"没写环节"。
# 判据不是"词短"，而是**这个词没有指向任何具体品类**：
#   核心部件（哪一类？）、关键材料（哪一种？）、基础器件（什么器件？）
# 「整机制造与总装」「品牌与产品运营」不在此列——它们指向确定的角色，是合法环节名。
GENERIC_SLOT_LABELS: frozenset[str] = frozenset({
    "核心部件", "关键部件", "核心零部件", "关键零部件", "核心元器件", "基础部件",
    "关键材料", "核心材料", "基础材料", "原材料", "材料",
    "基础器件", "元器件", "电子元器件", "零部件", "配件", "配套件",
    "专用设备", "通用设备", "生产设备", "关键设备", "检测仪器", "检测设备",
    "上游", "中游", "下游", "其他", "其它", "相关环节", "配套",
})

# 泛词的"后缀式"变体：核心部件类 / 关键材料类 …
_GENERIC_RE = re.compile(r"^(核心|关键|基础|重要|主要)(部件|零部件|元器件|器件|材料|设备|仪器)")

# 自研/内建能力：这类环节不该去检索"供应商"（P2 角色化槽位的判定词）。
# 🔴 只收**明确的工序/自有能力词**。刻意不含「研发／设计／算法／工艺／配方」——
#    那些环节确实存在外部服务商（设计公司、代研、工艺授权），一律判内建会把
#    该填的企业卡清空。判据是"这个环节有没有可能由外部主体承担"，
#    而不是"听起来像不像技术活"。
IN_HOUSE_HINTS = (
    "自研", "自建", "内建", "自制",
    "陈酿", "勾调", "制曲", "糖化", "发酵", "酿造", "蒸馏",
)

# 渠道/流通：这类环节的"企业"是渠道商，检索词与供应商不同。
CHANNEL_HINTS = ("渠道", "经销", "分销", "专卖", "零售", "电商", "团购", "终端", "门店")


def is_generic_label(label: str) -> bool:
    """该环节名是不是模板占位符（而非具体品类/确定角色）。"""
    s = str(label or "").strip()
    if not s:
        return True
    if s in GENERIC_SLOT_LABELS:
        return True
    return bool(_GENERIC_RE.match(s))


def role_for_label(label: str, *, is_core: bool = False) -> str:
    """环节 → 角色。``brand`` / ``in_house`` / ``procurement`` / ``channel`` / ``support``。

    P2 用途：`in_house`（陈酿/勾调/自研算法/制曲）是**厂商内建能力**，
    不该去搜"该环节的代表企业"——搜索一定会返回设备厂或代工厂，
    图上就变成"茅台的陈酿工序由某某设备公司完成"这种荒谬结论。
    """
    s = str(label or "").strip()
    if is_core:
        return "brand"
    if any(h in s for h in IN_HOUSE_HINTS):
        return "in_house"
    if any(h in s for h in CHANNEL_HINTS):
        return "channel"
    return "procurement"


def provides_companies(role: str) -> bool:
    """该角色是否应该有「代表企业」（内建能力与品牌卡的口径不同，见 role_for_label）。"""
    return role != "in_house"


def _clean_item(item: Any) -> str:
    s = str(item or "").strip().strip("，、。；;：:")
    if len(s) < 2 or len(s) > 10:
        return ""
    if re.search(r"[0-9０-９%％]", s):
        return ""                       # 数据三层截断：环节名里不许有数字
    if is_generic_label(s):
        return ""
    return s


def label_from_items(items: Any, *, max_len: int = 12, fallback: str = "") -> str:
    """用节点自己的具体品类词拼一个环节名（「结构件」+「软包电池」→「结构件与软包电池」）。

    为什么用 items 而不是 KB：items 是模型针对**这个环节**给的具体品类，
    与环节一一对应；KB 只能按行业给整批品类，无法知道哪个品类属于哪个环节。
    """
    picked: list[str] = []
    total = 0
    for raw in (items or []):
        w = _clean_item(raw)
        if not w or w in picked:
            continue
        add = len(w) + (1 if picked else 0)
        if picked and total + add > max_len:
            continue
        picked.append(w)
        total += add
        if len(picked) >= 2:
            break
    if picked:
        return "与".join(picked)
    return fallback


_NAME_KEYS = ("label", "name")
_ITEM_KEYS = ("key_products", "items")


def _name_key(node: dict[str, Any]) -> str:
    """节点名字段的键名：原始拓扑（A2 产出 / repair_topology 的输入）用 ``label``，
    ``ChainNode`` dump 出来的用 ``name``。返回实际有值的那个，都没有则空串。"""
    for k in _NAME_KEYS:
        if str(node.get(k) or "").strip():
            return k
    return ""


def _node_name(node: dict[str, Any]) -> str:
    k = _name_key(node)
    return str(node.get(k) or "").strip() if k else ""


def _node_items(node: dict[str, Any]) -> Any:
    for k in _ITEM_KEYS:
        v = node.get(k)
        if v:
            return v
    return []


def relabel_generic_nodes(
    top: dict[str, Any],
    *,
    max_len: int = 12,
) -> tuple[dict[str, Any], list[str]]:
    """把泛词环节名换成该节点自己的具体品类名（确定性修复，幂等）。

    实测来源（run-20261025111912 笔记本电脑）：14 个节点里 5 个上游卡的标题是
    「核心部件／关键材料／基础器件／专用设备／检测仪器」——因为 `chain_structure`
    的离散硬件骨架把这几行当成"固定槽位，不得改名"，模型照抄；
    而它们的 key_products 恰恰是**正确的具体品类**（结构件/软包电池/玻璃盖板/
    存储芯片/电源管理芯片）。也就是说模型知道答案，只是没地方写。
    本函数把这个错位纠正过来：标题用具体品类，泛词不再上图。

    只改**泛词且 items 非空**的节点：
      · 节点名是合法环节（如「整机制造与总装」）→ 不动；
      · items 也空 → 不动（没有依据就不瞎起名，留 lint 警告）。

    字段格式（2026-10-25 修）：本函数同时吃「原始拓扑」（``label`` / ``key_products``）
    与「ChainNode dump」（``name`` / ``items``）两种形状，**改哪个字段就写回哪个字段**。
    旧实现只读 ``label``、只写 ``label``，遇到 ``name`` 形状的节点会：
      ① 留痕里旧名字是空串（"泛词环节「」→「X」"，排查时无法定位）；
      ② 写出 ``{"name": "生产设备", "label": "酿造设备与灌装线"}`` 这种**双字段矛盾**节点。
    真跑路径（``repair_topology`` 收的是 A2 原始拓扑）踩不到，但这是静默埋雷，必须堵。
    """
    import copy

    fixed = copy.deepcopy(top)
    notes: list[str] = []
    nodes = [n for n in (fixed.get("nodes") or []) if isinstance(n, dict)]
    taken = {_node_name(n) for n in nodes if _node_name(n)}
    for n in nodes:
        key = _name_key(n)
        if not key:
            # 名字都没有 → 这是数据残缺，不是"泛词"，不该产生泛词留痕（否则刷屏且无法定位）
            continue
        old = str(n.get(key) or "").strip()
        if not is_generic_label(old):
            continue
        new = label_from_items(_node_items(n), max_len=max_len)
        if not new:
            notes.append(f"环节名「{old}」是泛词但无具体品类可依据，保持原样待人工确认")
            continue
        if new in taken:
            continue                     # 会撞名 → 不折腾，交给 lint
        n[key] = new                     # 🔴 写回**原字段**，不制造 name/label 双份
        taken.discard(old)
        taken.add(new)
        notes.append(f"泛词环节「{old}」→「{new}」（用本环节真实品类命名）")
    return fixed, notes


def generic_labels(top: dict[str, Any]) -> list[str]:
    """只读体检：还剩哪些泛词环节名（供 lint / 验收脚本统计）。"""
    return [nm for nm in (_node_name(n) for n in (top.get("nodes") or [])
                          if isinstance(n, dict)) if is_generic_label(nm)]


def kb_label_kind(label: str) -> str:
    """环节名的 KB 依据：``product``（真实品类词）/ ``industry``（申万行业名）/ ``unknown``。

    **只作校验，不作生成**——判"这个名字是不是一件真实存在的东西"，
    不负责"该有哪些环节"。`unknown` 不等于错：新品类（如「固态电池中试线」）
    本来就可能不在 2021 年底座里，所以只在 lint 记 warning，绝不据此改名。
    """
    s = str(label or "").strip()
    if not s:
        return "unknown"
    try:
        from chart_generator import chain_kb          # noqa: PLC0415

        if s in chain_kb.product_words():
            return "product"
        if s in chain_kb.industry_names():
            return "industry"
    except Exception:                                  # pragma: no cover
        return "unknown"
    return "unknown"
