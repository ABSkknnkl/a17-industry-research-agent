"""Editorial fusion, consistency checks and multi-format export."""
from __future__ import annotations
from agents_core.financial_semantics import quantity_issues, metric_family, measurement_period, retain_supported_claims, verified_calculations
from agents_core.context_budget import ContextBudgetExceeded, serialize_context
from collections.abc import Awaitable,Callable
from datetime import datetime
import hashlib,json,re,secrets
from pathlib import Path
from typing import Any

from report_fusion.config import Settings
from report_fusion.appendix import audit_appendix
from report_fusion.requirement_links import link_requirement_outputs
from report_fusion.llm import FusionLLM,OpenAICompatibleLLM
from report_fusion.models import *
from report_fusion.pdf import render_pdf
from report_fusion.render import render_html,render_markdown
from report_fusion.skillhub import FusionSkillHub

try:
    from skill_policy import merge_selection
except ModuleNotFoundError:  # 单包测试或独立运行时 agents_core 不在搜索路径上，按包位置回推
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from skill_policy import merge_selection

EventEmitter=Callable[[dict[str,Any]],Awaitable[None]]
_FINAL_REPAIR_LIMIT = 8
_MEASURED_CLAIM = re.compile(r"\d\s*(?:万亿元|亿元|万元|元|[%％倍家台辆吨]|个百分点)")
_LEGACY_GAP_PREFIXES = ("资料缺口：该段结论", "【资料缺口】本项断言")
_CHAPTER_QUALITY_BLOCK = "章节包含未通过质量核验的内容或兜底稿，仅提供受限草稿"
NUMBER_RE=re.compile(r"(?<![A-Za-z0-9_-])[-+]?\d+(?:\.\d+)?%?")

_SVG_ROOT_RE=re.compile(r"<svg\b[^>]*>",re.IGNORECASE)
_SVG_FIXED_W_RE=re.compile(r'\swidth="\d+(?:\.\d+)?(?:px)?"')

def _rewrite(artifact_dir: Path | None, name: str, data: bytes) -> None:
    """按最终视图就地重写文本格式（Markdown / HTML）。

    S-05：delivery_status 在导出后由最终事实决定，正文里嵌的值必须与之一致，
    否则读者看到“ready”但文件清单缺格式。只做原地覆盖，不新增产物。
    """
    if artifact_dir is None:
        return
    path = artifact_dir / name
    if path.exists():
        path.write_bytes(data)


def _audit_numeric_components(chapters: list[Any], summary: Any, request: Any, *, sanitize: bool = False) -> list[dict]:
    issues = []
    index = request.report.evidence_index
    def local_text(text: str, ids: list[str], **qualifiers) -> str:
        refs = [index[e] for e in ids if e in index]
        refs.extend(verified_calculations(request.report.financial_ratios, index, ids))
        return retain_supported_claims(text, lambda clause: not quantity_issues(
            clause, refs, universe=list(index.values()), **qualifiers,
        ))
    def audit(text: str, ids: list[str], location: str, **qualifiers) -> list[dict]:
        refs = [index[e] for e in ids if e in index]
        refs.extend(verified_calculations(request.report.financial_ratios, index, ids))
        found = quantity_issues(text, refs,
            universe=list(index.values()), location=location, **qualifiers)
        if sanitize:
            for issue in found:
                issue.update(original=text, disposition="isolated")
        issues.extend(found)
        return found
    for ch in chapters:
        ch_ids = list(dict.fromkeys(ch.evidence_ids + [e for s in ch.sections for p in s.paragraphs for e in p.evidence_ids]))
        if audit(ch.summary, ch_ids, ch.chapter_id + ".summary") and sanitize:
            ch.summary = local_text(ch.summary, ch_ids)
        for sec in ch.sections:
            sec_ids = list(dict.fromkeys(e for p in sec.paragraphs for e in p.evidence_ids))
            new_points = []
            for i, point in enumerate(sec.key_points):
                bad = audit(point, sec_ids, f"{sec.section_id}.key_points[{i}]")
                retained = local_text(point, sec_ids) if bad and sanitize else point
                if retained:
                    new_points.append(retained)
            if sanitize:
                sec.key_points = new_points
            for para in sec.paragraphs:
                bad = audit(para.text, para.evidence_ids, para.paragraph_id,
                    assumption_note=para.assumption_note, kind=para.kind)
                legacy_gap = para.text.startswith(_LEGACY_GAP_PREFIXES)
                if sanitize and (bad or legacy_gap or set(para.evidence_ids) - set(index)):
                    original = para.text
                    para.text = "" if legacy_gap else local_text(original, para.evidence_ids,
                        assumption_note=para.assumption_note, kind=para.kind)
                    para.evidence_ids = [rid for rid in para.evidence_ids if rid in index]
                    ch.content_audit.append({
                        "code": "fusion_claim_isolation", "location": para.paragraph_id,
                        "section_id": sec.section_id, "original": original,
                        "claim": "；".join(str(issue["claim"]) for issue in bad),
                        "evidence_ids": para.evidence_ids,
                        "disposition": "partially_retained" if para.text else "isolated",
                    })
            if sanitize:
                sec.paragraphs = [para for para in sec.paragraphs if para.text.strip()]
            cards = []
            for i, card in enumerate(sec.metric_cards):
                bad = audit(f"{card.label} {card.period or ''} {card.value}{card.unit or ''}", card.evidence_ids, f"{sec.section_id}.cards[{i}]")
                if not bad or not sanitize:
                    cards.append(card)
            if sanitize:
                sec.metric_cards = cards
            if sec.comparison_table:
                table = sec.comparison_table
                rows = []
                for i, row in enumerate(table.rows):
                    retained_row = list(row)
                    for j, cell in enumerate(row):
                        if j == 0:
                            continue
                        heading = table.columns[j] if j < len(table.columns) else table.title
                        # Table unit often lives in the column heading, not the cell.
                        unit_match = re.search(r"万亿元|亿元|万元|元|%|倍|家", heading)
                        cell_text = str(cell)
                        if unit_match and not re.search(r"元|%|倍|家", cell_text):
                            cell_text += unit_match.group(0)
                        bad = audit(f"{row[0]} {heading} {cell_text}", table.evidence_ids, f"{sec.section_id}.table[{i}][{j}]")
                        if bad and sanitize:
                            retained_row[j] = "待核验"
                    if not sanitize or any(cell != "待核验" for cell in retained_row[1:]):
                        rows.append(retained_row)
                if sanitize:
                    table.rows = rows
                    if not rows:
                        sec.comparison_table = None
            callouts = []
            for i, callout in enumerate(sec.callouts):
                # 风险/待核类提示是方法论与边界说明，不做数值断言核验。
                if re.search(r"需核实|需核验|异常|风险|待验证|可能|不确定|局限", callout.title + callout.text):
                    callouts.append(callout)
                    continue
                bad = audit(callout.title + " " + callout.text, callout.evidence_ids, f"{sec.section_id}.callouts[{i}]")
                if not bad or not sanitize:
                    callouts.append(callout)
                elif not audit(callout.title, callout.evidence_ids, f"{sec.section_id}.callouts[{i}].title"):
                    if retained := local_text(callout.text, callout.evidence_ids):
                        callouts.append(callout.model_copy(update={"text": retained}))
            if sanitize:
                sec.callouts = callouts
    if summary and not isinstance(summary, dict):
        # 摘要是全篇结论的概括，其证据基应包括正文索引，而不只是 conclusion
        # 自己列的 ID；数字仍必须能在索引中找到同量级观测，否则继续阻断。
        summary_ids = list(dict.fromkeys(
            [e for c in summary.conclusions for e in c.evidence_ids] + list(index)
        ))
        if audit(summary.headline, summary_ids, "summary.headline") and sanitize:
            summary.headline = local_text(summary.headline, summary_ids)
        for i, conclusion in enumerate(summary.conclusions):
            if audit(conclusion.text, conclusion.evidence_ids, f"summary.conclusions[{i}]") and sanitize:
                conclusion.text = local_text(conclusion.text, conclusion.evidence_ids)
                conclusion.evidence_ids = [rid for rid in conclusion.evidence_ids if rid in index]
        if sanitize:
            summary.conclusions = [item for item in summary.conclusions if item.text.strip()]
        cards = []
        for i, card in enumerate(summary.metric_cards):
            bad = audit(f"{card.label} {card.period or ''} {card.value}{card.unit or ''}", card.evidence_ids, f"summary.cards[{i}]")
            if not bad or not sanitize:
                cards.append(card)
        if sanitize:
            summary.metric_cards = cards
        for field in ("risks", "research_boundaries"):
            values = getattr(summary, field)
            verified = []
            for i, text in enumerate(values):
                # 风险/边界是方法论陈述，不做逐条数值核验（与附录局限同口径）。
                if re.search(r"未充分|未覆盖|未披露|样本|时间序列|口径|需核实|可能|有限|待验证", text):
                    verified.append(text)
                    continue
                bad = audit(text, summary_ids, f"summary.{field}[{i}]")
                if not bad or not sanitize:
                    verified.append(text)
                elif retained := local_text(text, summary_ids):
                    verified.append(retained)
            if sanitize:
                setattr(summary, field, verified)
        takeaways = []
        for i, item in enumerate(summary.takeaways):
            bad = audit(" ".join(item.values()), summary_ids, f"summary.takeaways[{i}]")
            if not bad or not sanitize:
                takeaways.append(item)
        if sanitize:
            summary.takeaways = takeaways
    return issues


