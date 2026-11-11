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
_NEEDS = re.compile(r"(needs?|requires?|built for|only (?:works )?(?:with|under)|must (?:use|be|set)|set)\W*$",
                    re.IGNORECASE)
# words just before the pair that mean "this value causes trouble"
_BREAKS = re.compile(r"(under|with|not supported (?:by|under|with)|unsupported (?:by|under|with)|breaks? (?:with|under))\W*$",
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


# Settings that protect the user. Scout never suggests a command that changes these, because a
# plugin's own warning could otherwise talk a user into weakening their security.
_SENSITIVE = re.compile(r"approv|secur|sandbox|isolat|egress|secret|redact|permission|yolo|unsafe|"
                        r"trust|allow|auth|token|password|guard|privacy|credential|firewall|"
                        r"(?:^|\.)host(?:\.|$)", re.IGNORECASE)


def is_sensitive(key: str) -> bool:
    return bool(_SENSITIVE.search(key))


def mismatches(issues: Iterable[Any], config: dict[str, Any]) -> list[dict[str, str]]:
    """Each warning that, read against your config, applies to you."""
    found = []
    for text in issue_texts(issues):
        for m in _PAIR.finditer(text):
            key, wanted = m.group(1), _norm(m.group(2))
            have_raw = lookup(config, key)
            if have_raw is None:
                continue
            have = _norm(have_raw)
            before = text[max(0, m.start() - 40):m.start()]
            after = text[m.end():m.end() + 40]
            if _NEEDS.search(before) and have != wanted:
                found.append({"key": key, "have": have, "wanted": wanted, "issue": text,
                              "why": f"It needs {key}: {wanted}. Yours is {have}."})
            elif (_BREAKS.search(before) or _BAD_AFTER.search(after)) and have == wanted:
                found.append({"key": key, "have": have, "wanted": "", "issue": text,
                              "why": f"It warns about {key}: {have}, which is your setting."})
    seen, unique = set(), []
    for f in found:
        if (f["key"], f["issue"]) not in seen:
            seen.add((f["key"], f["issue"]))
            unique.append(f)
    return unique
