"""Extract page UI metadata without capturing typed input values."""
from __future__ import annotations
import json
import re
from html.parser import HTMLParser

class UIInventory(HTMLParser):
    """Extract control labels from full HTML while skipping data list rows."""
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.depth = 0
        self.data_row_depth = 0
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: (value or "") for key, value in attrs}
        if tag in ("script", "style", "noscript", "svg"):
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        role = values.get("role", "")
        if tag in ("li", "tr"):
            self.data_row_depth += 1
            return
        if self.data_row_depth:
            return
        if tag in ("script", "style", "noscript", "svg"):
            return
        if tag in ("button", "a", "input", "select", "textarea") or role in ("button", "link", "tab", "menuitem"):
            if values.get("type") == "password":
                return
            item = {
                "tag": tag,
                "type": values.get("type", ""),
                "text": "",
                "aria_label": values.get("aria-label", "")[:100],
                "placeholder": values.get("placeholder", "")[:100],
                "title": values.get("title", "")[:100],
                "role": role,
            }
            if tag == "input":
                if any(item[key] for key in ("aria_label", "placeholder", "title")):
                    self.items.append(item)
                return
            self.current = item
            self.depth = 1
        elif self.current:
            self.depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if tag in ("li", "tr"):
            self.data_row_depth = max(0, self.data_row_depth - 1)
            return
        if self.data_row_depth:
            return
        if self.current:
            self.depth -= 1
            if self.depth <= 0:
                self.current["text"] = re.sub(r"\s+", " ", self.current["text"]).strip()[:100]
                if any(self.current.values()):
                    self.items.append(self.current)
                self.current = None

    def handle_data(self, data: str) -> None:
        if self.current and not self.data_row_depth and not self.skip_depth:
            self.current["text"] += data[:250]

def inventory(html: str) -> list[dict[str, str]]:
    parser = UIInventory()
    try:
        parser.feed(html)
    except Exception:
        pass
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in parser.items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            unique.append(item)
            seen.add(key)
        if len(unique) >= 250:
            break
    return unique
