"""Settings check: does a plugin's own warning name a setting you have?

Catalog entries list known issues in plain words, and many name a Hermes
setting ("Needs plugins.isolation: in_process", "Set web.cache_enabled:
false"). This compares those settings with your actual config, so you hear
"this plugin will not fully work for you" only when it is true for you.
Local only: reads your config, sends nothing anywhere.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

# key: value or key = value, where key is a dotted Hermes setting
_PAIR = re.compile(r"`?\b([a-z][a-z0-9_]*(?:\.[a-z0-9_][a-z0-9_-]*)+)`?\s*(?::|=)\s*`?([A-Za-z0-9_.-]+)`?")
# words just before the pair that mean "this plugin needs that value"
_NEEDS = re.compile(r"\b(needs?|requires?|built for|only (?:works )?(?:with|under)|must (?:use|be|set)|set)\W*$",
                    re.IGNORECASE)
# words just before the pair that mean "this value causes trouble"
_BREAKS = re.compile(r"\b(under|with|not supported (?:by|under|with)|unsupported (?:by|under|with)|breaks? (?:with|under))\W*$",
                     re.IGNORECASE)
_BAD_AFTER = re.compile(r"^\W*(?:is|are)?\s*(?:unsupported|not supported|unavailable|cannot|can't|does not|doesn't|skips?|breaks?)",
                        re.IGNORECASE)


def _norm(value: Any) -> str:
    return str(value).strip().strip("`'\".,;").lower().replace("-", "_")


def issue_texts(issues: Iterable[Any]) -> list[str]:
    """Known issues come as strings, or sometimes as one-key dicts."""
    out = []
    for issue in issues or []:
        if isinstance(issue, str):
            out.append(issue)
        elif isinstance(issue, dict):
            out.extend(f"{k}: {v}" for k, v in issue.items())
    return out


def lookup(config: dict[str, Any], key: str) -> Optional[Any]:
    """Dotted lookup; None when the setting is not present."""
    node: Any = config
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return None if isinstance(node, (dict, list)) else node


# An allowlist, not a denylist: a plugin's warning could otherwise talk a user into changing a
# setting that protects them (approvals, the model endpoint, the terminal backend...). Scout only
# ever suggests a command for the plugin's own settings or for a few settings known to be harmless.
SAFE_KEYS = {"web.cache_enabled"}


def can_suggest(key: str, plugin: Optional[str] = None) -> bool:
    if key in SAFE_KEYS:
        return True
    return bool(plugin) and key.startswith(f"plugins.entries.{plugin}.")


def is_sensitive(key: str, plugin: Optional[str] = None) -> bool:
    """True for every setting Scout will not suggest changing."""
    return not can_suggest(key, plugin)


def mismatches(issues: Iterable[Any], config: dict[str, Any]) -> list[dict[str, str]]:
    """Each warning that, read against your config, applies to you."""
    found = []
    for text in issue_texts(issues):
        for m in _PAIR.finditer(text):
            key = m.group(1)
            wanted_raw = m.group(2).strip("`'\".,;")  # printed as the plugin wrote it
            wanted = _norm(wanted_raw)                # compared loosely
            have_raw = lookup(config, key)
            if have_raw is None:
                continue
            have = _norm(have_raw)
            shown_have = str(have_raw).strip()[:60]
            before = text[max(0, m.start() - 40):m.start()]
            after = text[m.end():m.end() + 40]
            if _NEEDS.search(before) and have != wanted:
                found.append({"key": key, "have": shown_have, "wanted": wanted_raw, "issue": text,
                              "why": f"It needs {key}: {wanted_raw}. Yours is {shown_have}."})
            elif (_BREAKS.search(before) or _BAD_AFTER.search(after)) and have == wanted:
                found.append({"key": key, "have": shown_have, "wanted": "", "issue": text,
                              "why": f"It warns about {key}: {shown_have}, which is your setting."})
    seen, unique = set(), []
    for f in found:
        if (f["key"], f["issue"]) not in seen:
            seen.add((f["key"], f["issue"]))
            unique.append(f)
    return unique
