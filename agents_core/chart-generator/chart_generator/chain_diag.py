"""产业链图诊断引擎：23 条规则 → 结构化 Finding（P1，2026-10-19）。

═════════════════════════════════════════════════════════════════════════════
为什么需要它
═════════════════════════════════════════════════════════════════════════════

项目原有的验收手段是 ``scratch/verify_f8_f14_offline.py``：拿真实 A2 拓扑重跑规则，
输出人读的 ``print``。它有两个硬伤——

1. **只覆盖 6 个硬编码主题**，无法扩到 50 个行业；
2. **问题只有一句话**，不带规则编号/代码位置/修复动作，定位靠人回忆。

本模块把同样的断言升级为**结构化、可批量、可定位**的 Finding：

    {"rule_id":"CHAIN-BRAND-02", "severity":"P0",
     "node_label":"组件制造", "companies":["福斯特"],
     "hint":"从品牌卡移除，归位到上游「胶膜」节点",
     "code_ref":"chart_generator/chain_profile.py:730 brand_card_violations"}

拿到 ``code_ref`` 能直接打开对应函数，拿到 ``hint`` 知道改什么，
拿到 ``companies`` 能精确复现——这是"让 AI 快速找出问题"的前提。

═════════════════════════════════════════════════════════════════════════════
设计约束
═════════════════════════════════════════════════════════════════════════════

1. **只读**：本模块绝不修改拓扑；修复仍走 ``chain_topology.repair_topology``。
2. **不重复实现**：能调用既有函数就调用（``core_misplacement`` /
   ``brand_card_violations`` / ``wrong_fit_hits`` / ``lint_chain_svg``），
   避免"裁判有两套实现"的漂移（F17 的教训）。
3. **无基准不断言**：``leading_brand`` 为空（L0 画像）时，品牌卡相关规则**全部跳过**，
   只报结构问题——这是"宁可留空、不可错判"的延伸。
4. **确定性**：同一份拓扑跑两次结果必须完全一致（无随机、无时间依赖）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from chart_generator.chain_lint import (      # 同源导入：禁止复制这几条正则（F17 教训）
    _FINANCE_NUM_WORDS,
    _MODEL_TOKEN_RE,
    _NUM_RE,
    _PLACEHOLDER_WORDS,
    is_finance_number,
    sanitize_text_no_numbers,
)

from chart_generator.chain_profile import (
    banned_companies,
    base_leading_companies,
    brand_card_violations,
    brand_scope_warnings,
    cert_bodies,
    detect_profile,
    is_cert_node,
    is_leader_name,
    leading_companies,
    profile_source,
    profile_warnings,
    role_anchor,
    upstream_leaders,
    wrong_fit_hits,
    wrong_fit_map,
)
from chart_generator.chain_loader import profile_level
from chart_generator.chain_topology import (
    core_misplacement,
    degree_limit,
    topology_to_spec,
    validate_topology,
)

logger = logging.getLogger(__name__)

# 严重度：P0 = 必须修（专业观众一眼看出错），P1 = 应修（信息不完整），P2 = 提示
_P0, _P1, _P2 = "P0", "P1", "P2"

# 规则清单（与实施方案 §3.3 一一对应；新增规则必须同时补 test_chain_diag.py 的正反例）
RULE_REGISTRY: dict[str, dict[str, str]] = {
    "CHAIN-STRUCT-01": {"sev": _P0, "cat": "structure", "name": "节点/阶段完整性"},
    "CHAIN-STRUCT-02": {"sev": _P0, "cat": "structure", "name": "有且仅有 1 个 is_core"},
    "CHAIN-STRUCT-03": {"sev": _P0, "cat": "structure", "name": "单节点度数不超限"},
    "CHAIN-STRUCT-04": {"sev": _P0, "cat": "structure", "name": "实物流不指向研发/软件节点"},
    "CHAIN-STRUCT-05": {"sev": _P1, "cat": "structure", "name": "瓶颈只在上游且 1-3 个"},
    "CHAIN-STRUCT-06": {"sev": _P1, "cat": "structure", "name": "下游节点有 phase/buyer"},
    "CHAIN-STRUCT-07": {"sev": _P0, "cat": "structure", "name": "evidence_ids 不得引用不存在的编号"},
    "CHAIN-STRUCT-08": {"sev": _P0, "cat": "structure", "name": "企业跨节点唯一性"},
    "CHAIN-STRUCT-09": {"sev": _P0, "cat": "structure", "name": "企业可追溯（白名单/证据原文）"},
    "CHAIN-BRAND-01": {"sev": _P0, "cat": "brand", "name": "is_core 必须挂在中游"},
    "CHAIN-BRAND-02": {"sev": _P1, "cat": "brand", "name": "品牌卡成员待核（名单外）"},
    "CHAIN-BRAND-03": {"sev": _P0, "cat": "brand", "name": "品牌卡不含上游龙头"},
    "CHAIN-BRAND-04": {"sev": _P1, "cat": "brand", "name": "品牌卡 2-8 家"},
    "CHAIN-BRAND-05": {"sev": _P0, "cat": "brand", "name": "品牌卡与上游节点企业不重叠"},
    "CHAIN-CAP-01": {"sev": _P1, "cat": "capability", "name": "上/中游无空企业卡"},
    "CHAIN-CAP-02": {"sev": _P1, "cat": "capability", "name": "认证卡有机构兜底"},
    "CHAIN-CAP-03": {"sev": _P2, "cat": "capability", "name": "能力卡企业有角色锚点"},
    "CHAIN-SEM-01": {"sev": _P0, "cat": "semantic", "name": "wrong_fit 语义禁配零命中"},
    "CHAIN-SEM-02": {"sev": _P0, "cat": "semantic", "name": "ban_anywhere 全局禁配零命中"},
    "CHAIN-SEM-03": {"sev": _P1, "cat": "semantic", "name": "品牌卡不越出当前细分"},
    "CHAIN-TEXT-01": {"sev": _P0, "cat": "text", "name": "全图无数字"},
    "CHAIN-TEXT-02": {"sev": _P0, "cat": "text", "name": "无占位符"},
    "CHAIN-TEXT-03": {"sev": _P2, "cat": "text", "name": "节点名 ≤8 字、说明 ≤20 字"},
    "CHAIN-TEXT-04": {"sev": _P0, "cat": "text", "name": "清洗器误删型号/等级文本"},
    "CHAIN-RENDER-01": {"sev": _P0, "cat": "render", "name": "SVG 合法且无虚格"},
    "CHAIN-COVER-01": {"sev": _P2, "cat": "coverage", "name": "L0 画像须标注「名单待核」"},
}

# 代码位置索引：Finding.code_ref 直接指到可修改的地方
_CODE_REF = {
    "CHAIN-STRUCT": "chart_generator/chain_topology.py:847 validate_topology",
    "CHAIN-BRAND-01": "chart_generator/chain_topology.py:341 core_misplacement",
    "CHAIN-BRAND-02": "chart_generator/chain_profile.py:730 brand_card_violations",
    "CHAIN-BRAND-03": "chart_generator/chain_profile.py:730 brand_card_violations",
    "CHAIN-BRAND-04": "chart_generator/chain_topology.py:713 strengthen_brand_card",
    "CHAIN-BRAND-05": "chart_generator/chain_topology.py:1059 repair_topology",
    "CHAIN-CAP": "chart_generator/chain_topology.py:593 fill_empty_capability_cards",
    "CHAIN-SEM": "chart_generator/chain_profile.py:695 wrong_fit_map",
    "CHAIN-TEXT": "chart_generator/chain_lint.py:120 lint_chain_texts",
    "CHAIN-RENDER": "chart_generator/chain_lint.py:260 lint_chain_svg",
    "CHAIN-COVER": "chart_generator/chain_loader.py:200 profile_level",
}


def _code_ref(rule_id: str) -> str:
    if rule_id in _CODE_REF:
        return _CODE_REF[rule_id]
    return _CODE_REF.get(rule_id.rsplit("-", 1)[0], "")


# ── 数据结构 ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Finding:
    """一条可定位的问题。字段刻意少而准，便于 AI 直接消费。"""

    rule_id: str
    severity: str
    category: str
    message: str
    node_id: str | None = None
    node_label: str | None = None
    companies: tuple[str, ...] = ()
    hint: str = ""
    code_ref: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "code_ref": self.code_ref or _code_ref(self.rule_id),
        }
        if self.node_id:
            out["node_id"] = self.node_id
        if self.node_label:
            out["node_label"] = self.node_label
        if self.companies:
            out["companies"] = list(self.companies)
        if self.hint:
            out["hint"] = self.hint
        if self.evidence:
            out["evidence"] = self.evidence
        return out


@dataclass
class DiagReport:
    subject: str
    profile_key: str
    scope_key: str
    level: str
    stage: str
    findings: list[Finding]
    metrics: dict[str, Any]
    profile_source: str = ""
    profile_warnings: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if any(f.severity == _P0 for f in self.findings):
            return "fail"
        if any(f.severity == _P1 for f in self.findings):
            return "warn"
        return "pass"

    def by_rule(self) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = {}
        for f in self.findings:
            out.setdefault(f.rule_id, []).append(f)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "profile": {"key": self.profile_key, "scope": self.scope_key, "level": self.level},
            "stage": self.stage,
            "verdict": self.verdict,
            "metrics": self.metrics,
            "findings": [f.to_dict() for f in self.findings],
            "profile_source": self.profile_source,
            "profile_warnings": self.profile_warnings,
        }


# ── 主入口 ────────────────────────────────────────────────────────────────

def diagnose(
    topo: dict[str, Any],
    *,
    subject: str = "",
    svg: str | None = None,
    stage: str = "post_repair",
    allowed_companies: set[str] | None = None,
    allowed_evidence: set[str] | None = None,
    evidence_text: str | None = None,
) -> DiagReport:
    """对一份拓扑做全量诊断（只读，不修复）。

    Args:
        topo: A2 产出的 ``industry_chain_topology``（或 repair 后的版本）。
        subject: 行业主题；为空时从 ``topo.title``/``core_product`` 推断。
        svg: 已渲染的 SVG 文本；为空则跳过产物级检查。
        stage: ``"post_repair"``（默认，评估**最终出图**质量）或
               ``"pre_repair"``（评估 **A2 原始产出**，此时重复/越界预期会被
               repair 修掉，报告里只作输入质量信号）。
        allowed_companies/allowed_evidence/evidence_text: 证据白名单，透传给结构校验。
    """
    subj = _subject(topo, subject)
    prof = detect_profile(subj)
    nodes = [n for n in (topo.get("nodes") or []) if isinstance(n, dict)]
    core = next((n for n in nodes if n.get("is_core")), None)

    findings: list[Finding] = []
    findings += _check_structure(topo, nodes, subj,
                                 allowed_companies=allowed_companies,
                                 allowed_evidence=allowed_evidence,
                                 evidence_text=evidence_text)
    findings += _scan_topology_text(nodes)
    findings += _check_brand(topo, nodes, core, subj, prof)
    findings += _check_capability(nodes, subj, prof)
    findings += _check_semantics(nodes, subj, core)
    if svg:
        findings += _check_rendered(topo, nodes, svg)
    findings += _check_coverage(prof, subj)

    # 去重（同一 rule+节点+公司 只报一次），保持稳定顺序
    seen: set[tuple[str, str, str]] = set()
    uniq: list[Finding] = []
    for f in findings:
        sig = (f.rule_id, f.node_id or "", ",".join(f.companies))
        if sig in seen:
            continue
        seen.add(sig)
        uniq.append(f)

    severity_order = {_P0: 0, _P1: 1, _P2: 2}
    uniq.sort(key=lambda f: (severity_order.get(f.severity, 9), f.rule_id, f.node_label or ""))

    return DiagReport(
        subject=subj,
        profile_key=str(prof.get("key") or ""),
        scope_key=str(prof.get("scope_key") or ""),
        level=profile_level(prof),
        stage=stage,
        findings=uniq,
        metrics=_metrics(topo, nodes, core, uniq, prof),
        profile_source=profile_source(),
        profile_warnings=profile_warnings(),
    )


# ── 结构规则 ──────────────────────────────────────────────────────────────

_RD_HINTS = ("研发", "算法", "仿真", "设计", "软件", "eda", "ip授权", "授权", "数据", "训练")


def _check_structure(topo, nodes, subject, *, allowed_companies, allowed_evidence,
                     evidence_text) -> list[Finding]:
    out: list[Finding] = []

    # CHAIN-STRUCT-01：节点/阶段完整性
    if not nodes:
        out.append(_mk("CHAIN-STRUCT-01", "拓扑没有任何节点", hint="检查 A2 是否产出 industry_chain_topology"))
        return out
    stages = {str(n.get("stage") or "") for n in nodes}
    missing = [s for s in ("upstream", "midstream", "downstream") if s not in stages]
    if missing:
        out.append(_mk("CHAIN-STRUCT-01",
                       f"缺少阶段：{'、'.join(missing)}",
                       hint="补齐四段结构；纯软件/服务业可改分层模板，但仍需 stage 归类"))
    if len(nodes) < 8:
        out.append(_mk("CHAIN-STRUCT-01", f"节点过少（{len(nodes)} 个），图会缺块",
                       hint="上游 6-10 / 中游 4-5 / 下游 5-6 / 配套 4-5"))

    # CHAIN-STRUCT-02：有且仅有 1 个 is_core
    core_ids = [str(n.get("id")) for n in nodes if n.get("is_core")]
    if len(core_ids) == 0:
        out.append(_mk("CHAIN-STRUCT-02", "没有 is_core=true 的核心节点",
                       hint="把整机/本体节点标为 is_core（研发节点不能标）"))
    elif len(core_ids) > 1:
        labels = "、".join(str(_by_id(nodes, i).get("label") or i) for i in core_ids)
        out.append(_mk("CHAIN-STRUCT-02", f"is_core 有 {len(core_ids)} 个（{labels}），必须且仅有 1 个",
                       hint="只保留整机/本体那一个，其余置 false", companies=tuple()))

    # CHAIN-STRUCT-03：度数上限
    indeg: dict[str, int] = {}
    for e in (topo.get("edges") or []):
        tgt = str(e.get("target") or "")
        indeg[tgt] = indeg.get(tgt, 0) + 1
    for n in nodes:
        nid = str(n.get("id") or "")
        limit = degree_limit(str(n.get("stage") or ""), bool(n.get("is_core")))
        if indeg.get(nid, 0) > limit:
            out.append(_mk("CHAIN-STRUCT-03",
                           f"节点「{n.get('label')}」入线 {indeg[nid]} 条，超过上限 {limit}",
                           node=n, hint="合并上游连线或改由兄弟节点承接"))

    # CHAIN-STRUCT-04：实物流不得指向研发/软件节点
    for e in (topo.get("edges") or []):
        if str(e.get("flow") or "") != "material":
            continue
        tgt = _by_id(nodes, str(e.get("target") or ""))
        label = str(tgt.get("label") or "")
        if any(h in label.lower() for h in _RD_HINTS):
            out.append(_mk("CHAIN-STRUCT-04",
                           f"实物流指向研发/软件节点「{label}」",
                           node=tgt, hint="研发节点只出图纸与授权，改 technical 流或换目标为制造端"))

    # CHAIN-STRUCT-05：瓶颈
    bottlenecks = [n for n in nodes if n.get("bottleneck")]
    bad = [n for n in bottlenecks if str(n.get("stage") or "") != "upstream"]
    for n in bad:
        out.append(_mk("CHAIN-STRUCT-05", f"瓶颈标在了「{n.get('label')}」（{n.get('stage')}），只能标上游",
                       node=n, hint="移除 bottleneck 或改标到真正的上游卡脖子环节"))
    if len(bottlenecks) > 3:
        out.append(_mk("CHAIN-STRUCT-05", f"瓶颈标记 {len(bottlenecks)} 个，超过 3 个",
                       hint="只保留真正卡脖子的 1-3 个"))

    # CHAIN-STRUCT-06：下游 phase/buyer
    for n in nodes:
        if str(n.get("stage") or "") != "downstream":
            continue
        miss = [k for k in ("phase", "buyer") if not str(n.get(k) or "").strip()]
        if miss:
            out.append(_mk("CHAIN-STRUCT-06",
                           f"下游节点「{n.get('label')}」缺 {'/'.join(miss)}",
                           node=n, hint="补 phase（已落地/试点中/示范期/远期）与 buyer（采购方类型）"))

    # CHAIN-STRUCT-07：evidence_ids
    if allowed_evidence is not None:
        for n in nodes:
            for eid in (n.get("evidence_ids") or []):
                if str(eid) not in allowed_evidence:
                    out.append(_mk("CHAIN-STRUCT-07",
                                   f"节点「{n.get('label')}」引用不存在的证据 {eid}",
                                   node=n, hint="删除该编号或改为真实存在的证据"))

    # CHAIN-STRUCT-08：企业跨节点唯一性（产业链图最忌讳的错误）
    owner: dict[str, str] = {}
    for n in nodes:
        nid = str(n.get("id") or "")
        for c in (n.get("companies") or []):
            name = str(c).strip()
            if not name:
                continue
            prev = owner.get(name)
            if prev and prev != nid:
                out.append(_mk("CHAIN-STRUCT-08",
                               f"「{name}」同时出现在「{_label(nodes, prev)}」与「{_label(nodes, nid)}」",
                               node=n, companies=(name,),
                               hint="一家公司只能出现在一个环节：按主营归属，另一处删除"))
            else:
                owner[name] = nid

    # CHAIN-STRUCT-09：企业可追溯（白名单 / 证据原文 ≥3 字）
    if allowed_companies:
        ev = evidence_text or ""
        for n in nodes:
            if str(n.get("source_tier")) == "industry_common":
                continue
            for c in (n.get("companies") or []):
                name = str(c).strip()
                if not name:
                    continue
                if name not in allowed_companies and not (len(name) >= 3 and name in ev):
                    out.append(_mk("CHAIN-STRUCT-09",
                                   f"企业「{name}」不在证据白名单中",
                                   node=n, companies=(name,),
                                   hint="改从 A1 evidence_index 取企业，或确认它出现在证据原文里"))
    return out


# ── 文本规则（**清洗之前**扫原文） ────────────────────────────────────────

def _scan_topology_text(nodes) -> list[Finding]:
    """扫拓扑原文的数值 / 占位符 / **被清洗误删的型号文本**。

    为什么必须单独扫：渲染前 ``sanitize_text_no_numbers`` 会把含数值的整句删掉，
    SVG 体检**根本看不见被删的内容**（F17 的教训：清洗删掉的东西体检永远看不见）。

    CHAIN-TEXT-04 的来源（2026-10-19 实测）：F17 只给"≤12 字"的型号文本加了豁免，
    ``L2+级智驾感知核心传感器``（14 字）仍被整段删空 → 车载激光雷达「ADAS智驾」卡
    的描述直接消失，lint 报 0 问题。诊断必须在源头把这个"静默丢数据"抓出来。
    """
    out: list[Finding] = []
    for n in nodes:
        fields: list[tuple[str, str]] = [
            ("label", str(n.get("label") or "")),
            ("description", str(n.get("description") or "")),
        ]
        fields += [("key_products", str(x)) for x in (n.get("key_products") or [])]

        for field_name, text in fields:
            if not text.strip():
                continue
            for clause in re.split(r"[，。；;,.]", text):
                clause = clause.strip()
                if not clause:
                    continue
                if any(w in clause for w in _PLACEHOLDER_WORDS):
                    out.append(_mk("CHAIN-TEXT-02",
                                   f"{field_name} 含占位符「{clause}」",
                                   node=n, hint="删除占位符，留空或写真实内容"))
                    continue
                if not _NUM_RE.search(clause):
                    continue
                if is_finance_number(clause):
                    out.append(_mk("CHAIN-TEXT-01",
                                   f"{field_name} 含数值「{clause}」",
                                   node=n,
                                   hint="产业链图只保留结构与文字，删除份额/产能/营收等数值"))
                    continue
                # 型号/等级代号：不应该被清洗。若清洗器把它删空，就是静默丢数据。
                cleaned = sanitize_text_no_numbers(clause, max_len=999)
                if not cleaned.strip():
                    out.append(_mk("CHAIN-TEXT-04",
                                   f"{field_name} 的型号文本「{clause}」会被清洗器整段删除",
                                   node=n,
                                   hint="检查 chain_lint.is_finance_number 的型号豁免分支"))
    return out


# ── 品牌卡规则 ────────────────────────────────────────────────────────────

def _check_brand(topo, nodes, core, subject, prof) -> list[Finding]:
    out: list[Finding] = []
    if core is None:
        return out

    # CHAIN-BRAND-01：is_core 必须在中游
    move = core_misplacement(topo)
    if move is not None:
        cur_id, want_id = move
        out.append(_mk("CHAIN-BRAND-01",
                       f"is_core 挂错：「{_label(nodes, cur_id)}」应改为「{_label(nodes, want_id)}」",
                       node=_by_id(nodes, cur_id),
                       hint="把 is_core 移到整机/本体节点（企业数最多、最像核心产品）"))

    comps = [str(c).strip() for c in (core.get("companies") or []) if str(c).strip()]
    # CHAIN-BRAND-02 判定分两层（2026-10-19 实测校准）：
    #   · **细分名单 或 基础名单**命中 → 合法。消费无人机 scope 名单是道通/臻迪/昊翔，
    #     它们不在 aircraft 基础名单（大疆/亿航/纵横），只查基础会全部误报；
    #   · 在基础名单但不在细分名单 → 属 F14「标题与内容不一致」，只告警（CHAIN-SEM-03），
    #     不升 P0。半导体「刻蚀/沉积」品牌卡出现清洗/CMP 厂商就是这一类。
    scoped_leaders = leading_companies(subject)
    base_leaders = base_leading_companies(subject)
    ups = upstream_leaders(subject)

    # CHAIN-BRAND-02：品牌卡成员不在行业龙头名单 → **P1 待核，不阻断**。
    #
    # 🔴 2026-10-19 口径校准（用户质疑"其他行业怎么办"后修正）：
    # 旧实现把它当 P0 并建议"从品牌卡移除"——这是**用名单做排除式判定**，
    # 名单不全就会误杀真龙头（北京君正：存储芯片厂商，画像名单漏了它）。
    # 生产链路 `classify_company_traceability` 的既定策略是"真名降级 industry_common、
    # 画「待核」角标、**不删除**"（F1 已修），诊断必须与之一致，否则就是 F17 的
    # "两处口径不一致"。名单只用于提示与补强，**永远不作为删除依据**。
    if scoped_leaders or base_leaders:
        outside = [c for c in comps
                   if not is_leader_name(c, scoped_leaders)
                   and not is_leader_name(c, base_leaders)]
        if outside:
            out.append(_mk("CHAIN-BRAND-02",
                           f"品牌卡「{core.get('label')}」有 {len(outside)} 家不在行业龙头名单（待核）："
                           f"{'、'.join(outside)}",
                           node=core, companies=tuple(outside),
                           hint="人工/联网核实是否为本行业整机厂：是→补进 leading_brand；"
                                "否→加入 wrong_fit。在核实前保留在图上并标注「待核」，不要直接删除"))

    # CHAIN-BRAND-03：品牌卡不含上游龙头
    if ups:
        viol = brand_card_violations(topo, subject)
        if viol:
            out.append(_mk("CHAIN-BRAND-03",
                           f"品牌卡混入上游供应商：{'、'.join(viol)}",
                           node=core, companies=tuple(viol),
                           hint="归位到上游对应环节（rehome_brand_card_outliers）"))

    # CHAIN-BRAND-04：数量（**无基准不断言**：L0 画像没有 leading_brand，
    # 不知道"该有几家"，报"0 家"只会制造噪声）
    if scoped_leaders or base_leaders:
        if len(comps) > 8:
            out.append(_mk("CHAIN-BRAND-04", f"品牌卡 {len(comps)} 家，超过上限 8 家",
                           node=core, hint="只保留真实整机厂，其余下沉到能力卡/上游"))
        elif len(comps) < 2:
            out.append(_mk("CHAIN-BRAND-04", f"品牌卡只有 {len(comps)} 家，渲染不出本体品牌栏",
                           node=core, hint="至少 2 家；不足时用 leading_brand 兜底（strengthen_brand_card）"))

    # CHAIN-BRAND-05：品牌卡与上游节点重叠
    up_names: set[str] = set()
    for n in nodes:
        if str(n.get("stage") or "") == "upstream":
            up_names |= {str(c).strip() for c in (n.get("companies") or []) if str(c).strip()}
    conflict = sorted(set(comps) & up_names)
    if conflict:
        out.append(_mk("CHAIN-BRAND-05",
                       f"同一公司同时出现在品牌卡与上游：{'、'.join(conflict)}",
                       node=core, companies=tuple(conflict),
                       hint="按主营二选一：整机厂留品牌卡，零部件厂留上游"))

    # CHAIN-SEM-03：细分越界（不阻断）
    scope_out = brand_scope_warnings(topo, subject)
    if scope_out:
        out.append(_mk("CHAIN-SEM-03",
                       f"品牌卡出现当前细分之外的厂商：{'、'.join(scope_out)}",
                       node=core, companies=tuple(scope_out),
                       hint="标题已限定细分时应收窄品牌卡；否则把标题泛化"))
    return out


# ── 能力卡规则 ────────────────────────────────────────────────────────────

def _check_capability(nodes, subject, prof) -> list[Finding]:
    out: list[Finding] = []
    bodies = cert_bodies(subject)
    for n in nodes:
        label = str(n.get("label") or "")
        comps = [str(c).strip() for c in (n.get("companies") or []) if str(c).strip()]
        stage = str(n.get("stage") or "")
        if stage in ("upstream", "midstream") and not comps:
            out.append(_mk("CHAIN-CAP-01", f"能力卡「{label}」没有企业",
                           node=n, hint="填该环节专业公司；无合适候选则留空并在报告登记"))
        if is_cert_node(label) and not comps and not bodies:
            out.append(_mk("CHAIN-CAP-02", f"认证卡「{label}」无机构兜底",
                           node=n, hint="在画像 cert_bodies 补该行业真实认证机构"))
        # 认证卡走 cert_bodies，不参与角色锚点判定（否则鉴衡/SGS 会被误报）
        if is_cert_node(label):
            continue
        if comps and stage in ("upstream", "midstream") and not n.get("is_core"):
            anchors = role_anchor(subject) or {}
            if anchors:
                unmatched = [c for c in comps if c not in anchors and c not in (prof.get("cap_pool") or [])]
                if unmatched and len(unmatched) == len(comps):
                    out.append(_mk("CHAIN-CAP-03",
                                   f"能力卡「{label}」企业无法归属到任何锚点：{'、'.join(unmatched[:4])}",
                                   node=n, companies=tuple(unmatched[:4]),
                                   hint="确认这些公司是否真做这个环节；必要时补 upstream_anchor"))
    return out


# ── 语义规则 ──────────────────────────────────────────────────────────────

def _check_semantics(nodes, subject, core) -> list[Finding]:
    out: list[Finding] = []
    leaders = leading_companies(subject)
    banned = banned_companies(subject)
    for n in nodes:
        label = str(n.get("label") or "")
        comps = [str(c).strip() for c in (n.get("companies") or []) if str(c).strip()]
        if not comps:
            continue
        hits = wrong_fit_hits(label, comps, subject)
        if n.get("is_core"):
            hits = [c for c in hits if not is_leader_name(c, leaders)]
        for c in hits:
            out.append(_mk("CHAIN-SEM-01",
                           f"「{c}」主业与环节「{label}」不符",
                           node=n, companies=(c,),
                           hint="换成该环节专业公司；如属常见误配，把它加进 wrong_fit"))
        gban = [c for c in comps if any(c in b or b in c for b in banned)]
        for c in gban:
            out.append(_mk("CHAIN-SEM-02",
                           f"「{c}」属全局禁用名单（概念股噪声）",
                           node=n, companies=(c,),
                           hint="直接删除，换真实主营公司"))
    return out


# ── 产物规则（需要 SVG） ──────────────────────────────────────────────────

def _check_rendered(topo, nodes, svg: str) -> list[Finding]:
    out: list[Finding] = []
    try:
        spec = topology_to_spec(topo, fallback_title=str(topo.get("title") or ""))
        from chart_generator.chain_lint import lint_chain_svg
        issues = lint_chain_svg(spec, svg) or []
    except Exception as exc:                      # 渲染/解析失败本身就是问题
        out.append(_mk("CHAIN-RENDER-01", f"SVG 无法解析：{type(exc).__name__}: {exc}",
                       hint="检查渲染器输出是否是合法 SVG"))
        return out

    for it in issues:
        level = str(it.get("level") or it.get("severity") or "").lower()
        code = str(it.get("code") or "")
        msg = str(it.get("message") or it.get("msg") or "")
        if level == "error":
            rule = "CHAIN-TEXT-01" if ("数字" in msg or "num" in code.lower()) else (
                "CHAIN-TEXT-02" if "占位" in msg else "CHAIN-RENDER-01")
            out.append(_mk(rule, msg or code or "产物检查未通过", hint="按体检提示修正后重渲染"))
        elif level == "warning":
            out.append(_mk("CHAIN-TEXT-03", msg or code, hint="非阻断提示"))

    # 虚格（历史遗留，F11 已删，仍作为回归守卫）
    for bad in ("其他场景", "新兴应用持续涌现"):
        if bad in svg:
            out.append(_mk("CHAIN-RENDER-01", f"SVG 出现虚格文本「{bad}」",
                           hint="删除渲染器补位分支（F11）"))
    return out


# ── 覆盖度 ────────────────────────────────────────────────────────────────

def _check_coverage(prof, subject) -> list[Finding]:
    level = profile_level(prof)
    if level == "L0":
        return [_mk("CHAIN-COVER-01",
                    f"主题「{subject}」无行业画像（走通用模板），品牌卡无断言",
                    hint="在 chart_profiles/ 新增该行业 JSON（8 行即可），或确认图上已标注「名单待核」")]
    return []


# ── 工具函数 ──────────────────────────────────────────────────────────────

def _mk(rule_id: str, message: str, *, node: dict | None = None,
        companies: tuple[str, ...] = (), hint: str = "",
        evidence: dict | None = None) -> Finding:
    meta = RULE_REGISTRY.get(rule_id, {"sev": _P1, "cat": "other"})
    return Finding(
        rule_id=rule_id,
        severity=meta["sev"],
        category=meta["cat"],
        message=message,
        node_id=str(node.get("id")) if node else None,
        node_label=str(node.get("label")) if node and node.get("label") else None,
        companies=companies,
        hint=hint,
        code_ref=_code_ref(rule_id),
        evidence=evidence or {},
    )


def _by_id(nodes, nid: str) -> dict:
    for n in nodes:
        if str(n.get("id")) == str(nid):
            return n
    return {}


def _label(nodes, nid: str) -> str:
    return str(_by_id(nodes, nid).get("label") or nid)


def _subject(topo: dict, subject: str) -> str:
    return " ".join([
        str(subject or ""),
        str(topo.get("title") or ""),
        str(topo.get("core_product") or ""),
    ]).strip()


def _metrics(topo, nodes, core, findings, prof) -> dict[str, Any]:
    comps = [str(c).strip() for c in ((core or {}).get("companies") or []) if str(c).strip()]
    leaders = leading_companies(_subject(topo, ""))
    purity = None
    if leaders and comps:
        purity = round(sum(1 for c in comps if is_leader_name(c, leaders)) / len(comps), 3)
    empty_cards = [str(n.get("label")) for n in nodes
                   if str(n.get("stage") or "") in ("upstream", "midstream", "support")
                   and not [c for c in (n.get("companies") or []) if str(c).strip()]]
    return {
        "node_count": len(nodes),
        "brand_size": len(comps),
        "brand_purity": purity,
        "brand_label": str((core or {}).get("label") or ""),
        "empty_cards": len(empty_cards),
        "p0": sum(1 for f in findings if f.severity == _P0),
        "p1": sum(1 for f in findings if f.severity == _P1),
        "p2": sum(1 for f in findings if f.severity == _P2),
        "level": profile_level(prof),
    }
