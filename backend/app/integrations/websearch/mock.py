"""离线确定性 Web 搜索替身（仅自动化测试；``provider_mode="mock"``）。

红线：测试桩绝不伪造权威财经数据。返回的命中一律带「离线测试桩」字样、域名
指向 ``example.test``（RFC 2606 保留、不可解析），``source_org`` 明写测试桩——
即使被误当成真实联网证据，也能在报告与审计里一眼看出是桩数据，不会冒充
权威口径。行结构与 ``WebSearchClient._clean_hits`` 输出完全一致，保证下游
normalizer 对两条通道走同一条代码路径。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from app.integrations.skillhub.models import SkillQueryArgs
from app.schemas.acquisition import SkillName, SkillPayload

MOCK_SOURCE_ORG = "离线测试桩（非真实联网来源）"


class MockWebSearchClient:
    provider_mode = "mock"

    def __init__(self, *, hits: int = 2, empty: bool = False) -> None:
        self._hits = max(0, hits)
        self._empty = empty

    async def execute(self, skill_name: SkillName, args: SkillQueryArgs) -> SkillPayload:
        del skill_name  # 只承接 WEB_SEARCH
        retrieved_at = datetime.now(UTC).date().isoformat()
        rows: list[dict[str, object]] = []
        if not self._empty:
            for index in range(self._hits):
                rows.append(
                    {
                        "title": f"【离线测试桩】关于「{args.query}」的定性检索命中 {index + 1}",
                        "url": f"https://stub-{index + 1}.example.test/web-search",
                        "site_name": "example.test",
                        "snippet": (
                            "离线测试桩生成的定性描述，不含任何数值、财务指标或权威口径，"
                            "仅用于验证 L3 通道接线与层级打标。"
                        ),
                        "summary": "",
                        "published_at": retrieved_at,
                        "retrieved_at": retrieved_at,
                        "source_org": MOCK_SOURCE_ORG,
                        "domain": "example.test",
                    }
                )
        raw = json.dumps(rows, ensure_ascii=False, sort_keys=True)
        return SkillPayload(
            skill_name=SkillName.WEB_SEARCH,
            query=args.query,
            rows=rows,
            total_count=len(rows),
            page=args.page,
            trace_id=f"mock-web-{hashlib.sha256(args.query.encode('utf-8')).hexdigest()[:24]}",
            raw_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            source_name="离线测试桩 Web Search",
            source_locator=rows[0]["url"] if rows else "web-search:mock-empty",
        )