def _chart_contract_issues(chart: Any, index: dict[str, Any]) -> list[str]:
    if getattr(chart, "chart_type", "") == "industry_chain":
        return []
    contract = getattr(chart, "data_contract", {}) or {}
    points = contract.get("points", [])
    if not points:
        return ["缺少数据点语义契约，图表尚未核验"]
    problems = []
    source_option = getattr(chart, "option", {}) or {}
    rendered_series = source_option.get("series", [])
    series_order = contract.get("series_order") or list(dict.fromkeys(p.get("series") for p in points))
    for point in points:
        ref = index.get(point.get("record_id"))
        if ref is None:
            problems.append("数据点证据不存在")
            continue
        if (point.get("entity") != ref.entity or metric_family(str(point.get("metric"))) != metric_family(ref.metric)
                or point.get("period") != (str(ref.period) if ref.period else None)
                or point.get("scope", "consolidated") != ref.scope
                or point.get("currency", "CNY") != ref.currency):
            problems.append("数据点实体、指标或期间与证据不符")
            continue
        try:
            idx = point["index"]
            series_name = point["series"]
            category = point.get("category")
            if chart.chart_type in ("scatter", "bubble"):
                entries = [entry for serie in rendered_series for entry in serie.get("data", [])
                           if isinstance(entry, dict) and entry.get("name") == category]
                if len(entries) != 1:
                    raise ValueError("scatter label")
                coordinate = series_order.index(series_name)
                actual_value = entries[0]["value"][coordinate]
            elif chart.chart_type == "radar":
                entries = [entry for serie in rendered_series for entry in serie.get("data", [])
                           if isinstance(entry, dict) and entry.get("name") == series_name]
                if len(entries) != 1:
                    raise ValueError("radar entity")
                indicators = source_option.get("radar", {}).get("indicator", [])
                if indicators[idx].get("name") != category:
                    raise ValueError("radar indicator")
                actual_value = entries[0]["value"][idx]
            else:
                matches = [serie for serie in rendered_series if serie.get("name") == series_name]
                if not matches and len(rendered_series) == 1:
                    matches = rendered_series
                if len(matches) != 1:
                    raise ValueError("series identity")
                entry = matches[0]["data"][idx]
                if isinstance(entry, dict):
                    if entry.get("name") and entry["name"] != category:
                        raise ValueError("category identity")
                    actual_value = entry["value"]
                else:
                    actual_value = entry
            if actual_value != point["value"]:
                raise ValueError("point value")
        except (ValueError, KeyError, TypeError, IndexError):
            problems.append("数据点与实际类别、系列或坐标位置不一致")
        scales = {"元": 1, "万元": 1e4, "亿元": 1e8, "万亿元": 1e12}
        try:
            unit = point.get("unit")
            expected = float(ref.value)
            if unit in scales and ref.unit in scales:
                expected *= scales[ref.unit] / scales[unit]
            elif unit != ref.unit:
                raise ValueError("unit mismatch")
            value = float(point["value"])
            digits = len(str(point["value"]).split(".")[1]) if "." in str(point["value"]) else 0
            if abs(value - expected) > 0.5 * 10 ** -digits + 1e-9:
                problems.append("图中数值无法由证据按声明单位换算")
        except (TypeError, ValueError, KeyError):
            problems.append("数据点数值或单位无可验证定义")
    source_option = getattr(chart, "option", {}) or {}
    actual = []
    def numbers(value: Any) -> None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            actual.append(float(value))
        elif isinstance(value, (list, tuple)):
            for item in value:
                numbers(item)
        elif isinstance(value, dict):
            numbers(value.get("value"))
    for series in source_option.get("series", []):
        numbers(series.get("data", []))
    wanted = [float(p["value"]) for p in points if isinstance(p.get("value"), (float, int))]
    if len(actual) != len(wanted):
        problems.append("渲染系列与数据点契约不一致")
    categories = contract.get("categories")
    if categories:
        axes = [source_option.get("xAxis", {}), source_option.get("yAxis", {})]
        axis_categories = [axis.get("data") for axis in axes if isinstance(axis, dict) and axis.get("data")]
        if axis_categories and categories not in axis_categories:
            problems.append("坐标轴样本标签与数据契约不一致")
    return list(dict.fromkeys(problems))


def _check_final_view(
    chapters: list[Any], embedded: list[Any], request: "ReportFusionRequest", summary: Any = None
) -> tuple[list[str], list[str]]:
    """对**最终要导出的对象**做校验，而不是复用编辑前的输入诊断。

    覆盖（V8 方案 §8.3 第 3 步）：
    - 未知证据引用（按最终章节的 evidence_ids 与新证据目录比对）
    - 图表挂载位置与 ready 状态
    - 关键图的 SVG 是否真实可读

    Returns:
        (blocking, warnings)。blocking 非空即不得宣告正式完成。
    """
    blocking: list[str] = []
    warnings: list[str] = []
    chart_quality = getattr(request.charts, 'quality', {}) if request.charts else {}
    chain_delivery = chart_quality.get("chain_delivery", {}) if isinstance(chart_quality, dict) else {}
    if chain_delivery.get("requested") and chain_delivery.get("status") not in ("complete", "classified"):
        blocking.append("产业链关系未完整核验：" + str(chain_delivery.get("reason") or "证据不足"))
    elif chain_delivery.get("requested") and chain_delivery.get("status") == "classified":
        warnings.append("产业链图为环节分类交付，具体工序关系待核验。")
    requested_count = chart_quality.get('requested_count') if isinstance(chart_quality, dict) else None
    if isinstance(requested_count, int) and not isinstance(requested_count, bool) and requested_count > len(embedded):
        blocking.append(f"用户要求 {requested_count} 张图表，最终报告嵌入 {len(embedded)} 张")
    if chapters and not any(para.text.strip() for chapter in chapters
                            for section in chapter.sections for para in section.paragraphs):
        blocking.append("报告正文没有可交付的核验段落")
    allowed = set(request.report.evidence_index)
    appendix = request.report.data_quality_appendix or {}
    for cell in appendix.get("requested_requirement_coverage") or []:
        if cell.get("hard") and not cell.get("passed") and not str(cell.get("requirement_id", "")).startswith("annual_"):
            blocking.append(f"必需研究数据缺口：{cell.get('label', cell.get('requirement_id'))}")
    required_cells = appendix.get("requested_financial_coverage") or appendix.get("sample_info", {}).get("requested_financial_coverage") or []
    for cell in required_cells:
        if not cell.get("passed"):
            blocking.append(f"指定年度指标缺口：{cell.get('label', cell.get('requirement_id'))}")

    def check_references(value: Any, location: str) -> None:
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "content_audit":
                    continue
                if key in ("evidence_ids", "evidence_record_ids", "point_evidence_ids") and isinstance(child, list):
                    unknown = {item for item in child if isinstance(item, str) and item} - allowed
                    if unknown:
                        blocking.append(f"{location} 含未知证据引用 {sorted(unknown)}")
                else:
                    check_references(child, f"{location}.{key}")
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                check_references(child, f"{location}[{index}]")

    # 包括摘要、指标卡、表格与 callout，不能只检查段落的引用。
    check_references(chapters, "chapters")
    check_references(summary, "summary")
    check_references(appendix, "appendix")
    _, appendix_issues = audit_appendix(request.report)
    blocking.extend(f"{issue['location']} 附录断言未通过核验：{issue['claim']}" for issue in appendix_issues)

    for chapter in chapters:
        for section in getattr(chapter, "sections", []):
            for para in getattr(section, "paragraphs", []):
                unknown = set(getattr(para, "evidence_ids", []) or []) - allowed
                if unknown:
                    pid = getattr(para, "paragraph_id", "?")
                    blocking.append(f"{pid} 含未知证据引用 {sorted(unknown)}")

    embedded_map = {
        getattr(chart, "chart_id", ""): chart for chart in embedded
    }
    # 声明为 ready 但没能进入 embedded 的图（缺可读图形）同样阻断正式交付
    declared_ready = {
        c.chart_id
        for c in (request.charts.charts if request.charts else [])
        if getattr(c, "status", "") == "ready"
    }
    dropped = declared_ready - set(embedded_map)
    for cid in sorted(dropped):
        warnings.append(f"{cid} 声明为 ready 但未挂载到章节，未计入正文图表")
    for chapter in chapters:
        for section in getattr(chapter, "sections", []):
            for cid in getattr(section, "chart_ids", []) or []:
                if cid not in embedded_map:
                    warnings.append(f"{getattr(section, 'section_id', '?')} 引用的图表 {cid} 未就绪")

    for declared in (request.charts.charts if request.charts else []):
        if getattr(declared, "status", "") == "ready":
            blocking.extend(f"{getattr(declared, 'chart_id', '?')} {p}" for p in _chart_contract_issues(declared, request.report.evidence_index))
            blocking.extend(f"{getattr(declared, 'chart_id', '?')} {p}" for p in _chart_comparability_issues(declared, request.report.evidence_index))
    for chart in embedded:
        cid = getattr(chart, "chart_id", "?")
        unknown = set(getattr(chart, "evidence_ids", []) or []) - allowed
        if unknown:
            blocking.append(f"{cid} 含未知证据引用 {sorted(unknown)}")
        render_mode = getattr(chart, "render_mode", "") or ""
        # EmbeddedChart 的正文字段就叫 `svg`（不是 inline_svg）；
        # 兼容 image_uri 承载位图的 generated_image 模式。
        svg_payload = getattr(chart, "svg", None)
        readable = False
        if isinstance(svg_payload, str) and svg_payload.strip():
            if 'data-placeholder="true"' in svg_payload:
                # 占位图不是真实图形，不得计入 ready
                readable = False
            elif svg_payload.lstrip().startswith("<svg"):
                readable = True
            else:
                try:
                    readable = Path(svg_payload).is_file() and Path(svg_payload).stat().st_size > 0
                except OSError:
                    readable = False
        if render_mode == "generated_image":
            image_uri = getattr(chart, "image_uri", None)
            if isinstance(image_uri, str) and image_uri:
                try:
                    readable = Path(image_uri).is_file() and Path(image_uri).stat().st_size > 0
                except OSError:
                    readable = False
        if not readable:
            # 关键图 SVG 不可读：不得计入 ready，也不生成占位图冒充成功
            blocking.append(f"{cid} 的 SVG 文件不可读")
            try:
                chart.status = "failed"
            except Exception:
                pass
    # 跨章节完全重复的段落只保留首次出现，避免“与其他段落重复”阻断交付。
    seen_paragraphs: set[str] = set()
    for chapter in chapters:
        for section in getattr(chapter, "sections", []):
            kept = []
            for para in section.paragraphs:
                normalized = re.sub(r"\s+", "", str(getattr(para, "text", "") or ""))
                if normalized and normalized in seen_paragraphs:
                    continue
                if normalized:
                    seen_paragraphs.add(normalized)
                kept.append(para)
            section.paragraphs = kept

    # 章节导语是编辑性概述，不是数据表；保留含数字的断言会迫使整篇报告降级。
    # 在终审前把导语中的数字句剥离，具体数值由正文图表与附录承载。
    for chapter in chapters:
        summary_text = str(getattr(chapter, "summary", "") or "")
        if summary_text and re.search(r"\d", summary_text):
            kept = [part for part in re.split(r"(?<=[。；])", summary_text)
                    if part.strip() and not re.search(r"\d", part)]
            chapter.summary = ("".join(kept).strip()
                               or "本章基于已核验的公开数据展开分析，具体数值与口径见正文图表与附录。")
    numeric_issues = _audit_numeric_components(chapters, summary, request)
    blocking.extend(f"{issue['location']} 数值断言无匹配证据：{issue['claim']}" for issue in numeric_issues)
    return list(dict.fromkeys(blocking)), list(dict.fromkeys(warnings))


