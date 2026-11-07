"""V2 bundle → ChainGraphSpec（模板渲染契约）。

为什么需要这一层：
- V2 研究产出的是严格证据模型（activity / assertion / evidence），**不含版式**；
- 交付的产业链图必须走 `render_chain_svg`（lane_grid 研报级模板：分列卡网格、
  品牌卡、画像列头、瓶颈/阶段角标），而不是 V2 自带的四栏文字清单；
- 因此这里把 bundle + profile 编译成 `ChainGraphSpec`，复用同一条模板渲染路径。

边界（V8 最终方案 §10.4）：
- 只消费 supported 断言与 accepted membership；候选不升级为事实；
- 每个公司参与项绑定 activity + role + assertion/evidence；
- 证据 id 走 `chain2:` 命名空间，供 A4/A5 统一解析；
- 名单角色不足以画成"实际供货"，edges 只来自 supported precedes。
"""

from __future__ import annotations

import re
from hashlib import sha256
from typing import Any

CHAIN_PREFIX = "chain2:"
MAX_BRANDS_PER_NODE = 8
MAX_ITEMS_PER_NODE = 6


_LEGACY_GRAIN_HINTS = ("农业", "垦", "种业", "粮", "北大荒", "苏垦")


def _legacy_role_companies(subject: str) -> dict[str, list[str]]:
    """Return legacy retrieval seeds for diagnostics only, never chart admission."""
    try:
        from chart_generator.chain_profile import detect_profile

        prof = detect_profile(subject)
    except Exception:
        return {}
    if not isinstance(prof, dict):
        return {}

    out: dict[str, list[str]] = {}
    brand = [str(x).strip() for x in (prof.get("leading_brand") or []) if str(x).strip()]
    if brand:
        out["brand"] = brand

    # upstream_anchor：企业 → 角色描述，用来区分"原料"与"包装"
    anchor = prof.get("upstream_anchor") or {}
    grain: list[str] = []
    packaging: list[str] = []
    for name, role in anchor.items():
        role_text = str(role)
        if "原料" in role_text or "辅料" in role_text:
            grain.append(str(name))
        elif "包装" in role_text:
            packaging.append(str(name))
    if not packaging:
        packaging = [str(x).strip() for x in (prof.get("cap_pool") or []) if str(x).strip()]
    if grain:
        out["grain"] = grain
    if packaging:
        out["packaging"] = packaging
    return out


def _activity_index(profile: Any) -> dict[str, Any]:
    return {str(a.activity_key): a for a in getattr(profile, "activities", []) or []}


def _activity_entity_map(bundle: Any) -> dict[str, str]:
    """Resolve versioned activity IDs, rejecting ambiguous legacy name matches."""
    from .membership import activity_id

    profile = getattr(bundle, "profile_snapshot", None)
    if profile is None:
        return {}
    by_name: dict[str, list[str]] = {}
    entity_ids = set()
    for ent in bundle.entities:
        if ent.entity_type == "activity":
            entity_ids.add(str(ent.entity_id))
            by_name.setdefault(str(ent.canonical_name), []).append(str(ent.entity_id))
    out = {}
    for policy in profile.activities:
        expected = activity_id(profile, bundle.scope, policy.activity_key)
        candidates = by_name.get(policy.name, [])
        if expected in entity_ids:
            out[policy.activity_key] = expected
        elif len(candidates) == 1:
            out[policy.activity_key] = candidates[0]
    return out


def _entity_names(bundle: Any) -> dict[str, str]:
    return {
        str(e.entity_id): str(e.canonical_name)
        for e in getattr(bundle, "entities", []) or []
    }


def _accepted_memberships(bundle: Any) -> dict[tuple[str, str], list[str]]:
    """Only admitted organization/activity claims can populate representative cards.

    Product offers, client relationships and legacy seed lists are not activity
    admission. An empty accepted set must deny admission rather than bypass it.
    """
    profile = getattr(bundle, "profile_snapshot", None)
    if profile is None:
        return {}
    policies = _activity_index(profile)
    activity_entities = _activity_entity_map(bundle)
    entities = {str(e.entity_id): e for e in bundle.entities}
    evidence = {str(e.evidence_id) for e in bundle.evidence}
    assertions = {str(a.assertion_id): a for a in bundle.assertions}
    decisions = {
        str(d.decision_id): d for d in bundle.membership_decisions
        if d.status == "accepted" and d.profile_version == profile.version
    }
    out: dict[tuple[str, str], list[str]] = {}
    for claim in bundle.assertions:
        if claim.status != "supported" or claim.predicate.value not in ("participates_in", "performs"):
            continue
        decision = decisions.get(str(claim.qualifiers.extra.get("membership_decision_id") or ""))
        if decision is None:
            continue
        policy = policies.get(decision.activity_key)
        if (policy is None or policy.company_display_policy in ("process", "scenario")
                or claim.subject_id != decision.organization_id
                or claim.object_id != activity_entities.get(decision.activity_key)
                or claim.qualifiers.org_role not in policy.allowed_roles):
            continue
        inputs = [assertions.get(str(aid)) for aid in decision.input_assertion_ids]
        if not inputs or any(
                a is None or a.status != "supported" or a.predicate.value != "offers"
                or a.subject_id != claim.subject_id for a in inputs):
            continue
        admitted_evidence = {eid for a in inputs for eid in a.evidence_ids}
        if not set(claim.evidence_ids) <= admitted_evidence:
            continue
        org = entities.get(str(claim.subject_id))
        if (org is None or org.entity_type != "organization"
                or org.identity_status in ("ambiguous", "merged")
                or not claim.evidence_ids or not set(claim.evidence_ids) <= evidence):
            continue
        out.setdefault((str(claim.subject_id), str(claim.object_id)), []).append(str(claim.assertion_id))
    return out


