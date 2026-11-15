"""Bounded generate-audit-repair chapter writing agent."""

from __future__ import annotations

from collections import defaultdict
from agents_core.financial_semantics import (
    CLAIM_METRICS,
    QUANTITY_RE,
    financial_calculation_rows,
    measurement_period,
    metric_family,
    quantity_issues,
    retain_supported_claims,
    verified_calculations,
)
from agents_core.context_budget import ContextBudgetExceeded, serialize_context

import asyncio
import httpx
from collections.abc import Awaitable, Callable
from datetime import datetime
import json
from pathlib import Path
import re
import secrets
from typing import Any


from chapter_writer.config import Settings
from chapter_writer.llm import ChapterLLM, OpenAICompatibleLLM
from chapter_writer.models import (
    AppliedSkill, ChapterDraft, ChapterQualityReport, ChapterWritingRequest, ChapterWritingResult,
    ParagraphDraft, SectionDraft,
)
from chapter_writer.net_cash_ratio import (
    apply_net_cash_ratio_guard, build_net_cash_ratio_policy,
)
from chapter_writer.outline import DEFAULT_OUTLINE, OUTLINE_VERSION
from chapter_writer.retriever import DynamicEvidenceRetriever
from chapter_writer.skillhub import WritingSkill, WritingSkillHub

try:
    from skill_policy import merge_selection
except ModuleNotFoundError:  # 单包测试或独立运行时 agents_core 不在搜索路径上，按包位置回推
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from skill_policy import merge_selection

from skill_policy.requests import resolve_requested_skills

EventEmitter=Callable[[dict[str,Any]],Awaitable[None]]

def prepare_chapter_context(payload: dict[str, Any], system: str) -> tuple[str, dict[str, Any]]:
    """Drop duplicated and optional chapter context; never truncate required evidence."""
    packet = dict(payload)
    context = dict(packet.get('context') or {})
    packet['context'] = context
    omitted = []
    for key in ('global_facts', 'global_facts_prompt'):
        if key in context:
            context.pop(key)
            omitted.append('context.' + key)
    details = {'omitted_sections': omitted}
    packet['context_packing'] = details
    # New assignment hints are optional guidance: compress them before the
    # requirement matrix, financial assets and evidence. Requirement rows and
    # the evidence whitelist are never removed here.
    for key in ('question_coverage', 'suppressed_charts', 'verdict_diagnostics',
                'semantic_checks', 'analysis_facts', 'hypothesis_verdicts',
                'assignment_hints', 'primary_requirements',
                'requirement_evidence_matrix.details', 'comps_matrix', 'financial_ratios',
                'industry_chain_segments', 'findings', 'outline_hints', 'insights', None):
        try:
            text, size, budget = serialize_context(packet, system=system)
            details.update(bytes=size, budget_bytes=budget)
            text, size, budget = serialize_context(packet, system=system)
            details.update(bytes=size, budget_bytes=budget)
            return text, details
        except ContextBudgetExceeded:
            if key is None:
                raise
            if key == 'requirement_evidence_matrix.details':
                matrix = context.get('requirement_evidence_matrix')
                if isinstance(matrix, list):
                    compacted = []
                    for row in matrix:
                        if not isinstance(row, dict):
                            continue
                        requirement, coverage = row.get('requirement') or {}, row.get('coverage') or {}
                        req_fields = ('requirement_id','label','domain','hard','min_records','expected_metric_groups',
                                      'requires_entity_code','requires_period_end','requires_published_at',
                                      'acceptable_skill_ids','entity_names','period_ends','metric_families')
                        cov_fields = ('requirement_id','label','domain','hard','passed','evidence_count','evidence_record_ids','missing')
                        entry = {'requirement':{k:requirement[k] for k in req_fields if k in requirement},
                                 'coverage':{k:coverage[k] for k in cov_fields if k in coverage}}
                        if row.get('section_id'):
                            entry['section_id'] = row['section_id']
                        compacted.append(entry)
                    if compacted != matrix:
                        context['requirement_evidence_matrix'] = compacted
                        omitted.append('context.requirement_evidence_matrix.details')
                continue
            if context.get(key):
                context[key] = None if isinstance(context[key], dict) else []
                omitted.append('context.' + key)
    raise AssertionError('unreachable')

NUMBER_RE=re.compile(r"(?<![A-Za-z0-9_-])[-+]?\d+(?:\.\d+)?%?")
YEAR_OR_ORDINAL_RE=re.compile(r"^(?:19\d\d|20\d\d|[1-9]|10)$")

# 审计隔离后，只保留图表占位符而无论述的段落会被改写为显式缺口句。
# 该标记用于豁免段落去重检查（不同小节可以出现相同的缺口说明）。
GAP_NOTICE_MARK = "本项量化解读未通过证据核验"

_CHART_TAG_RE = re.compile(r"\[[^\]]*\]")
_CHART_BODY_NOISE_RE = re.compile(r"[，,。；;、：:！!？?\s]")
_CHART_LEAD_RE = re.compile(r"如图\s*所示[，,]\s*")


_CC_PERIOD_RE = re.compile(
    r"(20\d{2}\s*年(?:\s*(?:全年|年度|上半年|前三季度|第[一二三四1-4]季度|一季度|二季度|三季度|四季度))?"
    r"|全年|年度|上半年|前三季度|当季|单季)"
)
_CC_SCOPE_RE = re.compile(
    r"(中国市场|国内市场|全球市场|海外市场|行业整体|合并口径|母公司口径|中国|国内|全球|海外|行业)"
)
_CC_CLAUSE_RE = re.compile(r"[。；;\n！？!?]")
_CC_METRIC_BOUNDARY = "，,；;：:（("
_CC_ENTITY_RE = re.compile(
    r"[\u4e00-\u9fff]{2,10}(?:时代|汽车|锂能|股份|集团|科技|能源|电子|半导体|材料|电池|控股|电气|重工|工业|装备|新能源|有限公司)"
)


def _claim_entity(text: str, start: int, refs: list[Any]) -> str:
    """优先用段落证据的实体名绑定数值；没有证据时退回公司名后缀识别。"""
    candidates: list[tuple[int, str]] = []
    for ref in refs:
        if hasattr(ref, "model_dump"):
            ref = ref.model_dump(mode="json")
        if not isinstance(ref, dict):
            continue
        name = str(ref.get("entity") or ref.get("entity_name") or "")
        if not name:
            continue
        for match in re.finditer(re.escape(name), text):
            if match.start() < start:
                candidates.append((match.start(), name))
    if candidates:
        return max(candidates)[1]
    matches = [m for m in _CC_ENTITY_RE.finditer(text) if m.start() < start]
    return matches[-1].group(0) if matches else ""


def _nearest_metric(text: str, number_start: int) -> tuple[str, str] | None:
    """把数值绑定到同一子句内紧邻的指标，避免把别家公司的数字配给前文指标。"""
    boundary = max((text.rfind(ch, 0, number_start) for ch in _CC_METRIC_BOUNDARY), default=-1) + 1
    window = text[boundary:number_start]
    terms = [(window.rfind(term), term) for term in CLAIM_METRICS if term in window]
    if not terms:
        return None
    position, term = max(terms)
    gap = len(window) - (position + len(term))
    if gap > 8:
        return None
    return term, CLAIM_METRICS[term]


