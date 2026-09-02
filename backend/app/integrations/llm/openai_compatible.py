"""OpenAI-compatible structured adapters for Qwen/DeepSeek-style APIs."""

import json
import logging
from enum import StrEnum
from typing import Any, Literal, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.schemas.analysis import (
    AnalysisClaim,
    AnalysisDraft,
    ChartCandidate,
    CollaborationRequest,
    DataQualityIssue,
    DimensionAnalysis,
    DimensionCoverage,
    FinancialConsistencyCheck,
    ScenarioAnalysis,
    ValidationCard,
)
from app.schemas.chapter import ChapterDraftLoose
from app.schemas.readability import ReadabilityReport

SchemaT = TypeVar("SchemaT", bound=BaseModel)
logger = logging.getLogger(__name__)
_SAFE_DIAGNOSTIC_KEYS = frozenset(
    {
        "finish_reason",
        "request_id",
        "response_chars",
        "json_error_position",
        "validation_error_count",
        "validation_paths",
        "validation_types",
        "validation_inputs",
        "validation_expected",
        "raw_content_summary",
        "provider_error_type",
        "input_tokens",
        "output_tokens",
        "total_tokens",
    }
)


def _sanitize_diagnostics(diagnostics: dict[str, Any] | None) -> dict[str, Any]:
    if not diagnostics:
        return {}
    return {
        key: value
        for key, value in diagnostics.items()
        if key in _SAFE_DIAGNOSTIC_KEYS and isinstance(value, (str, int, float, bool, list, tuple))
    }


class StructuredOutputFailureCode(StrEnum):
    JSON_CONTAMINATION = "json_contamination"
    JSON_SYNTAX_INVALID = "json_syntax_invalid"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    SEMANTIC_VALIDATION_FAILED = "semantic_validation_failed"
    OUTPUT_TRUNCATED = "output_truncated"
    PROVIDER_ERROR = "provider_error"


