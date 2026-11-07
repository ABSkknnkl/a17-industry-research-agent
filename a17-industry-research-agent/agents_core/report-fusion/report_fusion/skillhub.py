"""Discover fusion skills bundled with this project."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class FusionSkill:
    name: str
    description: str
    instructions: str
    source: str
    adaptation: str
    always: bool = True
    path: Path | None = None


class FusionSkillHub:
    def __init__(self, skill_root: Path | None = None) -> None:
        self.skill_root = skill_root or Path(__file__).resolve().parent / "skills"
        self.catalog = self._discover()

    @staticmethod
    def _frontmatter(text: str, key: str) -> str:
        match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", text)
        return match.group(1).strip().strip("\"'") if match else ""

    def _discover(self) -> dict[str, FusionSkill]:
        catalog: dict[str, FusionSkill] = {}
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
            catalog[name] = FusionSkill(
                name=name, description=description,
                instructions=re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.S).strip(),
                source=str(metadata.get("source", "")), adaptation=str(metadata.get("adaptation", "")),
                always=bool(metadata.get("always", True)), path=skill_file,
            )
        return catalog

    def get(self, name: str) -> FusionSkill | None:
        return self.catalog.get(name)

    def catalog_summary(self) -> str:
        lines = []
        for s in sorted(self.catalog.values(), key=lambda x: (not x.always, x.name)):
            lines.append(f"- {s.name}: {s.description}")
        return "\n".join(lines)

    def get_tool_spec(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "invoke_skill",
                    "description": (
                        "调用报告融合与审校技能库中的专业技能。可用技能库清单:\n"
                        + self.catalog_summary()
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {
                                "type": "string",
                                "enum": list(self.catalog.keys()),
                                "description": "要调用的融合审校技能名称",
                            },
                            "reason": {
                                "type": "string",
                                "description": "结合全篇章节特征与审校需求，说明调用该技能的专业理由与质检重点",
                            },
                        },
                        "required": ["skill_name", "reason"],
                    },
                },
            }
        ]

    def select(self) -> list[FusionSkill]:
        return sorted(self.catalog.values(), key=lambda item: item.name)

    def describe(self) -> list[dict[str, object]]:
        return [{"name": s.name, "description": s.description, "source": s.source, "adaptation": s.adaptation, "always": s.always, "path": str(s.path)} for s in self.catalog.values()]