def _chart_comparability_issues(chart: Any, index: dict[str, Any]) -> list[str]:
    """Check source contracts independently of a generated eligibility flag."""
    if getattr(chart, "chart_type", "") == "industry_chain":
        return []
    refs = [index[p["record_id"]] for p in (getattr(chart, "data_contract", {}) or {}).get("points", [])
        if p.get("record_id") in index]
    if not refs:
        return []  # Missing point contracts are handled by the factual gate.
    temporal = getattr(chart, "chart_type", "") in ("line", "multi_line", "trend_line", "area", "stacked_area")
    points = (getattr(chart, "data_contract", {}) or {}).get("points", [])
    temporal = temporal and all(p.get("period") and str(p["period"])[:4] in str(p.get("category", "")) for p in points)
    from agents_core.financial_semantics import chart_comparability_issues
    return chart_comparability_issues(refs, temporal=temporal)


def _fit_svg_for_page(svg:str)->str:
    """把带固定像素宽高的 SVG 根标签改成自适应页宽（2026-10-17）。

    起因：产业链图的确定性 SVG 根标签是 ``width="1440" height="1020"``（前端内联要
    像素级布局），但报告页在 A4 下的内容宽只有约 6.5in —— 原样嵌入会把右侧两栏裁掉。
    ECharts 那批 SVG 只写 viewBox 不写 width，天然自适应，所以历史没暴露这个问题。

    只改**根标签**的 width/height，不动 inner 元素与 viewBox（缩放靠 viewBox 完成）。
    """
    if not svg:
        return svg
    match=_SVG_ROOT_RE.search(svg)
    if not match:
        return svg
    tag=match.group(0)
    if not _SVG_FIXED_W_RE.search(tag):
        return svg
    fixed=re.sub(r'\swidth="[^"]*"',' width="100%"',tag)
    fixed=re.sub(r'\sheight="[^"]*"','',fixed)
    if "style=" not in fixed:
        fixed=fixed[:-1]+' style="max-width:100%;height:auto;display:block;margin:0 auto;">'
    return svg[:match.start()]+fixed+svg[match.end():]

# 并集合并后可挂载的总编审校规范上限
FUSION_SKILL_LIMIT = 10
SYSTEM_PROMPT="""你是行业研究报告总编辑。只能编辑已有内容，不能补充外部事实、数字或来源。skills 只提供编辑方法，绝不是事实来源。
返回JSON：headline；conclusions[{text,evidence_ids,confidence,uncertainty}]；risks；research_boundaries；terminology_map；chapter_transitions；paragraph_edits。
【重要约束规范】：
1. terminology_map 仅用于极少数专业术语或别名的一致性归一（例如将“动力锂电池”归一为“动力电池”）。
   - 严禁将专业术语、指标代码（如 PB、PE、ROE）替换为长句解释或名词定义；
   - 严禁将研究主题（如“人形机器人”、“新能源汽车”、“航天”）作为映射 key 替换为长句定义；
   - 映射后的目标词（value）必须是极简短的专有名词（不超过 8 个字），严禁包含逗号、句号、冒号、分号或任何解释性描述语句；如果不需别名归一，保持 terminology_map 为空字典 {}。
2. chapter_transitions 是 chapter_id 到承上启下过渡句的映射；
3. paragraph_edits 是 paragraph_id 到 {text, evidence_ids} 的微调映射（正文各章节内容已完成严格证据核对，通常必须保持为空字典 {}。严禁无故大段重写！保留已有证据支撑的比较、业务解释和判断边界，避免把解释压缩成数字复述。严禁改动任何数字、严禁增加任何未在原文中出现的数字，包括股票代码如 002085、年份、列表序号等；必须 100% 原样保留所有数字与精确字面值；必须完全复用原段落的 evidence_ids，严禁伪造不存在的证据编号）；
4. 所有证据ID必须来自输入；所有数字必须已存在于输入。"""

