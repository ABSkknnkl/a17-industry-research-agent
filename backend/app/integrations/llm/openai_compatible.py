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
from app.schemas.chapter import ChapterDraft

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
    log = logger.info if event == "repair_succeeded" else logger.warning
    log("LLM structured output event", extra={"structured_output": details})


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


def _is_deepseek(model_name: str) -> bool:
    return model_name.lower().startswith("deepseek-")


def _structured_output(chat_model: Any, schema: type[Any], model_name: str) -> Any:
    if _is_deepseek(model_name):
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


def _normalize_known_schema_aliases(payload: Any, schema: type[Any]) -> Any:
    """Normalize narrowly defined provider aliases before strict validation."""
    if schema is not ChapterDraft or not isinstance(payload, dict):
        return payload
    sections = payload.get("sections")
    if not isinstance(sections, list):
        return payload
    for section in sections:
        if not isinstance(section, dict):
            continue
        paragraphs = section.get("paragraphs")
        if not isinstance(paragraphs, list):
            continue
        for paragraph in paragraphs:
            if not isinstance(paragraph, dict):
                continue
            paragraph_id = paragraph.get("paragraph_id")
            if isinstance(paragraph_id, str):
                for alias in ("PARA-", "PAR-"):
                    if paragraph_id.startswith(alias):
                        paragraph["paragraph_id"] = "P-" + paragraph_id.removeprefix(alias)
                        break
    return payload


def _validate_payload(payload: Any, schema: type[SchemaT]) -> SchemaT:
    try:
        return schema.model_validate(_normalize_known_schema_aliases(payload, schema))
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_input=False)
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
        raise StructuredOutputError(
            code,
            f"structured output failed {schema.__name__} validation",
            retryable=True,
            diagnostics={
                "validation_error_count": len(errors),
                "validation_paths": paths,
                "validation_types": error_types[:20],
            },
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
        chat_model: Any | None = None,
        segmented_threshold_chars: int = 36_000,
    ) -> None:
        self.model_name = model_name
        self._requires_json_instruction = _is_deepseek(model_name)
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
                    {"thinking": {"type": "disabled"}} if _is_deepseek(model_name) else None
                ),
            )
        self._chat_model = chat_model
        self._segmented_threshold_chars = max(1, segmented_threshold_chars)
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
        response = await _invoke_structured(
            structured_model,
            [system_message, HumanMessage(content=segment_runtime_prompt)],
        )
        try:
            return _coerce_structured_response(response, schema)
        except StructuredOutputError as exc:
            if exc.code is StructuredOutputFailureCode.OUTPUT_TRUNCATED:
                raise
            validation_error: ValueError = exc
        except ValueError as exc:
            validation_error = exc

        _log_structured_output_event(
            "repair_started",
            model_name=self.model_name,
            schema=schema,
            error=validation_error,
        )
        previous_response = _response_text_for_repair(response)
        previous_context = (
            "\n上一份当前分段输出如下，仅用于保持已有金融事实和 evidence_id：\n"
            + previous_response[:20_000]
            if previous_response
            else ""
        )
        repair_prompt = (
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
            [system_message, HumanMessage(content=repair_prompt)],
        )
        try:
            repaired = _coerce_structured_response(response, schema)
        except ValueError as repair_error:
            _log_structured_output_event(
                "repair_failed",
                model_name=self.model_name,
                schema=schema,
                error=repair_error,
            )
            raise
        _log_structured_output_event(
            "repair_succeeded",
            model_name=self.model_name,
            schema=schema,
        )
        return repaired

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
                + "只返回一个符合Schema的JSON对象，不要输出Markdown代码围栏、工具调用外壳或额外说明。\n"
                + "AnalysisDraft JSON Schema：\n"
                + _ANALYSIS_DRAFT_SCHEMA_JSON
            )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=runtime_prompt),
        ]
        response = await _invoke_structured(self._structured_model, messages)
        try:
            return _coerce_structured_response(response, AnalysisDraft)
        except StructuredOutputError as exc:
            if exc.code is StructuredOutputFailureCode.OUTPUT_TRUNCATED:
                raise
            validation_error: ValueError = exc
        except ValueError as exc:
            validation_error = exc
        _log_structured_output_event(
            "repair_started",
            model_name=self.model_name,
            schema=AnalysisDraft,
            error=validation_error,
        )
        # One bounded repair turn addresses provider formatting drift. The
        # repair prompt explicitly freezes financial facts and evidence so
        # this remains structural recovery rather than a hidden re-analysis.
        previous_response = _response_text_for_repair(response)
        repair_context = (
            "\n上一份模型输出如下，请保留其中的金融事实、数字、结论和 evidence_id，仅修复结构：\n"
            + previous_response[:30_000]
            if previous_response
            else "\n上一份模型输出为空或无法读取，请依据原始 analysis_request 重新生成相同任务的完整 JSON。"
        )
        repair_prompt = (
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
                HumanMessage(content=repair_prompt),
            ],
        )
        try:
            repaired = _coerce_structured_response(response, AnalysisDraft)
        except ValueError as repair_error:
            _log_structured_output_event(
                "repair_failed",
                model_name=self.model_name,
                schema=AnalysisDraft,
                error=repair_error,
            )
            raise
        _log_structured_output_event(
            "repair_succeeded",
            model_name=self.model_name,
            schema=AnalysisDraft,
        )
        return repaired


