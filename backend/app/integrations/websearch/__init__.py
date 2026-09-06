"""L3 联网插件适配包（2026-09-06 方案 §4）。

复用 ``app.integrations.skillhub.protocol.SkillHubClient`` 作为客户端契约，
不另立第二套 protocol——两个实现（博查 live 与离线 mock）满足同一协议即可，
多一层抽象只会让"到底谁实现了什么"变得难查。
"""

from app.integrations.websearch.client import (
    DEFAULT_DOMAIN_ALLOWLIST,
    WebSearchClient,
)
from app.integrations.websearch.mock import MockWebSearchClient

__all__ = [
    "DEFAULT_DOMAIN_ALLOWLIST",
    "MockWebSearchClient",
    "WebSearchClient",
]
