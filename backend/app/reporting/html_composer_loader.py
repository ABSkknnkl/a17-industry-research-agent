"""Load the canonical HTML composition catalog from the project skill.

The JSON catalog is the single source of truth for layout identifiers and
screen-safety thresholds.  The backend deliberately does not keep a copied
catalog: if the skill is unavailable, HTML still renders in a conservative
single-column mode and readiness exposes the degraded state.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CATALOG = (
    _PROJECT_ROOT / "skills" / "report-html-composer" / "references" / "layout-catalog.json"
)
_DEFAULT_DESIGN_BRIEF = (
    _PROJECT_ROOT / "skills" / "report-html-composer" / "references" / "design-brief.json"
)

ENV_CATALOG_PATH = "REPORT_HTML_COMPOSER_CATALOG"
ISSUE_CATALOG_MISSING = "report_html_composer_missing"
ISSUE_CATALOG_UNUSABLE = "report_html_composer_unusable"


@dataclass(frozen=True, slots=True)
class HtmlComposerCatalog:
    schema_version: str
    layouts: Mapping[str, Mapping[str, Any]]
    thresholds: Mapping[str, int]
    report_archetypes: Mapping[str, str]
    evidence_center: Mapping[str, Any]
    design_brief: Mapping[str, Any]
    run_exempt_layouts: frozenset[str]
    semantic_only_layouts: frozenset[str]
    fingerprint: str
    source: str
    path: str | None
    issue_code: str | None

    @property
    def is_canonical(self) -> bool:
        return self.source == "skill"

    def threshold(self, name: str, fallback: int) -> int:
        value = self.thresholds.get(name)
        return value if isinstance(value, int) and value > 0 else fallback


def resolve_catalog_path() -> Path | None:
    override = os.environ.get(ENV_CATALOG_PATH)
    candidate = Path(override).expanduser().resolve() if override else _DEFAULT_CATALOG
    return candidate if candidate.is_file() else None


def _fallback(issue_code: str, path: Path | None) -> HtmlComposerCatalog:
    logger.error(
        "HTML composition catalog unavailable (%s); using safe single-column mode. path=%s",
        issue_code,
        path,
    )
    return HtmlComposerCatalog(
        schema_version="degraded",
        layouts={},
        thresholds={},
        report_archetypes={},
        evidence_center={},
        design_brief={},
        run_exempt_layouts=frozenset(),
        semantic_only_layouts=frozenset(),
        fingerprint="",
        source="fallback",
        path=str(path) if path else None,
        issue_code=issue_code,
    )


def _validated_mapping(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return {str(key): item for key, item in value.items()}


def _build() -> HtmlComposerCatalog:
    path = resolve_catalog_path()
    if path is None:
        return _fallback(ISSUE_CATALOG_MISSING, None)
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("catalog root must be an object")
        if payload.get("schema_version") != "1.0":
            raise ValueError("unsupported catalog schema_version")
        layouts = _validated_mapping(payload.get("layouts"), field="layouts")
        normalized_layouts = {
            key: _validated_mapping(value, field=f"layouts.{key}")
            for key, value in layouts.items()
        }
        for key, value in normalized_layouts.items():
            if not isinstance(value.get("semantic_only", False), bool):
                raise ValueError(f"layouts.{key}.semantic_only must be boolean")
        thresholds_raw = _validated_mapping(payload.get("thresholds"), field="thresholds")
        run_exempt_raw = payload.get("run_exempt_layouts", [])
        if not isinstance(run_exempt_raw, list) or not all(
            isinstance(value, str) for value in run_exempt_raw
        ):
            raise ValueError("run_exempt_layouts must be an array of layout ids")
        if len(layouts) < 5:
            raise ValueError("catalog must define at least five layouts")
        thresholds: dict[str, int] = {}
        for key, value in thresholds_raw.items():
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"threshold {key} must be a positive integer")
            thresholds[key] = value
        design_brief_path = _DEFAULT_DESIGN_BRIEF
        design_brief = _validated_mapping(
            json.loads(design_brief_path.read_text(encoding="utf-8")),
            field="design_brief",
        )
        combined_fingerprint = hashlib.sha256(raw + design_brief_path.read_bytes()).hexdigest()
        evidence_center = _validated_mapping(
            payload.get("evidence_center"), field="evidence_center"
        )
        required_fields = evidence_center.get("required_fields")
        if not isinstance(required_fields, list) or not all(
            isinstance(value, str) and value for value in required_fields
        ):
            raise ValueError("evidence_center.required_fields must be an array of strings")
        required_source_contract = {
            "material",
            "publisher",
            "metric",
            "scope",
            "available_date",
            "reporting_period",
            "locator",
            "usage",
            "retrieval_method",
            "source_level",
        }
        if not required_source_contract.issubset(required_fields):
            missing = sorted(required_source_contract - set(required_fields))
            raise ValueError(f"evidence_center.required_fields missing: {missing}")
        return HtmlComposerCatalog(
            schema_version="1.0",
            layouts=normalized_layouts,
            thresholds=thresholds,
            report_archetypes={
                key: str(value)
                for key, value in _validated_mapping(
                    payload.get("report_archetypes"), field="report_archetypes"
                ).items()
            },
            evidence_center=evidence_center,
            design_brief=design_brief,
            run_exempt_layouts=frozenset(run_exempt_raw),
            semantic_only_layouts=frozenset(
                key for key, value in normalized_layouts.items() if value.get("semantic_only")
            ),
            fingerprint=combined_fingerprint,
            source="skill",
            path=str(path),
            issue_code=None,
        )
    except Exception:  # noqa: BLE001 - fail open by contract, but report it
        logger.exception("failed to load HTML composition catalog from %s", path)
        return _fallback(ISSUE_CATALOG_UNUSABLE, path)


@lru_cache(maxsize=1)
def get_html_composer_catalog() -> HtmlComposerCatalog:
    return _build()


def reset_html_composer_catalog_cache() -> None:
    get_html_composer_catalog.cache_clear()


def html_composer_issue_codes() -> list[str]:
    catalog = get_html_composer_catalog()
    return [catalog.issue_code] if catalog.issue_code else []


def html_composer_status() -> dict[str, Any]:
    catalog = get_html_composer_catalog()
    return {
        "source": catalog.source,
        "path": catalog.path,
        "schema_version": catalog.schema_version,
        "fingerprint": catalog.fingerprint,
        "canonical": catalog.is_canonical,
        "layout_count": len(catalog.layouts),
        "issue": catalog.issue_code,
    }
