"""用项目生图模型（生算云 router / .env 的 IMAGE_* 配置）生成一张图片。

用法::

    PYTHONPATH="<项目根>:<项目根>/agents_core/chart-generator" \
    <venv>/bin/python scripts/gen_page_image.py \
        --prompt-file output/prompts/P04_问题与痛点.txt \
        --out output/generated/P04_问题与痛点.png

设计说明（为什么这么做）：
- 直接复用 ``chart_generator.image_gen`` 的提交/轮询/取图函数，而不是在脚本里重写一套 HTTP 逻辑，
  这样脚本与「智能体3 产业链生图」走**完全相同的协议**，将来协议变更不会出现两套实现漂移。
- 这些函数虽以下划线开头（模块私有），但属同一项目内部复用，比复制粘贴更安全。
- 先 ``import backend.app.core.config`` 触发 ``_load_env_files()``：项目约定由它把 .env 注入
  ``os.environ``（只在变量不存在时写入），否则 IMAGE_API_KEY 读不到。
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
for extra in (ROOT, ROOT / "agents_core" / "chart-generator"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import backend.app.core.config  # noqa: F401  触发 .env 加载（副作用导入）
import httpx
from chart_generator.image_gen import (  # noqa: E402
    ImageGenSettings,
    _extract_request_id,
    _poll_until_image,
    _sniff_mime,
)

EXT_BY_MIME = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


async def _download_image(client: httpx.AsyncClient, image_url: str) -> bytes:
    """下载结果图，带协议回退与重试。

    为什么要回退：生图服务返回的 COS/OSS 直链是 **http**（80 端口），
    在受限网络/沙箱里 80 端口可能被拦截并返回 403；换成 https 走 443 通常即可取到，
    且签名基于路径与查询串，换协议不影响校验。

    Args:
        client: 复用的 httpx 客户端。
        image_url: 服务端返回的图片直链（http 或 https）。

    Returns:
        图片二进制内容；长度小于 32 字节视为无效。

    Raises:
        SystemExit: 所有协议与重试均失败时抛出，附带最后一次错误原因。
    """
    candidates = [image_url]
    if image_url.startswith("http://"):
        candidates.append("https://" + image_url[len("http://"):])

    last_err: Exception | None = None
    for url in candidates:
        for attempt in range(3):
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                if len(resp.content) >= 32:
                    return resp.content
                last_err = ValueError(f"返回内容过短：{len(resp.content)} bytes")
            except Exception as exc:  # noqa: BLE001  逐次重试，最后一次抛错
                last_err = exc
                await asyncio.sleep(1.5 * (attempt + 1))
    raise SystemExit(f"图片下载失败（已尝试 {len(candidates)} 种协议 × 3 次）：{last_err}")


async def generate_image(
    prompt: str,
    out_path: Path,
    size: str | None = None,
    request_id: str | None = None,
) -> Path:
    """提交一次生图任务并落盘。

    Args:
        prompt: 完整生图提示词。
        out_path: 输出文件路径（父目录会自动创建）。
        size: 覆盖 IMAGE_SIZE，None 时用 .env 配置（本项目为 auto）。
        request_id: 已有任务的 request_id。传入时**跳过提交**、直接轮询该任务并取图，
            用于「提交成功但轮询阶段报错」后的续取，避免重复提交造成二次扣费。

    Returns:
        实际写盘的图片路径（扩展名按返回的 MIME 修正）。

    Raises:
        SystemExit: 未配置 IMAGE_API_KEY 时直接退出，避免无谓的网络往返。
        httpx.HTTPStatusError: 提交或取图阶段 HTTP 失败。
    """
    cfg = ImageGenSettings.from_env()
    if not cfg.api_key:
        raise SystemExit("IMAGE_API_KEY 未配置：请在 .env 中填写后重试")

    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}

    if request_id:
        print(f"[续取] 复用已受理任务 request_id={request_id}（不重新提交、不重复扣费）", flush=True)
    else:
        if cfg.extra_body:
            body = dict(cfg.extra_body)
            body["model"] = cfg.model
            body["prompt"] = prompt
        else:
            body = {
                "model": cfg.model,
                "prompt": prompt,
                "sequential_image_generation": "auto",
                "sequential_image_generation_options": {"max_count": 1},
                "size": size or cfg.size,
                "watermark": False,
            }
        print(f"[提交] model={cfg.model} size={body.get('size')} prompt={len(prompt)} 字符", flush=True)

    async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
        if not request_id:
            resp = await client.post(f"{cfg.base_url}/tasks/generations", headers=headers, json=body)
            resp.raise_for_status()
            request_id = _extract_request_id(resp.json())
        print(f"[受理] request_id={request_id}，开始轮询…", flush=True)
        image_url = await _poll_until_image(client, headers, cfg.base_url, request_id, cfg.timeout_seconds)
        print(f"[出图] 下载 {image_url[:80]}…", flush=True)
        data = await _download_image(client, image_url)

    if len(data) < 32:
        raise SystemExit(f"返回图像数据异常（{len(data)} bytes）")

    mime = _sniff_mime(data)
    final = out_path.with_suffix("." + EXT_BY_MIME.get(mime, "png"))
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(data)
    print(f"[完成] {final}  {len(data):,} bytes  {mime}", flush=True)
    return final


def main() -> None:
    ap = argparse.ArgumentParser(description="用项目生图模型生成图片")
    ap.add_argument("--prompt-file", default=None,
                    help="提示词文本文件路径（UTF-8）；用 --request-id 续取时可不传")
    ap.add_argument("--out", required=True, help="输出图片路径（扩展名按返回 MIME 自动修正）")
    ap.add_argument("--size", default=None, help="覆盖 IMAGE_SIZE，如 1536x1024；默认用 .env 的 auto")
    ap.add_argument("--request-id", default=None,
                    help="复用已受理任务并取图（不重新提交、不重复扣费）")
    args = ap.parse_args()

    prompt = Path(args.prompt_file).read_text(encoding="utf-8").strip() if args.prompt_file else ""
    asyncio.run(generate_image(prompt, Path(args.out), args.size, args.request_id))


if __name__ == "__main__":
    main()