class StructuredOutputError(ValueError):
    """Safe, machine-readable failure raised by an LLM structured adapter."""

    def __init__(
        self,
        code: StructuredOutputFailureCode,
        message: str,
        *,
        retryable: bool,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.diagnostics = _sanitize_diagnostics(diagnostics)


class AnalysisCoreDraft(BaseModel):
    """Smaller contract used only for long Agent 2 requests."""

    model_config = ConfigDict(extra="forbid")

    headline: str
    overall_confidence: Literal["high", "medium", "low"]
    financial_quality: Literal[
        "consistent",
        "differences_explained",
        "differences_pending_verification",
    ]
    claims: list[AnalysisClaim] = Field(min_length=1)
    dimensions: list[DimensionAnalysis] = Field(min_length=5, max_length=5)
    validation_cards: list[ValidationCard] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_required_sections(self) -> "AnalysisCoreDraft":
        if {item.name for item in self.dimensions} != {
            "competition",
            "growth",
            "macro_policy",
            "industry_chain",
            "risk",
        }:
            raise ValueError("core dimensions must contain each required dimension once")
        if {item.name for item in self.validation_cards} != {
            "scope_comparability",
            "financial_quality",
            "valuation_expectation",
        }:
            raise ValueError("core validation cards must contain each required card once")
        return self


class AnalysisSupplementDraft(BaseModel):
    """Risk, scenario and downstream-support fields for long Agent 2 requests."""

    model_config = ConfigDict(extra="forbid")

    scenarios: list[ScenarioAnalysis] = Field(min_length=3, max_length=3)
    risks: list[str] = Field(min_length=1)
    collaboration_requests: list[CollaborationRequest] = Field(default_factory=list)
    chart_candidates: list[ChartCandidate] = Field(default_factory=list)
    data_quality_issues: list[DataQualityIssue] = Field(default_factory=list, max_length=100)
    financial_consistency_checks: list[FinancialConsistencyCheck] = Field(
        default_factory=list,
        max_length=20,
    )
    dimension_coverage: list[DimensionCoverage] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_required_sections(self) -> "AnalysisSupplementDraft":
        if {item.name for item in self.scenarios} != {"base", "upside", "downside"}:
            raise ValueError("supplement scenarios must contain each required scenario once")
        coverage_names = [item.dimension for item in self.dimension_coverage]
        if len(coverage_names) != len(set(coverage_names)):
            raise ValueError("supplement dimension coverage cannot contain duplicates")
        return self


def _format_structured_event_message(details: dict[str, Any]) -> str:
    ordered_keys = (
        "event",
        "model_name",
        "schema",
        "error_code",
        "error_type",
        "validation_error_count",
        "validation_paths",
        "validation_types",
        "validation_inputs",
        "validation_expected",
        "finish_reason",
        "response_chars",
        "raw_content_summary",
    )
    parts = [
        f"{key}={details[key]}"
        for key in ordered_keys
        if key in details and details[key] not in (None, "", [], {})
    ]
    return "LLM structured output event | " + " | ".join(parts)


def _log_structured_output_event(
    event: str,
    *,
    model_name: str,
    schema: type[BaseModel],
    error: ValueError | None = None,
) -> None:
    details: dict[str, Any] = {
        "event": event,
        "model_name": model_name,
        "schema": schema.__name__,
    }
    if isinstance(error, StructuredOutputError):
        details["error_code"] = error.code.value
        details.update(error.diagnostics)
    elif error is not None:
        details.update(
            {
                "error_code": StructuredOutputFailureCode.SCHEMA_VALIDATION_FAILED.value,
                "error_type": type(error).__name__,
            }
        )
    # BUG-2（2026-09-02）：默认 logging formatter 不渲染 extra，曾导致日志只剩
    # 一句 "LLM structured output event"、排障只能回读 checkpoint。现把关键诊断
    # 直接拼进消息体；extra 仍保留，供结构化采集与既有断言使用。
    message = _format_structured_event_message(details)
    log = logger.info if event == "repair_succeeded" else logger.warning
    log(message, extra={"structured_output": details})


def _failure_code(error: ValueError) -> str:
    if isinstance(error, StructuredOutputError):
        return error.code.value
    return StructuredOutputFailureCode.SCHEMA_VALIDATION_FAILED.value


def _segmented_system_prompt(
    base_system_prompt: str,
    *,
    schema: type[BaseModel],
    label: str,
) -> str:
    schema_json = json.dumps(
        schema.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        base_system_prompt
        + _VALIDATION_ENUM_DISAMBIGUATION
        + "\n\n# 长上下文分段结构化输出契约\n"
        + f"本轮只输出{label}，不得输出完整报告或其他分段字段。"
        + "所有金融事实、数字和 evidence_id 必须来自 analysis_request；不得补写未知事实。"
        + "只返回一个符合下方 Schema 的 JSON 对象，不要输出 Markdown 或额外说明。\n"
        + schema_json
    )


def _segmented_runtime_prompt(
    runtime_prompt: str,
    *,
    schema: type[BaseModel],
    label: str,
) -> str:
    try:
        payload = json.loads(runtime_prompt)
    except json.JSONDecodeError:
        return (
            runtime_prompt
            + "\n\n当前技术输出契约：只输出"
            + schema.__name__
            + f"（{label}）对应的标准 JSON。"
        )
    if not isinstance(payload, dict):
        return runtime_prompt
    payload["technical_output_contract"] = {
        "schema": schema.__name__,
        "segment": label,
        "requirements": [
            "只输出当前分段Schema声明的字段",
            "所有金融事实、数字和evidence_id必须来自analysis_request",
            "不得输出Markdown、额外解释或其他分段字段",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


_ANALYSIS_DRAFT_SCHEMA_JSON = json.dumps(
    AnalysisDraft.model_json_schema(),
    ensure_ascii=False,
    separators=(",", ":"),
)

# BUG-1(a)（2026-09-02）：两组高度相似的枚举易被模型互相抄错
# （validation_cards[].status vs 顶层 financial_quality）。在系统提示中显式
# 列出各自合法取值并声明互不通用，降低枚举混淆概率；后端别名归一兜底见
# _VALIDATION_STATUS_ALIASES / _FINANCIAL_QUALITY_ALIASES。
_VALIDATION_ENUM_DISAMBIGUATION = (
    "\n# 枚举防混淆约定（最高优先级）\n"
    "三张校验卡 validation_cards[].status 只允许三个取值：passed / "
    "differences_explained / pending_verification。\n"
    "顶层字段 financial_quality 只允许三个取值：consistent / "
    "differences_explained / differences_pending_verification。\n"
    "两组枚举互不通用：不得把 consistent 或 differences_pending_verification "
    "写进 validation_cards[].status；也不得把 passed 或 pending_verification "
    "写进 financial_quality。\n"
)


def _is_deepseek_style(model_name: str) -> bool:
    """DeepSeek 直连，或经火山方舟网关路由到 DeepSeek 系推理模型的代号
    （Auto 模式下 ark-code-latest 会路由到 deepseek-v4-flash-ga-260731）。
    此类端点统一按 DeepSeek 兼容模式处理：关思考 + json_mode 结构化输出。"""
    return model_name.lower().startswith(("deepseek-", "ark-code-"))


def _structured_output(chat_model: Any, schema: type[Any], model_name: str) -> Any:
    if _is_deepseek_style(model_name):
        # DeepSeek-compatible endpoints can acknowledge a forced function call
        # without returning usable arguments. JSON mode removes that extra
        # envelope for both analysis and chapter generation while ``include_raw``
        # still lets the adapter validate provider content deterministically.
        return chat_model.with_structured_output(
            schema,
            method="json_mode",
            include_raw=True,
        )
    return chat_model.with_structured_output(schema)


def _content_to_text(content: Any) -> str | None:
    if isinstance(content, list):
        content = "".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    if not isinstance(content, str) or not content.strip():
        return None
    return content.strip()


def _response_diagnostics(response: Any) -> dict[str, Any]:
    raw = response.get("raw") if isinstance(response, dict) else response
    metadata = getattr(raw, "response_metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    diagnostics: dict[str, Any] = {}
    finish_reason = metadata.get("finish_reason") or metadata.get("stop_reason")
    if isinstance(finish_reason, str):
        diagnostics["finish_reason"] = finish_reason
    request_id = metadata.get("request_id") or metadata.get("id")
    if isinstance(request_id, str):
        diagnostics["request_id"] = request_id
    content = _content_to_text(getattr(raw, "content", None))
    if content is not None:
        diagnostics["response_chars"] = len(content)
    usage = getattr(raw, "usage_metadata", None)
    if isinstance(usage, dict):
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, int):
                diagnostics[key] = value
    return diagnostics


def _raise_if_provider_truncated(response: Any) -> None:
    diagnostics = _response_diagnostics(response)
    finish_reason = str(diagnostics.get("finish_reason", "")).lower()
    if finish_reason in {"length", "max_tokens", "max_output_tokens"}:
        raise StructuredOutputError(
            StructuredOutputFailureCode.OUTPUT_TRUNCATED,
            "structured model output was truncated by the provider",
            retryable=True,
            diagnostics=diagnostics,
        )


def _has_unclosed_json_structure(text: str, start: int) -> bool:
    stack: list[str] = []
    in_string = False
    escaped = False
    pairs = {"}": "{", "]": "["}
    for character in text[start:]:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "{[":
            stack.append(character)
        elif character in "}]":
            if not stack or stack[-1] != pairs[character]:
                return False
            stack.pop()
    return in_string or bool(stack)


def _json_from_content(content: Any) -> Any:
    text = _content_to_text(content)
    if text is None:
        raise StructuredOutputError(
            StructuredOutputFailureCode.JSON_SYNTAX_INVALID,
            "structured model returned no parsed object or JSON content",
            retryable=True,
        )
    if text.startswith("```"):
        first_newline = text.find("\n")
        last_fence = text.rfind("```")
        if first_newline >= 0 and last_fence > first_newline:
            text = text[first_newline + 1 : last_fence].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as original_error:
        starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
        if not starts:
            raise StructuredOutputError(
                StructuredOutputFailureCode.JSON_CONTAMINATION,
                "structured model output did not contain a JSON object",
                retryable=True,
                diagnostics={"response_chars": len(text)},
            ) from original_error
        start = min(starts)
        try:
            payload, end = json.JSONDecoder().raw_decode(text, idx=start)
        except json.JSONDecodeError as decode_error:
            if _has_unclosed_json_structure(text, start):
                raise StructuredOutputError(
                    StructuredOutputFailureCode.OUTPUT_TRUNCATED,
                    "structured model returned an unclosed JSON value",
                    retryable=True,
                    diagnostics={
                        "response_chars": len(text),
                        "json_error_position": decode_error.pos,
                    },
                ) from decode_error
            raise StructuredOutputError(
                StructuredOutputFailureCode.JSON_SYNTAX_INVALID,
                "structured model returned invalid JSON syntax",
                retryable=True,
                diagnostics={
                    "response_chars": len(text),
                    "json_error_position": decode_error.pos,
                },
            ) from decode_error
        suffix = text[end:].strip()
        if "{" in suffix or "[" in suffix:
            raise StructuredOutputError(
                StructuredOutputFailureCode.JSON_CONTAMINATION,
                "structured model returned multiple JSON values",
                retryable=True,
                diagnostics={"response_chars": len(text)},
            ) from original_error
        return payload


_DIMENSION_ALIASES = {
    "竞争": "competition",
    "竞争格局": "competition",
    "行业竞争": "competition",
    "增长": "growth",
    "行业增长": "growth",
    "宏观政策": "macro_policy",
    "政策": "macro_policy",
    "产业链": "industry_chain",
    "供应链": "industry_chain",
    "风险": "risk",
    "风险分析": "risk",
}

# BUG-1（2026-09-02）：``ValidationCard.status`` 与 ``AnalysisDraft.financial_quality``
# 两组枚举高度相似，flash 级模型会把 financial_quality 的取值抄进校验卡
# status（RUN 5e73b49f 实证：financial_quality 卡的 status 连写 4 次
# ``consistent``）。这里做确定性单向归一兜底：
#   - 校验卡 status 收到 financial_quality 风格值 → 映射回 status 合法枚举
#   - financial_quality 收到 status 风格值 → 映射回 financial_quality 合法枚举
# 两组枚举共享 ``differences_explained``，故它无需映射。
_VALIDATION_STATUS_ALIASES = {
    "consistent": "passed",
    "differences_pending_verification": "pending_verification",
}
_FINANCIAL_QUALITY_ALIASES = {
    "passed": "consistent",
    "pending_verification": "differences_pending_verification",
}


def _normalize_dimension(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return _DIMENSION_ALIASES.get(value.strip(), value)


def _normalize_analysis_aliases(payload: dict[str, Any]) -> None:
    dimensions = payload.get("dimensions")
    if isinstance(dimensions, list):
        for dimension in dimensions:
            if isinstance(dimension, dict):
                dimension["name"] = _normalize_dimension(dimension.get("name"))

    quality_issues = payload.get("data_quality_issues")
    if isinstance(quality_issues, list):
        for issue in quality_issues:
            if not isinstance(issue, dict):
                continue
            affected = issue.get("affected_dimensions")
            if isinstance(affected, list):
                issue["affected_dimensions"] = [_normalize_dimension(value) for value in affected]

    coverage = payload.get("dimension_coverage")
    if isinstance(coverage, list):
        for item in coverage:
            if isinstance(item, dict):
                item["dimension"] = _normalize_dimension(item.get("dimension"))

    # BUG-1(b)（2026-09-02）：接线枚举混淆兜底。模型把 financial_quality 的
    # 取值抄进校验卡 status（或反向）时，确定性映射回各自合法枚举；已合法
    # 的取值（含两组共享的 differences_explained）经 .get 原样保留。
    validation_cards = payload.get("validation_cards")
    if isinstance(validation_cards, list):
        for card in validation_cards:
            if not isinstance(card, dict):
                continue
            status = card.get("status")
            if isinstance(status, str):
                card["status"] = _VALIDATION_STATUS_ALIASES.get(status.strip(), status)
    financial_quality = payload.get("financial_quality")
    if isinstance(financial_quality, str):
        payload["financial_quality"] = _FINANCIAL_QUALITY_ALIASES.get(
            financial_quality.strip(), financial_quality
        )


def _normalize_known_schema_aliases(payload: Any, schema: type[Any]) -> Any:
    """Normalize narrowly defined provider aliases before strict validation."""
    if not isinstance(payload, dict):
        return payload
    if schema in {AnalysisDraft, AnalysisCoreDraft, AnalysisSupplementDraft}:
        _normalize_analysis_aliases(payload)
        return payload
    return payload


def _summarize_value(value: Any, limit: int = 200) -> str:
    """Render a model-provided (possibly illegal) value for diagnostics."""
    if value is None:
        return "<missing>"
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + "…"
    try:
        text = str(value)
    except (TypeError, ValueError):
        return "<unprintable>"
    return text if len(text) <= limit else text[:limit] + "…"


def _summarize_payload(payload: Any, limit: int = 600) -> str:
    """Truncated JSON excerpt of the model output, for failure triage."""
    if not isinstance(payload, (dict, list)):
        return ""
    try:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return ""
    return text if len(text) <= limit else text[:limit] + "…"


def _validate_payload(payload: Any, schema: type[SchemaT]) -> SchemaT:
    try:
        return schema.model_validate(_normalize_known_schema_aliases(payload, schema))
    except ValidationError as exc:
        errors = exc.errors(include_url=False)
        error_types = [str(item.get("type", "unknown")) for item in errors]
        semantic_only = bool(error_types) and all(
            error_type == "assertion_error" or error_type.startswith("value_error")
            for error_type in error_types
        )
        code = (
            StructuredOutputFailureCode.SEMANTIC_VALIDATION_FAILED
            if semantic_only
            else StructuredOutputFailureCode.SCHEMA_VALIDATION_FAILED
        )
        paths = [
            ".".join(str(part) for part in item.get("loc", ())) or "<root>" for item in errors[:20]
        ]
        # BUG-2（2026-09-02）：把非法值、允许枚举与原始内容摘要一并带入诊断，
        # 之后排障只看后端日志即可，无需回读 checkpoint 快照。
        inputs = [_summarize_value(item.get("input")) for item in errors[:20]]
        expected = [
            str((item.get("ctx") or {}).get("expected"))
            for item in errors[:20]
            if (item.get("ctx") or {}).get("expected") is not None
        ]
        diagnostics: dict[str, Any] = {
            "validation_error_count": len(errors),
            "validation_paths": paths,
            "validation_types": error_types[:20],
            "validation_inputs": inputs,
            "validation_expected": expected,
        }
        content_summary = _summarize_payload(payload)
        if content_summary:
            diagnostics["raw_content_summary"] = content_summary
        raise StructuredOutputError(
            code,
            f"structured output failed {schema.__name__} validation",
            retryable=True,
            diagnostics=diagnostics,
        ) from exc


def _coerce_structured_response(response: Any, schema: type[SchemaT]) -> SchemaT:
    _raise_if_provider_truncated(response)
    if not isinstance(response, dict) or "parsed" not in response:
        return _validate_payload(response, schema)
    parsed = response.get("parsed")
    if parsed is not None:
        return _validate_payload(parsed, schema)
    raw = response.get("raw")
    tool_calls = getattr(raw, "tool_calls", None) or []
    if tool_calls:
        arguments = tool_calls[0].get("args")
        if arguments is not None:
            return _validate_payload(arguments, schema)
    payload = _json_from_content(getattr(raw, "content", None))
    return _validate_payload(payload, schema)


def _response_text_for_repair(response: Any) -> str | None:
    """Recover the first response so a repair turn can preserve its facts."""
    if isinstance(response, dict) and "parsed" in response:
        parsed = response.get("parsed")
        if parsed is not None:
            if isinstance(parsed, BaseModel):
                parsed = parsed.model_dump(mode="json")
            try:
                return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
            except (TypeError, ValueError):
                return str(parsed)
        raw = response.get("raw")
        return _content_to_text(getattr(raw, "content", None))
    if isinstance(response, BaseModel):
        return response.model_dump_json()
    if isinstance(response, (dict, list)):
        return json.dumps(response, ensure_ascii=False, separators=(",", ":"))
    return _content_to_text(response)


async def _invoke_structured(model: Any, messages: list[Any]) -> Any:
    try:
        return await model.ainvoke(messages)
    except StructuredOutputError:
        raise
    except Exception as exc:
        raise StructuredOutputError(
            StructuredOutputFailureCode.PROVIDER_ERROR,
            "structured model provider call failed",
            retryable=True,
            diagnostics={"provider_error_type": type(exc).__name__},
        ) from exc


class OpenAICompatibleAnalysisModel:
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 60,
        max_output_tokens: int = 8_192,
        chat_model: Any | None = None,
        segmented_threshold_chars: int = 10_000,
        max_repair_attempts: int = 1,
    ) -> None:
        self.model_name = model_name
        self._requires_json_instruction = _is_deepseek_style(model_name)
        if chat_model is None:
            if not api_key:
                raise ValueError("LLM_API_KEY is required when mock mode is disabled")
            chat_model = ChatOpenAI(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                temperature=0.1,
                timeout=timeout_seconds,
                max_retries=2,
                # BUG-5（2026-09-01）：max_tokens 走 ChatOpenAI 显式参数，
                # model_kwargs 透传会触发 langchain-openai 弃用 UserWarning。
                max_tokens=max_output_tokens,
                extra_body=(
                    {"thinking": {"type": "disabled"}} if _is_deepseek_style(model_name) else None
                ),
            )
        self._chat_model = chat_model
        self._segmented_threshold_chars = max(1, segmented_threshold_chars)
        # flash 级模型对严格 Pydantic 契约存在概率性漂移：默认 1 轮修复
        # 保持既定 fail-closed 语义（单测契约），生产装配可提高到多轮。
        self._max_repair_attempts = max(0, max_repair_attempts)
        self._structured_model = _structured_output(chat_model, AnalysisDraft, model_name)

    async def _generate_segment(
        self,
        *,
        system_prompt: str,
        runtime_prompt: str,
        schema: type[SchemaT],
        label: str,
    ) -> SchemaT:
        structured_model = _structured_output(self._chat_model, schema, self.model_name)
        system_message = SystemMessage(
            content=_segmented_system_prompt(
                system_prompt,
                schema=schema,
                label=label,
            )
        )
        segment_runtime_prompt = _segmented_runtime_prompt(
            runtime_prompt,
            schema=schema,
            label=label,
        )
        validation_error: ValueError | None = None
        previous_response: str | None = None
        for attempt in range(self._max_repair_attempts + 1):
            prompt = segment_runtime_prompt
            if validation_error is not None:
                _log_structured_output_event(
                    "repair_started",
                    model_name=self.model_name,
                    schema=schema,
                    error=validation_error,
                )
                previous_context = (
                    "\n上一份当前分段输出如下，仅用于保持已有金融事实和 evidence_id：\n"
                    + previous_response[:20_000]
                    if previous_response
                    else ""
                )
                prompt = (
                    segment_runtime_prompt
                    + "\n\n上一份当前分段未通过结构校验。请只修复当前分段的 JSON 结构、字段名、必填字段和枚举，"
                    + "不得改变金融事实、数字、结论或 evidence_id。"
                    + previous_context
                    + "\n错误分类："
                    + _failure_code(validation_error)
                    + "\n校验错误："
                    + str(validation_error)[:2_000]
                )
            response = await _invoke_structured(
                structured_model,
                [system_message, HumanMessage(content=prompt)],
            )
            try:
                segment = _coerce_structured_response(response, schema)
            except StructuredOutputError as exc:
                if exc.code is StructuredOutputFailureCode.OUTPUT_TRUNCATED:
                    raise
                validation_error = exc
            except ValueError as exc:
                validation_error = exc
            else:
                if attempt > 0:
                    _log_structured_output_event(
                        "repair_succeeded",
                        model_name=self.model_name,
                        schema=schema,
                    )
                return segment
            previous_response = _response_text_for_repair(response) or previous_response
        _log_structured_output_event(
            "repair_failed",
            model_name=self.model_name,
            schema=schema,
            error=validation_error,
        )
        raise validation_error

    async def _generate_segmented_analysis(
        self,
        *,
        system_prompt: str,
        runtime_prompt: str,
    ) -> AnalysisDraft:
        segments: list[tuple[type[BaseModel], str]] = [
            (AnalysisCoreDraft, "核心分析"),
            (AnalysisSupplementDraft, "情景、风险、协同与图表补充"),
        ]
        payload: dict[str, Any] = {}
        for schema, label in segments:
            segment = await self._generate_segment(
                system_prompt=system_prompt,
                runtime_prompt=runtime_prompt,
                schema=schema,
                label=label,
            )
            payload.update(segment.model_dump(mode="json"))
        return _validate_payload(payload, AnalysisDraft)

    async def generate_analysis(
        self,
        *,
        system_prompt: str,
        runtime_prompt: str,
    ) -> AnalysisDraft:
        if len(runtime_prompt) >= self._segmented_threshold_chars:
            return await self._generate_segmented_analysis(
                system_prompt=system_prompt,
                runtime_prompt=runtime_prompt,
            )
        if self._requires_json_instruction:
            system_prompt = (
                system_prompt
                + "\n\n# 最高优先级技术输出契约\n"
                + "下方JSON Schema高于前文所有报告模板、表格格式、展示结构和字段命名要求。"
                + "你当前不是输出面向用户的Markdown报告，而是为下游程序输出AnalysisDraft。"
                + "必须严格使用Schema中的英文属性名和英文枚举值；不得翻译字段名或枚举值；"
                + "不得增加Schema未声明的属性；数组与对象类型不得互换。"
                + "只返回一个符合Schema的JSON对象，不要输出Markdown代码围栏、工具调用外壳或额外说明。"
                + _VALIDATION_ENUM_DISAMBIGUATION
                + "\nAnalysisDraft JSON Schema：\n"
                + _ANALYSIS_DRAFT_SCHEMA_JSON
            )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=runtime_prompt),
        ]
        # Bounded repair turns address provider formatting drift. Each repair
        # prompt explicitly freezes financial facts and evidence so this
        # remains structural recovery rather than a hidden re-analysis.
        validation_error: ValueError | None = None
        previous_response: str | None = None
        for attempt in range(self._max_repair_attempts + 1):
            prompt = runtime_prompt
            if validation_error is not None:
                _log_structured_output_event(
                    "repair_started",
                    model_name=self.model_name,
                    schema=AnalysisDraft,
                    error=validation_error,
                )
                repair_context = (
                    "\n上一份模型输出如下，请保留其中的金融事实、数字、结论和 evidence_id，仅修复结构：\n"
                    + previous_response[:30_000]
                    if previous_response
                    else "\n上一份模型输出为空或无法读取，请依据原始 analysis_request 重新生成相同任务的完整 JSON。"
                )
                prompt = (
                    runtime_prompt
                    + "\n\n上一份 JSON 未通过 AnalysisDraft 结构校验。请只修正 JSON 结构、字段名称、必填字段和枚举格式，"
                    + "不得新增、删改或替换金融事实、数字、结论和 evidence_id。"
                    + repair_context
                    + "\n错误分类："
                    + _failure_code(validation_error)
                    + "\n校验错误："
                    + str(validation_error)[:2_000]
                    + "\n请重新返回完整且有效的 JSON 对象，不要输出其他文字。"
                )
            response = await _invoke_structured(
                self._structured_model,
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=prompt),
                ],
            )
            try:
                draft = _coerce_structured_response(response, AnalysisDraft)
            except StructuredOutputError as exc:
                if exc.code is StructuredOutputFailureCode.OUTPUT_TRUNCATED:
                    raise
                validation_error = exc
            except ValueError as exc:
                validation_error = exc
            else:
                if attempt > 0:
                    _log_structured_output_event(
                        "repair_succeeded",
                        model_name=self.model_name,
                        schema=AnalysisDraft,
                    )
                return draft
            previous_response = _response_text_for_repair(response) or previous_response
        _log_structured_output_event(
            "repair_failed",
            model_name=self.model_name,
            schema=AnalysisDraft,
            error=validation_error,
        )
        raise validation_error


