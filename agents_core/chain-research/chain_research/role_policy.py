"""活动级角色政策与有界种子（D2，V8 最终方案 §9）。

三条硬规则：
1. **品牌与代工执行者必须分开**：品牌活动只接受品牌角色，ODM 活动只接受代工角色；
   同一主体可在不同活动里分别持角色，但不得互相顶替。
2. **名单只作候选**：registry 的角色记录只生成 seed candidate，不写 supported_assertions。
3. **名单不制造供货边**：角色通过不证明 supplies_to；本模块不产出任何交易边。
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

# 源名单的中文角色/层级 → 政策角色词
_ROLE_CANON: dict[str, str] = {
    "龙头": "leading",
    "核心": "core",
    "配套": "supporting",
    "整机品牌": "brand",
    "代工制造商": "odm",
    "ODM": "odm",
    "部件供应商": "component_supplier",
    "芯片设计商": "chip_designer",
    "存储厂商": "storage_vendor",
    "显示厂商": "display_vendor",
    "渠道商": "channel",
    "零售商": "retailer",
    "软件提供方": "software_vendor",
    "服务机构": "service_provider",
    "原料供应商": "raw_material_supplier",
    "包装供应商": "packaging_supplier",
    "白酒品牌": "brand",
    "生产商": "brand",
}

# 品牌活动 ↔ 代工活动 的角色隔离（不允许对方角色进入）
_ACTIVITY_ROLE_FAMILY: dict[str, str] = {
    "brand": "brand",
    "odm": "odm",
}


def normalize_role(role_text: str | None) -> str:
    """政策角色规范化；未知角色保持原样小写，不发明映射。"""
    text = str(role_text or "").strip()
    if not text:
        return ""
    return _ROLE_CANON.get(text, text.casefold())


def load_role_policy(profile_id: str) -> dict[str, Any]:
    """读取活动级角色政策（profile_data/role_policy.json）。"""
    raw = files("chain_research").joinpath("profile_data", "role_policy.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    policy = (data.get("profiles") or {}).get(profile_id)
    if policy is None:
        raise ValueError(f"未登记角色政策: {profile_id}")
    return policy


def activity_policy(profile, activity_key: str) -> dict[str, Any]:
    """取某活动的政策视图（来自 profile.activities + role_policy 覆盖）。"""
    activity = next(
        (a for a in profile.activities if str(getattr(a, "activity_key", "")) == activity_key),
        None,
    )
    if activity is None:
        raise ValueError(f"画像 {profile.profile_id} 无活动: {activity_key}")

    override = (load_role_policy(profile.profile_id).get("activities") or {}).get(activity_key, {})
    allowed = override.get("allowed_role_tokens")
    if allowed is None:
        allowed = [normalize_role(r) for r in (getattr(activity, "allowed_roles", None) or [])]
    return {
        "activity_key": activity_key,
        "stage": str(getattr(activity, "stage", "")),
        "activity_kind": str(getattr(activity, "activity_kind", "")),
        "allowed_role_tokens": [r for r in allowed if r],
        "role_family": _ACTIVITY_ROLE_FAMILY.get(activity_key, ""),
        "brand_odm_isolation": bool(override.get("brand_odm_isolation", False)),
        "policy_status": str(override.get("policy_status", "draft")),
        "review_notes": str(override.get("review_notes", "")),
        "seed_limit": int(override.get("seed_limit", 6)),
        "source_refs": list(getattr(activity, "source_refs", None) or []),
    }


def role_allowed(profile, activity_key: str, role_text: str | None) -> tuple[bool, str]:
    """判断某角色是否被该活动允许（含品牌/ODM 隔离）。"""
    policy = activity_policy(profile, activity_key)
    role = normalize_role(role_text)
    if not role:
        return False, "角色为空"
    family = policy["role_family"]
    if family == "brand" and role in ("odm",):
        return False, "品牌活动不接受代工角色（品牌与 ODM 必须分开）"
    if family == "odm" and role in ("brand",):
        return False, "ODM 活动不接受品牌角色（品牌与代工执行者必须分开）"
    if role not in policy["allowed_role_tokens"]:
        return False, f"角色 {role} 不在活动 {activity_key} 的允许列表 {policy['allowed_role_tokens']} 内"
    return True, ""


def seed_candidates(
    profile,
    theme_id: str,
    activity_key: str,
    registry,
    *,
    market_scope: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """从 registry 取**有界**种子候选（只用于检索规划，不写断言）。

    Args:
        profile: IndustryProfile。
        theme_id: registry 主题 id（如 theme-白酒）。
        activity_key: 画像活动键。
        registry: IndustryRegistry（可为 None：无发布时返回空）。
        market_scope: 市场范围（A股/港股/美股）。
        limit: 上限；缺省取活动政策的 seed_limit，并受全局硬上限 12 约束。

    Returns:
        候选列表，每项含 organization_id / name / role / reason。
    """
    if registry is None:
        return []
    policy = activity_policy(profile, activity_key)
    cap = min(int(limit if limit is not None else policy["seed_limit"]), 12)
    if cap <= 0:
        return []

    rows = registry.candidates_for(theme_id, activity_key=activity_key, market_scope=market_scope, limit=200)
    out: list[dict[str, Any]] = []
    for row in rows:
        role = normalize_role(row.get("role"))
        # 名单角色词是粗粒度（leading_brand_or_upstream），按活动所属环节归一
        if role.startswith("leading") or role.startswith("core") or role == "supporting":
            role = _stage_role(policy["stage"], policy["role_family"])
        ok, reason = role_allowed(profile, activity_key, role)
        if not ok:
            continue
        out.append({
            "organization_id": row.get("organization_id"),
            "name": row.get("organization_name"),
            "role": role,
            "role_status": row.get("role_status"),
            "reason": "registry 角色候选（仍需业务证据）",
        })
        if len(out) >= cap:
            break
    return out


def _stage_role(stage: str, family: str) -> str:
    """粗粒度名单角色按活动环节归一为政策角色词。"""
    if family == "brand":
        return "brand"
    if family == "odm":
        return "odm"
    if stage == "upstream":
        return "component_supplier"
    if stage == "downstream":
        return "channel"
    if stage == "support":
        return "service_provider"
    return "core"


def supplies_edge_allowed() -> tuple[bool, str]:
    """名单/角色判定**永不**产生交易边（supplies_to）。

    实际供货关系必须由该对主体的方向与时间范围证据单独支持；
    政策结构、工艺顺序与企业交易关系分开建模。
    """
    return False, "角色通过不证明客户供货：supplies_to 必须由主体对级证据单独支持"


def projector_keyword_would_shadow(profile, subject: str) -> bool:
    """旧关键词投影守卫：泛主题不得吞掉更细的专用画像。

    规则：若主题命中某专用画像的别名，但显式画像缺失，调用方必须按
    profile_id 精确解析而不是走关键词投影。
    """
    from chain_research.profiles import normalize_topic

    normalized = normalize_topic(subject)
    aliases = {normalize_topic(a) for a in [profile.subject, *(profile.aliases or [])]}
    if normalized in aliases:
        return False
    # 主题包含专用画像别名（如"白酒产业链"包含"白酒"）→ 需要专用画像优先
    return any(alias and alias in normalized for alias in aliases)
