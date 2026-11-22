"""Keep adjacent references readable in chapter drafts and rendered reports."""

import re

_FIGURE = r"\[CHART-[\w-]+\]|(?:图\s*)?\d+"
_LEAD = rf"如图\s*(?:{_FIGURE})(?:\s*、\s*(?:{_FIGURE}))*\s*所示[，,]\s*"
_FIGURE_RE = re.compile(_FIGURE, re.IGNORECASE)
_LEADS_RE = re.compile(rf"(?:{_LEAD})+", re.IGNORECASE)


def normalize_figure_leads(text: str, removed_chart_id: str | None = None) -> str:
    """Merge consecutive figure leads without discarding distinct chart IDs."""
    def render(match: re.Match[str]) -> str:
        figures = []
        for token in _FIGURE_RE.findall(match[0]):
            if token.startswith("["):
                if token.casefold() == f"[{removed_chart_id}]".casefold():
                    continue
            else:
                token = re.sub(r"^图\s*", "", token)
            if token not in figures:
                figures.append(token)
        if not figures:
            return ""
        parts = [token if i == 0 or token.startswith("[") else f"图 {token}"
                 for i, token in enumerate(figures)]
        return f"如图 {'、'.join(parts)} 所示，"

    return _LEADS_RE.sub(render, text)
