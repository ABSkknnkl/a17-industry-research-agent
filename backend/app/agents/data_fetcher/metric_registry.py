"""Canonical metric definitions shared by Agent 1 planning and coverage checks.

The registry keeps routing deterministic for known financial/operating metrics
and, more importantly, records the raw fields that must actually be sent to
SkillHub.  A correct skill choice is not sufficient when the requested metric
never appears in the provider query.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from app.schemas.acquisition import SkillName


@dataclass(frozen=True, slots=True)
class MetricSpec:
    """Deterministic routing and query contract for one canonical metric.

    ``unsupported``（2026-09-01 方案第三刀）：数据源未验证的指标注册为
    unsupported——保留词表命中（供澄清门/用户裁决门显式披露），但确定性
    层绝不硬路由，绝不编造。
    """

    key: str
    display_name: str
    aliases: tuple[str, ...]
    primary_skill: SkillName
    query_fields: tuple[str, ...]
    unsupported: bool = False
    # 2026-09-01 最终方案（BUG-1 口径护栏）：公司财报口径指标仅在公司语境
    # （公司实体在场且/或无行业语境词，由解析层判定）时可作指标锁；
    # 行业问句命中转披露通道，不得静默取公司级数据。
    requires_company_entity: bool = False


_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec(
        "revenue",
        "营业收入",
        ("营业收入", "营收", "销售收入", "主营业务收入"),
        SkillName.FINANCE,
        ("营业收入",),
    ),
    MetricSpec(
        "gross_margin",
        "毛利率",
        ("毛利率", "销售毛利率", "综合毛利率"),
        SkillName.FINANCE,
        ("毛利率", "营业收入", "营业成本"),
    ),
    MetricSpec(
        "net_profit",
        "净利润",
        ("净利润",),
        SkillName.FINANCE,
        ("净利润",),
    ),
    MetricSpec(
        "attributable_net_profit",
        "归母净利润",
        ("归母净利润", "归属于母公司所有者的净利润", "归属母公司股东净利润"),
        SkillName.FINANCE,
        ("归母净利润",),
    ),
    MetricSpec(
        "operating_cost",
        "营业成本",
        ("营业成本", "主营业务成本"),
        SkillName.FINANCE,
        ("营业成本",),
    ),
    MetricSpec(
        "net_margin",
        "净利率",
        ("净利率", "销售净利率", "归母净利率"),
        SkillName.FINANCE,
        ("净利率", "归母净利润", "营业收入"),
    ),
    MetricSpec(
        "r_and_d_expense_ratio",
        "研发费用率",
        ("研发费用率", "研发投入占比", "研发强度"),
        SkillName.FINANCE,
        ("研发费用率", "研发费用", "营业收入"),
    ),
    MetricSpec(
        "selling_expense_ratio",
        "销售费用率",
        ("销售费用率",),
        SkillName.FINANCE,
        ("销售费用率", "销售费用", "营业收入"),
    ),
    MetricSpec(
        "management_expense_ratio",
        "管理费用率",
        ("管理费用率",),
        SkillName.FINANCE,
        ("管理费用率", "管理费用", "营业收入"),
    ),
    MetricSpec(
        "expense_ratios",
        "各项费用率",
        ("各项费用率", "期间费用率", "费用率"),
        SkillName.FINANCE,
        ("研发费用率", "销售费用率", "管理费用率", "营业收入"),
    ),
    MetricSpec(
        "roe",
        "ROE",
        ("roe", "净资产收益率", "加权平均净资产收益率"),
        SkillName.FINANCE,
        ("ROE", "净利润", "股东权益"),
    ),
    MetricSpec(
        "pe",
        "PE",
        ("pe", "pe估值", "市盈率", "滚动市盈率"),
        SkillName.INDEX,
        ("市盈率", "数据日期"),
    ),
    MetricSpec(
        "pb",
        "PB",
        ("pb", "pb估值", "市净率"),
        SkillName.INDEX,
        ("市净率", "数据日期"),
    ),
    MetricSpec(
        "inventory_turnover",
        "存货周转率",
        ("存货周转率",),
        SkillName.FINANCE,
        ("存货周转率", "营业成本", "存货"),
    ),
    MetricSpec(
        "receivables_turnover",
        "应收账款周转率",
        ("应收账款周转率", "应收周转率"),
        SkillName.FINANCE,
        ("应收账款周转率", "营业收入", "应收账款"),
    ),
    MetricSpec(
        "asset_turnover",
        "总资产周转率",
        ("总资产周转率", "资产周转率"),
        SkillName.FINANCE,
        ("总资产周转率", "营业收入", "总资产"),
    ),
    MetricSpec(
        "inventory_days",
        "存货周转天数",
        # 2026-09-01 方案（第三刀·词表）：口语「库存」≠书面「存货」，两条都留。
        # 最终方案（BUG-1/OBS 4.5）：公司财报口径，行业问句命中不得锁定。
        ("存货周转天数", "存货天数", "库存周转天数", "库存周转"),
        SkillName.FINANCE,
        ("存货周转天数", "营业成本", "存货"),
        requires_company_entity=True,
    ),
    MetricSpec(
        "receivables_days",
        "应收账款周转天数",
        ("应收账款周转天数", "应收周转天数"),
        SkillName.FINANCE,
        ("应收账款周转天数", "营业收入", "应收账款"),
    ),
    MetricSpec(
        "overseas_revenue_share",
        "海外收入占比",
        # 2026-09-01 方案（第三刀·词表）：+外销占比。「出口占比」已按最终方案
        # BUG-1 回退移除（行业问句命中会静默路由公司级数据）；行业出口诉求
        # 登记研究边界词表（research_boundary_terms.yaml），走澄清披露。
        (
            "海外收入占比",
            "境外收入占比",
            "境外营收占比",
            "海外营收占比",
            "外销占比",
        ),
        SkillName.BUSINESS,
        ("海外收入占比", "境外营业收入", "营业收入"),
        requires_company_entity=True,
    ),
    MetricSpec(
        "shipment_volume",
        "出货量",
        # P0-4（2026-08-31 方案）：补“发货量”别名；“销量/销售量”已由
        # sales_volume 独立注册，不重复挂靠以免词表漂移。
        # P0-6（2026-09-01 方案）：primary_skill 改 INDUSTRY——真实接口
        # 实测出货量是行业口径指标（business_query 查不到且静默回退
        # 行情数据）；公司级需求降级为行业口径查询并带口径标签。
        ("出货量", "出货规模", "交付量", "发货量"),
        SkillName.INDUSTRY,
        ("出货量", "销量"),
    ),
    MetricSpec(
        "capacity",
        "产能",
        # P0-4 曾把「规划产能/有效产能」挂在本族；2026-09-01 方案（第三刀·
        # 口径细分）将其拆出独立注册（effective_capacity 等），配合第二刀
        # 最长匹配优先，不再归一为泛化「产能」（治 A06/B06 口径合并丢失）。
        ("产能", "产能规模", "设计产能", "名义产能"),
        SkillName.INDUSTRY,
        ("产能",),
    ),
    MetricSpec(
        # 2026-09-01 方案（第三刀·口径细分）：有效/在建/规划产能独立成族。
        "effective_capacity",
        "有效产能",
        ("有效产能", "现有产能"),
        SkillName.INDUSTRY,
        ("产能",),
    ),
    MetricSpec(
        "under_construction_capacity",
        "在建产能",
        ("在建产能", "建设中产能"),
        SkillName.INDUSTRY,
        ("产能",),
    ),
    MetricSpec(
        "planned_capacity",
        "规划产能",
        ("规划产能", "拟建产能"),
        SkillName.INDUSTRY,
        ("产能",),
    ),
    MetricSpec(
        # P0-4（2026-08-31 方案）：新增产能利用率（开工率/稼动率归一）。
        # primary_skill 取 INDUSTRY 与方案表格一致：该指标是行业景气口径，
        # 非 company 实体绑定口径。
        "capacity_utilization",
        "产能利用率",
        # 2026-09-01 方案（第三刀·词表）：+开工饱和度（E05「生产饱和吗」类口语）。
        ("产能利用率", "开工率", "稼动率", "开工饱和度"),
        SkillName.INDUSTRY,
        ("产能利用率", "产能", "产量"),
    ),
    MetricSpec(
        "production_volume",
        "产量",
        # P0-6（2026-09-01 方案）：产量同属产业运营指标，行业口径。
        ("产量", "生产量"),
        SkillName.INDUSTRY,
        ("产量",),
    ),
    MetricSpec(
        "sales_volume",
        "销量",
        ("销量", "销售量", "销售数量"),
        SkillName.BUSINESS,
        ("销量",),
    ),
    MetricSpec(
        "commercial_property_sales_area",
        "商品房销售面积",
        ("商品房销售面积", "全国商品房销售面积"),
        SkillName.MACRO,
        ("商品房销售面积",),
    ),
    MetricSpec(
        "commercial_property_sales_value",
        "商品房销售额",
        ("商品房销售额", "全国商品房销售额"),
        SkillName.MACRO,
        ("商品房销售额",),
    ),
    MetricSpec(
        "real_estate_development_investment",
        "房地产开发投资额",
        ("房地产开发投资额", "房地产开发投资完成额"),
        SkillName.MACRO,
        ("房地产开发投资额",),
    ),
    MetricSpec(
        "housing_new_start_area",
        "房屋新开工面积",
        ("房屋新开工面积", "房地产新开工面积"),
        SkillName.MACRO,
        ("房屋新开工面积",),
    ),
    MetricSpec(
        "market_share",
        "市场份额",
        # P0-4（2026-08-31 方案）：+占有率/份额，与 intent_merger 的
        # _METRIC_TYPE_KEYWORDS 保持同一词面，避免两处词表漂移。
        ("市场份额", "市占率", "市场占有率", "厂商份额", "占有率", "份额"),
        SkillName.STOCK_SELECTOR,
        ("市场份额", "市占率", "出货量", "销量"),
    ),
    MetricSpec(
        "cr3",
        "CR3",
        ("cr3", "前三家集中度"),
        SkillName.STOCK_SELECTOR,
        ("市场份额",),
    ),
    MetricSpec(
        "cr5",
        "CR5",
        ("cr5", "前五家集中度", "行业集中度"),
        SkillName.STOCK_SELECTOR,
        ("市场份额",),
    ),
    MetricSpec(
        # 2026-09-01 方案（第三刀·词表）：+CR10（CR3/CR5 已有）。
        "cr10",
        "CR10",
        ("cr10", "前十家集中度"),
        SkillName.STOCK_SELECTOR,
        ("市场份额",),
    ),
    MetricSpec(
        # 2026-09-01 方案（第三刀·词表）：渗透率数据源未验证——注册为
        # unsupported：命中可见、走澄清门/用户裁决门，不硬路由、不编造。
        # 待用 pywencai 反向探测确认问财行业库字段后再解除。
        "penetration_rate",
        "渗透率",
        ("渗透率", "渗透水平"),
        SkillName.INDUSTRY,
        ("渗透率",),
        unsupported=True,
    ),
)


def normalize_metric_name(value: str) -> str:
    """Normalise punctuation/spacing without erasing meaningful Chinese text."""

    return re.sub(r"[\s_\-/%（）()]+", "", str(value)).casefold()


_CORE_ALIASES: dict[str, MetricSpec] = {
    normalize_metric_name(alias): spec for spec in _SPECS for alias in spec.aliases
}

# 词表双轨（2026-09-01 方案第四刀·改动点 3）：核心高频指标留在代码
# （代码即契约）；长尾别名与派生词否定表外置 YAML，改配置即生效不发版。
# SQLite 表化后置（本期不做）。


def _config_path(env_var: str, default_name: str) -> Path:
    override = os.environ.get(env_var, "").strip()
    if override:
        return Path(override)
    # app/agents/data_fetcher/metric_registry.py -> backend/config/<default_name>
    root = Path(__file__).resolve().parents[3]
    return root / "config" / default_name


def _load_yaml_mapping(path: Path) -> dict[str, object]:
    try:
        if not path.exists():
            return {}
        import yaml

        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:  # noqa: BLE001 - 词表加载失败必须静默回退核心词表
        return {}


_EXTERNAL_ALIAS_CACHE: dict[tuple[str, float], dict[str, MetricSpec]] = {}


def external_alias_specs() -> dict[str, MetricSpec]:
    """长尾别名外置（``backend/config/metric_aliases.yaml``）。

    YAML 形态：``{metric_key: [alias, ...]}``；未知 key 静默忽略。
    核心注册表同名别名优先（外部只补长尾，不覆盖契约）。按路径+修改时间
    缓存，热修即时生效。
    """

    path = _config_path("METRIC_ALIASES_PATH", "metric_aliases.yaml")
    try:
        cache_key = (str(path), path.stat().st_mtime if path.exists() else 0.0)
    except OSError:
        cache_key = (str(path), 0.0)
    cached = _EXTERNAL_ALIAS_CACHE.get(cache_key)
    if cached is not None:
        return cached
    specs_by_key = {spec.key: spec for spec in _SPECS}
    loaded: dict[str, MetricSpec] = {}
    raw = _load_yaml_mapping(path)
    for metric_key, aliases in raw.items():
        spec = specs_by_key.get(str(metric_key))
        if spec is None or not isinstance(aliases, list):
            continue
        for alias in aliases:
            if not isinstance(alias, str) or not alias.strip():
                continue
            normalized = normalize_metric_name(alias)
            if normalized:
                loaded[normalized] = spec
    _EXTERNAL_ALIAS_CACHE.clear()
    _EXTERNAL_ALIAS_CACHE[cache_key] = loaded
    return loaded


def alias_map() -> dict[str, MetricSpec]:
    """核心注册表 + 外置长尾别名；核心优先。"""

    merged = dict(external_alias_specs())
    merged.update(_CORE_ALIASES)
    return merged


_BLACKLIST_CACHE: dict[tuple[str, float], dict[str, tuple[str, ...]]] = {}


def derivative_blacklist() -> dict[str, tuple[str, ...]]:
    """派生词否定表（第二刀）：归一化 alias → 归一化派生词元组。

    外置 ``backend/config/metric_derivative_blacklist.yaml``，形态：
    ``{alias: [派生词, ...]}``（如 ``产能: [投资, 爬坡, 过剩]``）。
    命中 alias 且原文 ±8 字符窗口检出派生词 → 不 lock，降级交 L2。
    新词不发版，改配置即生效；加载失败静默回退空表（旧行为）。
    """

    path = _config_path("METRIC_DERIVATIVE_BLACKLIST_PATH", "metric_derivative_blacklist.yaml")
    try:
        cache_key = (str(path), path.stat().st_mtime if path.exists() else 0.0)
    except OSError:
        cache_key = (str(path), 0.0)
    cached = _BLACKLIST_CACHE.get(cache_key)
    if cached is not None:
        return cached
    loaded: dict[str, tuple[str, ...]] = {}
    raw = _load_yaml_mapping(path)
    for alias, words in raw.items():
        if not isinstance(alias, str) or not isinstance(words, list):
            continue
        normalized_alias = normalize_metric_name(alias)
        normalized_words = tuple(
            normalize_metric_name(word)
            for word in words
            if isinstance(word, str) and word.strip()
        )
        normalized_words = tuple(word for word in normalized_words if word)
        if normalized_alias and normalized_words:
            loaded[normalized_alias] = normalized_words
    _BLACKLIST_CACHE.clear()
    _BLACKLIST_CACHE[cache_key] = loaded
    return loaded


def find_derivative_hit(
    text: str, spec: MetricSpec, *, window: int = 8
) -> tuple[str, str] | None:
    """命中 alias 的前后窗口（±window 字符）检出派生词则返回 (alias, 派生词)。

    在归一化文本上定位（去空白/标点、大小写折叠），与 ``_segment_metrics``
    的子串匹配同口径。未检出返回 None（正常 lock）。

    业务裁决 1（预测类诉求）：否定表支持特殊键 ``"*"``——其派生词
    （增量/预计/预测/前瞻）对**任意命中 alias** 生效：问句含未来导向词
    时统一判派生诉求，禁止用历史指标查询替代预测结果。
    """

    blacklist = derivative_blacklist()
    if not blacklist:
        return None
    compact_text = normalize_metric_name(text)
    if not compact_text:
        return None
    generic_derivatives = blacklist.get("*", ())
    for alias in spec.aliases:
        compact_alias = normalize_metric_name(alias)
        if not compact_alias or compact_alias not in compact_text:
            continue
        derivatives = blacklist.get(compact_alias, ())
        if not derivatives and not generic_derivatives:
            continue
        start = 0
        while True:
            index = compact_text.find(compact_alias, start)
            if index < 0:
                break
            begin = max(0, index - window)
            end = min(len(compact_text), index + len(compact_alias) + window)
            context = compact_text[begin:end]
            for derivative in (*derivatives, *generic_derivatives):
                if derivative in context:
                    return alias, derivative
            start = index + len(compact_alias)
    return None


_BOUNDARY_CACHE: dict[tuple[str, float], tuple[str, ...]] = {}


def research_boundary_terms() -> tuple[str, ...]:
    """研究边界词表（2026-09-01 最终方案 §5，业务裁决 2 落地）。

    ``backend/config/research_boundary_terms.yaml``，形态 ``{terms: [...]}``。
    命中边界词的诉求**永不硬路由**：进 ``unresolved_metrics`` 披露通道，
    走澄清门/用户裁决门。词表缺失或加载失败时静默回退空表。
    """

    path = _config_path("METRIC_BOUNDARY_TERMS_PATH", "research_boundary_terms.yaml")
    try:
        cache_key = (str(path), path.stat().st_mtime if path.exists() else 0.0)
    except OSError:
        cache_key = (str(path), 0.0)
    cached = _BOUNDARY_CACHE.get(cache_key)
    if cached is not None:
        return cached
    raw = _load_yaml_mapping(path)
    terms_raw = raw.get("terms")
    loaded: tuple[str, ...] = (
        tuple(
            str(term).strip()
            for term in terms_raw
            if isinstance(term, str) and term.strip()
        )
        if isinstance(terms_raw, list)
        else ()
    )
    _BOUNDARY_CACHE.clear()
    _BOUNDARY_CACHE[cache_key] = loaded
    return loaded


def get_metric_spec(value: str) -> MetricSpec | None:
    """Return an exact canonical match; callers retain deterministic fallbacks."""

    aliases = alias_map()
    compact = normalize_metric_name(value)
    if compact in aliases:
        return aliases[compact]
    # User-facing labels often add a harmless suffix such as "数据" or "变化".
    for alias, spec in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if alias and (compact.startswith(alias) or compact.endswith(alias)):
            return spec
    return None


def iter_metric_aliases() -> tuple[tuple[str, MetricSpec], ...]:
    """Expose (alias, spec) pairs for deterministic substring extraction.

    最长匹配优先（第二刀）：按别名长度降序，调用方对已被更长别名覆盖
    的短别名跳过，保证「在建产能」赢「产能」。
    """

    return tuple(
        (alias, spec)
        for alias, spec in sorted(alias_map().items(), key=lambda item: len(item[0]), reverse=True)
    )


def metric_expected_fields(spec: MetricSpec) -> list[str]:
    """Provider fields plus stable identity/time fields for each data family."""

    identity_by_skill: dict[SkillName, tuple[str, ...]] = {
        SkillName.FINANCE: ("股票代码", "股票简称", "报告期", "单位"),
        SkillName.BUSINESS: ("股票代码", "股票简称", "报告期", "单位"),
        SkillName.STOCK_SELECTOR: ("股票代码", "股票简称", "报告期", "单位"),
        SkillName.INDUSTRY: ("行业名称", "报告期", "单位", "来源"),
        SkillName.MACRO: ("指标名称", "报告期", "单位", "来源"),
    }
    return list(dict.fromkeys((*identity_by_skill.get(spec.primary_skill, ()), *spec.query_fields)))
