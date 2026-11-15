"""Discover and route writing skills bundled with this project."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class WritingSkill:
    name: str
    description: str
    instructions: str
    chapters: tuple[str, ...]
    source: str
    adaptation: str
    always: bool = False
    path: Path | None = None


class WritingSkillHub:
    def __init__(self, skill_root: Path | None = None) -> None:
        self.skill_root = skill_root or Path(__file__).resolve().parent / "skills"
        self.catalog = self._discover()

    @staticmethod
    def _frontmatter(text: str, key: str) -> str:
        match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", text)
        return match.group(1).strip().strip("\"'") if match else ""

    def _discover(self) -> dict[str, WritingSkill]:
        catalog: dict[str, WritingSkill] = {}
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
            catalog[name] = WritingSkill(
                name=name, description=description,
                instructions=re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.S).strip(),
                chapters=tuple(metadata.get("chapters", [])), source=str(metadata.get("source", "")),
                adaptation=str(metadata.get("adaptation", "")), always=bool(metadata.get("always", False)), path=skill_file,
            )
        return catalog

    def get(self, name: str) -> WritingSkill | None:
        return self.catalog.get(name)

    def catalog_summary(self) -> str:
        lines = []
        for s in sorted(self.catalog.values(), key=lambda x: (not x.always, x.name)):
            always_tag = "【通用基础】" if s.always else ""
            lines.append(f"- {s.name}: {always_tag}{s.description}")
        return "\n".join(lines)

    def get_tool_spec(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "invoke_skill",
                    "description": (
                        "调用章节撰写方法论技能库中的专业技能。可用技能库清单:\n"
                        + self.catalog_summary()
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {
                                "type": "string",
                                "enum": list(self.catalog.keys()),
                                "description": "要调用的写作技能名称",
                            },
                            "reason": {
                                "type": "string",
                                "description": "结合本章节核心主题与输入证据，说明调用该技能的专业理由与写作关注点",
                            },
                        },
                        "required": ["skill_name", "reason"],
                    },
                },
            }
        ]

    def select(self, chapter_id: str | None = None) -> list[WritingSkill]:
        return sorted(
            [skill for skill in self.catalog.values() if skill.always or chapter_id is None or chapter_id in skill.chapters],
            key=lambda item: (not item.always, item.name),
        )

    def describe(self) -> list[dict[str, object]]:
        return [{"name": s.name, "description": s.description, "chapters": list(s.chapters), "source": s.source, "adaptation": s.adaptation, "always": s.always, "path": str(s.path)} for s in self.catalog.values()]

