"""Provider-neutral SkillHub client boundary."""

from typing import Protocol

from app.integrations.skillhub.models import SkillQueryArgs
from app.schemas.acquisition import SkillName, SkillPayload


class SkillHubClient(Protocol):
    provider_mode: str

    async def execute(self, skill_name: SkillName, args: SkillQueryArgs) -> SkillPayload:
        """Execute one logical SkillHub capability and return normalized transport data."""