class OpenAICompatibleChapterModel:
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 60,
        chat_model: Any | None = None,
        max_repair_attempts: int = 1,
    ) -> None:
        self.model_name = model_name
        self._requires_json_instruction = _is_deepseek_style(model_name)
        if chat_model is None:
            if not api_key:
                raise ValueError("LLM_API_KEY is required when mock mode is disabled")
            chat_model = ChatOpenAI(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                temperature=0.1,
                timeout=timeout_seconds,
                max_retries=2,
                extra_body=(
                    {"thinking": {"type": "disabled"}} if _is_deepseek_style(model_name) else None
                ),
            )
        self._max_repair_attempts = max(0, max_repair_attempts)
        self._structured_model = _structured_output(chat_model, ChapterDraftLoose, model_name)

    async def generate_chapter(
        self,
        *,
        system_prompt: str,
        runtime_prompt: str,
    ) -> ChapterDraftLoose:
        if self._requires_json_instruction:
            system_prompt = (
                system_prompt
                + "\n必须仅返回符合给定结构的 JSON 对象，不要输出 Markdown 代码围栏或额外说明。"
            )
        # Bounded repair turns keep a provider's formatting drift from
        # discarding all previously generated chapters. The model sees the
        # validation failure, while evidence and financial content remain
        # unchanged. Exhausted attempts still fail closed.
        validation_error: ValueError | None = None
        for attempt in range(self._max_repair_attempts + 1):
            prompt = runtime_prompt
            if validation_error is not None:
                _log_structured_output_event(
                    "repair_started",
                    model_name=self.model_name,
                    schema=ChapterDraftLoose,
                    error=validation_error,
                )
                prompt = (
                    runtime_prompt
                    + "\n\n上一份 JSON 未通过结构校验。请只修正结构和字段格式，不得新增、删改或替换金融事实、数字、证据引用和结论。"
                    + "\n错误分类："
                    + _failure_code(validation_error)
                    + "\n校验错误："
                    + str(validation_error)[:2_000]
                    + "\n请重新返回完整且有效的 JSON 对象。"
                )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt),
            ]
            try:
                response = await _invoke_structured(self._structured_model, messages)
                loose = _coerce_structured_response(response, ChapterDraftLoose)
            except StructuredOutputError as exc:
                if exc.code is StructuredOutputFailureCode.OUTPUT_TRUNCATED:
                    raise
                validation_error = exc
            except ValueError as exc:
                validation_error = exc
            else:
                if attempt > 0:
                    _log_structured_output_event(
                        "repair_succeeded",
                        model_name=self.model_name,
                        schema=ChapterDraftLoose,
                    )
                return loose
        _log_structured_output_event(
            "repair_failed",
            model_name=self.model_name,
            schema=ChapterDraftLoose,
            error=validation_error,
        )
        raise validation_error


