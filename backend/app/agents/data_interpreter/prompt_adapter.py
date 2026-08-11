"""Technical runtime envelope applied around the unchanged finance prompt."""

import json

from app.schemas.analysis import AnalysisRequest


def build_runtime_prompt(
    request: AnalysisRequest,
    *,
    audit_feedback: list[str] | None = None,
) -> str:
    payload = {
        "task": "依据全球主要股票市场金融分析框架生成可供后续智能体消费的结构化分析。",
        "analysis_request": request.model_dump(mode="json"),
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
            "requirements": [
                "仅引用analysis_request中存在的evidence_id",
                "claims、scenarios和chart_candidates中的evidence_ids不得为空；没有证据支持的项目不要输出",
                "维度字段只能使用allowed_dimension_names中的英文枚举，不得翻译或创造别名",
                "先核对市场、证券类型、交易所、币种、会计准则和复权口径",
                "跨市场比较必须完成币种换算、财年对齐和多地上市去重",
                "不得输出Markdown代码围栏或内部推理过程",
                "缺失信息写入collaboration_requests",
                "三种情景必须共享同一事实底座",
                "P0图表候选仅优先使用line、bar、pie、radar、industry_chain",
                "line用于时间趋势，bar用于类别对比或排名，pie仅用于单时点且类别不超过5的正值互斥占比",
                "radar仅用于3至8个已标准化且同尺度指标，industry_chain仅用于有来源的上下游节点关系",
                "每个图表候选必须填写analysis_purpose、insight_goal、priority和chapter_hint，避免同一结论重复制图",
                "用data_quality_issues标记missing、stale、conflict、estimated或"
                "not_comparable；不得把数据缺口改写成事实",
                "用financial_consistency_checks记录财务勾稽或盈利质量检查；无法核验时标记unavailable或warning，不得补造数字",
                "用dimension_coverage标记五个研究维度为supported、partial或insufficient，并引用相应evidence_id",
                "research_brief限定本次研究范围；excluded_topics不得进入结论，资料不足时透明说明",
                "不得输出投资建议、收益承诺、个股推荐或择时建议",
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
