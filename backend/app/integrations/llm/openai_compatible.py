"""OpenAI-compatible structured adapters for Qwen/DeepSeek-style APIs."""

import json
from typing import Any, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.schemas.analysis import AnalysisDraft
from app.schemas.chapter import ChapterDraft

SchemaT = TypeVar("SchemaT", bound=BaseModel)

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


def _json_from_content(content: Any) -> Any:
    text = _content_to_text(content)
    if text is None:
        raise ValueError("structured model returned no parsed object or JSON content")
    if text.startswith("```"):
        first_newline = text.find("\n")
        last_fence = text.rfind("```")
        if first_newline >= 0 and last_fence > first_newline:
            text = text[first_newline + 1 : last_fence].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(text[start : end + 1])


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


def _coerce_structured_response(response: Any, schema: type[SchemaT]) -> SchemaT:
    if not isinstance(response, dict) or "parsed" not in response:
        return schema.model_validate(_normalize_known_schema_aliases(response, schema))
    parsed = response.get("parsed")
    if parsed is not None:
        return schema.model_validate(_normalize_known_schema_aliases(parsed, schema))
    raw = response.get("raw")
    tool_calls = getattr(raw, "tool_calls", None) or []
    if tool_calls:
        arguments = tool_calls[0].get("args")
        if arguments is not None:
            return schema.model_validate(_normalize_known_schema_aliases(arguments, schema))
    payload = _json_from_content(getattr(raw, "content", None))
    return schema.model_validate(_normalize_known_schema_aliases(payload, schema))


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


class OpenAICompatibleAnalysisModel:
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
        self._structured_model = _structured_output(chat_model, AnalysisDraft, model_name)

    async def generate_analysis(
        self,
        *,
        system_prompt: str,
        runtime_prompt: str,
    ) -> AnalysisDraft:
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
        response = await self._structured_model.ainvoke(messages)
        try:
            return _coerce_structured_response(response, AnalysisDraft)
        except ValueError as exc:
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
                + "\n校验错误："
                + str(exc)[:2_000]
                + "\n请重新返回完整且有效的 JSON 对象，不要输出其他文字。"
            )
            response = await self._structured_model.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=repair_prompt),
                ]
            )
            return _coerce_structured_response(response, AnalysisDraft)


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
            response = await self._structured_model.ainvoke(messages)
            return _coerce_structured_response(response, ChapterDraft)
        except ValueError as exc:
            # One bounded repair turn keeps a provider's formatting drift from
            # discarding all previously generated chapters. The model sees the
            # validation failure, while evidence and financial content remain
            # unchanged. A second invalid response still fails closed.
            repair_prompt = (
                runtime_prompt
                + "\n\n上一份 JSON 未通过结构校验。请只修正结构和字段格式，不得新增、删改或替换金融事实、数字、证据引用和结论。"
                + "\n校验错误："
                + str(exc)[:2_000]
                + "\n请重新返回完整且有效的 JSON 对象。"
            )
            response = await self._structured_model.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=repair_prompt),
                ]
            )
            return _coerce_structured_response(response, ChapterDraft)
