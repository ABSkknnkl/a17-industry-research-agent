"""调用智能体3的生图模型（shengsuanyun router / gpt-image-2）生成 P08 信息图。

协议与 agents_core/chart-generator/chart_generator/image_gen.py 完全一致：
POST {base}/tasks/generations -> 202 {"code":"success","data":{"request_id":...}}
GET  {base}/tasks/generations/{request_id} -> 轮询直到 COMPLETED
"""
import json
import sys
import time
from pathlib import Path

import httpx

PROJECT = Path("/Users/Zhuanz1/Downloads/行业研究智能体-全链路系统 4")
PROMPT_FILE = PROJECT / "output/prompts/P08_核心优势_三份并行.txt"
OUT_FILE = PROJECT / "output/generated/P08_核心优势_三份并行.png"

# ── 读取 .env（不打印密钥）──
env = {}
for line in (PROJECT / ".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip()

API_KEY = env["IMAGE_API_KEY"]
BASE = env["IMAGE_BASE_URL"].rstrip("/")
MODEL = env.get("IMAGE_MODEL", "openai/gpt-image-2")
TIMEOUT = float(env.get("IMAGE_TIMEOUT_SECONDS", "600"))

prompt = PROMPT_FILE.read_text(encoding="utf-8")
print(f"prompt chars={len(prompt)} model={MODEL} base={BASE}", flush=True)

headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
body = {
    "model": MODEL,
    "prompt": prompt,
    "background": "auto",
    "moderation": "auto",
    "n": 1,
    "quality": "high",
    "size": "1536x1024",
}

with httpx.Client(timeout=60) as client:
    res = client.post(f"{BASE}/tasks/generations", headers=headers, json=body)
    print(f"submit status={res.status_code}", flush=True)
    res.raise_for_status()
    payload = res.json()
    data = payload.get("data") or {}
    request_id = data.get("request_id") or data.get("task_id")
    if not request_id:
        print(f"no request_id: {json.dumps(payload, ensure_ascii=False)[:500]}", flush=True)
        sys.exit(1)
    print(f"request_id={request_id}", flush=True)

    deadline = time.monotonic() + TIMEOUT
    poll_url = f"{BASE}/tasks/generations/{request_id}"
    image_url = None
    while time.monotonic() < deadline:
        pr = client.get(poll_url, headers=headers)
        pr.raise_for_status()
        pdata = (pr.json().get("data") or {})
        status = str(pdata.get("status") or "").upper()
        print(f"status={status}", flush=True)
        if status == "COMPLETED":
            results = pdata.get("data") or {}
            urls = results.get("image_urls") or []
            if urls:
                image_url = urls[0]
            else:
                items = results.get("results") or []
                if items:
                    image_url = items[0].get("image_url")
            if not image_url:
                print(f"completed without url: {json.dumps(pdata, ensure_ascii=False)[:800]}", flush=True)
                sys.exit(1)
            break
        if status in ("FAILED", "CANCELED", "CANCELLED"):
            print(f"failed: {pdata.get('fail_reason')}", flush=True)
            sys.exit(1)
        time.sleep(5)
    else:
        print("timeout", flush=True)
        sys.exit(1)

    print(f"image_url={image_url[:120]}...", flush=True)
    img = client.get(image_url, timeout=120)
    img.raise_for_status()
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_bytes(img.content)
    print(f"saved={OUT_FILE} bytes={len(img.content)}", flush=True)
