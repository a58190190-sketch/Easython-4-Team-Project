"""Extract page UI metadata without capturing typed input values."""
from __future__ import annotations
import json
import re
from html.parser import HTMLParser

class UIInventory(HTMLParser):
    """Extract visible control labels and declared interaction hints from HTML."""
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    EVENT_ATTRIBUTES = {
        "onclick", "ondblclick", "oncontextmenu", "onmouseover", "onmouseenter",
        "onpointerover", "onpointerenter", "onmousedown", "onkeydown", "onchange", "onsubmit",
    }
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.depth = 0
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: (value or "") for key, value in attrs}
        if self.skip_depth:
            if tag not in self.VOID_TAGS:
                self.skip_depth += 1
            return
        if tag in ("script", "style", "noscript"):
            self.skip_depth += 1
            return
        role = values.get("role", "")
        if self.current and tag == "br":
            self.current["text"] += " "
            return
        if self.current and tag == "img":
            alt = values.get("alt", "").strip()
            if alt:
                self.current["text"] += " " + alt
            return
        if self.current and tag == "svg":
            icon_label = values.get("aria-label") or values.get("title") or ""
            if icon_label:
                self.current["text"] += " " + icon_label
        has_declared_interaction = any(values.get(name) for name in self.EVENT_ATTRIBUTES)
        if tag in ("button", "a", "input", "select", "textarea") or role in ("button", "link", "tab", "menuitem") or has_declared_interaction:
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
                "href": values.get("href", "")[:300],
                "events": ",".join(sorted(name for name in self.EVENT_ATTRIBUTES if values.get(name)))[:160],
            }
            if tag == "input":
                if any(item[key] for key in ("aria_label", "placeholder", "title")):
                    self.items.append(item)
                return
            self.current = item
            self.depth = 1
        elif self.current and tag not in self.VOID_TAGS:
            self.depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if self.current and tag not in self.VOID_TAGS:
            self.depth -= 1
            if self.depth <= 0:
                self.current["text"] = re.sub(r"\s+", " ", self.current["text"]).strip()[:100]
                if any(self.current[key] for key in ("text", "aria_label", "placeholder", "title", "href", "events")):
                    self.items.append(self.current)
                self.current = None

    def handle_data(self, data: str) -> None:
        if self.current and not self.skip_depth:
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