def bundle_to_topology(bundle: Any, *, subject: str = "") -> dict[str, Any]:
    """Compile policy structure and admitted roles without adding seed companies."""
    profile = getattr(bundle, "profile_snapshot", None)
    names = _entity_names(bundle)
    policies = _activity_index(profile) if profile is not None else {}
    activity_entities = _activity_entity_map(bundle)
    memberships = _accepted_memberships(bundle)
    by_assertion = {str(a.assertion_id): a for a in bundle.assertions}
    categories = {str(c.category_id): str(c.name) for c in profile.categories} if profile else {}
    nodes = []
    for key, policy in policies.items():
        activity_entity = activity_entities.get(key)
        companies, evidence_ids = [], []
        for (org_id, activity_id), assertion_ids in memberships.items():
            if activity_id != activity_entity:
                continue
            if names[org_id] not in companies:
                companies.append(names[org_id])
            for aid in assertion_ids:
                for eid in by_assertion[aid].evidence_ids:
                    ref = CHAIN_PREFIX + str(eid)
                    if ref not in evidence_ids:
                        evidence_ids.append(ref)
        nodes.append({
            "id": key, "label": policy.name, "stage": policy.stage,
            "key_products": [categories[c] for c in policy.category_ids if c in categories],
            "companies": companies,
            "description": policy.description,
            "is_core": policy.activity_kind == "brand",
            "evidence_ids": evidence_ids,
            "source_tier": "evidence" if evidence_ids else "industry_common",
            "bottleneck": False, "phase": "", "buyer": "",
        })
    by_entity = {v: k for k, v in activity_entities.items()}
    if profile is None:
        from .view import compile_chain_view

        for card in compile_chain_view(bundle).cards:
            by_entity[card.activity_id] = card.activity_id
            nodes.append({
                "id": card.activity_id, "label": card.title, "stage": card.stage,
                "key_products": card.products, "companies": card.companies,
                "description": card.description, "source_tier": "industry_common",
            })
    evidence = {e.evidence_id for e in bundle.evidence}
    edges = {}
    for claim in bundle.assertions:
        if (claim.status != "supported" or claim.predicate.value != "precedes"
                or not claim.evidence_ids or not set(claim.evidence_ids) <= evidence):
            continue
        source, target = by_entity.get(claim.subject_id), by_entity.get(claim.object_id)
        if source and target and source != target:
            relation_key = (source, target)
            stable_id = sha256(f"{source}\0{target}".encode()).hexdigest()[:16]
            edge = edges.setdefault(relation_key, {
                "source": source, "target": target, "label": "工序先后", "flow": "material",
                "edge_id": f"edge-{stable_id}", "assertion_ids": set(), "evidence_ids": set(),
            })
            edge["assertion_ids"].add(str(claim.assertion_id))
            edge["evidence_ids"].update(CHAIN_PREFIX + str(eid) for eid in claim.evidence_ids)
    relations = [
        {**edge, "assertion_ids": sorted(edge["assertion_ids"]), "evidence_ids": sorted(edge["evidence_ids"])}
        for _, edge in sorted(edges.items())
    ]
    release = str(getattr(bundle.quality, "release_status", "") or "")
    status = {"verified": "范围内已核验", "partial": "部分覆盖（结构待认证）",
              "draft": "结构草案", "failed": "研究失败"}.get(release, "覆盖未认证")
    topic = subject or str(bundle.scope.subject)
    missing = sum(not n["companies"] for n in nodes if n["id"] not in policies or policies[n["id"]].company_display_policy not in ("process", "scenario"))
    suffix = f" · {missing}个活动的代表企业待核" if missing else ""
    return {"title": f"{topic}产业链全景", "subtitle": status + suffix + " · 代表参与不表示特定客户供货",
            "core_product": "", "stages": [], "nodes": nodes, "edges": relations,
            "source": "v2_bundle", "release_status": release}


def bundle_to_chain_spec(bundle: Any, *, subject: str = "") -> Any:
    """bundle → ChainGraphSpec（走与 LLM 拓扑相同的模板契约）。"""
    from chart_generator.chain_topology import topology_to_spec

    top = bundle_to_topology(bundle, subject=subject)
    spec = topology_to_spec(top, fallback_title=str(top.get("title") or ""), verified_edges=True)
    # 溯源：标明这张图由 V2 证据包编译（不是 LLM 直出拓扑），便于诊断与版本核对
    spec.source = "v2_bundle"
    return spec
