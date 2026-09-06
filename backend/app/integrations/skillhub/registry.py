"""Register every P0/P1 SkillHub capability behind the shared ToolGateway."""

from typing import Any

from pydantic import BaseModel

from app.integrations.skillhub.catalog import SKILL_CATALOG
from app.integrations.skillhub.models import SkillQueryArgs
from app.integrations.skillhub.protocol import SkillHubClient
from app.runtime.models import RuntimePolicy
from app.runtime.tool_gateway import ToolDefinition, ToolGateway, ToolHandler
from app.schemas.acquisition import SkillName


def _make_handler(client: SkillHubClient, skill_name: SkillName) -> ToolHandler:
    async def handler(args: BaseModel) -> Any:
        validated = SkillQueryArgs.model_validate(args)
        return await client.execute(skill_name, validated)

    return handler


def create_skillhub_gateway(
    client: SkillHubClient,
    *,
    runtime_policy: RuntimePolicy | None = None,
    web_search_client: SkillHubClient | None = None,
) -> ToolGateway:
    tools: list[ToolDefinition] = []
    for skill_name in SKILL_CATALOG:
        if skill_name == SkillName.WEB_SEARCH:
            # L3 联网走独立供应商，绝不能发给问财网关。未配置（联网关闭或
            # 无密钥）时干脆不注册该工具——调用会得到 tool_not_found，
            # 而不是被静默路由到错误的供应商。
            if web_search_client is None:
                continue
            handler_client: SkillHubClient = web_search_client
        else:
            handler_client = client
        tools.append(
            ToolDefinition(
                name=skill_name.value,
                args_model=SkillQueryArgs,
                handler=_make_handler(handler_client, skill_name),
                preserve_structured_content=True,
            )
        )
    return ToolGateway(tools, default_policy=runtime_policy)
