"""Project-level discovery and routing for interpretation methodology skills."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from data_interpreter.models import AnalysisRequest, StructuredResearchDataset


@dataclass(frozen=True)
class AnalysisSkill:
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


class AnalysisSkillHub:
    def __init__(self, skill_root: Path | None = None) -> None:
        self.skill_root = skill_root or Path(__file__).resolve().parent / "skills"
        self.catalog = self._discover()

    def _discover(self) -> dict[str, AnalysisSkill]:
        catalog: dict[str, AnalysisSkill] = {}
        if not self.skill_root.exists():
            return catalog
        for skill_file in sorted(self.skill_root.glob("*/SKILL.md")):
            meta_file = skill_file.parent / "_meta.json"
            if not meta_file.exists():
                continue
            text = skill_file.read_text(encoding="utf-8")
            name = self._frontmatter(text, "name")
            description = self._frontmatter(text, "description")
            if not name or name != skill_file.parent.name or not description:
                continue
            metadata = json.loads(meta_file.read_text(encoding="utf-8"))
            instructions = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.S).strip()
            catalog[name] = AnalysisSkill(
                name=name,
                description=description,
                instructions=instructions,
                domains=tuple(metadata.get("domains", [])),
                keywords=tuple(metadata.get("keywords", [])),
                source=str(metadata.get("source", "")),
                adaptation=str(metadata.get("adaptation", "")),
                always=bool(metadata.get("always", False)),
                requires_signal=bool(metadata.get("requires_signal", False)),
                path=skill_file,
            )
        return catalog

    @staticmethod
    def _frontmatter(text: str, key: str) -> str:
        match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", text)
        return match.group(1).strip().strip('"\'') if match else ""

    def select(
        self,
        request: AnalysisRequest,
        dataset: StructuredResearchDataset,
        *,
        limit: int = 7,
    ) -> list[AnalysisSkill]:
        query = " ".join([request.subject, *request.focus_points]).casefold()
        populated = {
            domain for domain in (
                "industry", "companies", "financials", "macro", "industry_chain", "reports", "news"
            ) if getattr(dataset, domain)
        }
        data_context = " ".join(
            f"{record.metric} {record.value if isinstance(record.value, str) and len(record.value) <= 200 else ''}"
            for record in dataset.all_records()
        ).casefold()
        mandatory = [skill for skill in self.catalog.values() if skill.always]
        optional: list[tuple[float, AnalysisSkill]] = []
        for skill in self.catalog.values():
            if skill.always:
                continue
            keyword_hits = sum(keyword.casefold() in query for keyword in skill.keywords)
            data_hits = sum(keyword.casefold() in data_context for keyword in skill.keywords)
            domain_hits = len(populated.intersection(skill.domains))
            if skill.requires_signal and not keyword_hits and not data_hits:
                continue
            # Explicit research intent outranks incidental words found in long news/report text.
            score = keyword_hits * 10.0 + min(data_hits, 2) * 0.75 + domain_hits * 0.5
            if score > 0:
                optional.append((score, skill))
        optional.sort(key=lambda pair: (pair[0], pair[1].name), reverse=True)
        return (sorted(mandatory, key=lambda item: item.name) + [item for _, item in optional])[:limit]

    def get(self, name: str) -> AnalysisSkill | None:
        return self.catalog.get(name)

    def describe(self) -> list[dict[str, object]]:
        return [
            {
                "name": skill.name,
                "description": skill.description,
                "domains": list(skill.domains),
                "keywords": list(skill.keywords),
                "source": skill.source,
                "adaptation": skill.adaptation,
                "always": skill.always,
                "requires_signal": skill.requires_signal,
                "path": str(skill.path) if skill.path else None,
            }
            for skill in self.catalog.values()
        ]

    def catalog_summary(self) -> str:
        lines = []
        for s in sorted(self.catalog.values(), key=lambda x: (not x.always, x.name)):
            always_tag = "【必须基础技能】" if s.always else ""
            lines.append(f"- {s.name}: {always_tag}{s.description}")
        return "\n".join(lines)

    def get_tool_spec(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "invoke_skill",
                    "description": (
                        "调用投研方法论技能库中的专业技能，对数据集进行针对性解读。可用技能库清单:\n"
                        + self.catalog_summary()
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {
                                "type": "string",
                                "enum": list(self.catalog.keys()),
                                "description": "要调用的投研方法论技能名称",
                            },
                            "reason": {
                                "type": "string",
                                "description": "结合当前数据特征与研报需求，说明调用该技能的专业理由与分析重点",
                            },
                        },
                        "required": ["skill_name", "reason"],
                    },
                },
            }
        ]