class OpenAICompatibleReadabilityModel:
    """Input-isolated LLM judge for paragraph readability (soft gate).

    只接收 paragraph_text 与 kind，不喂 summary、标题、自我评价或人工
    comment，防止自夸文本带偏打分（评审器输入隔离原则）。
    """

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 60,
        chat_model: Any | None = None,
    ) -> None:
        self.model_name = model_name
        self._requires_json_instruction = _is_deepseek_style(model_name)
        if chat_model is None:
            if not api_key:
                raise ValueError("LLM_API_KEY is required when mock mode is disabled")
            chat_model = ChatOpenAI(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                temperature=0.1,
                timeout=timeout_seconds,
                max_retries=2,
                extra_body=(
                    {"thinking": {"type": "disabled"}} if _is_deepseek_style(model_name) else None
                ),
            )
        self._structured_model = _structured_output(chat_model, ReadabilityReport, model_name)

    async def review_paragraph(
        self,
        *,
        paragraph_text: str,
        kind: str,
    ) -> ReadabilityReport:
        system_prompt = (
            "你是行业研究报告的可读性评审器，只依据给定段落文本评审，不评价段落之外的内容，"
            "不引入新事实、数值或结论。\n"
            "评审四个维度：通顺度（语法与句子结构）、通俗度（术语是否有解释、普通读者能否读懂）、"
            "连贯性（句间逻辑衔接）、客观性（有无自夸、空泛强调、内部话术泄漏）。\n"
            "打分锚点：0.9=可读（专业且清晰）；0.6=勉强可读（能懂但读感重）；0.3=读不通"
            "（病句/语义断裂/非人类语言）。score 为 0~1 软分，1 为完全可读。\n"
            "9:1 裁判原则：凡客观可判定的缺陷（双主语病句、裸标签拼接、数据字段或占位符泄漏、"
            "自夸语句、空泛模板话术）一经出现即显著拉低总分（通常不高于 0.5），不要再用软维度"
            "为其补分；软维度只评规则判不了的通顺、通俗、连贯。\n"
            "few-shot 参照（合成示例，仅示意尺度）：\n"
            "通顺度【正】“营业收入同比增长12%，统计口径与上年同期一致。”→0.9；"
            "【负】“由于需求回暖使其价格出现上涨。”→0.3（双主语病句）。\n"
            "通俗度【正】“利润池，即产业链中利润集中的环节，正向中游迁移。”→0.9（术语有白话解释）；"
            "【负】“估值锚、景气度与护城河共同决定投资逻辑。”→0.4（术语堆砌未解释）。\n"
            "连贯性【正】“样本企业数量为10家；鉴于样本仍需扩充，该结论的适用范围有限。”→0.85；"
            "【负】“样本企业数量为10家。限制条件：样本仍需扩充。”→0.5（裸标签机械拼接）。\n"
            "客观性【正】“行业集中度较高，CR3在50%以上。”→0.9；"
            "【负】“本报告深入剖析了行业底层逻辑，前景广阔值得期待。”→0.35（自夸+空泛结论）。\n"
            "软判补充指引（规则判不了、由你把关的形态）：\n"
            "1) 句子各自合法但主语缺失、指代链断裂、读不出段落主旨（分段逃逸）→不高于0.55；\n"
            "2) 机翻腔（“被…所驱动”“正在被…着”）、公告腔（“根据…规定，现予以…”）、"
            "营销口号（“抢占窗口期！”“不容错过”）→不高于0.5；\n"
            "3) 术语用引号罗列成串且全段无一处解释 → 通俗度不高于0.55；\n"
            "4) 数字密集但每个数字都得到解读的规范表述是正常研报文体，不得因此压分；\n"
            "5) 重复填充（同一内容词在同句反复出现≥3次、信息零增量，如“改善…改善…改善”）→不高于0.4。\n"
            "返回ReadabilityReport JSON：score为0到1的可读性软分；findings列出具体问题，"
            "dimension取值通顺度/通俗度/连贯性/客观性，severity取值must_fix/suggest，"
            "每条包含reason（哪里读不懂）与rewrite_hint（修改方向）；"
            "paragraph_id固定为空字符串；findings为空表示可读。"
        )
        if self._requires_json_instruction:
            system_prompt = (
                system_prompt
                + "\n必须仅返回符合给定结构的 JSON 对象，不要输出 Markdown 代码围栏或额外说明。"
            )
        runtime_prompt = json.dumps(
            {"paragraph_text": paragraph_text, "kind": kind},
            ensure_ascii=False,
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=runtime_prompt),
        ]
        response = await _invoke_structured(self._structured_model, messages)
        return _coerce_structured_response(response, ReadabilityReport)
