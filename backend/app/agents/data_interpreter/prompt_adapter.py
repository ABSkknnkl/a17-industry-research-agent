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
            "requirements": [
                "仅引用analysis_request中存在的evidence_id",
                "先核对市场、证券类型、交易所、币种、会计准则和复权口径",
                "跨市场比较必须完成币种换算、财年对齐和多地上市去重",
                "不得输出Markdown代码围栏或内部推理过程",
                "缺失信息写入collaboration_requests",
                "三种情景必须共享同一事实底座",
                "不得输出投资建议、收益承诺、个股推荐或择时建议",
            ],
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
