"""Plain-text formatting for chat. Works the same in the CLI, Telegram or Discord."""

from __future__ import annotations

from typing import Any

_LABEL = {
    "conflict": "CONFLICT",
    "pulled": "PULLED",
    "likely": "CAUTION",
    "settings": "YOUR SETTINGS",
    "overlap": "OVERLAP",
    "update": "UPDATE",
    "known_issue": "KNOWN ISSUE",
}


def conflicts_text(findings: list[dict[str, Any]], plugin_count: int, limit: int = 8) -> str:
    serious = [f for f in findings if f["severity"] >= 2]
    head = (
        f"Plugin Scout: {plugin_count} enabled plugin(s) checked. "
        + (f"{len(serious)} to look at." if serious else "All clear, nothing conflicting.")
    )
    if not findings:
        return head
    lines = [head, ""]
    for f in findings[:limit]:
        lines.append(f"[{_LABEL[f['kind']]}] {f['title']}")
        for e in f["evidence"][:4]:
            lines.append(f"  - {e}")
    if len(findings) > limit:
        lines.append(f"...and {len(findings) - limit} more (minor).")
    return "\n".join(lines)


def picks_text(picks: list[dict[str, Any]], profile: dict[str, Any]) -> str:
    if not profile.get("sessions"):
        return ("Plugin Scout: not enough history yet. Use Hermes for a few days and ask again; "
                "picks are based on what you actually do.")
    if not picks:
        return (f"Plugin Scout: read {profile['sessions']} session(s) from the last "
                f"{profile['window_days']} days. No plugin stands out for what you do yet.")
    s = "" if profile["sessions"] == 1 else "s"
    lines = [f"Plugin Scout: {len(picks)} pick{'' if len(picks) == 1 else 's'} from "
             f"{profile['sessions']} session{s} in the last {profile['window_days']} days."]
    for p in picks:
        tier = f" [{p['tier']}]" if p.get("tier") in ("official", "verified") else ""
        lines.append(f"\n{p['title']}{tier}")
        if p.get("why"):
            lines.append(f"  {p['why']}")
        lines.append(f"  Why: {p['evidence']}")
        if p.get("heads_up"):
            lines.append(f"  Heads up: {p['heads_up']}")
        lines.append(f"  Install: {p['install']}   Not for you: /scout dismiss {p['name']}")
    return "\n".join(lines)


def whats_new_text(changes: dict[str, list], since: str, catalog_size: int, limit: int = 12) -> str:
    new, updated, removed = changes["new"], changes["updated"], changes["removed"]
    if not (new or updated or removed):
        return f"Plugin Scout: no catalog changes since {since}. {catalog_size} plugins listed."
    lines = [f"Plugin Scout: since {since}: {len(new)} new, {len(updated)} updated, {len(removed)} removed."]
    if new:
        lines.append("New: " + ", ".join(new[:limit]) + (" ..." if len(new) > limit else ""))
    for u in updated[:limit]:
        lines.append(f"Updated: {u['name']} {u['from'] or '?'} -> {u['to'] or '?'}")
    for r in removed[:limit]:
        lines.append(f"Removed: {r['name']}" + (f" ({r['reason']})" if r["reason"] else ""))
    return "\n".join(lines)


def digest_text(findings: list[dict[str, Any]], relevant: list[dict[str, Any]],
                changes: dict[str, list], since: str, catalog_size: int) -> str:
    """The weekly note: only what matters to you, then one line on the rest."""
    to_act = [f for f in findings if f["kind"] in ("conflict", "pulled", "likely", "settings", "update")]
    total = len(changes["new"]) + len(changes["updated"]) + len(changes["removed"])
    rest = (f"Catalog since {since}: {len(changes['new'])} new, {len(changes['updated'])} updated, "
            f"{len(changes['removed'])} removed ({catalog_size} plugins listed).")
    if not to_act and not relevant:
        if total:
            return f"Plugin Scout, this week: all clear. Nothing new fits how you use Hermes.\n{rest}"
        return f"Plugin Scout, this week: all clear. No catalog changes since {since}."
    lines = ["Plugin Scout, this week:"]
    for f in to_act[:5]:
        lines.append(f"[{_LABEL[f['kind']]}] {f['title']}")
        if f["evidence"]:
            lines.append(f"  - {f['evidence'][0]}")
    for p in relevant:
        lines.append(f"[NEW FOR YOU] {p['title']}")
        lines.append(f"  - {p['evidence']}")
        lines.append(f"  - Install: {p['install']}   Not for you: /scout dismiss {p['name']}")
    lines.append(rest)
    return "\n".join(lines)
