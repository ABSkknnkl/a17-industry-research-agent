"""Discover and route chart-methodology skills bundled with this project."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from chart_generator.models import ChartGenerationRequest


@dataclass(frozen=True)
class ChartSkill:
    name: str
    description: str
    instructions: str
    domains: tuple[str, ...]
    keywords: tuple[str, ...]
    source: str
    adaptation: str
    always: bool = False
    requires_signal: bool = False
    path: Path | None = None


class ChartSkillHub:
    def __init__(self, skill_root: Path | None = None) -> None:
        self.skill_root = skill_root or Path(__file__).resolve().parent / "skills"
        self.catalog = self._discover()

    @staticmethod
    def _frontmatter(text: str, key: str) -> str:
        match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", text)
        return match.group(1).strip().strip("\"'") if match else ""

    def _discover(self) -> dict[str, ChartSkill]:
        catalog: dict[str, ChartSkill] = {}
        for skill_file in sorted(self.skill_root.glob("*/SKILL.md")):
            meta_file = skill_file.parent / "_meta.json"
            if not meta_file.exists():
                continue
            text = skill_file.read_text(encoding="utf-8")
            metadata = json.loads(meta_file.read_text(encoding="utf-8"))
            name = self._frontmatter(text, "name")
            description = self._frontmatter(text, "description")
            if not name or name != skill_file.parent.name or not description:
                continue
            catalog[name] = ChartSkill(
                name=name, description=description,
                instructions=re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.S).strip(),
                domains=tuple(metadata.get("domains", [])), keywords=tuple(metadata.get("keywords", [])),
                source=str(metadata.get("source", "")), adaptation=str(metadata.get("adaptation", "")),
                always=bool(metadata.get("always", False)), requires_signal=bool(metadata.get("requires_signal", False)),
                path=skill_file,
            )
        return catalog

    def select(self, request: ChartGenerationRequest) -> list[ChartSkill]:
        context = json.dumps(request.report.model_dump(mode="json"), ensure_ascii=False, default=str).casefold()
        domains = {item.domain for item in request.report.evidence_index.values()}
        selected: list[ChartSkill] = []
        for skill in self.catalog.values():
            signal = bool(domains.intersection(skill.domains)) or any(word.casefold() in context for word in skill.keywords)
            if skill.always or signal or not skill.requires_signal:
                selected.append(skill)
        return sorted(selected, key=lambda item: (not item.always, item.name))

    def get(self, name: str) -> ChartSkill | None:
        return self.catalog.get(name)

    def describe(self) -> list[dict[str, object]]:
        return [{"name": s.name, "description": s.description, "domains": list(s.domains), "keywords": list(s.keywords), "source": s.source, "adaptation": s.adaptation, "always": s.always, "path": str(s.path)} for s in self.catalog.values()]

    def catalog_summary(self) -> str:
        lines = []
        for s in self.catalog.values():
            lines.append(f"- {s.name}: {s.description}")
        return "\n".join(lines)

    def get_tool_spec(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "invoke_skill",
                    "description": (
                        "从技能库中调用专业图表技能以加载其规范与规则。可用技能:\n"
                        + self.catalog_summary()
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {
                                "type": "string",
                                "enum": list(self.catalog.keys()),
                                "description": "要调用的图表技能名称",
                            },
                            "reason": {
                                "type": "string",
                                "description": "结合当前数据特征说明调用该技能的具体理由与应用场景",
                            },
                        },
                        "required": ["skill_name", "reason"],
                    },
                },
            }
        ]

