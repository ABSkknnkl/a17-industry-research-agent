#!/usr/bin/env python3
"""用已冻结的 A3 图表版母本导出带真实目录页码的 HTML 与 PDF。"""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
from pathlib import Path

from layout.composer import compose_reference_async, publish


async def main() -> None:
    result = await compose_reference_async()
    work = Path(__file__).resolve().parent
    output = work / "output" / f"reference_a3_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    publish(result, output)
    print(json.dumps({
        "artifact_dir": str(output),
        "page_count": result.page_count,
        "toc_count": len(result.toc_items),
        "outline_count": len(result.outline),
        "chain_page": result.page_map["fig8"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
