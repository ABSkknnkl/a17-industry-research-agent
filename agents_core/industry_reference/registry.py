"""版本化只读主数据查询接口（D1）。

契约（V8 最终方案 §8.3）：
- 只读；发布版本由 current.json 指向，可回退。
- 接口返回 accepted/candidate/conflict/unknown 与依据，不只返回布尔白名单。
- 分类成分与产业链角色互不替代；rank/weight 不生成 leader_score。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from industry_reference.identity import (
    normalize_entity_name,
    resolve_organization,
    resolve_security,
    split_security_token,
)
from industry_reference.models import ResolutionResult


class IndustryRegistry:
    """已发布行业主数据的只读视图。"""

    def __init__(self, release_dir: Path) -> None:
        self.release_dir = Path(release_dir)
        self.manifest: dict[str, Any] = self._load_json("manifest.json", default={})
        self.organizations: list[dict[str, Any]] = self._load_jsonl("organizations.jsonl")
        self.securities: list[dict[str, Any]] = self._load_jsonl("securities.jsonl")
        self.classifications: list[dict[str, Any]] = self._load_jsonl("classifications.jsonl")
        self.roles: list[dict[str, Any]] = self._load_jsonl("role_candidates.jsonl")
        self.conflicts: list[dict[str, Any]] = self._load_jsonl("conflicts.jsonl")

        self._org_by_id = {o.get("organization_id"): o for o in self.organizations}
        # 把组织名挂到证券记录上，便于解析时回填
        for sec in self.securities:
            org = self._org_by_id.get(sec.get("organization_id")) or {}
            sec.setdefault("organization_name", org.get("canonical_name"))

    # ── 加载 ────────────────────────────────────────────────────────────
    def _load_json(self, name: str, *, default: Any = None) -> Any:
        path = self.release_dir / name
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_jsonl(self, name: str) -> list[dict[str, Any]]:
        path = self.release_dir / name
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    @classmethod
    def load(cls, base_dir: Path | None = None, release_id: str | None = None) -> "IndustryRegistry":
        """加载指定发布版本；缺省按 current.json 指针。"""
        root = Path(base_dir) if base_dir else _default_base()
        releases = root / "releases"
        if release_id:
            target = releases / release_id
        else:
            pointer = root / "current.json"
            if not pointer.exists():
                raise FileNotFoundError(
                    f"缺少 current.json 发布指针：{pointer}（请先运行 import_industry_reference.py）"
                )
            current = json.loads(pointer.read_text(encoding="utf-8"))
            target = releases / str(current.get("release_id") or "")
        if not target.exists():
            raise FileNotFoundError(f"发布版本不存在: {target}")
        return cls(target)

    @classmethod
    def try_load(cls, base_dir: Path | None = None) -> "IndustryRegistry | None":
        """可选加载：未发布时返回 None（调用方走既有证据发现路径）。"""
        try:
            return cls.load(base_dir)
        except FileNotFoundError:
            return None

    # ── 身份 ────────────────────────────────────────────────────────────
    def resolve_security(self, token: str, scope: dict[str, Any] | None = None) -> ResolutionResult:
        """解析证券身份；scope 可限定 market（A股/港股/美股）。"""
        result = resolve_security(token, self.securities)
        if scope and scope.get("market") and result.status in ("accepted", "candidate"):
            target_org = result.organization_id
            markets = {
                s.get("market") for s in self.securities if s.get("organization_id") == target_org
            }
            if scope["market"] not in markets:
                return ResolutionResult(
                    status="conflict",
                    organization_id=result.organization_id,
                    canonical_name=result.canonical_name,
                    reason=f"主体存在，但不在请求市场 {scope['market']}（实际：{sorted(m for m in markets if m)}）",
                )
        return result

    def resolve_organization(self, name_or_security: str) -> ResolutionResult:
        return resolve_organization(name_or_security, self.organizations, self.securities)

    # ── 分类成分 ────────────────────────────────────────────────────────
    def classifications_for(self, security_id: str) -> list[dict[str, Any]]:
        """返回该证券的申万成分记录（可能多条，保留 rank/weight 与源声明）。"""
        return [c for c in self.classifications if c.get("security_id") == security_id]

    # ── 角色候选 ────────────────────────────────────────────────────────
    def candidates_for(
        self,
        theme_id: str,
        *,
        activity_key: str | None = None,
        role: str | None = None,
        market_scope: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """按主题/活动/角色取**有界**候选（不写 supported_assertions）。

        规则：
        - 只返回 accepted / candidate（conflict 与 rejected 不进入候选）。
        - 市场范围过滤：主体至少有一个证券落在 market_scope 内。
        - limit 为硬上限，默认 12，防止把整张名单灌进检索。
        """
        cap = 12 if limit is None else max(0, int(limit))
        out: list[dict[str, Any]] = []
        for r in self.roles:
            if str(r.get("theme_id") or "") != str(theme_id):
                continue
            if str(r.get("role_status") or "") not in ("accepted", "candidate"):
                continue
            if activity_key and str(r.get("activity_key") or "") != activity_key:
                continue
            if role and str(r.get("role") or "") != role:
                continue
            if market_scope:
                org_markets = {
                    s.get("market") for s in self.securities
                    if s.get("organization_id") == r.get("organization_id")
                }
                if not (org_markets & set(market_scope)):
                    continue
            out.append(r)
        # 稳定排序：已接受优先，其次源声明层级，再按名称
        tier_rank = {"龙头": 0, "核心": 1, "配套": 2, "": 3}
        out.sort(key=lambda r: (
            0 if r.get("role_status") == "accepted" else 1,
            tier_rank.get(str(r.get("source_declared_tier") or ""), 3),
            str(r.get("organization_name") or ""),
        ))
        return out[:cap]

    def role_decision(
        self,
        organization_id: str,
        scope: dict[str, Any],
        role: str,
    ) -> dict[str, Any]:
        """查询某主体在给定主题/活动下是否具备某角色，并给出依据。"""
        theme_id = str(scope.get("theme_id") or "")
        activity_key = scope.get("activity_key")
        matched = [
            r for r in self.roles
            if r.get("organization_id") == organization_id
            and str(r.get("theme_id") or "") == theme_id
            and (activity_key is None or str(r.get("activity_key") or "") == str(activity_key))
            and str(r.get("role") or "") == role
        ]
        if not matched:
            conflict = [
                c for c in self.conflicts
                if c.get("kind") == "severe_identity_conflict"
                and organization_id in str(c.get("names") or "")
            ]
            if conflict:
                return {
                    "status": "conflict",
                    "reason": "该主体涉及身份冲突，角色不可判定",
                    "evidence": conflict,
                }
            return {
                "status": "unknown",
                "reason": "名单无该角色记录；不走默认放行，继续按证据发现",
                "evidence": [],
            }
        accepted = [r for r in matched if r.get("role_status") == "accepted"]
        status = "accepted" if accepted else "candidate"
        return {
            "status": status,
            "reason": (
                "名单角色命中（名单只作候选，仍需业务证据才能升级为 supported）"
                if accepted
                else "角色候选：名单出现不等于具备能力，需另行业务证据核验"
            ),
            "evidence": matched,
        }

    # ── 主题/画像 ───────────────────────────────────────────────────────
    def themes(self) -> list[dict[str, Any]]:
        """已发布主题清单（来自角色记录），含候选数量。"""
        agg: dict[str, dict[str, Any]] = {}
        for r in self.roles:
            tid = str(r.get("theme_id") or "")
            if not tid:
                continue
            entry = agg.setdefault(tid, {
                "theme_id": tid,
                "theme_name": r.get("theme_name") or tid,
                "role_count": 0,
                "activities": set(),
            })
            entry["role_count"] += 1
            if r.get("activity_key"):
                entry["activities"].add(str(r["activity_key"]))
        return [
            {**v, "activities": sorted(v["activities"])}
            for v in sorted(agg.values(), key=lambda x: x["theme_id"])
        ]


def _default_base() -> Path:
    """默认主数据根目录：仓库内 data/industry_reference。"""
    return Path(__file__).resolve().parents[2] / "data" / "industry_reference"
