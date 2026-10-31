"""Conservative body extraction and bounded relevant windows; no fact inference."""
from html.parser import HTMLParser


class BodyParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.lines = []
        self.main_lines = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        skipped = tag in ('script', 'style', 'nav', 'header', 'footer', 'aside', 'noscript') or 'hidden' in attrs
        parent_skip = self.stack[-1][1] if self.stack else False
        main = tag in ('main', 'article') or attrs.get('role') == 'main' or (self.stack[-1][2] if self.stack else False)
        if tag not in ('br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'track', 'col'):
            self.stack.append((tag, skipped or parent_skip, main))

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if data.strip() and not (self.stack and self.stack[-1][1]):
            self.lines.append(data.strip())
            if self.stack and self.stack[-1][2]:
                self.main_lines.append(data.strip())


def html_body(raw):
    parser = BodyParser()
    parser.feed(raw)
    parser.close()
    return '\n'.join(parser.main_lines or parser.lines)


def relevant_context(text, terms, limit=24000):
    if len(text) <= limit:
        return text
    # Preserve full source separately. Extracted quotes must still match that source.
    ranges = [(0, min(2000, limit))]
    lower = text.casefold()
    for term in terms:
        if not term.strip():
            continue
        start = 0
        for _ in range(3):
            pos = lower.find(term.casefold(), start)
            if pos < 0:
                break
            ranges.append((max(0, pos-400), min(len(text), pos+1000)))
            start = pos+len(term)
    merged = []
    for lo, hi in sorted(ranges):
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
        else:
            merged.append((lo, hi))
    return '\n[原文片段间有省略]\n'.join(text[lo:hi] for lo, hi in merged)[:limit]