def _cross_chapter_claim_audit(
    chapters: list[ChapterDraft], evidence: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Flag same-key numeric conclusions that contradict across chapters.

    Only report, never rewrite text. Different period/scope/unit are distinct
    keys and are never treated as conflicts. At most two conflicts are recorded.
    """
    rows = []
    for chapter in chapters:
        for section in chapter.sections:
            for paragraph in section.paragraphs:
                refs = [
                    evidence[rid] for rid in paragraph.evidence_ids
                    if evidence and rid in evidence
                ]
                for sentence in _CC_CLAUSE_RE.split(paragraph.text):
                    text = sentence.strip()
                    if not text:
                        continue
                    period_match = _CC_PERIOD_RE.search(text)
                    scope_match = _CC_SCOPE_RE.search(text)
                    for match in QUANTITY_RE.finditer(text):
                        unit = match.group(2)
                        if not unit:
                            continue
                        metric = _nearest_metric(text, match.start())
                        if metric is None:
                            continue
                        term, family = metric
                        entity = _claim_entity(text, match.start(), refs)
                        raw = match.group(1).replace(",", "").replace("−", "-")
                        try:
                            value = float(raw)
                        except ValueError:
                            continue
                        unit = "%" if unit in ("%", "％") else unit
                        decimals = len(raw.split(".", 1)[1]) if "." in raw else 0
                        rows.append({
                            "family": family, "metric": term, "entity": entity,
                            "value": value, "unit": unit, "decimals": decimals,
                            "period": re.sub(r"\s+", "", period_match.group(1)) if period_match else "",
                            "scope": scope_match.group(1) if scope_match else "",
                            "chapter_id": chapter.chapter_id, "section_id": section.section_id,
                            "paragraph_id": paragraph.paragraph_id, "text": text,
                        })
    by_key: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_key.setdefault(
            (row["family"], row["entity"], row["period"], row["scope"], row["unit"]),
            [],
        ).append(row)
    conflicts = []
    for key, group in by_key.items():
        pair = None
        for i, left in enumerate(group):
            for right in group[i + 1:]:
                if left["chapter_id"] == right["chapter_id"]:
                    continue
                tolerance = 0.5 * 10 ** (-min(left["decimals"], right["decimals"]))
                if abs(left["value"] - right["value"]) > tolerance:
                    pair = (left, right)
                    break
            if pair:
                break
        if not pair:
            continue
        left, right = pair
        claim = (
            f"{left['entity'] + ' ' if left['entity'] else ''}{left['metric']}"
            f"（{left['period'] or '未标注期间'}／{left['scope'] or '未标注范围'}）"
            f"{left['chapter_id']} 为 {left['value']:g}{left['unit']}，"
            f"{right['chapter_id']} 为 {right['value']:g}{right['unit']}"
        )
        conflicts.append({
            "code": "cross_chapter_claim_conflict",
            "location": f"{left['section_id']}/{right['section_id']}",
            "section_id": left["section_id"],
            "claim": claim,
            "disposition": "flagged",
            "chapter_ids": [left["chapter_id"], right["chapter_id"]],
            "paragraph_ids": [left["paragraph_id"], right["paragraph_id"]],
        })
        for chapter in chapters:
            if chapter.chapter_id in (left["chapter_id"], right["chapter_id"]):
                entry = dict(conflicts[-1])
                if not any(
                    existing.get("code") == entry["code"]
                    and existing.get("claim") == entry["claim"]
                    and existing.get("location") == entry["location"]
                    for existing in chapter.content_audit
                ):
                    chapter.content_audit.append(entry)
        if len(conflicts) >= 2:
            break
    return conflicts


def paragraph_body(text: str) -> str:
    """去掉图表占位符与格式标点后，段落的实际论述部分。"""
    body = _CHART_TAG_RE.sub("", text or "")
    body = body.replace("如图", "").replace("所示", "")
    return _CHART_BODY_NOISE_RE.sub("", body)


def has_chart_discussion(text: str) -> bool:
    """段落是否有可挂图的论述；显式缺口句属于已隔离正文，不算解读。"""
    body = paragraph_body(text)
    return bool(body) and GAP_NOTICE_MARK not in body


def strip_chart_tag(text: str, chart_id: str) -> str:
    """移除未就绪图表的图号，并清掉只为该图号存在的「如图…所示」引子。"""
    cleaned = (text or "").replace(f"[{chart_id}]", "")
    cleaned = _CHART_LEAD_RE.sub("", cleaned)
    return cleaned.strip()


def chart_section_score(section: Any, chart_evidence: set[str]) -> tuple:
    """优先选择已有对齐解读的 chart_readout 小节，其次有正文且证据重叠的小节。"""
    discussion = [p for p in section.paragraphs if has_chart_discussion(p.text)]
    readouts = [p for p in discussion if p.kind == "chart_readout"]
    aligned = [p for p in readouts if chart_evidence & set(p.evidence_ids)]
    section_evidence = {e for p in section.paragraphs for e in p.evidence_ids}
    return (bool(aligned), bool(chart_evidence & section_evidence), bool(readouts), bool(discussion),
            len(chart_evidence & section_evidence))


def _align_chart_reference(section: Any, chart_id: str, chart: Any) -> bool:
    evidence_ids = set(chart.get("evidence_ids", []) if isinstance(chart, dict) else chart.evidence_ids)
    contract = (chart.get("data_contract") if isinstance(chart, dict) else getattr(chart, "data_contract", {})) or {}
    points = contract.get("points") or []
    families = {metric_family(str(point.get("metric") or "")) for point in points}
    metric_terms = CLAIM_METRICS | {
        "销量": "nev_sales", "出口量": "nev_exports", "出口": "nev_exports",
        "渗透率": "nev_penetration",
    }
    tag = f"[{chart_id}]"
    matched = []
    for paragraph in section.paragraphs:
        if not has_chart_discussion(paragraph.text):
            continue
        first_sentence = re.split(r"[。；;！？!?]", _CHART_TAG_RE.sub("", paragraph.text), maxsplit=1)[0].casefold()
        # Auto-insertion puts the chart at the opening claim, so use the
        # same local check for pre-existing and newly added chart references.
        lead = re.split(r"限制|上述|仍需|尚需", first_sentence, maxsplit=1)[0]
        mentions = {family for term, family in metric_terms.items() if term.casefold() in lead}
        if (not evidence_ids or evidence_ids.intersection(paragraph.evidence_ids)) and (
            not families or families.intersection(mentions)
        ):
            matched.append(paragraph)
        elif tag in paragraph.text:
            paragraph.text = strip_chart_tag(paragraph.text, chart_id)
    if not matched:
        note = f"{chart_id} 暂无与图表证据对应的正文解读。"
        if note not in section.uncertainties:
            section.uncertainties.append(note)
        return any(has_chart_discussion(p.text) for p in section.paragraphs)
    if not any(tag in paragraph.text for paragraph in matched):
        target = next((paragraph for paragraph in matched if paragraph.kind == "chart_readout"), matched[0])
        target.text = f"如图 {tag} 所示，{target.text}"
    note = f"{chart_id} 暂无与图表证据对应的正文解读。"
    section.uncertainties = [item for item in section.uncertainties if item != note]
    return True


def drop_chart_tag_from_section(section: Any, chart_id: str) -> None:
    """移除本小节里不再合法的图号；只剩引子时写成显式缺口句，不造空段。"""
    for para in section.paragraphs:
        if f"[{chart_id}]" not in (para.text or ""):
            continue
        cleaned = strip_chart_tag(para.text, chart_id)
        para.text = cleaned or (
            f"关于「{section.title}」，{GAP_NOTICE_MARK}；"
            "相关图表引用已移除，待补充可核验解读。"
        )

# 单章写作规范的默认预算；强制规范与用户显式选择优先保留。
CHAPTER_SKILL_LIMIT = 10

_NARRATIVE_KINDS = {"analysis", "thesis", "comparison", "chart_readout"}
_READOUT = re.compile(
    r"从.{0,32}(?:到|至).{0,32}(?:上升|下降|持平|回落|提高|扩大|收窄)"
    r"|由于|归因于|不能据此|仅能|不足以判断|仍需核对|仍需结合|无法判断"
)


def _lists_numbers(paragraph: ParagraphDraft) -> bool:
    if paragraph.kind not in _NARRATIVE_KINDS or not paragraph.evidence_ids or _READOUT.search(paragraph.text):
        return False
    clauses = [part.strip() for part in re.split(r"[。；;！!？?\n]", paragraph.text) if part.strip()]
    counts = [sum(bool(unit) for _, unit in QUANTITY_RE.findall(part)) for part in clauses]
    return bool(counts and all(counts) and sum(counts) >= 2)

SYSTEM_PROMPT="""你是机构级证券与行业研究报告章节写作智能体。你必须将内容组织成可直接供前端/PDF排版的结构化组件，而不是连续长文章。
严格要求：
1. 只使用输入 context 中的 evidence、insights、findings、hypothesis_verdicts、analysis_facts、semantic_checks、question_coverage、suppressed_charts、comps_matrix、financial_ratios、industry_chain_segments 和 charts 信息，严禁捏造事实和数字。
   - `hypothesis_verdicts` 的 `verdict` 可用于表述假设的验证状态；`covered_evidence`/`required_evidence` 是覆盖说明，不是 record_id，不得当作证据引用。
   - `analysis_facts` 与 `semantic_checks` 只用于已核实事实、期间和校验状态；`semantic_checks` 中的原始错误句不提供，不得复述或改写为结论。
   - 保留原始计量单位，或只作可复算的同维度换算（例如辆转万辆）。同比、复合增速、占比和百分点变化必须写明指标、期间及口径，并在该段 evidence_ids 绑定全部原始操作数。缺任一操作数时改写为证据缺口。
   - 复用图表的数值时同时引用该值所需的原始证据。图号不能充当数值或因果依据，且只能用于讨论该图实际绘制的对象和指标。
   - `requirement_evidence_matrix` 中带 section_id 的必答缺口须在指定小节的 uncertainties 和正文结论里明确交代。
   - 上游告警及缺口提示仅用于定位待核事项。正文以证据和覆盖矩阵为准，区分「没有观测」「序列不全」「有数值但单位或口径待核」。
   - `question_coverage`、`suppressed_charts` 及其 `reason_code` 只能用于说明数据或图表限制，本身不构成事实依据。
   - 正文只能引用本章提示包 `evidence`/`charts` 中实际存在的 record_id；图表脚注与 `data_contract` 的单位、期间、范围和来源必须保留，不得改写为其它口径。
2. 写作风格采用“断言主旨驱动 (Thesis-Driven)”：
   - 先回答本节问题，再选支撑判断的关键数字。把明细、平行指标和重复读数留给表格或指标卡；`key_points` 与摘要只保留读者需要记住的结论。
   - 每段只承担一个判断：给出证据对应的主体、期间和口径，然后说明变化、差异或业务含义。同一段的核心数字共用一次解读，无需逐个数字补一句归因。
   - 有同口径对照时解释方向和差异。有直接披露时注明谁披露了什么，才写成因。只有单期数字时交代该数字能回答什么；若要继续解释，指出具体还缺哪项数据。避免“值得关注”“总体向好”等空句。
   - 摘要概括本章最重要的判断，篇幅随证据和问题决定；无需为了凑字增加背景或重复结论。
   - 有连续序列或跨企业可比证据的小节，分别写清主判断、最有信息量的拐点或对照、以及这个变化对行业判断的含义。三者可各用一段。写出读者需要跟踪的指标和能推翻判断的观测结果。
   - 数值集中于证据段、图表或表格；分析段解释结构与经营含义。章节摘要和要点优先用有证据支持的定性概括，避免将带数字的长句在各处重复。缺少驱动证据时，仍可说明这个观察对哪些判断有用，并提出可验证的解释。
   - 每个数值句写全主体、观测期、指标、单位和绑定的记录。优先沿用证据的 ISO 日期及期间类型。百分比必须写明是水平、同比、环比还是百分点差。只写已核的单个转折或具体对照，先核对完整窗口再写「最高」「首次」或「持续」。年度总量、年末当月值与累计值分别表述。
   - 涉及用户问题时，逐项回答。将完整数列留给图或表，正文解释最关键的变化。比较分组时先比较组内离散与组间差异，再解释各指标对不同业务模式的含义。区分研发费用率与技术效果、现金转换与利润规模。场景与跟踪指标只描述可验证条件，缺少模型或明确资料时省略预测阈值。
   - 对已经由图表或计算表回答的指标，正文只选最能区分结论的一处对照。除图表解读段外，每段至多保留一个关键数字。其余篇幅用于解释如何检验判断、应观察哪些指标及什么变化会推翻判断。
   - 月度指标必须依据已验收的记录陈述覆盖情况。若题面起止月均在完整序列内，不得声称仅覆盖最近一年或缺失中间年份。集团分产品收入占比统一按年报项目原名叙述，不能自行缩窄成纯整车或动力电池业务。
   - evidence 只是本章检索结果。未看到某个字段不能推断本次研究缺失该数据。资料缺口须对应明确未通过的覆盖项，或限定为当前证据无法回答的具体机制。已覆盖的分产品项目与研发费用率可按年报和财务表分析，不把缺少分部利润、资本化明细等同于缺少收入或研发费用。
   - 暂无直接依据的原因、情景和传导机制仅作待检验解释。写清什么证据能验证它，避免把上游假设编号或机器状态词直接写进报告。
3. `kind` 必须选用受控枚举：
   - `thesis`：本节核心判断与影响；
   - `evidence`：直接数据论据与口径引用；
   - `comparison`：横向同业对标或纵向历史周期对比；
   - `chart_readout`：图表邻接解读（图前结论、图中拐点、图后含义三段式）；
   - `risk`：风险、反例与制约因素；
   - `methodology`：口径与测算方法；
   - `transition`：必要的承上启下；
   - `analysis` / `scenario`：综合分析或情景推演。
4. 页面组件抽取（充分利用上下文中的量化资产）：
   - `metric_cards`：若本节涉及关键量化指标（如市值、增速、杜邦ROE、净现比、估值溢价），提炼 1~3 个指标卡：label, value, unit, period, evidence_ids；
   - `comparison_table`：若本节涉及多企业横向对标或三档情景推演，提炼结构化对比表：title, columns, rows, evidence_ids；
   - `callouts`：若本节存在关键风险提示、政策边界或不可外推声明，提炼为 callout：type("risk"|"boundary"|"highlight"), title, text, evidence_ids；
   - `layout_hint`：根据图文关系选择：text_only, chart_right, chart_full, comparison_table, metrics_grid。
5. 图文协同与显式强锚点：挂接的 `chart_ids` 必须在对应小节正文中提供具有分析深度的邻接解读（段落 `kind` 优先选用 `chart_readout`）。【强制约束】正文引用图表时必须显式出现对应图表的完整占位符（如 `[CHART-xx]`），严禁仅写模糊的“如图所示”而遗漏 `[CHART-xx]` 标签！排版引擎将统一映射为最终图表顺序编号。【严禁捏造未挂接图表占位符】：若本小节未挂接图表（`chart_ids` 为空），严禁在正文中插入任何 `[CHART-xx]` 占位符或图表引用！只能引用在上下文 `charts` 中真实存在的图表 ID！
6. 风险与情景推演规范（尤其针对第七章或预测性章节）：
   - 仅在输入提供可核验的测算依据时写量化情景，区分假设与结果；概率和阈值需要来源。
   - 资料只支持定性判断时，写清触发条件、待观察指标和判断边界；情景数量随证据决定。
   - 必须包含非外推声明 (Non-extrapolation Disclaimer，建议放置在 callout 中)：依据本次证据说明样本结构代表性边界与期间跨度局限，禁止线性外推至整个产业。
7. 全局事实与一致性锚点（强制约束）：严格遵循输入及上下文中的 `global_facts`。凡提及行业/样本总市值，必须统一按照 `global_facts` 给出，严禁在不同章节出现数量级矛盾；凡提及企业产业链环节归属，只使用 `global_facts` 中有证据支持的关系，无证据的关系须标注「归属待核」，不得自行锁定或让同一标的在上中下游反复横跳。
8. 非宏观章节套话禁令：除宏观综述或宏观驱动专章外，其余产业、竞争、财务等章节严禁重复展开脱节宏观指标（如社融、工业增加值）的周期无效性免责声明套话！保持对本行业真实财务、业务与竞争态势的专注。
9. 返回严格 JSON 格式（【极其重要规范】：你的输出必须且只能是一个纯合法的 JSON 对象。严禁在输出开头添加任何 Markdown 标题如 "# 标题" 或引言文字；严禁输出任何 ```json 代码块外围文本；正文内部出现的双引号若非 JSON 键值语法边界，一律使用中文双引号“”或转义）：
{
  "chapter_id": "CH-xx",
  "title": "...",
  "summary": "用最短篇幅概括本章有证据的核心判断",
  "sections": [
    {
      "section_id": "SEC-xx-xx",
      "title": "...",
      "purpose": "...",
      "key_points": ["核心要点1", "核心要点2"],
      "paragraphs": [
        {"paragraph_id": "P-xx-xx-01", "kind": "thesis", "text": "...", "evidence_ids": ["..."], "assumption_note": null}
      ],
      "chart_ids": ["..."],
      "uncertainties": ["..."],
      "metric_cards": [{"label": "...", "value": "...", "unit": "...", "period": "...", "evidence_ids": ["..."]}],
      "comparison_table": null,
      "callouts": [],
      "layout_hint": "chart_right"
    }
  ]
}"""


def extract_numbers(text:str)->list[str]:
    return NUMBER_RE.findall(text)


# Industry-specific company/segment dictionaries are deliberately absent here.
# A role may only be asserted when an A2 relation points back to this run's
# evidence index; otherwise it is a sample description with pending attribution.


def extract_global_quantitative_anchor(report: Any) -> dict[str, Any]:
    comps_matrix = getattr(report, "comps_matrix", None)
    if isinstance(comps_matrix, dict):
        comps = comps_matrix.get("entries") or comps_matrix.get("comps") or []
        total_mc = comps_matrix.get("total_market_cap")
        median_pe = comps_matrix.get("median_pe")
        median_pb = comps_matrix.get("median_pb")
        median_gross_margin = comps_matrix.get("median_gross_margin")
    else:
        comps = (getattr(comps_matrix, "entries", None) or getattr(comps_matrix, "comps", [])) if comps_matrix else []
        total_mc = getattr(comps_matrix, "total_market_cap", None) if comps_matrix else None
        median_pe = getattr(comps_matrix, "median_pe", None) if comps_matrix else None
        median_pb = getattr(comps_matrix, "median_pb", None) if comps_matrix else None
        median_gross_margin = getattr(comps_matrix, "median_gross_margin", None) if comps_matrix else None

    if not total_mc and comps:
        mc_list = [
            (c.get("market_cap") if isinstance(c, dict) else getattr(c, "market_cap", 0)) or 0
            for c in comps
        ]
        total_mc = sum(mc_list)

    mc_val = round(total_mc, 2) if total_mc else 0.0
    mc_wan_yi = round(mc_val / 10000.0, 2)
    if mc_val >= 10000:
        mc_str = f"{mc_val:,.2f} 亿元（约 {mc_wan_yi:.2f} 万亿元）"
    elif mc_val > 0:
        mc_str = f"{mc_val:,.2f} 亿元（约 {mc_wan_yi:.2f} 万亿元）"
    else:
        mc_str = "暂无汇总数据"

    total_companies = len(comps) if comps else 0

    def _tier(c: Any) -> str:
        return str(c.get("valuation_tier") if isinstance(c, dict) else getattr(c, "valuation_tier", "") or "")

    profitable_count = sum(1 for c in comps if _tier(c) == "profitable") if comps else 0
    # 未分类 / 待核的标的不得被算进「早期、亏损、高估值」，否则会把
    # 数据缺失误写成全样本亏损的强断言（见 format_global_facts_prompt）。
    loss_count = sum(1 for c in comps if _tier(c) == "loss_or_high_multiple") if comps else 0
    unknown_count = total_companies - profitable_count - loss_count

    # Chain roles are only asserted for A2 relations that point back to a
    # record in this run's evidence index and whose subject matches the company.
    # A representative-company list on its own is a sample description, so its
    # attribution stays pending instead of being locked into the prompt.
    evidence_index = getattr(report, "evidence_index", None) or {}
    canonical_segments: dict[str, str] = {}
    pending_attribution: list[str] = []
    for seg in getattr(report, "industry_chain_segments", []) or []:
        is_dict = isinstance(seg, dict)
        s_name = str((seg.get("segment_name") if is_dict else getattr(seg, "segment_name", "")) or "").strip()
        refs = (seg.get("evidence_record_ids") if is_dict else getattr(seg, "evidence_record_ids", [])) or []
        reps = (seg.get("representative_companies") if is_dict else getattr(seg, "representative_companies", [])) or []
        if not s_name:
            continue
        # Only a reviewed full-chain card may assert "company X belongs to
        # segment Y".  Legacy segments are tagged industry_common and their
        # evidence ids point at quotes / classification fields, which prove
        # identity but not membership.  Fixtures without the new field keep
        # the historical behaviour so existing chapter tests stay valid.
        seg_tier = str((seg.get("source_tier") if is_dict else getattr(seg, "source_tier", None)) or "")
        seg_basis = str((seg.get("attribution_basis") if is_dict else getattr(seg, "attribution_basis", None)) or "")
        has_tier_field = (is_dict and "source_tier" in seg) or hasattr(seg, "source_tier")
        reviewed_card = seg_tier == "reviewed_profile" and bool(seg_basis)
        attribution_allowed = (
            not has_tier_field
            or (seg_tier in ("reviewed_profile", "evidence") and bool(seg_basis))
        )
        supported_entities: set[str] = set()
        for rid in refs:
            rec = evidence_index.get(rid) if hasattr(evidence_index, "get") else None
            if rec is None:
                continue
            entity = (rec.get("entity") if isinstance(rec, dict) else getattr(rec, "entity", None)) or ""
            if str(entity).strip():
                supported_entities.add(str(entity).strip())
        for comp in reps:
            c_str = str(comp).strip()
            if not c_str or re.match(r"^\d{6}\.[A-Z]{2}$", c_str) or c_str.replace(".", "").isdigit():
                continue
            if not attribution_allowed:
                if c_str not in canonical_segments and c_str not in pending_attribution:
                    pending_attribution.append(c_str)
                continue
            # A reviewed full-chain card is itself the attribution basis; it
            # must not depend on A1 quote / classification records that only
            # prove a company exists, not which segment it belongs to.
            if reviewed_card or c_str in supported_entities:
                canonical_segments.setdefault(c_str, s_name)
            elif c_str not in canonical_segments and c_str not in pending_attribution:
                pending_attribution.append(c_str)

    return {
        "market_cap_val": mc_val,
        "market_cap_wan_yi": mc_wan_yi,
        "market_cap_str": mc_str,
        "total_companies": total_companies,
        "profitable_count": profitable_count,
        "loss_count": loss_count,
        "unknown_count": unknown_count,
        "median_pe": median_pe,
        "median_pb": median_pb,
        "median_gross_margin": median_gross_margin,
        "canonical_segments": canonical_segments,
        "pending_attribution": pending_attribution,
    }


def format_global_facts_prompt(facts: dict[str, Any]) -> str:
    lines = [
        "【全篇全局量化基准与事实锚点（强制约束，所有章节必须保持高度一致，严禁互相矛盾）】",
    ]
    if facts.get("total_companies"):
        profitable_count = facts.get("profitable_count") or 0
        loss_count = facts.get("loss_count") or 0
        unknown_count = facts.get("unknown_count") or 0
        medians_missing = all(
            facts.get(k) is None for k in ("median_pe", "median_pb", "median_gross_margin")
        )
        # 估值分层/盈利中枢缺失时，不要下「成熟盈利 0 家、全部亏损或高估值」
        # 这类强断言：那通常意味着字段没取到，而不是样本确实全亏损。
        if profitable_count == 0 and (unknown_count > 0 or medians_missing):
            detail = f"其中分层待核 {unknown_count} 家；" if unknown_count else ""
            lines.append(
                f"- 样本公司总数：{facts['total_companies']} 家；{detail}估值分层与盈利中枢数据不足。"
                "不得据此判定样本整体盈利状态或估值梯队，严禁写成「全部亏损 / 全部高估值」"
            )
        else:
            extra = f"，分层待核 {unknown_count} 家" if unknown_count else ""
            lines.append(
                f"- 样本公司总数：{facts['total_companies']} 家（成熟盈利：{profitable_count} 家，"
                f"早期/亏损/高估值：{loss_count} 家{extra}）"
            )
    if facts.get("market_cap_str") and facts["market_cap_str"] != "暂无汇总数据":
        lines.append(f"- 样本总市值标准基准：{facts['market_cap_str']}（全篇必须以此为准，严禁在不同章节出现数量级矛盾）")
    if facts.get("median_pe") is not None:
        lines.append(f"- 估值与盈利中枢：成熟标的 PE(TTM) 中位数 {facts['median_pe']} 倍，PB 中位数 {facts.get('median_pb')} 倍，销售毛利率中枢 {facts.get('median_gross_margin')}%")
    if facts.get("canonical_segments"):
        lines.append("- 本次证据支持的企业环节归属（只按下列有据关系描述，并保留对应记录 ID）：")
        for comp, seg in list(facts["canonical_segments"].items())[:12]:
            lines.append(f"  * {comp}: {seg}")
    if facts.get("pending_attribution"):
        lines.append("- 以下代表公司仅见于本次样本名单，缺少可回指证据，归属待核；只能按来源描述样本，不得写成确定的环节结论：")
        lines.append("  * " + "、".join(facts["pending_attribution"][:12]))
    return "\n".join(lines)


class ChapterWriterAgent:
    def __init__(self,*,settings:Settings|None=None,llm:ChapterLLM|None=None,skillhub:WritingSkillHub|None=None)->None:
        self.settings=settings or Settings.from_env(); self.llm=llm or OpenAICompatibleLLM(self.settings); self.skillhub=skillhub or WritingSkillHub()

    async def _plan_chapter_skills(
        self,
        outline_chapter: Any,
        context: dict[str, Any],
        request: ChapterWritingRequest,
    ) -> list[tuple[WritingSkill, str, str]]:
        # Every applicable writing rule is already included by policy. A model
        # planning round cannot improve that union; avoid one paid call per chapter.
        policy_skills = self.skillhub.select(outline_chapter.chapter_id)
        requested, _ = resolve_requested_skills(
            request.selected_skills, self.skillhub.catalog, stage="writing",
        )
        requested = [s for s in requested
                     if s.always or outline_chapter.chapter_id in s.chapters]
        requested_names = {s.name for s in requested}
        merged = merge_selection(
            [], policy_skills, requested_skills=requested, limit=CHAPTER_SKILL_LIMIT,
        )
        return [
            (skill, "用户显式选择；按适用章节加载" if skill.name in requested_names
             else skill.adaptation or "章节大纲特征匹配",
             "user" if skill.name in requested_names else "policy")
            for skill in merged.final
        ]

    async def run(self,request:ChapterWritingRequest,emit:EventEmitter|None=None,save_artifacts:bool=True)->ChapterWritingResult:
        run_id=f"chapters-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
        artifact_dir=self.settings.output_dir/"runs"/run_id if save_artifacts else None
        events:list[dict[str,Any]]=[]
        async def record(event:str,**details:Any)->None:
            item={"timestamp":datetime.now().astimezone().isoformat(),"event":event,"details":details}; events.append(item)
            if emit:
                try: await emit(item)
                except Exception: pass
        await record("chapter_writing_started",source_report_id=request.report.report_id)
        outline=request.outline or DEFAULT_OUTLINE
        allowed_evidence=set(request.report.evidence_index)
        ready_charts={c.chart_id:c for c in (request.charts.charts if request.charts else []) if c.status=="ready"}
        global_facts=extract_global_quantitative_anchor(request.report)
        global_facts_prompt=format_global_facts_prompt(global_facts)
        net_cash_policy = build_net_cash_ratio_policy(request.report)
        retriever = DynamicEvidenceRetriever(request)
        concurrency = getattr(self.settings, "max_concurrency", 7)
        semaphore = asyncio.Semaphore(concurrency)
        if artifact_dir:
            (artifact_dir / "chapters").mkdir(parents=True, exist_ok=True)

        _, unavailable_skills = resolve_requested_skills(
            request.selected_skills, self.skillhub.catalog, stage="writing",
        )
        if unavailable_skills:
            await record("skill_skipped", skills=unavailable_skills,
                         reason="写作阶段没有对应规范，分析技能不一定存在写作映射")
        selected_by_chapter: dict[str, list[WritingSkill]] = {}
        skill_reasons: dict[str, str] = {}
        # D-11：跨章共享的越界证据留痕通道（asyncio 单线程事件循环内 append 安全；
        # _audit_chapter 内为同步调用，无 await 打断）。汇入 result.warnings，不触发重写。
        foreign_drops: list[str] = []

        async def _write_chapter(outline_chapter: Any) -> tuple[ChapterDraft, str | None, str | None]:
            async with semaphore:
                context = retriever.retrieve(outline_chapter.chapter_id, outline_chapter)
                context["global_facts"] = global_facts
                context["global_facts_prompt"] = global_facts_prompt
                context["net_cash_ratio_policy"] = net_cash_policy["prompt"]
                planned_skills = await self._plan_chapter_skills(outline_chapter, context, request)
                selected_by_chapter[outline_chapter.chapter_id] = [skill for skill, _, _ in planned_skills]
                for skill, reason, route_type in planned_skills:
                    skill_reasons[skill.name] = reason
                    if route_type == "user":
                        await record("skill_requested", chapter_id=outline_chapter.chapter_id, skill=skill.name, reason=reason)
                    elif route_type == "llm":
                        await record("skill_invoked_by_llm", chapter_id=outline_chapter.chapter_id, skill=skill.name, reason=reason)
                    else:
                        await record("skill_routed_by_policy", chapter_id=outline_chapter.chapter_id, skill=skill.name, route_type="fast_skill_router", reason=reason)
                context["skills"] = [{"name": skill.name, "instructions": skill.instructions} for skill, _, _ in planned_skills]
                await record("skill_loaded", chapter_id=outline_chapter.chapter_id,
                             skills=[s.name for s, _, _ in planned_skills],
                             planner="chapter_policy", model_planning_calls=0)
                chapter, fallback_id, warning = await self._generate_audited_chapter(
                    request, outline_chapter, context, ready_charts, global_facts, record, foreign_drops
                )
                if artifact_dir:
                    (artifact_dir / "chapters" / f"{chapter.chapter_id}.json").write_text(
                        chapter.model_dump_json(indent=2) + "\n", encoding="utf-8"
                    )
                return chapter, fallback_id, warning

        chapter_results = await asyncio.gather(*[_write_chapter(c) for c in outline])
        await record("skills_planned", skills={chapter_id: [skill.name for skill in skills] for chapter_id, skills in selected_by_chapter.items()})
        chapters: list[ChapterDraft] = [item[0] for item in chapter_results]
        net_cash_corrections = apply_net_cash_ratio_guard(chapters, net_cash_policy)
        if net_cash_corrections:
            await record("net_cash_ratio_guard_applied", corrections=len(net_cash_corrections),
                         verified=len(net_cash_policy["verified"]), missing=len(net_cash_policy["missing"]))
        fallback_ids = [item[1] for item in chapter_results if item[1] is not None]
        warnings = list(request.report.warnings) + [item[2] for item in chapter_results if item[2] is not None] + list(dict.fromkeys(foreign_drops))
        if net_cash_corrections:
            warnings.append(f"净现比口径修正 {len(net_cash_corrections)} 处（A2 无可引用值，禁止自算）")
        issues=self._audit_package(chapters,allowed_evidence,ready_charts,global_facts,
            evidence=request.report.evidence_index)
        issues.extend(item[2] for item in chapter_results if item[2] and item[2].startswith("段落资料缺口："))
        cited={eid for chapter in chapters for section in chapter.sections for para in section.paragraphs for eid in para.evidence_ids}
        coverage=len(cited)/len(allowed_evidence) if allowed_evidence else 0
        if fallback_ids: issues.append(f"{len(fallback_ids)} 章使用确定性兜底稿")
        status="completed" if not fallback_ids and not issues else "partial"
        quality=ChapterQualityReport(passed=not issues,chapter_count=len(chapters),section_count=sum(len(c.sections) for c in chapters),evidence_coverage=min(coverage,1),issues=issues,fallback_chapter_ids=fallback_ids)
        applied=[]
        for skill in self.skillhub.catalog.values():
            chapters_used=[chapter_id for chapter_id,skills in selected_by_chapter.items() if any(s.name == skill.name for s in skills)]
            if chapters_used:
                adaptation = skill_reasons.get(skill.name, skill.adaptation)
                applied.append(AppliedSkill(name=skill.name,description=skill.description,source=skill.source,adaptation=adaptation,chapters=chapters_used))
        result=ChapterWritingResult(run_id=run_id,source_report_id=request.report.report_id,subject=request.report.subject,as_of=request.report.as_of,status=status,outline_version=OUTLINE_VERSION if request.outline is None else "custom-1",model_name=self.settings.llm_model if self.llm.is_available else "deterministic-fallback",applied_skills=applied,chapters=chapters,quality=quality,warnings=warnings+issues+[f"写作阶段没有对应技能：{name}" for name in unavailable_skills],artifact_dir=str(artifact_dir.resolve()) if artifact_dir else None)
        result.question_answers = retriever.summarize_question_answers(chapters)
        await record("chapter_writing_completed",status=status,chapters=len(chapters),fallbacks=len(fallback_ids))
        if artifact_dir:
            artifact_dir.mkdir(parents=True,exist_ok=True)
            (artifact_dir/"request.json").write_text(request.model_dump_json(indent=2)+"\n",encoding="utf-8")
            (artifact_dir/"input_report.json").write_text(request.report.model_dump_json(indent=2)+"\n",encoding="utf-8")
            (artifact_dir/"input_charts.json").write_text((request.charts.model_dump_json(indent=2) if request.charts else "{}")+"\n",encoding="utf-8")
            (artifact_dir/"chapter_result.json").write_text(result.model_dump_json(indent=2)+"\n",encoding="utf-8")
            (artifact_dir/"events.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in events),encoding="utf-8")
        return result

    async def _generate_audited_chapter(
        self, request: ChapterWritingRequest, outline_chapter: Any,
        context: dict[str, Any], ready_charts: dict[str, Any],
        global_facts: dict[str, Any], record: Callable[..., Awaitable[None]], drop_log: list[str],
    ) -> tuple[ChapterDraft, str | None, str | None]:
        """Shared generation, repair and evidence audit for full and targeted writing."""
        allowed_evidence = set(request.report.evidence_index)
        global_facts_prompt = context["global_facts_prompt"]
        chapter = None
        errors: list[str] = []
        paragraph_warning = None
        if self.llm.is_available:
            for attempt in range(request.options.max_repairs + 1):
                try:
                    payload = {
                        "outline": outline_chapter.model_dump(mode="json"),
                        "subject": request.report.subject,
                        "as_of": request.report.as_of.isoformat(),
                        "audience": request.options.audience,
                        "style": request.options.style,
                        "target_length": request.options.target_length,
                        "instruction": request.options.instruction,
                        "context": context,
                        "global_facts": global_facts_prompt,
                        "previous_errors": errors[:24],
                    }
                    # The model client owns request retries; do not multiply them here.
                    system = SYSTEM_PROMPT
                    if errors:
                        system += (
                            "\n上一版未通过事实核验。保留已有大纲与小节编号。凡上一版包含密集数字，"
                            "把完整序列留给现有图表，将正文重写为判断、经营含义和跟踪条件。"
                            "仅在主体、指标、期间和全部记录能逐句对应时保留数字。"
                            "没有直接来源的原因写成可检验的假设。每节仍须有独立的实质分析。"
                        )
                    if context.get("question_assignments"):
                        system += (
                            "\n本章逐题主答见 context.question_assignments。每题在指定 section_id 直接给出"
                            "可验证的结论与边界。优先引用题目关联的已核证据和本章已有图表。"
                            "只在 evidence 中核对并引用 record_id。逐题写独立的主判断段，禁止把同组图中的其他指标张冠李戴。没有图时用已核事实或表格回答。"
                            "缺证或部分可比时说明缺少的指标、主体或期间，不补写未经验证的数字。"
                            "supporting_chart_sections 仅用于提示读者参阅对应章节，不能在本章挂接这些图。"
                            "related_question_sections 可用于指向相关主答小节，避免重复展开。"
                        )
                    prompt, packing = prepare_chapter_context(payload, system)
                    await record("context_budget_checked", chapter_id=outline_chapter.chapter_id,
                                 **packing)
                    raw = await self.llm.generate_json(system, prompt)
                    chapter = ChapterDraft.model_validate(raw)
                    chapter.content_audit = []
                    if any(not section.paragraphs for section in chapter.sections):
                        raise ValueError("生成章节含空节")
                    errors = self._audit_chapter(chapter, outline_chapter, allowed_evidence, ready_charts, context, global_facts, drop_log=drop_log)
                    await record("skill_linter_checked", chapter_id=outline_chapter.chapter_id, passed=not errors, issues=errors)
                    await record("chapter_attempt", chapter_id=outline_chapter.chapter_id, attempt=attempt + 1, issues=errors)
                    quarantined = []
                    for section in chapter.sections:
                        card_errors = [issue for issue in errors if issue.startswith(f"{section.section_id} 指标卡「")
                                       and issue.endswith("数值缺少证据绑定")]
                        for issue in card_errors:
                            label = issue.split("「", 1)[1].split("」", 1)[0]
                            section.metric_cards = [card for card in section.metric_cards if card.label != label]
                        table_error = f"{section.section_id} 对比表数值缺少证据绑定"
                        if table_error in errors:
                            section.comparison_table = None
                        removed = card_errors + ([table_error] if table_error in errors else [])
                        if removed:
                            chapter.content_audit.extend({
                                "code": "chapter_component_isolation", "location": section.section_id,
                                "section_id": section.section_id, "claim": issue, "disposition": "isolated",
                            } for issue in removed)
                            quarantined.extend(removed)
                    if quarantined:
                        errors = self._audit_chapter(chapter, outline_chapter, allowed_evidence,
                            ready_charts, context, global_facts, drop_log=drop_log)
                    if not errors:
                        if quarantined:
                            paragraph_warning = f"段落资料缺口：{chapter.chapter_id} {'；'.join(quarantined)}"
                        if attempt < request.options.max_repairs:
                            await self._add_numeric_readout(
                                chapter, outline_chapter, allowed_evidence, ready_charts, context, global_facts, record,
                            )
                        break
                    positions = {p.paragraph_id: (si, pi) for si, section in enumerate(chapter.sections)
                                 for pi, p in enumerate(section.paragraphs)}
                    failures = {pid: [issue for issue in errors if issue.startswith(pid + " ")]
                                for pid in positions}
                    failures = {pid: issues for pid, issues in failures.items() if issues}
                    if failures and all(any(issue in group for group in failures.values()) for issue in errors):
                        if (attempt == 0 and request.options.max_repairs >= 2
                                and len(failures) > request.options.max_repairs
                                and any(all(p.paragraph_id in failures for p in section.paragraphs)
                                        for section in chapter.sections)):
                            await record("chapter_redraft_requested", chapter_id=chapter.chapter_id,
                                         failing_paragraphs=len(failures))
                            chapter = None
                            continue
                        unresolved = list(quarantined)
                        remaining_repairs = request.options.max_repairs - attempt
                        for pid, para_issues in failures.items():
                            si, pi = positions[pid]
                            original = chapter.sections[si].paragraphs[pi]
                            repair_payload = {"subject": request.report.subject,
                                "section_id": chapter.sections[si].section_id,
                                "paragraph": original.model_dump(mode="json"), "issues": para_issues,
                                "evidence": context.get("evidence", {})}
                            await record("paragraph_repair_started", chapter_id=chapter.chapter_id,
                                         section_id=chapter.sections[si].section_id, paragraph_id=pid,
                                         issues=para_issues, evidence_ids=original.evidence_ids)
                            repaired = False
                            reason = "repair_disabled"
                            if remaining_repairs > 0:
                                remaining_repairs -= 1
                                try:
                                    reason = "audit_failed"
                                    repair_system = SYSTEM_PROMPT + "\n只返回修复后的单个段落 JSON，保持 paragraph_id。"
                                    prompt, _, _ = serialize_context(repair_payload, system=repair_system)
                                    raw = await self.llm.generate_json(repair_system, prompt)
                                    replacement = ParagraphDraft.model_validate(raw)
                                    if replacement.paragraph_id != pid:
                                        raise ValueError("paragraph_id 不一致")
                                    trial = chapter.model_copy(deep=True)
                                    trial.sections[si].paragraphs[pi] = replacement
                                    trial_issues = self._audit_chapter(trial, outline_chapter, allowed_evidence,
                                        ready_charts, context, global_facts)
                                    if not any(issue.startswith(pid + " ") for issue in trial_issues) and not (set(trial_issues) - set(errors)):
                                        chapter.sections[si].paragraphs[pi] = trial.sections[si].paragraphs[pi]
                                        repaired = True
                                        reason = "passed"
                                except Exception as exc:
                                    reason = type(exc).__name__
                            disposition = "repaired"
                            if not repaired:
                                evidence = context.get("evidence", {})
                                refs = [evidence[rid] for rid in original.evidence_ids if rid in evidence]
                                ratios = financial_calculation_rows(context.get("financial_ratios") or [], context.get("comps_matrix"))
                                refs.extend(verified_calculations(ratios, evidence, original.evidence_ids))
                                retained = retain_supported_claims(original.text, lambda clause: not quantity_issues(
                                    clause, refs, universe=list(evidence.values()),
                                    assumption_note=original.assumption_note, kind=original.kind,
                                    comparisons=(context.get("analysis_facts") or {}).get("comparisons") or [],
                                ))
                                trial = chapter.model_copy(deep=True)
                                if retained and retained != original.text:
                                    trial.sections[si].paragraphs[pi].text = retained
                                    trial_errors = self._audit_chapter(trial, outline_chapter,
                                        allowed_evidence, ready_charts, context, global_facts)
                                    if any(issue.startswith(pid + " ") for issue in trial_errors):
                                        retained = ""
                                else:
                                    retained = ""
                                chapter.sections[si].paragraphs[pi] = original.model_copy(update={
                                    "text": retained, "evidence_ids": original.evidence_ids if retained else [],
                                })
                                disposition = "partially_retained" if retained else "isolated"
                                unresolved.extend(para_issues)
                            chapter.content_audit.append({
                                "code": "chapter_claim_repair", "location": pid,
                                "section_id": chapter.sections[si].section_id,
                                "original": original.text, "claim": "；".join(para_issues),
                                "evidence_ids": original.evidence_ids, "disposition": disposition,
                                "reason": reason,
                            })
                            await record("paragraph_repair_completed", chapter_id=chapter.chapter_id,
                                         paragraph_id=pid, passed=repaired, reason=reason, issues=para_issues)
                        remaining = self._audit_chapter(chapter, outline_chapter, allowed_evidence,
                            ready_charts, context, global_facts, drop_log=drop_log)
                        for section in chapter.sections:
                            section.paragraphs = [para for para in section.paragraphs if para.text.strip()]
                        if remaining:
                            unresolved.extend(remaining)
                        if unresolved:
                            paragraph_warning = f"段落资料缺口：{chapter.chapter_id} {'；'.join(unresolved)}"
                        break
                    chapter = None
                except Exception as exc:
                    chapter = None
                    errors = [str(exc)[:500] if isinstance(exc, ContextBudgetExceeded) else type(exc).__name__]
                    await record("chapter_attempt_failed", chapter_id=outline_chapter.chapter_id, attempt=attempt + 1, error=errors[0])
                    if isinstance(exc, (ContextBudgetExceeded, httpx.HTTPError, TimeoutError)):
                        break
        fallback_id = None
        warning = paragraph_warning
        if chapter is None:
            chapter = self._fallback_chapter(request, outline_chapter, context, ready_charts, global_facts)
            fallback_id = outline_chapter.chapter_id
            warning = f"{outline_chapter.chapter_id} 使用确定性兜底稿：{'；'.join(errors) if errors else '未配置模型'}"
            await record("chapter_fallback", chapter_id=outline_chapter.chapter_id)
            fb_errors = self._audit_chapter(chapter, outline_chapter, allowed_evidence, ready_charts, context, global_facts, drop_log=drop_log)
            await record("skill_linter_checked", chapter_id=outline_chapter.chapter_id, passed=not fb_errors, issues=fb_errors)
        return chapter, fallback_id, warning

    async def _add_numeric_readout(
        self, chapter, outline, allowed_evidence, charts, context, global_facts, record,
    ) -> None:
        """Use one remaining repair slot to interpret an otherwise valid numeric list."""
        candidate = next(((si, pi) for si, section in enumerate(chapter.sections)
                          for pi, para in enumerate(section.paragraphs) if _lists_numbers(para)), None)
        if candidate is None:
            return
        si, pi = candidate
        section = chapter.sections[si]
        paragraph = section.paragraphs[pi]
        evidence = context.get("evidence") or {}
        refs = {rid: evidence[rid] for rid in paragraph.evidence_ids if rid in evidence}
        if not refs:
            return
        system = (
            "给通过事实核验的投研段落补一到两句简洁解读。只依据所给记录，说明这些数字"
            "支持的比较或业务判断。解释因果必须有直接披露；如果缺证据，指出具体缺少的科目"
            "或材料。保持原有事实，不重复数字，不新增量化断言，不写套话。"
            '只返回 JSON {"interpretation":"要追加到段末的解读"}。'
        )
        try:
            prompt, _, _ = serialize_context({
                "section_title": section.title, "purpose": section.purpose,
                "paragraph": paragraph.text, "evidence": refs,
            }, system=system)
            raw = await self.llm.generate_json(system, prompt)
            value = raw.get("interpretation")
            explanation = value.strip() if isinstance(value, str) else ""
            accepted = False
            if (explanation and len(explanation) <= 160 and explanation not in paragraph.text
                    and not any(unit for _, unit in QUANTITY_RE.findall(explanation))
                    and _READOUT.search(explanation)):
                trial = chapter.model_copy(deep=True)
                paragraph_trial = trial.sections[si].paragraphs[pi]
                separator = "" if paragraph.text.rstrip().endswith(("。", "！", "？", ".", "!", "?")) else "。"
                paragraph_trial.text = paragraph.text.rstrip() + separator + explanation
                if not self._audit_chapter(trial, outline, allowed_evidence, charts, context, global_facts):
                    section.paragraphs[pi] = paragraph_trial
                    accepted = True
        except Exception as exc:
            await record("numeric_readout_skipped", paragraph_id=paragraph.paragraph_id,
                         reason=type(exc).__name__)
            return
        await record("numeric_readout_checked", paragraph_id=paragraph.paragraph_id, accepted=accepted)

    def _audit_chapter(
        self,
        chapter: ChapterDraft,
        outline: Any,
        allowed: set[str],
        charts: dict[str, Any],
        context: dict[str, Any] | None = None,
        global_facts: dict[str, Any] | None = None,
        drop_log: list[str] | None = None,
    ) -> list[str]:
        issues = []
        # D-11 修复：越界证据被过滤时必须留痕。drop_log 是一条**独立于 issues 的软通道**——
        # issues 非空会触发本章重写/兜底（越界引用不应导致整章作废），而 drop_log 汇入
        # result.warnings，使“模型引用了非本章证据”这一事实可观测、可据以评估提示词质量。
        def _note_dropped(where: str, foreign: set[str]) -> None:
            if drop_log is not None and foreign:
                drop_log.append(
                    f"{chapter.chapter_id} {where}引用了非本章/未授权证据 {sorted(foreign)}，已剔除（越界留痕）"
                )

        if chapter.chapter_id != outline.chapter_id:
            issues.append("chapter_id 与大纲不一致")
        if [s.section_id for s in chapter.sections] != [s.section_id for s in outline.sections]:
            issues.append("section_id 或章节顺序与大纲不一致")
        seen_text = set()
        evidence_dict = (context.get("evidence") or {}) if context else {}
        context = context or {}
        ratios = financial_calculation_rows(context.get("financial_ratios") or [], context.get("comps_matrix"))
        if context is not None and "evidence" in context:
            allowed = allowed.intersection(evidence_dict)

        for row in context.get("requirement_evidence_matrix") or []:
            requirement = row.get("requirement") or {}
            coverage = row.get("coverage") or {}
            # Annual penetration has an explicit section owner and can be
            # independently missing even when monthly observations exist.
            if (coverage.get("passed") is not False
                    or not requirement.get("hard")
                    or "nev_penetration" not in (requirement.get("metric_families") or [])
                    or not re.search(r"全年|年度", requirement.get("label") or "")):
                continue
            owner = next((section for section in chapter.sections
                          if section.section_id == row.get("section_id")), None)
            if owner and "年度全口径渗透率缺少完整的同口径证据。" not in owner.uncertainties:
                owner.uncertainties.append("年度全口径渗透率缺少完整的同口径证据。")

        # Consistency repair: fix 22.14万亿 vs 2.21万亿 scale anomaly in chapter summary
        if global_facts and global_facts.get("market_cap_wan_yi"):
            cw = global_facts["market_cap_wan_yi"]
            cw_str = f"{cw}万亿元"
            cm_str = f"{cw * 10000:.2f}亿元"
            wrong_pattern = r"2\.21\s*万亿(?:元)?" if cw > 10 else r"22\.14\s*万亿(?:元)?"
            chapter.summary = re.sub(wrong_pattern, cw_str, chapter.summary)
            if cw <= 10:
                chapter.summary = re.sub(r"221411(?:\.07)?\s*亿元", cm_str, chapter.summary)

        for section in chapter.sections:
            expected = next((x for x in outline.sections if x.section_id == section.section_id), None)
            if expected:
                section.title = expected.title
                section.purpose = expected.purpose

            # Consistency repair in section key_points
            if global_facts and global_facts.get("market_cap_wan_yi"):
                cw = global_facts["market_cap_wan_yi"]
                cw_str = f"{cw}万亿元"
                cm_str = f"{cw * 10000:.2f}亿元"
                wrong_pattern = r"2\.21\s*万亿(?:元)?" if cw > 10 else r"22\.14\s*万亿(?:元)?"
                section.key_points = [
                    re.sub(r"221411(?:\.07)?\s*亿元", cm_str, re.sub(wrong_pattern, cw_str, kp)) if cw <= 10 else re.sub(wrong_pattern, cw_str, kp)
                    for kp in section.key_points
                ]

            for para in section.paragraphs:
                unknown = set(para.evidence_ids) - allowed
                if unknown:
                    _note_dropped(f"段落 {para.paragraph_id} ", unknown)
                    para.evidence_ids = [e for e in para.evidence_ids if e in allowed]

                # Consistency repair in paragraph text
                if global_facts and global_facts.get("market_cap_wan_yi"):
                    cw = global_facts["market_cap_wan_yi"]
                    cw_str = f"{cw}万亿元"
                    cm_str = f"{cw * 10000:.2f}亿元"
                    wrong_pattern = r"2\.21\s*万亿(?:元)?" if cw > 10 else r"22\.14\s*万亿(?:元)?"
                    para.text = re.sub(wrong_pattern, cw_str, para.text)
                    if cw <= 10:
                        para.text = re.sub(r"221411(?:\.07)?\s*亿元", cm_str, para.text)

                # Industry-specific entity rewrites were removed. A role may only
                # be asserted from this run's evidence, never from a fixed phrase map.

                # Filter out pure years (19xx, 20xx) and small list ordinals (1-10)
                nums = extract_numbers(para.text)
                substantive_nums = [n for n in nums if not YEAR_OR_ORDINAL_RE.match(n.strip())]

                # R4（V8 最终方案 §7.2）：**假设说明不能为已发生的事实数字提供依据**。
                # 旧实现的 `or para.assumption_note` 让模型自填任意一句"综合测算"
                # 就能豁免缺证据检查。现在只有 kind 维度（scenario/risk/methodology/
                # transition）保留窄通道；assumption_note 一律不构成豁免。
                if substantive_nums and not para.evidence_ids and not (
                    para.kind in ("scenario", "risk", "methodology", "transition")
                    and bool(re.search(r"假设|情景|如果|若|设定|敏感性", para.text))
                ):
                    matched_eids: list[str] = []
                    for eid, rec in evidence_dict.items():
                        if eid not in allowed:
                            continue
                        val_str = str(rec.get("value", "")).strip()
                        metric_str = str(rec.get("metric", "")).strip()
                        entity_str = str(rec.get("entity", "")).strip()
                        if val_str and len(val_str) >= 2 and val_str in para.text:
                            matched_eids.append(eid)
                        elif metric_str and len(metric_str) >= 2 and metric_str in para.text:
                            if entity_str and entity_str in para.text:
                                matched_eids.append(eid)
                    if matched_eids:
                        para.evidence_ids = list(dict.fromkeys(matched_eids))

                # R4：第二道检查与第一道同口径；assumption_note 不再是豁免项。
                if substantive_nums and not para.evidence_ids and not (
                    para.kind in ("scenario", "risk", "methodology", "transition")
                    and bool(re.search(r"假设|情景|如果|若|设定|敏感性", para.text))
                ):
                    issues.append(f"{para.paragraph_id} 数字缺少证据支撑（假设说明不能替代证据）")

                semantic_refs = [evidence_dict[eid] for eid in para.evidence_ids if eid in evidence_dict]
                semantic_refs.extend(verified_calculations(ratios, evidence_dict, para.evidence_ids))
                semantic_issues = quantity_issues(para.text,
                    semantic_refs,
                    universe=list(evidence_dict.values()), assumption_note=para.assumption_note,
                    kind=para.kind, location=para.paragraph_id,
                    comparisons=((context or {}).get("analysis_facts") or {}).get("comparisons") or [])
                issues.extend(
                    f"{para.paragraph_id} 因果判断缺少独立依据：{item['claim']}"
                    if item["code"] == "unsupported_causal_claim"
                    else f"{para.paragraph_id} 数值语义未通过：{item['claim']}（需同实体、指标和期间证据）"
                    for item in semantic_issues
                )
                normalized = "".join(para.text.split())
                # 空壳段落（只有图表占位符、尚待改写）与显式缺口句都是审计
                # 隔离的标准化产物，允许多节复用，不应触发重复重写。
                shell_only = bool(para.text.strip()) and not re.sub(
                    r"如图|所示|[,，。；;\s]", "", re.sub(r"\[[^\]]*\]", "", para.text or "")
                )
                if normalized in seen_text and GAP_NOTICE_MARK not in para.text and not shell_only:
                    issues.append(f"{para.paragraph_id} 与其他段落重复")
                seen_text.add(normalized)
                if len(para.text) > 1000:
                    issues.append(f"{para.paragraph_id} 段落过长")

            # Prune charts that do not belong to this chapter
            valid_cids = []
            for cid in section.chart_ids:
                if cid in charts:
                    chart_obj = charts[cid]
                    rec_ch = getattr(chart_obj, "recommended_chapter_id", None) or (
                        chart_obj.get("recommended_chapter_id") if isinstance(chart_obj, dict) else None
                    )
                    if not rec_ch or rec_ch == outline.chapter_id:
                        valid_cids.append(cid)
            section.chart_ids = valid_cids

            # Ground structured UI components & fix metric cards
            if section.metric_cards:
                for mc in section.metric_cards:
                    if getattr(mc, "evidence_ids", None):
                        _note_dropped("指标卡 ", set(mc.evidence_ids) - allowed)
                        mc.evidence_ids = [e for e in mc.evidence_ids if e in allowed]
                    # R4（V8 最终方案 §7.1）：指标卡是证据承载对象——
                    # 承载数值却无任何合法证据绑定，必须计入审计问题，
                    # 不能因为"看起来结构化"就默认可信。
                    mc_value = str(getattr(mc, "value", "") or "")
                    claim = f"{mc.label} {mc.period or ''} {mc_value}{mc.unit or ''}"
                    if not mc.evidence_ids and mc.period:
                        candidates = []
                        for entry in (context.get("comps_matrix") or {}).get("entries") or []:
                            company = entry.get("company_name") or ""
                            if not company or company not in mc.label:
                                continue
                            family = next((CLAIM_METRICS[term] for term in sorted(CLAIM_METRICS, key=len, reverse=True)
                                           if term.casefold() in mc.label.casefold()), None)
                            source = (entry.get("metric_provenance") or {}).get(family) or {}
                            ids = source.get("input_record_ids") or [source.get("record_id")]
                            if ids and set(ids) <= allowed:
                                refs = [evidence_dict[eid] for eid in ids]
                                refs += verified_calculations(ratios, evidence_dict, ids)
                                if not quantity_issues(claim, refs, universe=list(evidence_dict.values())):
                                    candidates.append(tuple(ids))
                        if len(set(candidates)) == 1:
                            mc.evidence_ids = list(candidates[0])
                    if mc_value and extract_numbers(mc_value) and not getattr(mc, "evidence_ids", None):
                        issues.append(
                            f"{section.section_id} 指标卡「{getattr(mc, 'label', '')}」数值缺少证据绑定"
                        )
                    elif mc_value and mc.evidence_ids and evidence_dict:
                        refs = [evidence_dict[eid] for eid in mc.evidence_ids if eid in evidence_dict]
                        refs += verified_calculations(ratios, evidence_dict, mc.evidence_ids)
                        if quantity_issues(claim, refs, universe=list(evidence_dict.values())):
                            issues.append(f"{section.section_id} 指标卡「{mc.label}」数值缺少证据绑定")
                    if global_facts and global_facts.get("market_cap_wan_yi") and "市值" in mc.label:
                        cw = global_facts["market_cap_wan_yi"]
                        if "22.14" in str(mc.value):
                            mc.value = f"{cw}万亿"
                        elif "221411" in str(mc.value):
                            mc.value = f"{cw * 10000:.2f}"
            if section.comparison_table and getattr(section.comparison_table, "evidence_ids", None):
                _note_dropped("对比表 ", set(section.comparison_table.evidence_ids) - allowed)
                section.comparison_table.evidence_ids = [e for e in section.comparison_table.evidence_ids if e in allowed]
            # R4：对比表同样承载数值——行内含实质数字却无证据绑定，记为审计问题
            if section.comparison_table is not None:
                table_rows = getattr(section.comparison_table, "rows", None) or []
                table_eids = getattr(section.comparison_table, "evidence_ids", None) or []
                row_nums: list[str] = []
                for row in table_rows:
                    cells = row if isinstance(row, (list, tuple)) else (
                        list(row.values()) if isinstance(row, dict) else [row]
                    )
                    for cell in cells:
                        row_nums.extend(
                            n for n in extract_numbers(str(cell))
                            if not YEAR_OR_ORDINAL_RE.match(n.strip())
                        )
                if row_nums and not table_eids:
                    issues.append(
                        f"{section.section_id} 对比表数值缺少证据绑定"
                    )
            if section.callouts:
                for co in section.callouts:
                    if getattr(co, "evidence_ids", None):
                        _note_dropped("callout ", set(co.evidence_ids) - allowed)
                        co.evidence_ids = [e for e in co.evidence_ids if e in allowed]

        # Auto-attach any unattached charts designated for this chapter.
        # 优先挂到已有对齐解读的小节；全章无正文时保留首个合法挂接，不造段。
        attached_cids = {cid for s in chapter.sections for cid in s.chart_ids}
        chapter_charts = [
            cid for cid, c in charts.items()
            if getattr(c, "recommended_chapter_id", None) == outline.chapter_id
        ]
        for cid in chapter_charts:
            if cid not in attached_cids:
                chart_evidence = set(getattr(charts[cid], "evidence_ids", []) or [])
                best_sec = max(
                    chapter.sections,
                    key=lambda s: chart_section_score(s, chart_evidence),
                    default=None,
                )
                if best_sec is not None:
                    best_sec.chart_ids.append(cid)
                    attached_cids.add(cid)

        for section in chapter.sections:
            for cid in section.chart_ids:
                if not _align_chart_reference(section, cid, charts[cid]):
                    issues.append(f"{section.section_id} 图表解读缺少可核验证据")

        # 审计隔离后可能留下「如图 [CHART-xx] 所示，」这类只有占位符、没有
        # 任何论述的空壳段落。改写为显式缺口句并保留图表引用：既不让空句
        # 进入排版层，也不删段（删段会造成空节，反而触发整章重写）。
        for section in chapter.sections:
            for para in section.paragraphs:
                text = para.text or ""
                body = paragraph_body(text)
                # 完全空的段落留给 repair 分支按既有语义删除（无证据数字必须
                # 被隔离，不得借缺口句复活）；这里只处理有占位符却无论述的空壳句。
                if not text.strip() or body:
                    continue
                tags = re.findall(r"\[[^\]]*\]", text)
                lead = f"如图 {'、'.join(tags)} 所示，" if tags else ""
                para.text = (
                    f"{lead}关于「{section.title}」，{GAP_NOTICE_MARK}；"
                    "相关数值已隔离，待补充同口径证据后再行判断。"
                )
                para.evidence_ids = []

        chapter.evidence_ids = list(dict.fromkeys(e for s in chapter.sections for p in s.paragraphs for e in p.evidence_ids))
        chapter.chart_ids = list(dict.fromkeys(c for s in chapter.sections for c in s.chart_ids))
        return list(dict.fromkeys(issues))

    def _fallback_chapter(
        self,
        request: ChapterWritingRequest,
        outline: Any,
        context: dict[str, Any],
        charts: dict[str, Any],
        global_facts: dict[str, Any] | None = None,
    ) -> ChapterDraft:
        evidence_by_id = context["evidence"]
        evidence_ids = list(evidence_by_id)
        universe = list(evidence_by_id.values())
        insights = context["insights"]
        questions_by_section = defaultdict(list)
        for question in context.get("question_assignments") or []:
            questions_by_section[question["section_id"]].append(question)
        chapters = []
        ch_charts = [
            c.chart_id
            for c in charts.values()
            if getattr(c, "recommended_chapter_id", None) == outline.chapter_id
        ]
        for index, section in enumerate(outline.sections):
            possible = [cid for i, cid in enumerate(ch_charts) if i % max(1, len(outline.sections)) == index][:1]
            chart_prefix = f"如图 [{possible[0]}] 所示，" if possible else ""
            chosen: list[str] = []
            base = ""
            if index < len(insights):
                insight = insights[index]
                claim = str(insight.get("conclusion") or insight.get("title") or "").strip()
                ids = insight.get("evidence_record_ids") or []
                if claim and ids and all(rid in evidence_by_id for rid in ids):
                    refs = [evidence_by_id[rid] for rid in ids]
                    if not quantity_issues(claim, refs, universe=universe):
                        base, chosen = claim, list(dict.fromkeys(ids))
            if not chosen:
                for eid in evidence_ids[index::3]:
                    item = evidence_by_id[eid]
                    period = measurement_period(item)
                    entity, unit, value = item.get("entity"), item.get("unit"), item.get("value")
                    if isinstance(value, str) and item.get("domain") in {"news", "reports", "events", "industry_chain"}:
                        excerpt = " ".join(value.split())
                        if excerpt and len(excerpt) <= 240:
                            claim = f"来源记载：{excerpt.rstrip('。')}。"
                            if not quantity_issues(claim, [item], universe=universe):
                                base, chosen = claim, [eid]
                                break
                    metric = metric_family(item.get("metric", ""))
                    label = next((term for term, key in CLAIM_METRICS.items()
                                  if key == metric and re.search(r"[\u4e00-\u9fff]", term)), None)
                    if (not period or not entity or not unit or not label or type(value) not in (int, float)
                            or item.get("scope", "consolidated") != "consolidated"
                            or item.get("currency", "CNY") != "CNY"
                            or any("conflict" in issue for issue in item.get("issues", []))):
                        continue
                    claim = f"{entity}截至{period[1].isoformat()}的{label}为{value}{unit}。"
                    if not quantity_issues(claim, [item], universe=universe):
                        base, chosen = claim + f"该数字是单期观察，判断{label}变化仍需核对同口径的前期数据。", [eid]
                        break
            text = chart_prefix + (base or f"“{section.title}”缺少可用于判断的直接证据。")
            question_paragraphs = []
            for question in questions_by_section[section.section_id]:
                refs = {
                    rid for row in question["requirements"] for rid in row["evidence_record_ids"]
                }
                supported = next(
                    (
                        (claim, ids)
                        for insight in insights
                        if (ids := insight.get("evidence_record_ids") or []) and set(ids) <= refs
                        and all(rid in evidence_by_id for rid in ids)
                        and (claim := str(insight.get("conclusion") or "").strip())
                        and not quantity_issues(claim, [evidence_by_id[rid] for rid in ids], universe=universe)
                    ),
                    None,
                )
                question_id = question["question_id"]
                body = supported[0] if supported else "现有证据尚不足以给出可核验的综合判断。"
                if supported and any(row["status"] != "covered" for row in question["requirements"]):
                    body += "其余相关指标或期间仍有证据缺口。"
                question_paragraphs.append(ParagraphDraft(
                    paragraph_id=f"P-{outline.chapter_id[-2:]}-{index+1:02d}-{question_id}",
                    kind="analysis", text=f"{question_id}：{body}", evidence_ids=supported[1] if supported else [],
                ))
            chapters.append(
                SectionDraft(
                    section_id=section.section_id,
                    title=section.title,
                    purpose=section.purpose,
                    key_points=[],
                    paragraphs=question_paragraphs + [
                        ParagraphDraft(
                            paragraph_id=f"P-{outline.chapter_id[-2:]}-{index+1:02d}-01",
                            kind="chart_readout" if possible else "analysis",
                            text=text,
                            evidence_ids=chosen,
                        )
                    ],
                    chart_ids=possible,
                    uncertainties=[] if chosen else ["缺少与本节直接相关的可验证资料"],
                )
            )
        all_ids = list(dict.fromkeys(e for s in chapters for p in s.paragraphs for e in p.evidence_ids))
        chart_ids = list(dict.fromkeys(c for s in chapters for c in s.chart_ids))
        return ChapterDraft(
            chapter_id=outline.chapter_id,
            title=outline.title,
            summary=f"本章围绕{outline.title}整理现有证据，并明确资料边界。",
            sections=chapters,
            evidence_ids=all_ids,
            chart_ids=chart_ids,
            used_fallback=True,
        )

    def _audit_package(
        self,
        chapters: list[ChapterDraft],
        allowed: set[str],
        charts: dict[str, Any],
        global_facts: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> list[str]:
        issues = []
        if len(chapters) != 7:
            issues.append("报告不是7章")
        if sum(len(x.sections) for x in chapters) != 21:
            issues.append("报告不是21节")
        if len({x.chapter_id for x in chapters}) != len(chapters):
            issues.append("章节ID重复")

        # Single-Placement Lock: verify and enforce each chart appears in AT MOST ONE section across the entire report
        seen_cids: dict[str, tuple[str, str]] = {}
        for chapter in chapters:
            for section in chapter.sections:
                for para in section.paragraphs:
                    if set(para.evidence_ids) - allowed:
                        issues.append("存在未知证据引用")

                clean_cids = []
                for cid in section.chart_ids:
                    if cid not in charts:
                        issues.append(f"{section.section_id} 存在未就绪图表引用 {cid}")
                        drop_chart_tag_from_section(section, cid)
                        continue
                    chart_obj = charts[cid]
                    rec_ch = getattr(chart_obj, "recommended_chapter_id", None) or (
                        chart_obj.get("recommended_chapter_id") if isinstance(chart_obj, dict) else None
                    )
                    # If chart was explicitly recommended for another chapter, remove from here
                    if rec_ch and rec_ch != chapter.chapter_id:
                        drop_chart_tag_from_section(section, cid)
                        continue
                    # If chart was already placed elsewhere, enforce single placement
                    if cid in seen_cids:
                        drop_chart_tag_from_section(section, cid)
                        continue
                    seen_cids[cid] = (chapter.chapter_id, section.section_id)
                    clean_cids.append(cid)
                section.chart_ids = clean_cids
            chapter.chart_ids = list(dict.fromkeys(c for s in chapter.sections for c in s.chart_ids))

        # Ensure all ready charts designated for a chapter are placed in that chapter.
        # 空节必须显式处理：可保留合法挂接，但不得访问 paragraphs[0]，也不补空壳图注。
        for cid, chart_obj in charts.items():
            rec_ch = getattr(chart_obj, "recommended_chapter_id", None) or (
                chart_obj.get("recommended_chapter_id") if isinstance(chart_obj, dict) else None
            )
            if rec_ch and cid not in seen_cids:
                target_ch = next((c for c in chapters if c.chapter_id == rec_ch), None)
                if target_ch and target_ch.sections:
                    chart_evidence = set(getattr(chart_obj, "evidence_ids", []) or [])
                    target_sec = max(
                        target_ch.sections,
                        key=lambda s: chart_section_score(s, chart_evidence),
                        default=None,
                    )
                    if target_sec is None:
                        continue
                    target_sec.chart_ids.append(cid)
                    target_ch.chart_ids = list(dict.fromkeys(c for s in target_ch.sections for c in s.chart_ids))
                    seen_cids[cid] = (target_ch.chapter_id, target_sec.section_id)

        # 已挂图但全节没有实际论述（空节或只剩隔离句）：保留合法挂接，记录解读缺口。
        for chapter in chapters:
            for section in chapter.sections:
                for cid in section.chart_ids:
                    if not _align_chart_reference(section, cid, charts[cid]):
                        issues.append(f"{section.section_id} 图表解读缺少可核验证据")

        # Cross-chapter market cap consistency audit
        mc_values = []
        for ch in chapters:
            for sec in ch.sections:
                for p in sec.paragraphs:
                    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*万亿", p.text):
                        val = float(m.group(1))
                        if val > 0.05:
                            mc_values.append((ch.chapter_id, val))
        if mc_values:
            vals = [v for _, v in mc_values]
            if max(vals) > min(vals) * 3.0:
                issues.append(f"跨章节总市值存在量级冲突：最高 {max(vals)} 万亿，最低 {min(vals)} 万亿")

        # P3：跨章同键结论只报告，不改正文；是否阻断由 A5 按严重级别决定。
        _cross_chapter_claim_audit(chapters, evidence)

        return list(dict.fromkeys(issues))
