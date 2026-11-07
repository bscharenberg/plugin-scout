"""Cleaning for text that comes from outside this plugin.

Catalog entries, other plugins' manifests and model replies are written by
someone else. Everything from those sources passes through here once, at
the door, before any other code sees it:

- control characters and terminal escape codes are removed, so text cannot
  repaint or hide parts of your terminal;
- invisible and direction-changing Unicode is removed, so text cannot look
  different from what it says;
- lengths are capped, so one huge field cannot flood a report or a prompt;
- plugin names must match the catalog's own rule, so a name can never carry
  shell syntax into a suggested command.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# C0 and C1 controls (includes ESC, which starts terminal escape codes) and DEL
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")  # line breaks become spaces
# zero-width characters, word joiner, byte order mark, and bidirectional overrides
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")
_SPACES = re.compile(r"\s+")

NAME = re.compile(r"^[a-z0-9_-]{1,64}$")          # the catalog's own rule for keys
TOOL_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
SHA = re.compile(r"^[0-9a-f]{40}$")

LIMITS = {"title": 120, "description": 4000, "maintainer": 80, "category": 40, "tier": 20,
          "version": 64, "requires_hermes": 40, "repo": 300, "reason": 400}
MAX_ISSUES, ISSUE_LIMIT, MAX_LIST = 20, 600, 200


def clean(value: Any, limit: int = 500) -> str:
    """Plain, single-line, visible text no longer than `limit` characters."""
    if value is None:
        return ""
    text = _INVISIBLE.sub("", _CONTROL.sub(" ", str(value)))
    text = _SPACES.sub(" ", text).strip()
    if len(text) > limit:
        text = text[: max(0, limit - 3)].rstrip() + "..."
    return text


def name(value: Any) -> Optional[str]:
    """A catalog-style plugin name, or None if it does not follow the rule."""
    text = str(value or "").strip()
    return text if NAME.match(text) else None


def tool_names(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(v) for v in values[:MAX_LIST] if TOOL_NAME.match(str(v))]


def issues(values: Any) -> list[str]:
    """Known issues as clean strings (the catalog sometimes uses one-key dicts)."""
    out: list[str] = []
    for item in values if isinstance(values, list) else []:
        if isinstance(item, dict):
            out.extend(clean(f"{k}: {v}", ISSUE_LIMIT) for k, v in item.items())
        elif isinstance(item, str):
            out.append(clean(item, ISSUE_LIMIT))
    return [i for i in out if i][:MAX_ISSUES]


def catalog_entry(raw: Any) -> Optional[dict[str, Any]]:
    """Only the fields this plugin uses, cleaned. None when the name is not valid."""
    if not isinstance(raw, dict):
        return None
    key = name(raw.get("name"))
    if not key:
        return None
    entry: dict[str, Any] = {"name": key}
    for field, limit in LIMITS.items():
        if field in raw and field != "reason":
            entry[field] = clean(raw.get(field), limit) or None
    repo = entry.get("repo") or ""
    entry["repo"] = repo if repo.startswith("https://") else None
    sha = str(raw.get("sha") or "").strip().lower()
    entry["sha"] = sha if SHA.match(sha) else None
    entry["known_issues"] = issues(raw.get("known_issues"))
    caps = raw.get("capabilities") if isinstance(raw.get("capabilities"), dict) else {}
    entry["capabilities"] = {k: tool_names(caps.get(k))
                             for k in ("provides_tools", "provides_hooks", "provides_middleware", "requires_env")}
    return entry


def removed_entry(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    key = name(raw.get("name"))
    if not key:
        return None
    return {"name": key, "reason": clean(raw.get("reason"), LIMITS["reason"])}
