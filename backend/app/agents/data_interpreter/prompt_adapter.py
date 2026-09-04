"""Technical runtime envelope applied around the unchanged finance prompt."""

import json

from app.agents.common.content_dedup import rank_by_richness
from app.schemas.analysis import AnalysisRequest
from app.schemas.evidence import EvidenceItem

# evidence_items 是 A2 prompt 中唯一无界的上下文来源（真实链路可达 110+ 条，
# 触发分段生成）。超出上限的低信息量证据降级为 ID 引用而非丢弃，
# 保证 allowed_evidence_ids 全集不变、下游溯源检查不受影响。
DEFAULT_MAX_FULL_EVIDENCE_ITEMS = 60


def _cap_evidence_items(
    items: list[EvidenceItem],
    max_full_items: int,
) -> tuple[list[EvidenceItem], list[str]]:
    """Keep the richest evidence in full form; downgrade the rest to ID references.

    Kept items preserve their original relative order so the prompt stays
    stable across runs. Overflow IDs also follow the original order.
    """
    if max_full_items < 1:
        raise ValueError("max_full_items must be >= 1")
    if len(items) <= max_full_items:
        return list(items), []
    keep_ids = {item.evidence_id for item in rank_by_richness(items)[:max_full_items]}
    full_items = [item for item in items if item.evidence_id in keep_ids]
    overflow_ids = [item.evidence_id for item in items if item.evidence_id not in keep_ids]
    return full_items, overflow_ids


def build_runtime_prompt(
    request: AnalysisRequest,
    *,
    audit_feedback: list[str] | None = None,
    calculated_metrics: list[dict[str, object]] | None = None,
    calculation_issues: list[dict[str, object]] | None = None,
    max_full_evidence_items: int = DEFAULT_MAX_FULL_EVIDENCE_ITEMS,
) -> str:
    full_items, overflow_ids = _cap_evidence_items(request.evidence_items, max_full_evidence_items)
    analysis_request_payload = request.model_dump(mode="json")
    analysis_request_payload["evidence_items"] = [
        item.model_dump(mode="json") for item in full_items
    ]
    requirements = [
        "仅引用analysis_request中存在的evidence_id",
        "claims、scenarios和chart_candidates中的evidence_ids不得为空；没有证据支持的项目不要输出",
        "维度字段只能使用allowed_dimension_names中的英文枚举，不得翻译或创造别名",
        "先核对市场、证券类型、交易所、币种、会计准则和复权口径",
        "跨市场比较必须完成币种换算、财年对齐和多地上市去重",
        "不得输出Markdown代码围栏或内部推理过程",
        "缺失信息写入collaboration_requests",
        "逐项读取requirement_coverage；partial或missing只能形成数据缺口/不确定性说明，不得补造用户要求的指标、政策或机构观点",
        "三种情景必须共享同一事实底座",
        "P0图表候选仅优先使用line、bar、pie、radar、industry_chain",
        "line用于时间趋势，bar用于类别对比或排名，pie仅用于单时点且类别不超过5的正值互斥占比",
        "radar仅用于3至8个已标准化且同尺度指标，industry_chain仅用于有来源的上下游节点关系",
        "每个图表候选必须填写analysis_purpose、insight_goal、priority和chapter_hint，避免同一结论重复制图",
        "用data_quality_issues标记missing、stale、conflict、estimated或"
        "not_comparable；不得把数据缺口改写成事实",
        "用financial_consistency_checks记录财务勾稽或盈利质量检查；无法核验时标记unavailable或warning，不得补造数字",
        "deterministic_calculations由服务端固定公式生成，可解释但不得修改数值、公式、口径或证据引用",
        "calculated_metrics和calculation_issues字段由服务端最终覆盖，模型保持为空",
        "用dimension_coverage标记五个研究维度为supported、partial或insufficient，并引用相应evidence_id",
        "research_brief限定本次研究范围；excluded_topics不得进入结论，资料不足时透明说明",
        "不得输出投资建议、收益承诺、个股推荐或择时建议",
    ]
    if overflow_ids:
        requirements.append(
            "overflow_evidence_ids中的证据超出上下文预算，仅可见ID；"
            "不得描述其数值、单位或来源细节，也不得作为结论依据；"
            "确需其内容时写入collaboration_requests"
        )
    # analysis_notes 透传护栏（2026-09-01 仲裁接线）：仅在存在否决/分析型
    # 碎片时注入；空列表不得污染常规运行的提示词。
    if request.analysis_notes:
        requirements.append(
            "analysis_notes列出的诉求已被判定为分析型/派生诉求（判断题、"
            "影响传导类或语义层显式否决），未单独取数；仅作为分析线索参考，"
            "不得当作已采集数据，不得为其虚构数值或evidence_id"
        )
    payload = {
        "task": "依据全球主要股票市场金融分析框架生成可供后续智能体消费的结构化分析。",
        "analysis_request": analysis_request_payload,
        "overflow_evidence_ids": overflow_ids,
        "deterministic_calculations": calculated_metrics or [],
        "deterministic_calculation_issues": calculation_issues or [],
        "audit_feedback": audit_feedback or [],
        "technical_output_contract": {
            "schema": "AnalysisDraft",
            "allowed_evidence_ids": [item.evidence_id for item in request.evidence_items],
            "allowed_dimension_names": [
                "competition",
                "growth",
                "macro_policy",
                "industry_chain",
                "risk",
            ],
            "requirements": requirements,
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