class OpenAICompatibleChapterModel:
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
        self._requires_json_instruction = _is_deepseek(model_name)
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
                    {"thinking": {"type": "disabled"}} if _is_deepseek(model_name) else None
                ),
            )
        self._structured_model = _structured_output(chat_model, ChapterDraft, model_name)

    async def generate_chapter(
        self,
        *,
        system_prompt: str,
        runtime_prompt: str,
    ) -> ChapterDraft:
        if self._requires_json_instruction:
            system_prompt = (
                system_prompt
                + "\n必须仅返回符合给定结构的 JSON 对象，不要输出 Markdown 代码围栏或额外说明。"
                + " paragraph_id 必须严格使用 P-两位章节-两位小节-两位序号，例如 P-04-01-01。"
            )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=runtime_prompt),
        ]
        try:
            response = await _invoke_structured(self._structured_model, messages)
            return _coerce_structured_response(response, ChapterDraft)
        except StructuredOutputError as exc:
            if exc.code is StructuredOutputFailureCode.OUTPUT_TRUNCATED:
                raise
            validation_error: ValueError = exc
        except ValueError as exc:
            validation_error = exc
        _log_structured_output_event(
            "repair_started",
            model_name=self.model_name,
            schema=ChapterDraft,
            error=validation_error,
        )
        # One bounded repair turn keeps a provider's formatting drift from
        # discarding all previously generated chapters. The model sees the
        # validation failure, while evidence and financial content remain
        # unchanged. A second invalid response still fails closed.
        repair_prompt = (
            runtime_prompt
            + "\n\n上一份 JSON 未通过结构校验。请只修正结构和字段格式，不得新增、删改或替换金融事实、数字、证据引用和结论。"
            + "\n错误分类："
            + _failure_code(validation_error)
            + "\n校验错误："
            + str(validation_error)[:2_000]
            + "\n请重新返回完整且有效的 JSON 对象。"
        )
        response = await _invoke_structured(
            self._structured_model,
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=repair_prompt),
            ],
        )
        try:
            repaired = _coerce_structured_response(response, ChapterDraft)
        except ValueError as repair_error:
            _log_structured_output_event(
                "repair_failed",
                model_name=self.model_name,
                schema=ChapterDraft,
                error=repair_error,
            )
            raise
        _log_structured_output_event(
            "repair_succeeded",
            model_name=self.model_name,
            schema=ChapterDraft,
        )
        return repaired
