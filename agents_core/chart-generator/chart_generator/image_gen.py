"""Industry-chain image generation boundary used by Chart Generator Agent (Agent 3).

合并自同花顺项目 Agent3 的「证据约束图谱 → 确定性正文 → LLM 编译 → 拓扑/纯度门禁 → 生图」链路。
只有 Agent 3 可以调用本模块；整条流水线默认只允许成功生成 1 张产业链图。

Live protocol (shengsuanyun router):

    POST {base}/tasks/generations              -> 202 {"code":"success","data":{"request_id":...}}
    GET  {base}/tasks/generations/{request_id} -> data.status until COMPLETED | FAILED
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from chart_generator.industry_chain import (
    PROMPT_COMPILER_SYSTEM,
    assert_pure_image_prompt,
    build_chain_graph_from_segments,
    build_chain_image_prompt_body,
    build_connection_section,
    build_required_content_blocks,
    finalize_chain_prompt,
    missing_required_blocks,
    select_chain_template_from_text,
)

logger = logging.getLogger(__name__)

# Process-wide budget: 生图模型仅允许成功调用一次
_IMAGE_BUDGET = 1
_image_spent = False

_POLL_INTERVAL_SECONDS = 3.0
_TERMINAL_SUCCESS = frozenset({"COMPLETED"})
_TERMINAL_FAILURE = frozenset({"FAILED", "CANCELED", "CANCELLED"})
_PENDING_STATUS = frozenset({"SUBMITTING", "PENDING", "QUEUED", "RUNNING", "GENERATING"})


def reset_image_budget() -> None:
    global _IMAGE_BUDGET, _image_spent
    _IMAGE_BUDGET = 1
    _image_spent = False


def image_budget_remaining() -> int:
    return max(0, _IMAGE_BUDGET)


def _try_consume_budget() -> bool:
    global _IMAGE_BUDGET, _image_spent
    if _image_spent or _IMAGE_BUDGET <= 0:
        return False
    _IMAGE_BUDGET -= 1
    _image_spent = True
    return True


def _refund_budget() -> None:
    global _IMAGE_BUDGET, _image_spent
    if _image_spent:
        _IMAGE_BUDGET = 1
        _image_spent = False


@dataclass(frozen=True)
class ImageGenSettings:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 600.0
    size: str = "auto"
    extra_body: dict[str, Any] | None = None
    llm_api_key: str = ""
    llm_base_url: str = "https://ark.cn-beijing.volces.com/api/plan/v3"
    llm_model: str = "deepseek-v4-flash"
    llm_timeout_seconds: float = 180.0

    @classmethod
    def from_env(cls) -> "ImageGenSettings":
        raw_extra = os.getenv("IMAGE_EXTRA_FIELDS", "").strip()
        extra: dict[str, Any] | None = None
        if raw_extra:
            try:
                parsed = json.loads(raw_extra)
                if isinstance(parsed, dict):
                    extra = parsed
            except json.JSONDecodeError:
                logger.warning("IMAGE_EXTRA_FIELDS 不是合法 JSON，忽略")
        return cls(
            api_key=os.getenv("IMAGE_API_KEY", "").strip(),
            base_url=os.getenv("IMAGE_BASE_URL", "https://router.shengsuanyun.com/api/v1").rstrip("/"),
            model=os.getenv("IMAGE_MODEL", "openai/gpt-image-2").strip(),
            timeout_seconds=float(os.getenv("IMAGE_TIMEOUT_SECONDS", "600")),
            size=os.getenv("IMAGE_SIZE", "auto").strip() or "auto",
            extra_body=extra,
            llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://ark.cn-beijing.volces.com/api/plan/v3").rstrip("/"),
            llm_model=os.getenv("LLM_MODEL", "deepseek-v4-flash").strip(),
            llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "180")),
        )


@dataclass
class GeneratedImage:
    image_path: str
    image_uri: str
    image_mime_type: str
    generation_prompt: str
    generation_prompt_model: str
    generation_image_model: str
    chain_template: str
    chain_graph: dict[str, Any]


class OpenAICompatiblePromptCompiler:
    """用项目大模型把 verified_chain_graph 编译成纯文字生图提示词。"""

    def __init__(self, *, model_name: str, api_key: str, base_url: str, timeout_seconds: float) -> None:
        self.model_name = model_name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def compile_prompt(self, *, system_prompt: str, runtime_prompt: str) -> str:
        from chart_generator.llm import _clean_json_content  # noqa: F401  # keep import surface stable

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            res = await client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self.model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": runtime_prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 6000,
                },
            )
            res.raise_for_status()
            content = res.json()["choices"][0]["message"].get("content") or ""
        # 剥掉可能的代码围栏
        content = re.sub(r"^```(?:text|markdown)?\s*", "", content.strip())
        content = re.sub(r"\s*```$", "", content).strip()
        if len(content) < 80:
            raise ValueError("compiled industry-chain prompt is underspecified")
        return content


def _sniff_mime(content: bytes) -> str:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _extract_request_id(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ValueError("image submit returned a non-object payload")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("image submit payload is missing data.request_id")
    request_id = data.get("request_id") or data.get("task_id")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("image submit payload is missing data.request_id")
    return request_id


def _first_image_url(data: dict) -> str | None:
    results = data.get("data")
    if isinstance(results, dict):
        urls = results.get("image_urls")
        if isinstance(urls, list) and urls and isinstance(urls[0], str):
            return urls[0]
        items = results.get("results")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            url = items[0].get("image_url")
            if isinstance(url, str) and url:
                return url
    return None


async def _poll_until_image(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    base_url: str,
    request_id: str,
    timeout_seconds: float,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    poll_url = f"{base_url}/tasks/generations/{request_id}"
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("image generation timed out")
        response = await client.get(poll_url, headers=headers)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("image task poll returned a non-object payload")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("image task poll payload is missing data")
        status = str(data.get("status") or "").upper()
        if status in _TERMINAL_SUCCESS:
            image_url = _first_image_url(data)
            if not image_url:
                raise ValueError("image task completed without an image url")
            return image_url
        if status in _TERMINAL_FAILURE:
            reason = data.get("fail_reason") or status
            raise RuntimeError(f"image task failed: {reason}")
        if status not in _PENDING_STATUS:
            raise RuntimeError(f"image task in unexpected state: {status}")
        await asyncio.sleep(min(_POLL_INTERVAL_SECONDS, remaining))


async def _compile_pure_prompt(
    *,
    graph: dict[str, Any],
    template: str,
    cfg: ImageGenSettings,
    prompt_model: str,
) -> tuple[str, str]:
    """确定性正文 + （可选）LLM 编译 + 拓扑/纯度门禁。返回 (最终提示词, prompt_model)。"""
    deterministic = "\n".join(
        [
            build_chain_image_prompt_body(graph, template),
            build_connection_section(graph),
        ]
    )
    # 先做确定性版本的门禁（保证即使 LLM 不可用也有合格提示词）
    base_prompt, _ = finalize_chain_prompt(deterministic, graph)
    assert_pure_image_prompt(base_prompt)

    if not (cfg.llm_api_key and cfg.llm_model):
        return base_prompt, prompt_model or cfg.llm_model or "deterministic"

    compiler = OpenAICompatiblePromptCompiler(
        model_name=cfg.llm_model,
        api_key=cfg.llm_api_key,
        base_url=cfg.llm_base_url,
        timeout_seconds=cfg.llm_timeout_seconds,
    )
    from chart_generator.industry_chain import build_prompt_runtime_payload

    try:
        raw = await compiler.compile_prompt(
            system_prompt=PROMPT_COMPILER_SYSTEM,
            runtime_prompt=build_prompt_runtime_payload(graph, template),
        )
        blocks = build_required_content_blocks(graph, template)
        dropped = missing_required_blocks(raw, blocks)
        if dropped:
            logger.warning(
                "生图提示词编译器遵约率：%d/%d 块被原样保留（丢失 %d）",
                len(blocks) - len(dropped), len(blocks), len(dropped),
            )
        finalized, missing = finalize_chain_prompt(raw, graph)
        if missing:
            logger.warning("生图提示词拓扑缺失 %d 项，已确定性补全", len(missing))
        assert_pure_image_prompt(finalized)
        return finalized, compiler.model_name
    except Exception as e:
        logger.warning(f"LLM 提示词编译失败，回退确定性正文: {e}")
        return base_prompt, prompt_model or cfg.llm_model or "deterministic"


def build_verified_graph_for_report(
    *,
    subject: str,
    title: str,
    segments: list[dict[str, Any]] | None,
    option: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """优先用 data-analysis 的 industry_chain_segments；缺失时从 ECharts option 兜底清洗。"""
    if segments:
        return build_chain_graph_from_segments(
            title=title, subject=subject, segments=segments,
        )
    # 兜底：从 option.series[0].data/links 构建（会清洗噪声节点）
    option = option or {}
    series = option.get("series") if isinstance(option, dict) else None
    if isinstance(series, dict):
        series = [series]
    if not isinstance(series, list):
        series = []
    raw_nodes = []
    raw_links = []
    for s in series:
        if not isinstance(s, dict):
            continue
        raw_nodes.extend([n for n in (s.get("data") or []) if isinstance(n, dict)])
        raw_links.extend([lk for lk in (s.get("links") or []) if isinstance(lk, dict)])

    from chart_generator.industry_chain import _clean_node_label  # type: ignore

    nodes, edges = [], []
    id_map: dict[str, str] = {}
    for i, n in enumerate(raw_nodes, start=1):
        label = _clean_node_label(n.get("name", ""))
        if not label:
            continue
        cat = str(n.get("category") or "midstream")
        stage = {"上游": "upstream", "中游": "midstream", "下游": "downstream"}.get(cat, cat)
        if stage not in ("upstream", "midstream", "downstream", "support"):
            stage = "midstream"
        nid = f"N{i}"
        id_map[str(n.get("id") or n.get("name"))] = nid
        nodes.append({
            "node_id": nid, "label": label, "stage": stage, "group": stage,
            "node_kind": "other", "companies": [], "logo_names": [],
            "is_core": False, "evidence_ids": ["OPT"],
        })
    for lk in raw_links:
        src = id_map.get(str(lk.get("source")))
        tgt = id_map.get(str(lk.get("target")))
        if src and tgt:
            edges.append({
                "source": src, "target": tgt, "label": "关联",
                "flow_type": "supply", "evidence_ids": ["OPT"],
            })
    return {
        "title": title,
        "subtitle": f"{subject}的价值传导与供需流向",
        "template_id": "horizontal_flow",
        "core_product_name": subject,
        "nodes": nodes,
        "edges": edges,
        "evidence_ids": ["OPT"],
        "allowed_company_names": [],
        "allowed_logo_names": [],
    }


async def generate_industry_chain_image(
    *,
    subject: str,
    title: str,
    option: dict[str, Any],
    artifact_dir: Path | None,
    chart_id: str,
    segments: list[dict[str, Any]] | None = None,
    settings: ImageGenSettings | None = None,
    prompt_model: str = "deepseek-v4-flash",
) -> GeneratedImage | None:
    """Agent3 产业链生图入口：编译合格提示词后调用生图模型（全链路仅成功 1 次）。"""
    cfg = settings or ImageGenSettings.from_env()
    graph = build_verified_graph_for_report(
        subject=subject, title=title, segments=segments, option=option,
    )
    template = select_chain_template_from_text(
        metric_name=title,
        industry_topic=subject,
        core_product_name=graph.get("core_product_name"),
        chain_template_hint=graph.get("template_id"),
    )
    graph["template_id"] = template

    try:
        prompt, used_prompt_model = await _compile_pure_prompt(
            graph=graph, template=template, cfg=cfg, prompt_model=prompt_model,
        )
    except Exception as e:
        logger.warning(f"产业链生图提示词构建失败（Agent3）: {e}")
        return None

    if not cfg.api_key:
        logger.warning("IMAGE_API_KEY 未配置，跳过产业链 AI 生图；提示词已就绪")
        return None
    if not _try_consume_budget():
        logger.info("产业链生图预算已耗尽（仅允许成功一次），跳过本次生图")
        return None

    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }
    if cfg.extra_body:
        body: dict[str, Any] = dict(cfg.extra_body)
        body["model"] = cfg.model
        body["prompt"] = prompt
    else:
        body = {
            "model": cfg.model,
            "prompt": prompt,
            "sequential_image_generation": "auto",
            "sequential_image_generation_options": {"max_count": 1},
            "size": cfg.size,
            "watermark": False,
        }

    try:
        async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
            submit = await client.post(
                f"{cfg.base_url}/tasks/generations", headers=headers, json=body,
            )
            submit.raise_for_status()
            request_id = _extract_request_id(submit.json())
            image_url = await _poll_until_image(
                client, headers, cfg.base_url, request_id, cfg.timeout_seconds,
            )
            img_res = await client.get(image_url)
            img_res.raise_for_status()
            body_bytes = img_res.content
    except Exception as e:
        _refund_budget()
        logger.warning(f"产业链生图调用失败（Agent3），保留 SVG 回退: {e}")
        return None

    if not body_bytes or len(body_bytes) < 32:
        _refund_budget()
        logger.warning("产业链生图未返回有效图像数据，保留 SVG 回退")
        return None

    mime = _sniff_mime(body_bytes)
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(mime, "png")
    image_uri = f"images/{chart_id}_chain.{ext}"
    if artifact_dir:
        out_dir = artifact_dir / "images"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{chart_id}_chain.{ext}"
        out_path.write_bytes(body_bytes)
        image_path = str(out_path.resolve())
        image_uri = str(out_path.resolve())
    else:
        image_path = image_uri

    # 同时落盘提示词，便于审计
    if artifact_dir:
        prompt_path = artifact_dir / "images" / f"{chart_id}_chain.prompt.txt"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")

    logger.info(f"产业链生图成功（Agent3）: {image_uri} ({len(body_bytes):,} bytes, {mime})")
    return GeneratedImage(
        image_path=image_path,
        image_uri=image_uri,
        image_mime_type=mime,
        generation_prompt=prompt,
        generation_prompt_model=used_prompt_model,
        generation_image_model=cfg.model,
        chain_template=template,
        chain_graph=graph,
    )


def build_industry_chain_prompt_only(
    *,
    subject: str,
    title: str,
    option: dict[str, Any] | None = None,
    segments: list[dict[str, Any]] | None = None,
) -> str:
    """只产合格生图提示词（不调用生图模型），供调试/人机审核。"""
    graph = build_verified_graph_for_report(
        subject=subject, title=title, segments=segments, option=option,
    )
    template = select_chain_template_from_text(
        metric_name=title,
        industry_topic=subject,
        core_product_name=graph.get("core_product_name"),
        chain_template_hint=graph.get("template_id"),
    )
    prompt = "\n".join(
        [
            build_chain_image_prompt_body(graph, template),
            build_connection_section(graph),
        ]
    )
    finalized, _ = finalize_chain_prompt(prompt, graph)
    assert_pure_image_prompt(finalized)
    return finalized