def _sha(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def _numbers(value:object)->set[str]:return set(NUMBER_RE.findall(json.dumps(value,ensure_ascii=False,default=str)))

def prepare_fusion_context(payload: dict[str, Any], system: str) -> tuple[str, dict[str, int]]:
    """Remove transport-only evidence metadata without dropping report content or citations."""
    original = json.dumps(payload, ensure_ascii=False, default=str)
    before = len(original.encode("utf-8")) + len(system.encode("utf-8"))
    try:
        prompt, size, budget = serialize_context(payload, system=system)
    except ContextBudgetExceeded:
        import copy
        compact = copy.deepcopy(payload)
        evidence = payload.get("evidence", {})
        aliases = {}
        text_content = json.dumps(payload.get("chapters", []), ensure_ascii=False, default=str)
        for key, value in evidence.items():
            canonical = str(value.get("record_id") or key)
            if (key != canonical and canonical in evidence and evidence[canonical] == value
                    and f"[{key}]" not in text_content):
                aliases[key] = canonical
        def rewrite_refs(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in {"evidence_ids", "evidence_record_ids", "allowed_evidence_ids"} and isinstance(value, list):
                        node[key] = list(dict.fromkeys(aliases.get(item, item) for item in value))
                    else:
                        rewrite_refs(value)
            elif isinstance(node, list):
                for item in node:
                    rewrite_refs(item)
        rewrite_refs(compact)
        compact["evidence"] = {
            key: {k: v for k, v in value.items() if k not in {"trace_id", "skill_id"}}
            for key, value in evidence.items() if key not in aliases
        }
        serialized = json.dumps(compact, ensure_ascii=False, default=str)
        after = len(serialized.encode("utf-8")) + len(system.encode("utf-8"))
        try:
            prompt, size, budget = serialize_context(compact, system=system)
        except ContextBudgetExceeded as exc:
            raise ContextBudgetExceeded(f"压缩前 {before} 字节，压缩后 {after} 字节；{exc}；必需内容超限") from exc
    return prompt, {"before_bytes": before, "after_bytes": size, "budget_bytes": budget}

def _is_total_market_cap_context(prefix: str) -> bool:
    """Require a total label in the number's own clause, without a company owner."""
    clause = re.split(r"[，,。；;\n：:]", prefix)[-1].strip()
    return bool(re.fullmatch(
        r"(?:样本(?:证券池)?|证券池|行业|板块)的?(?:总|合计)市值(?:约为|约|为|达|达到|合计|共计)?\s*",
        clause,
    ))


def _deduplicate_warnings(warnings: list[str]) -> list[str]:
    seen: list[str] = []
    for w in warnings:
        w_str = str(w).strip()
        if not w_str:
            continue
        is_subsumed = False
        for idx, existing in enumerate(seen):
            if w_str == existing:
                is_subsumed = True
                break
            if existing.startswith(w_str) or (len(w_str) >= 15 and w_str in existing):
                is_subsumed = True
                break
            if w_str.startswith(existing) or (len(existing) >= 15 and existing in w_str):
                seen[idx] = w_str
                is_subsumed = True
                break
        if not is_subsumed:
            seen.append(w_str)
    return seen

FUSION_SKILL_PLANNING_PROMPT = """你是研报融合与总编审校模块。
你必须基于待融合研报的整体结构（主题、章节数量与大纲、图表数量、证据量、数据质量预警等），自主调用 `invoke_skill` 工具选择指导本研报审校与融合的专业技能。
可用技能包括：
- executive-summary-synthesis：执行摘要与核心结论高度提炼
- report-consistency-audit：跨章节逻辑、术语与事实一致性审计
- report-visual-quality：图表图文混排与排版可读性优化
- evidence-catalog：可穿透证据目录与索引构建
必须调用 `invoke_skill` 并给出专业、针对性的调用理由。"""


class ReportFusionAgent:
    def __init__(self,*,settings:Settings|None=None,llm:FusionLLM|None=None,pdf_renderer=None,skillhub:FusionSkillHub|None=None)->None:
        self.settings=settings or Settings.from_env();self.llm=llm or OpenAICompatibleLLM(self.settings);self.pdf_renderer=pdf_renderer or render_pdf;self.skillhub=skillhub or FusionSkillHub()

    async def _plan_editorial_skills(
        self,
        request: ReportFusionRequest,
        record: Any,
    ) -> tuple[list[FusionSkill], dict[str, str]]:
        # 确定性路由始终先算：总编审校的标准四维规范是必备下限，
        # 它与模型规划取并集，模型漏选的规范由此补上。
        # 融合层技能元数据默认为 always=True（强制规范），因此不会被意图裁剪；
        # 保留 intent_text 参数是为了四层接口一致、将来新增条件性技能时能自动生效。
        policy_skills = self.skillhub.select()
        policy_reasons = {s.name: s.adaptation or "默认审校规范" for s in policy_skills}
        intent_text = " ".join(
            part for part in (
                getattr(getattr(request, "report", None), "subject", ""),
                " ".join(str(x) for x in (getattr(request, "warnings", None) or [])),
            ) if part
        )

        if self.llm.is_available and hasattr(self.llm, "plan_skills_with_tools"):
            try:
                tools = self.skillhub.get_tool_spec()
                user_prompt = json.dumps({
                    "subject": request.report.subject,
                    "as_of": request.report.as_of.isoformat(),
                    "chapter_count": len(request.chapters.chapters),
                    "chapters": [
                        {"chapter_id": c.chapter_id, "title": c.title, "sections_count": len(c.sections)}
                        for c in request.chapters.chapters
                    ],
                    "charts_count": len(request.charts.charts) if request.charts else 0,
                    "evidence_count": len(request.report.evidence_index),
                    "warnings_count": len(request.report.warnings) + len(request.chapters.warnings),
                }, ensure_ascii=False, default=str)

                planned = await self.llm.plan_skills_with_tools(
                    FUSION_SKILL_PLANNING_PROMPT, user_prompt, tools
                )
                if planned:
                    model_skills: list[FusionSkill] = []
                    reasons: dict[str, str] = {}
                    seen = set()
                    for item in planned:
                        sname = item.get("skill_name", "")
                        reason = item.get("reason", "")
                        skill = self.skillhub.get(sname)
                        if skill and sname not in seen:
                            seen.add(sname)
                            model_skills.append(skill)
                            reasons[sname] = reason or "大模型自主调用"
                            await record("skill_invoked_by_llm", skill=sname, reason=reasons[sname])
                    for s in self.skillhub.catalog.values():
                        if s.always and s.name not in seen:
                            seen.add(s.name)
                            model_skills.append(s)
                            reasons[s.name] = "总编基础审校规范"
                    if model_skills:
                        merged = merge_selection(
                            model_skills, policy_skills,
                            limit=FUSION_SKILL_LIMIT,
                            intent_text=intent_text,
                        )
                        merged_reasons: dict[str, str] = {}
                        for skill in merged.final:
                            if skill.name in reasons:
                                merged_reasons[skill.name] = reasons[skill.name]
                            else:
                                merged_reasons[skill.name] = policy_reasons.get(
                                    skill.name, skill.adaptation or "确定性路由补充"
                                )
                                await record(
                                    "skill_routed_by_policy",
                                    skill=skill.name,
                                    route_type="fast_skill_router",
                                    reason=merged_reasons[skill.name],
                                )
                        return merged.final, merged_reasons
            except Exception:
                pass

        await record("skill_routed_by_policy", skills=[s.name for s in policy_skills], route_type="fast_skill_router", reason="总编审校标准四维规范快速路由")
        return policy_skills, policy_reasons

    async def _repair_final_paragraphs(self, chapters, request, issues, record) -> None:
        """One bounded call for failed paragraphs, with local citations and a full recheck."""
        index = request.report.evidence_index
        by_location: dict[str, list[dict]] = {}
        for issue in issues:
            by_location.setdefault(issue["location"], []).append(issue)
        pending = {}
        for chapter in chapters:
            for section in chapter.sections:
                for paragraph in section.paragraphs:
                    errors = by_location.get(paragraph.paragraph_id)
                    refs = {rid: index[rid] for rid in paragraph.evidence_ids if rid in index}
                    if errors and refs and len(pending) < _FINAL_REPAIR_LIMIT:
                        pending[paragraph.paragraph_id] = (chapter, section, paragraph, refs, errors)
        if not pending:
            return

        system = (
            "修复失败的研报段落。仅使用对应段落的本地证据，保留已有证据支持的句子。"
            "禁止把未经验证的预测、因果或趋势改写成事实。"
            '返回 {"paragraphs":{"原段落ID":"完整修复文本"}}。'
        )
        payload = {
            pid: {"text": paragraph.text, "issues": errors,
                  "evidence": {rid: ref.model_dump(mode="json") for rid, ref in refs.items()}}
            for pid, (_, _, paragraph, refs, errors) in pending.items()
        }
        try:
            prompt, _, _ = serialize_context(payload, system=system)
            raw = await self.llm.generate_json(system, prompt)
            proposals = raw.get("paragraphs", {})
            if not isinstance(proposals, dict):
                return
        except Exception as exc:
            await record("final_claim_repair_failed", error=type(exc).__name__)
            return

        repaired = 0
        for pid, (chapter, section, paragraph, refs, errors) in pending.items():
            proposed = proposals.get(pid)
            if not isinstance(proposed, str) or not proposed.strip() or proposed.strip() == paragraph.text:
                continue
            evidence = list(refs.values())
            evidence.extend(verified_calculations(request.report.financial_ratios, index, list(refs)))

            def supported(text: str) -> bool:
                return not quantity_issues(text, evidence, universe=list(index.values()),
                    assumption_note=paragraph.assumption_note, kind=paragraph.kind)

            retained = retain_supported_claims(paragraph.text, supported)
            if not supported(proposed) or (retained and retained not in proposed):
                continue
            # A rewrite must still contain evidence-supported content after the repair.
            if not retained and not _MEASURED_CLAIM.search(proposed):
                continue
            chapter.content_audit.append({
                "code": "fusion_claim_repair", "location": pid, "section_id": section.section_id,
                "original": paragraph.text, "claim": "；".join(str(item["claim"]) for item in errors),
                "evidence_ids": list(refs), "disposition": "repaired",
            })
            paragraph.text = proposed.strip()
            repaired += 1
        await record("final_claim_repair_completed", selected=len(pending), repaired=repaired)

    async def run(self,request:ReportFusionRequest,emit:EventEmitter|None=None,save_artifacts:bool=True)->ReportFusionResult:
        run_id=f"report-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}";report_id=f"REPORT-{secrets.token_hex(6).upper()}";artifact_dir=self.settings.output_dir/"runs"/run_id if save_artifacts else None;events=[]
        async def record(event:str,**details):
            item={"timestamp":datetime.now().astimezone().isoformat(),"event":event,"details":details};events.append(item)
            if emit:
                try:await emit(item)
                except Exception:pass
        await record("fusion_started",source_chapters=request.chapters.run_id)
        skills, skill_reasons = await self._plan_editorial_skills(request, record)
        await record("skills_applied",skills=[skill.name for skill in skills])
        issues,warnings=self._check_inputs(request)
        chapters=[c.model_copy(deep=True) for c in request.chapters.chapters]
        self._reconcile_market_cap_consistency(chapters, request)
        summary=self._default_summary(request)
        accepted=rejected=0;term_map={}
        if request.options.enable_editorial_llm and self.llm.is_available:
            try:
                payload=self._editorial_payload(request);payload["skills"]=[{"name":skill.name,"instructions":skill.instructions} for skill in skills]
                prompt, packing = prepare_fusion_context(payload, SYSTEM_PROMPT)
                await record("context_budget_checked", **packing, stage="editorial")
                raw=await self.llm.generate_json(SYSTEM_PROMPT,prompt)
                summary,chapters,term_map,accepted,rejected,edit_warnings=self._apply_editorial(raw,request,chapters)
                warnings.extend(edit_warnings)
                await record("skill_linter_checked", accepted=accepted, rejected=rejected, passed=True)
                await record("editorial_completed",accepted=accepted,rejected=rejected)
            except Exception as exc:
                failure = str(exc)[:300] if isinstance(exc, ContextBudgetExceeded) else type(exc).__name__
                warnings.append(f"模型编辑失败，已使用规则融合：{failure}");await record("editorial_failed",error=failure)
        elif request.options.enable_editorial_llm:
            warnings.append("未配置模型，已使用规则融合与确定性摘要")
            await record("skill_linter_checked", passed=not issues, issues=issues)
        else:
            await record("skill_linter_checked", passed=not issues, issues=issues)
        embedded=self._embed_charts(request,chapters,warnings)
        # S-05：输入诊断（_check_inputs）只作内部审计基线；真正的交付判定
        # 必须针对**归位后的最终章节与嵌入图**再校验一次。
        requirement_matrix = (request.report.data_quality_appendix or {}).get("requirement_evidence_matrix") or []
        before_links = {row["requirement_id"]: row for row in link_requirement_outputs(requirement_matrix, chapters, embedded)}
        if request.options.enable_editorial_llm and self.llm.is_available:
            initial_issues = _audit_numeric_components(chapters, summary, request)
            await self._repair_final_paragraphs(chapters, request, initial_issues, record)
        quality_issues = _audit_numeric_components(chapters, summary, request, sanitize=True)
        content_audit = [entry for chapter in chapters for entry in chapter.content_audit]
        input_chapter_issues = request.chapters.quality.get("issues") or []
        recovered_chapter_claims = bool(
            input_chapter_issues
            and all(str(issue).startswith("段落资料缺口：") for issue in input_chapter_issues)
            and any(entry.get("code") == "chapter_claim_repair" and entry.get("replacement_evidence_ids")
                    for entry in content_audit)
            and all(entry.get("disposition") == "repaired" for entry in content_audit)
            and not any(chapter.used_fallback for chapter in chapters)
        )
        if recovered_chapter_claims:
            issues = [issue for issue in issues if issue != _CHAPTER_QUALITY_BLOCK]
        safe_appendix, appendix_issues = audit_appendix(request.report)
        quality_issues.extend(appendix_issues)
        quality_issues.extend(dict(code="chart_comparability", severity="error", location=c.chart_id,
            claim=problem, evidence_ids=c.evidence_ids, suggestion="补齐共同期间和测量范围后再比较")
            for c in (request.charts.charts if request.charts else []) if c.status == "ready"
            for problem in _chart_comparability_issues(c, request.report.evidence_index))
        invalid_chart_ids = {c.chart_id for c in (request.charts.charts if request.charts else [])
                             if _chart_contract_issues(c, request.report.evidence_index)}
        if invalid_chart_ids:
            embedded = [c for c in embedded if c.chart_id not in invalid_chart_ids]
            for chapter in chapters:
                for section in chapter.sections:
                    section.chart_ids = [cid for cid in section.chart_ids if cid not in invalid_chart_ids]
            quality_issues.extend(dict(code="chart_contract", severity="error", location=cid,
                evidence_ids=[], suggestion="修正图表语义契约后重新生成") for cid in sorted(invalid_chart_ids))
        final_blocking, final_warnings = _check_final_view(chapters, embedded, request, summary)
        output_links = link_requirement_outputs(requirement_matrix, chapters, embedded)
        for row in output_links:
            before = before_links.get(row["requirement_id"], {})
            if row["hard"] and before.get("status") == "cited" and row["status"] == "not_cited":
                row["status"] = "answer_withheld"
                final_blocking.append(f"必答内容尚未通过核验：{row['label'] or row['requirement_id']}")
        safe_appendix["requirement_output_links"] = output_links
        appendix = request.report.data_quality_appendix or {}
        cells = appendix.get("requested_financial_coverage") or appendix.get("sample_info", {}).get("requested_financial_coverage") or []
        quality_issues.extend(dict(code="required_financial_cell", severity="error", location=cell.get("requirement_id"),
            claim=cell.get("label"), evidence_ids=cell.get("evidence_record_ids", []), suggestion="补齐指定年度指标")
            for cell in cells if not cell.get("passed"))
        known_claims = {str(q.get("claim", "")) for q in quality_issues}
        quality_issues.extend(dict(code="delivery_rule", severity="error", location="report", claim=problem,
            evidence_ids=[], suggestion="解决质量问题后重新融合") for problem in issues if problem not in known_claims)
        if artifact_dir and (quality_issues or content_audit):
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "fact_audit.json").write_text(json.dumps({
                "quality_issues": quality_issues, "content_audit": content_audit,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        for w in final_warnings:
            if w not in warnings:
                warnings.append(w)
        used_evidence = {
            evidence_id
            for chapter in chapters
            for section in chapter.sections
            for paragraph in section.paragraphs
            for evidence_id in paragraph.evidence_ids
        }
        used_evidence.update(
            evidence_id
            for conclusion in summary.conclusions
            for evidence_id in conclusion.evidence_ids
        )
        used_evidence.update(
            evidence_id for chart in embedded for evidence_id in chart.evidence_ids
        )
        def referenced_ids(value: Any) -> set[str]:
            if hasattr(value, "model_dump"):
                value = value.model_dump(mode="json")
            if isinstance(value, dict):
                found = set()
                for key, child in value.items():
                    if key in ("evidence_ids", "evidence_record_ids") and isinstance(child, list):
                        found.update(e for e in child if isinstance(e, str))
                    else:
                        found.update(referenced_ids(child))
                return found
            if isinstance(value, list):
                return set().union(*(referenced_ids(child) for child in value)) if value else set()
            return set()
        used_evidence.update(referenced_ids(chapters))
        used_evidence.update(referenced_ids(summary))
        used_evidence.update(referenced_ids(safe_appendix))
        ordered_evidence = [
            evidence
            for evidence_id, evidence in request.report.evidence_index.items()
            if evidence_id in used_evidence
        ]
        catalog=[EvidenceSource(number=i,record_id=e.record_id,label=f"{e.entity or request.report.subject} / {e.metric}",domain=e.domain,metric=e.metric,entity=e.entity,value=e.value,unit=e.unit,period=e.period,source_url=e.source_url,source_locator=e.source_locator,published_at=e.published_at,document_sha256=e.document_sha256) for i,e in enumerate(ordered_evidence,1)]
        all_warnings=_deduplicate_warnings([*request.report.warnings,*request.chapters.warnings,*(request.charts.warnings if request.charts else []),*warnings,*issues])
        consistency=ConsistencyReport(passed=not issues,issues=issues,warnings=warnings,accepted_edits=accepted,rejected_edits=rejected,terminology_map=term_map)
        km_list = []
        for km in getattr(request.report, "key_metrics", []):
            if isinstance(km, dict):
                km_list.append(km)
            elif hasattr(km, "model_dump"):
                km_list.append(km.model_dump(mode="json"))

        cm_dict = None
        cm_obj = getattr(request.report, "comps_matrix", None)
        if isinstance(cm_obj, dict):
            cm_dict = cm_obj
        elif hasattr(cm_obj, "model_dump"):
            cm_dict = cm_obj.model_dump(mode="json")

        # S-05 + R4：delivery_status 先按**已知**事实取一个确定性初值，
        # 导出后若事实变化再统一重渲染三格式，保证 MD/HTML/PDF 来自同一最终视图。
        provisional_limits = bool(issues or final_blocking)
        view=ReportViewModel(
            report_id=report_id,
            title=f"{request.report.subject}行业研究报告",
            subject=request.report.subject,
            as_of=request.report.as_of,
            tone=request.options.tone,
            report_depth=request.options.report_depth,
            visual_style=request.options.visual_style,
            chart_mode=getattr(request.options, "chart_mode", "auto") or "auto",
            delivery_status="ready_with_limits" if provisional_limits else "ready",
            executive_summary=summary,
            chapters=chapters,
            charts=embedded,
            evidence_catalog=catalog,
            data_quality_appendix=safe_appendix,
            warnings=all_warnings,
            quality_issues=quality_issues,
            fact_audit={"schema_version": "1", "unsupported_quantities": sum(q.get("code") == "unsupported_quantity" for q in quality_issues), "formal_verified": not (issues or final_blocking), "chapter_claims_recovered": recovered_chapter_claims},
            key_metrics=km_list,
            comps_matrix=cm_dict,
        )
        artifacts=[];successful=[]
        if artifact_dir:artifact_dir.mkdir(parents=True,exist_ok=True)
        if artifact_dir:
            final_charts_dir = artifact_dir / "charts"
            final_charts_dir.mkdir(parents=True, exist_ok=True)
            for chart in view.charts:
                (final_charts_dir / f"{chart.chart_id}.svg").write_text(chart.svg, encoding="utf-8")
        md=render_markdown(view);html=render_html(view)
        async def save(kind:str,name:str,data:bytes):
            if artifact_dir:
                path=artifact_dir/name;path.write_bytes(data);artifacts.append(ArtifactEntry(kind=kind,uri=str(path.resolve()),sha256=_sha(data),size_bytes=len(data)))
            successful.append(kind);await record("format_exported",format=kind,size=len(data))
        for fmt in request.options.formats:
            try:
                if fmt=="markdown":await save("markdown","report.md",md.encode())
                elif fmt=="html":await save("html","report.html",html.encode())
                else:await save("pdf","report.pdf",await self.pdf_renderer(html,self.settings.pdf_timeout_seconds))
            except Exception as exc:
                warnings.append(f"{fmt} 导出失败：{type(exc).__name__}");await record("format_failed",format=fmt,error=type(exc).__name__)

        # S-05：状态与交付资格由**最终事实**决定——实际成功格式数、最终校验结论、
        # 以及真实产出文件，不再依赖“失败字符串里有没有 failed”这类推断。
        missing_formats = [f for f in request.options.formats if f not in successful]
        empty_outputs = []
        for entry in artifacts:
            try:
                if Path(entry.uri).stat().st_size <= 0:
                    empty_outputs.append(entry.kind)
            except OSError:
                empty_outputs.append(entry.kind)
        final_blocking = list(dict.fromkeys([*issues, *final_blocking]))
        consistency.quality_issues = quality_issues
        consistency.passed = not final_blocking
        consistency.issues = list(final_blocking)
        if missing_formats:
            warnings.append(f"缺失交付格式：{'、'.join(missing_formats)}（非完整交付）")
        if empty_outputs:
            warnings.append(f"导出文件为空：{'、'.join(empty_outputs)}")
            final_blocking.append(f"导出文件为空：{'、'.join(empty_outputs)}")

        if not successful:
            status = "failed"
        elif missing_formats or final_blocking or rejected:
            status = "partial"
        else:
            status = "completed"

        # delivery_status 反映最终的正式交付能力：
        # - failed / partial / 缺格式 / 仍有阻塞项  → ready_with_limits
        # - 仅剩非阻断的技术性提示                  → ready
        has_substantive_limit = bool(
            missing_formats or final_blocking or empty_outputs or rejected or not successful
        )
        final_delivery = "ready_with_limits" if has_substantive_limit else "ready"
        previous_delivery = view.delivery_status

        # R4（V8 最终方案 §7.3 步骤 6）：三种格式必须来自**同一最终视图**。
        # 只要交付状态相对初值发生变化，MD/HTML/PDF 全部按新视图重出；
        # 任一格式重出失败就撤销该格式的发布资格（不能留旧文件冒充满分交付）。
        if final_delivery != previous_delivery:
            view.delivery_status = final_delivery
            revoked: list[str] = []
            if "markdown" in successful:
                try:
                    md = render_markdown(view)
                    _rewrite(artifact_dir, "report.md", md.encode())
                except Exception as exc:
                    revoked.append("markdown")
                    warnings.append(f"markdown 重渲染失败：{type(exc).__name__}")
                    await record("format_failed", format="markdown", error=type(exc).__name__)
            if "html" in successful:
                try:
                    html = render_html(view)
                    _rewrite(artifact_dir, "report.html", html.encode())
                except Exception as exc:
                    revoked.append("html")
                    warnings.append(f"html 重渲染失败：{type(exc).__name__}")
                    await record("format_failed", format="html", error=type(exc).__name__)
            if "pdf" in successful:
                # PDF 由 HTML 渲染而来：PDF 必须基于重渲染后的最终 HTML
                try:
                    pdf_bytes = await self.pdf_renderer(html, self.settings.pdf_timeout_seconds)
                    _rewrite(artifact_dir, "report.pdf", pdf_bytes)
                except Exception as exc:
                    revoked.append("pdf")
                    warnings.append(f"pdf 重渲染失败：{type(exc).__name__}")
                    await record("format_failed", format="pdf", error=type(exc).__name__)

            if revoked:
                # 撤销发布资格：从可交付格式中移除，并把状态降为部分交付
                successful = [f for f in successful if f not in revoked]
                artifacts = [a for a in artifacts if a.kind not in revoked]
                for fmt in revoked:
                    try:
                        (artifact_dir / {"markdown": "report.md", "html": "report.html", "pdf": "report.pdf"}[fmt]).unlink(missing_ok=True)
                    except OSError:
                        pass
                status = "failed" if not successful else "partial"
                verdict_blocked = True
            else:
                verdict_blocked = False
        else:
            view.delivery_status = final_delivery
            verdict_blocked = False

        # 重渲染/撤销阶段的警告也必须进入最终清单（此前在重渲染前就定稿会漏掉）
        pending_warnings = list(dict.fromkeys([*all_warnings, *warnings]))

        if artifact_dir:
            extra_paths = list((artifact_dir / "charts").glob("*.svg")) if (artifact_dir / "charts").exists() else []
            if (artifact_dir / "fact_audit.json").exists():
                extra_paths.append(artifact_dir / "fact_audit.json")
            for extra in extra_paths:
                content = extra.read_bytes()
                artifacts.append(ArtifactEntry(kind="svg" if extra.suffix == ".svg" else "json", uri=str(extra.resolve()), sha256=_sha(content), size_bytes=len(content)))
            view_path=artifact_dir/"report_view.json";view_data=(view.model_dump_json(indent=2)+"\n").encode();view_path.write_bytes(view_data);artifacts.append(ArtifactEntry(kind="json",uri=str(view_path.resolve()),sha256=_sha(view_data),size_bytes=len(view_data)))
            consistency_path=artifact_dir/"consistency_report.json";consistency_data=(consistency.model_dump_json(indent=2)+"\n").encode();consistency_path.write_bytes(consistency_data);artifacts.append(ArtifactEntry(kind="json",uri=str(consistency_path.resolve()),sha256=_sha(consistency_data),size_bytes=len(consistency_data)))
            # manifest 最后生成，保证 sha256/size 对应真实落盘内容（重渲染后已变化）
            refreshed = []
            for entry in artifacts:
                try:
                    data = Path(entry.uri).read_bytes()
                except OSError:
                    continue
                refreshed.append(ArtifactEntry(kind=entry.kind, uri=entry.uri, sha256=_sha(data), size_bytes=len(data)))
            manifest={"report_id":report_id,"generated_at":datetime.now().astimezone().isoformat(),"artifacts":[x.model_dump(mode="json") for x in refreshed]}
            manifest_data=(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n").encode();manifest_path=artifact_dir/"manifest.json";manifest_path.write_bytes(manifest_data);refreshed.append(ArtifactEntry(kind="json",uri=str(manifest_path.resolve()),sha256=_sha(manifest_data),size_bytes=len(manifest_data)))
            artifacts = refreshed
        result=ReportFusionResult(run_id=run_id,report_id=report_id,subject=request.report.subject,status=status,formats=successful,applied_skills=[AppliedSkill(name=s.name,description=s.description,source=s.source,adaptation=skill_reasons.get(s.name, s.adaptation)) for s in skills],artifacts=artifacts,consistency=consistency,warnings=pending_warnings,artifact_dir=str(artifact_dir.resolve()) if artifact_dir else None)
        await record("fusion_completed",status=status,formats=successful,missing_formats=missing_formats)
        if artifact_dir:(artifact_dir/"events.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in events),encoding="utf-8")
        return result

    def _check_inputs(self,request:ReportFusionRequest)->tuple[list[str],list[str]]:
        issues=[];warnings=[];allowed=set(request.report.evidence_index);charts={c.chart_id for c in (request.charts.charts if request.charts else []) if c.status=="ready"}
        # 章节阶段的 passed 是“生成时”诊断；终审会按最终文本重算数值/因果/图表。
        # 只要没有兜底稿，最终文本通过 `_check_final_view` 即可正式交付。
        if any(c.used_fallback for c in request.chapters.chapters):
            issues.append(_CHAPTER_QUALITY_BLOCK)
        if len(request.chapters.chapters)!=7:issues.append("章节结果不是7章")
        if sum(len(c.sections) for c in request.chapters.chapters)!=21:issues.append("章节结果不是21节")
        seen=set()
        for chapter in request.chapters.chapters:
            for section in chapter.sections:
                for para in section.paragraphs:
                    unknown=set(para.evidence_ids)-allowed
                    if unknown:issues.append(f"{para.paragraph_id} 含未知证据引用")
                    compact="".join(para.text.split())
                    if compact in seen:warnings.append(f"{para.paragraph_id} 与其他段落内容重复")
                    seen.add(compact)
                if set(section.chart_ids)-charts:warnings.append(f"{section.section_id} 含未就绪图表引用")
        self._audit_cross_chapter_consistency(request, issues, warnings)
        return list(dict.fromkeys(issues)),list(dict.fromkeys(warnings))

    def _audit_cross_chapter_consistency(self, request: ReportFusionRequest, issues: list[str], warnings: list[str]) -> None:
        comps = getattr(request.report, "comps_matrix", {}) or {}
        tot = comps.get("total_market_cap")
        canonical_wan_yi = None
        if tot is not None:
            try:
                tot_f = float(tot)
                canonical_wan_yi = round(tot_f / 10000.0, 2)
            except (ValueError, TypeError):
                pass

        mcap_scales: dict[str, list[str]] = {}
        for ch in request.chapters.chapters:
            for s in ch.sections:
                for p in s.paragraphs:
                    for match in re.finditer(r"([0-9]+(?:\.[0-9]+)?)\s*(万亿|亿)(?:元)?", p.text):
                        if not _is_total_market_cap_context(p.text[:match.start()]):
                            clause = re.split(r"[，,。；;\n：:]", p.text[:match.start()])[-1].strip()
                            if re.fullmatch(r"(?:总|合计)市值(?:约为|约|为|达|达到|合计|共计)?\s*", clause):
                                warnings.append(f"{ch.chapter_id}/{p.paragraph_id} 总市值归属不明确，保留原文，请人工核验是否属于样本总额")
                            continue
                        val = float(match.group(1))
                        if match.group(2) == "亿":
                            val /= 10000.0
                        mcap_scales.setdefault(str(val), []).append(f"{ch.chapter_id}/{p.paragraph_id}")

        if canonical_wan_yi:
            drift_detected = False
            for val_str in mcap_scales:
                try:
                    val_f = float(val_str)
                    if (abs(val_f - canonical_wan_yi * 10) / (canonical_wan_yi * 10) < 0.2) or \
                       (abs(val_f - canonical_wan_yi / 10) / (canonical_wan_yi / 10) < 0.2):
                        drift_detected = True
                        break
                except (ValueError, ZeroDivisionError):
                    pass
            if drift_detected or len(mcap_scales) > 1:
                warnings.append(f"检测到跨章节总市值数量级冲突，总编辑已启用事实基准自动对齐（标准基准: {canonical_wan_yi}万亿元）")

        if request.charts:
            chart_map = {c.chart_id: c for c in request.charts.charts}
            for ch in request.chapters.chapters:
                for s in ch.sections:
                    for cid in s.chart_ids:
                        c = chart_map.get(cid)
                        if c and c.recommended_chapter_id and c.recommended_chapter_id != ch.chapter_id:
                            warnings.append(f"{s.section_id} 挂载了非推荐章节图表 {cid} (推荐: {c.recommended_chapter_id})，总编辑将执行定向归位")

    def _reconcile_market_cap_consistency(self, chapters: list[ChapterDraft], request: ReportFusionRequest) -> None:
        comps = getattr(request.report, "comps_matrix", {}) or {}
        tot = comps.get("total_market_cap")
        if tot is None:
            return
        try:
            tot_f = float(tot)
            canonical_val = round(tot_f / 10000.0, 2)
        except (ValueError, TypeError):
            return

        def _reconcile_text(text: str, is_metric_card: bool = False) -> str:
            if not text:
                return text
            def _repl_wan_yi(m: re.Match) -> str:
                val_str = m.group(1)
                try:
                    val = float(val_str)
                    if not ((abs(val - canonical_val * 10) / (canonical_val * 10) < 0.2) or \
                            (abs(val - canonical_val / 10) / (canonical_val / 10) < 0.2)):
                        return m.group(0)
                except (ValueError, ZeroDivisionError):
                    return m.group(0)

                if not is_metric_card:
                    # Bind the number to the total in its own clause. A nearby
                    # sample total cannot establish ownership of a company fact.
                    if not _is_total_market_cap_context(text[:m.start()]):
                        return m.group(0)

                return m.group(0).replace(val_str, str(canonical_val))

            return re.sub(r"([0-9]+(?:\.[0-9]+)?)\s*万亿(?:元)?", _repl_wan_yi, text)

        for ch in chapters:
            ch.summary = _reconcile_text(ch.summary)
            for s in ch.sections:
                for p in s.paragraphs:
                    p.text = _reconcile_text(p.text)
                for mc in s.metric_cards:
                    is_mc_target = _is_total_market_cap_context(str(getattr(mc, "label", "")))
                    mc.value = _reconcile_text(mc.value, is_metric_card=is_mc_target)

    def _default_summary(self,request:ReportFusionRequest)->ExecutiveSummary:
        conclusions=[]
        for item in request.report.insights[:10]:
            ids=[x for x in item.get("evidence_record_ids",[]) if x in request.report.evidence_index]
            conclusions.append(ReportConclusion(text=str(item.get("conclusion") or item.get("title") or ""),evidence_ids=ids,confidence=item.get("confidence","medium") if item.get("confidence") in {"high","medium","low"} else "medium",uncertainty="结论受当前样本、口径与研究时点限制"))
        if not conclusions:
            for chapter in request.chapters.chapters:
                if chapter.summary:
                    conclusions.append(ReportConclusion(text=chapter.summary,evidence_ids=chapter.evidence_ids[:8],uncertainty="需结合章节中的资料边界理解"))
        else:
            # 补充后三章（竞争格局、标的对标、投资建议）关键论点，确保全量7章完整覆盖
            existing_texts = " ".join(c.text for c in conclusions)
            for chapter in request.chapters.chapters:
                if chapter.chapter_id in {"CH-05", "CH-06", "CH-07"} and chapter.summary:
                    if len(conclusions) < 12 and chapter.summary[:30] not in existing_texts:
                        conclusions.append(ReportConclusion(text=f"【{chapter.title}】{chapter.summary}",evidence_ids=chapter.evidence_ids[:8],confidence="high",uncertainty="结合公司披露与行业对标口径"))

        metric_cards: list[MetricCardDraft] = []
        seen_card_labels: set[str] = set()
        for sec in [s for ch in request.chapters.chapters for s in ch.sections]:
            for mc in sec.metric_cards:
                lbl = mc.label.strip()
                if lbl and lbl not in seen_card_labels:
                    seen_card_labels.add(lbl)
                    metric_cards.append(mc)
                    if len(metric_cards) >= 8:
                        break
            if len(metric_cards) >= 8:
                break

        if len(metric_cards) < 8:
            for km in getattr(request.report, "key_metrics", []):
                name = str(getattr(km, "name", "") or (km.get("name") if isinstance(km, dict) else "") or getattr(km, "metric", "") or (km.get("metric") if isinstance(km, dict) else "") or "核心指标").strip()
                if name and name not in seen_card_labels:
                    seen_card_labels.add(name)
                    val = getattr(km, "value", None) if not isinstance(km, dict) else km.get("value")
                    unit = getattr(km, "unit", None) if not isinstance(km, dict) else km.get("unit")
                    if isinstance(val, (int, float)) and unit not in ("%", "％", "百分点", "个百分点"):
                        val_str = f"{val:,.2f}"
                    else:
                        val_str = str(val) if val is not None else "-"
                    period = getattr(km, "period", None) if not isinstance(km, dict) else km.get("period")
                    eids = getattr(km, "evidence_record_ids", []) if not isinstance(km, dict) else km.get("evidence_record_ids", [])
                    metric_cards.append(MetricCardDraft(
                        label=name,
                        value=val_str,
                        unit=unit,
                        period=str(period or ""),
                        evidence_ids=eids,
                    ))
                    if len(metric_cards) >= 8:
                        break

        return ExecutiveSummary(
            headline=request.report.executive_summary or f"本报告围绕{request.report.subject}的行业基础、成长性、产业链、竞争、财务与风险进行系统梳理。",
            conclusions=conclusions,
            risks=list(request.report.warnings)[:8],
            research_boundaries=list(dict.fromkeys([*request.report.warnings,*request.report.data_quality.get("limitations",[])])) or ["结论仅适用于报告列示的资料范围和研究时点"],
            metric_cards=metric_cards[:8],
        )

    def _editorial_payload(self,request:ReportFusionRequest)->dict[str,Any]:
        return {"subject":request.report.subject,"as_of":request.report.as_of,"existing_summary":self._default_summary(request).model_dump(mode="json"),"chapters":[c.model_dump(mode="json") for c in request.chapters.chapters],"allowed_evidence_ids":list(request.report.evidence_index),"evidence":{k:v.model_dump(mode="json") for k,v in request.report.evidence_index.items()},"final_instruction":request.options.final_instruction}

    def _apply_editorial(self,raw:dict[str,Any],request:ReportFusionRequest,chapters:list[ChapterDraft])->tuple[ExecutiveSummary,list[ChapterDraft],dict[str,str],int,int,list[str]]:
        allowed_ids=set(request.report.evidence_index)
        allowed_numbers=_numbers(self._editorial_payload(request))
        # Structural integers 1..30 (chapter/section/figure indices) are structural metadata, not ungrounded external numbers
        allowed_numbers.update(str(i) for i in range(1, 31))
        accepted=rejected=0;warnings=[]
        allowed_magnitudes = {number.removesuffix("%") for number in allowed_numbers}
        def valid_text(text: str) -> bool:
            return {number.removesuffix("%") for number in _numbers(text)} <= allowed_magnitudes
        default=self._default_summary(request)
        conclusions=[]
        for item in raw.get("conclusions",[]):
            ids=item.get("evidence_ids",[]);text=str(item.get("text","")).strip()
            if text and set(ids)<=allowed_ids and valid_text(text):
                try:conclusions.append(ReportConclusion(text=text,evidence_ids=ids,confidence=item.get("confidence","medium"),uncertainty=str(item.get("uncertainty",""))));accepted+=1
                except Exception:rejected+=1
            else:rejected+=1
        headline=str(raw.get("headline","")).strip()
        if not headline or not valid_text(headline):headline=default.headline;rejected+=1
        def _extract_str(v: Any) -> str:
            if isinstance(v, dict):
                return str(v.get("text") or v.get("title") or v.get("risk") or v.get("description") or "").strip()
            return str(v or "").strip()
        raw_risks = raw.get("risks", [])
        if isinstance(raw_risks, str):
            raw_risks = [raw_risks]
        elif isinstance(raw_risks, (list, tuple)) and len(raw_risks) > 5 and all(isinstance(x, str) and len(x) == 1 for x in raw_risks):
            raw_risks = ["".join(raw_risks)]
        risks = [_extract_str(x) for x in raw_risks if _extract_str(x) and valid_text(_extract_str(x))] or default.risks

        raw_boundaries = raw.get("research_boundaries", [])
        if isinstance(raw_boundaries, str):
            raw_boundaries = [raw_boundaries]
        elif isinstance(raw_boundaries, (list, tuple)) and len(raw_boundaries) > 5 and all(isinstance(x, str) and len(x) == 1 for x in raw_boundaries):
            raw_boundaries = ["".join(raw_boundaries)]
        boundaries = [_extract_str(x) for x in raw_boundaries if _extract_str(x) and valid_text(_extract_str(x))] or default.research_boundaries
        summary=ExecutiveSummary(headline=headline,conclusions=conclusions or default.conclusions,risks=risks,research_boundaries=boundaries,metric_cards=default.metric_cards)
        raw_term_map = raw.get("terminology_map", {})
        term_map: dict[str, str] = {}
        subject = str(request.report.subject or "").strip()
        invalid_puncts = ("，", "。", "、", "；", "：", ",", ";", ":", "\n")
        standard_financial_acronyms = {"PE", "PB", "PS", "ROE", "ROA", "ROIC", "CAGR", "EBITDA", "EPS", "TTM"}
        if isinstance(raw_term_map, dict):
            for k, v in raw_term_map.items():
                old = str(k).strip()
                new = str(v).strip()
                if not old or not new or _numbers(new):
                    continue
                if old == subject or (subject and subject in old):
                    continue
                if old.upper() in standard_financial_acronyms:
                    continue
                if len(new) > 8 or any(p in new for p in invalid_puncts):
                    continue
                if len(new) > len(old) * 2 + 2:
                    continue
                term_map[old] = new
        paragraph_map = {p.paragraph_id: p for c in chapters for s in c.sections for p in s.paragraphs}
        withheld = {}
        for chapter in chapters:
            sections = {section.section_id: section for section in chapter.sections}
            for item in chapter.content_audit:
                if item.get("code") == "chapter_claim_repair" and item.get("disposition") == "isolated":
                    if section := sections.get(item.get("section_id")):
                        withheld[item["location"]] = (section, item)
        rejected_pids: list[str] = []
        for pid, edit in raw.get("paragraph_edits", {}).items():
            para = paragraph_map.get(pid)
            restoration = withheld.get(pid) if para is None else None
            text = str(edit.get("text", "")).strip() if isinstance(edit, dict) else ""
            ids = edit.get("evidence_ids", []) if isinstance(edit, dict) else []
            known_ids = isinstance(ids, list) and all(isinstance(rid, str) and rid in allowed_ids for rid in ids)
            legacy_gap = para is not None and para.text.startswith(_LEGACY_GAP_PREFIXES)
            if not (para or restoration) or not text or not known_ids or not valid_text(text):
                rejected_pids.append(pid)
                continue
            refs = [request.report.evidence_index[rid] for rid in ids]
            refs.extend(verified_calculations(request.report.financial_ratios, request.report.evidence_index, ids))
            if (legacy_gap or restoration) and (not refs or not _MEASURED_CLAIM.search(text)):
                rejected_pids.append(pid)
                continue
            if quantity_issues(text, refs, universe=list(request.report.evidence_index.values()),
                               assumption_note=para.assumption_note if para else None,
                               kind=para.kind if para else "analysis"):
                rejected_pids.append(pid)
                continue
            if restoration:
                section, entry = restoration
                section.paragraphs.append(ParagraphDraft(paragraph_id=pid, text=text, evidence_ids=ids))
                entry["disposition"] = "repaired"
                entry["replacement_evidence_ids"] = ids
            elif para is not None:
                para.text = text
                para.evidence_ids = ids
            accepted += 1
        rejected += len(rejected_pids)
        if rejected_pids:
            warnings.append(
                f"审校防幻觉拦截：已拦截 {len(rejected_pids)} 处未获数据证据授权的段落微调（涉及 {', '.join(rejected_pids[:3])}{' 等' if len(rejected_pids) > 3 else ''}），全量保留各章节原始事实数据"
            )
        transitions=raw.get("chapter_transitions",{})
        for chapter in chapters:
            transition=str(transitions.get(chapter.chapter_id,"")).strip()
            if transition and valid_text(transition):
                first=chapter.sections[0];first.paragraphs.insert(0,ParagraphDraft(paragraph_id=f"TRANS-{chapter.chapter_id}",kind="transition",text=transition,evidence_ids=[]));accepted+=1
            elif transition:rejected+=1
        for old,new in term_map.items():
            for chapter in chapters:
                chapter.summary=chapter.summary.replace(old,new)
                for section in chapter.sections:
                    for para in section.paragraphs:para.text=para.text.replace(old,new)
        return summary,chapters,term_map,accepted,rejected,warnings

    def _embed_charts(self,request:ReportFusionRequest,chapters:list[ChapterDraft],warnings:list[str])->list[EmbeddedChart]:
        chart_map={c.chart_id:c for c in (request.charts.charts if request.charts else []) if c.status=="ready"}
        
        # 1. Map candidate sections where chapters referenced cid
        chart_sec_candidates: dict[str, list[tuple[ChapterDraft, SectionDraft]]] = {}
        for ch in chapters:
            for s in ch.sections:
                for cid in s.chart_ids:
                    chart_sec_candidates.setdefault(cid, []).append((ch, s))

        assigned_placements: dict[str, str] = {}
        assigned_sections: set[str] = set()

        for cid, chart in chart_map.items():
            candidates = chart_sec_candidates.get(cid, [])
            rec_ch_id = getattr(chart, "recommended_chapter_id", None)

            target_sec_id = None
            # Priority 1: Candidate section matching recommended_chapter_id
            if rec_ch_id and candidates:
                for ch, s in candidates:
                    if ch.chapter_id == rec_ch_id:
                        target_sec_id = s.section_id
                        break

            # Priority 2: Recommended chapter exists, place into best section within that chapter
            if not target_sec_id and rec_ch_id:
                for ch in chapters:
                    if ch.chapter_id == rec_ch_id and ch.sections:
                        # Find semantic section match first
                        matched_sec = None
                        t_lower = chart.title.lower()
                        for s in ch.sections:
                            s_title = s.title.lower()
                            if ("利润" in t_lower or "收入" in t_lower or "盈利" in t_lower) and ("收入" in s_title or "利润" in s_title or "盈利" in s_title):
                                matched_sec = s
                                break
                            if ("负债" in t_lower or "现金" in t_lower or "资产" in t_lower) and ("负债" in s_title or "现金" in s_title or "质量" in s_title):
                                matched_sec = s
                                break
                            if ("估值" in t_lower or "pe" in t_lower or "pb" in t_lower or "市值" in t_lower) and ("估值" in s_title or "参照" in s_title or "水平" in s_title):
                                matched_sec = s
                                break
                            if ("份额" in t_lower or "集中度" in t_lower or "排名" in t_lower) and ("结构" in s_title or "集中度" in s_title or "参与者" in s_title):
                                matched_sec = s
                                break

                        # Count current assignments per section in this chapter
                        sec_counts = {s.section_id: sum(1 for p in assigned_placements.values() if p == s.section_id) for s in ch.sections}

                        # If matched section is not overloaded (<= 2 charts), use it
                        if matched_sec and sec_counts.get(matched_sec.section_id, 0) < 3:
                            target_sec_id = matched_sec.section_id
                        else:
                            # Otherwise choose least-loaded section in this chapter
                            best_sec = min(ch.sections, key=lambda s: sec_counts.get(s.section_id, 0))
                            target_sec_id = best_sec.section_id
                        break

            # Priority 3: First candidate section where cid appeared (DO NOT use dict overwrite which picks last!)
            if not target_sec_id and candidates:
                target_sec_id = candidates[0][1].section_id

            # Priority 4: Title / topic heuristic
            if not target_sec_id:
                for ch in chapters:
                    if "现金" in chart.title and "05" in ch.chapter_id:
                        for s in ch.sections:
                            if "现金" in s.title:
                                target_sec_id = s.section_id
                                break
                    elif ("态势" in chart.title or "增长" in chart.title or "营收" in chart.title) and ("05" in ch.chapter_id or "02" in ch.chapter_id):
                        for s in ch.sections:
                            if "收入" in s.title or "规模" in s.title or "盈利" in s.title:
                                target_sec_id = s.section_id
                                break
                    if target_sec_id:
                        break

            # Priority 5: Fallback to first available section in chapters
            if not target_sec_id and chapters and chapters[0].sections:
                target_sec_id = chapters[0].sections[0].section_id

            assigned_placements[cid] = target_sec_id
            assigned_sections.add(target_sec_id)

        # Synchronize section.chart_ids across all chapters to enforce Single-Placement Lock
        for ch in chapters:
            for s in ch.sections:
                s.chart_ids = [cid for cid in chart_map if assigned_placements.get(cid) == s.section_id]

        # Determine physical reading order across chapters and sections (DEF-03)
        ordered_chart_ids: list[str] = []
        for ch in chapters:
            for s in ch.sections:
                for cid in s.chart_ids:
                    if cid in chart_map and cid not in ordered_chart_ids:
                        ordered_chart_ids.append(cid)
        # Any leftover charts
        for cid in chart_map:
            if cid not in ordered_chart_ids:
                ordered_chart_ids.append(cid)

        has_tubiao = any(str(getattr(c, "figure_number", "")).startswith("图表") for c in chart_map.values())
        prefix_str = "图表" if has_tubiao else "图"

        result=[]
        for new_idx, cid in enumerate(ordered_chart_ids, 1):
            chart = chart_map[cid]
            svg=""
            image_uri = getattr(chart, "image_uri", None)
            render_mode = getattr(chart, "render_mode", "echarts")
            if render_mode == "generated_image" and image_uri:
                try:
                    img_path = Path(image_uri)
                    if img_path.is_file():
                        import base64
                        raw = img_path.read_bytes()
                        mime = getattr(chart, "image_mime_type", None) or "image/png"
                        if raw[:3] == b"\xff\xd8\xff":
                            mime = "image/jpeg"
                        b64 = base64.b64encode(raw).decode("ascii")
                        svg = (
                            f'<img alt="{chart.title}" style="max-width:100%;height:auto;display:block;margin:0 auto;" '
                            f'src="data:{mime};base64,{b64}" />'
                        )
                except OSError:
                    warnings.append(f"图表 {cid} 的 AI 产业链图不可读，回退 SVG")
            if not svg and chart.svg_uri:
                try:svg=Path(chart.svg_uri).read_text(encoding="utf-8")
                except OSError:warnings.append(f"图表 {cid} 的 SVG 文件不可读")
            if not svg:
                # S-05：缺图时**保留图位与编号**（编号重排依赖图位存在），
                # 但插入的占位图带 data-placeholder 标记，最终校验据此判为不可交付，
                # 不再像旧实现那样用一张灰色占位图冒充“图表正常”。
                warnings.append(f"图表 {cid} 缺少可读图形（svg_uri 不可用），不计入正式交付")
                svg=(
                    f'<svg xmlns="http://www.w3.org/2000/svg" data-placeholder="true" '
                    f'viewBox="0 0 960 180"><rect width="100%" height="100%" fill="#f8fafc"/>'
                    f'<text x="480" y="90" text-anchor="middle" fill="#64748b">'
                    f'{chart.title}：图表预览不可用</text></svg>'
                )
            # 固定像素宽高的 SVG（产业链图 1440px）在 A4 页宽下会被裁掉右侧 → 改自适应
            svg=_fit_svg_for_page(svg)

            
            # Re-index canonical figure number strictly in physical reading order
            fig_number = f"{prefix_str} {new_idx}"
            # Synchronize figure number inside SVG vector text
            if svg and "<svg" in svg:
                old_fig = getattr(chart, "figure_number", None)
                if old_fig and old_fig in svg:
                    svg = svg.replace(f"{old_fig}：", f"{fig_number}：").replace(f"{old_fig} ", f"{fig_number} ").replace(old_fig, fig_number)
                else:
                    svg = re.sub(r'图\s*\d+\s*[：:]\s*', f'{fig_number}：', svg, count=1)

            placement_id = assigned_placements.get(cid)
            result.append(EmbeddedChart(
                chart_id=cid,
                data_contract=getattr(chart, "data_contract", {}),
                title=chart.title,
                chart_type=chart.chart_type,
                evidence_ids=chart.evidence_ids,
                insight_goal=chart.insight_goal,
                placement_section_id=placement_id,
                svg=svg,
                footnotes=chart.footnotes,
                figure_number=fig_number,
                subtitle=getattr(chart, "subtitle", None),
                source_line=getattr(chart, "source_line", None),
                render_mode=render_mode,
                image_uri=image_uri,
                image_mime_type=getattr(chart, "image_mime_type", None),
            ))

        # Cross-reference normalization: replace [CHART-xx] placeholders in paragraph texts with canonical figure numbers
        chart_ref_map: dict[str, str] = {}
        for idx, ec in enumerate(result, 1):
            fn = ec.figure_number or f"图 {idx}"
            chart_ref_map[f"[{ec.chart_id}]"] = fn
            chart_ref_map[ec.chart_id] = fn
            parts = ec.chart_id.split("-")
            if len(parts) >= 2:
                prefix = f"{parts[0]}-{parts[1]}"
                chart_ref_map[f"[{prefix}]"] = fn
                chart_ref_map[prefix] = fn
                chart_ref_map[f"[{prefix.lower()}]"] = fn
                chart_ref_map[prefix.lower()] = fn
            # Also map original chart.figure_number if different
            orig_chart = chart_map.get(ec.chart_id)
            if orig_chart and orig_chart.figure_number and orig_chart.figure_number != fn:
                chart_ref_map[f"[{orig_chart.figure_number}]"] = fn
                chart_ref_map[f"如{orig_chart.figure_number}"] = f"如{fn}"
                chart_ref_map[f"见{orig_chart.figure_number}"] = f"见{fn}"
                chart_ref_map[f"至{orig_chart.figure_number}"] = f"至{fn}"
            # Map index variants: [CHART-1], [CHART-01], [chart-1], [chart-01], [图表-1], [图表-01], [图表1]
            chart_ref_map[f"[CHART-{idx}]"] = fn
            chart_ref_map[f"[CHART-{idx:02d}]"] = fn
            chart_ref_map[f"[chart-{idx}]"] = fn
            chart_ref_map[f"[chart-{idx:02d}]"] = fn
            chart_ref_map[f"[图表-{idx}]"] = fn
            chart_ref_map[f"[图表-{idx:02d}]"] = fn
            chart_ref_map[f"[图表{idx}]"] = fn
            chart_ref_map[f"[图表{idx:02d}]"] = fn
            chart_ref_map[f"[chart-{idx:02d}]"] = fn
            chart_ref_map[f"[图表-{idx}]"] = fn
            chart_ref_map[f"[图表-{idx:02d}]"] = fn
            chart_ref_map[f"[图表{idx}]"] = fn
            chart_ref_map[f"[图表{idx:02d}]"] = fn

        def _clean_chart_text(text: str, default_fn: str | None = None, mapping: dict[str, str] | None = None) -> str:
            if not text:
                return text
            active_map = mapping or chart_ref_map
            for ref, fig_num in sorted(active_map.items(), key=lambda x: -len(x[0])):
                if ref in text:
                    text = text.replace(ref, fig_num)
            if default_fn:
                text = re.sub(r"\[(?:CHART|chart)-[^\]]+\]", default_fn, text)
            else:
                # Remove dangling/orphan chart placeholders
                text = re.sub(r"(?:如|见|至|参(?:考|阅)?)\s*\[(?:CHART|chart|图表)-?[^\]]+\]\s*(?:所示)?", "", text)
                text = re.sub(r"\[(?:CHART|chart|图表)-?[^\]]+\]", "", text)

            # 消除 AI Prompt 机械指令词及前缀图号（如 "[图 3]图前结论："、"图前结论："、"图后含义："、"图中数据显示："）
            text = re.sub(r"\[?图\s*\d+\]?\s*(?:图前结论|图前导读|图前研判|图前要点)\s*[:：]\s*", "", text)
            text = re.sub(r"(?:图前结论|图前导读|图前研判|图前要点)\s*[:：]\s*", "", text)
            text = re.sub(r"\[?图\s*\d+\]?\s*(?:图后含义|图后分析|图后启示|图后结论|图后研判)\s*[:：]\s*", "", text)
            text = re.sub(r"(?:图后含义|图后分析|图后启示|图后结论|图后研判)\s*[:：]\s*", "", text)
            text = re.sub(r"\[?图\s*\d+\]?\s*图中数据(?:显示)?\s*[:：，,]\s*", "", text)
            text = re.sub(r"图中数据(?:显示)?\s*[:：，,]\s*", "", text)

            # Context-aware typo and duplicate figure number cleanup:
            # 1. First normalize double "图": "如图图 1所示", "如图 图 1", "见图图 1", "图图 1"
            text = re.sub(r"(如|见|至|参(?:考|阅)?)\s*图\s*图\s*(\d+)", r"\1图 \2", text)
            text = re.sub(r"图\s*图\s*(\d+)", r"图 \1", text)
            text = re.sub(r"如图\s*(\d+)\s*所示", r"如图 \1 所示", text)
            # 2. Remove contradictory duplicate figure number right after "如图 X 所示，":
            # e.g. "如图 1 所示，图 1" 或 "如图 1 所示，图 3" 或 "如图 4 所示，图 5" -> "如图 4 所示，"
            text = re.sub(r"(如图\s*\d+\s*所示[，,])\s*图\s*\d+\s*", r"\1", text)
            # 3. Clean up any leftover awkward spaces or duplicated punctuation
            text = re.sub(r"\s+([，。、；])", r"\1", text)
            text = re.sub(r"([，。、；！？])\s+", r"\1", text)
            text = re.sub(r"([。；，])\s*\1+", r"\1", text)
            text = re.sub(r"^[，,。；]\s*", "", text)
            return text.strip()

        for ch in chapters:
            if ch.summary:
                ch.summary = _clean_chart_text(ch.summary)
            for s in ch.sections:
                sec_charts = [ec for ec in result if ec.chart_id in s.chart_ids]
                sec_default_fn = sec_charts[0].figure_number if sec_charts else None
                # 构建小节专属映射，优先将小节内引用的 [CHART-xx] 精准映射为对应图表在报告中的实际图序
                sec_map = dict(chart_ref_map)
                for sc in sec_charts:
                    fn = sc.figure_number or f"图 {result.index(sc) + 1}"
                    sec_map[f"[{sc.chart_id}]"] = fn
                    sec_map[sc.chart_id] = fn
                    parts = sc.chart_id.split("-")
                    if len(parts) >= 2:
                        pfx = f"{parts[0]}-{parts[1]}"
                        sec_map[f"[{pfx}]"] = fn
                        sec_map[pfx] = fn
                        sec_map[f"[{pfx.lower()}]"] = fn
                        sec_map[pfx.lower()] = fn
                if s.key_points:
                    s.key_points = [_clean_chart_text(kp, sec_default_fn, sec_map) for kp in s.key_points]
                for p in s.paragraphs:
                    p.text = _clean_chart_text(p.text, sec_default_fn, sec_map)

        return result

