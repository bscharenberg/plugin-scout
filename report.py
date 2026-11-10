"""Plain-text formatting for chat. Works the same in the CLI, Telegram or Discord."""

from __future__ import annotations

from typing import Any

try:
    from . import usage
except ImportError:  # loaded as a plain module (tests)
    import usage

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


HEADS_UP = ("settings", "update", "known_issue")
CLASHES = ("conflict", "likely")


def _pick_lines(p: dict[str, Any]) -> list[str]:
    tier = f" [{p['tier']}]" if p.get("tier") in ("official", "verified") else ""
    conf = f" ({p['confidence']})" if p.get("confidence") else ""
    lines = [f"{p['title']}{tier}{conf}"]
    if p.get("why"):
        lines.append(f"  {p['why']}")
    lines.append(f"  Why: {p['evidence']}")
    if p.get("heads_up"):
        lines.append(f"  Heads up: {p['heads_up']}")
    lines.append(f"  Install: {p['install']}   Not for you: /scout dismiss {p['name']}")
    return lines


def _finding_lines(f: dict[str, Any], evidence: int = 2) -> list[str]:
    return [f"[{_LABEL[f['kind']]}] {f['title']}"] + [f"  - {e}" for e in f["evidence"][:evidence]]


def overview_text(picks: list[dict[str, Any]], profile: dict[str, Any],
                  findings: list[dict[str, Any]], plugin_count: int) -> str:
    """The default /scout view: what fits you first, then heads-ups, then clashes."""
    lines = ["Plugin Scout"]
    for f in (f for f in findings if f["kind"] == "pulled"):  # safety first, always
        lines += [""] + _finding_lines(f)
    lines += ["", "For you:"]
    if _no_signal(profile):
        lines.append("  Not enough to go on yet. Use Hermes for a few days, or tell me what you use: "
                     "/scout interests spotify, notion, travel")
    elif not picks:
        lines.append("  Nothing in the catalog stands out for what you do yet.")
    for p in picks:
        lines += ["  " + line for line in _pick_lines(p)]
    heads = [f for f in findings if f["kind"] in HEADS_UP]
    clashes = [f for f in findings if f["kind"] in CLASHES]
    if heads:
        lines += ["", "Heads-ups on your plugins:"]
        for f in heads[:4]:
            lines += ["  " + line for line in _finding_lines(f)]
    if clashes:
        lines += ["", "Plugins that may clash:"]
        for f in clashes[:3]:
            lines += ["  " + line for line in _finding_lines(f, evidence=3)]
    if not heads and not clashes:
        lines += ["", "No other plugins enabled yet, so nothing to check." if plugin_count == 0 else
                  f"Your {plugin_count} enabled plugin{'' if plugin_count == 1 else 's'}: all clear."]
    if picks and (profile.get("sessions") or 0) < THIN_HISTORY:
        lines += ["", COLD_START_TIP]
    lines += ["", "More: /scout profile (what I know about you), /scout check, /scout week, /scout help"]
    return "\n".join(lines)


THIN_HISTORY = 5
LABELS = usage.LABELS
COLD_START_TIP = ("Tip: picks sharpen as you use Hermes. To help now, tell me what you use: "
                  "/scout interests spotify, notion, travel")


def _sources(profile: dict[str, Any]) -> str:
    """Plain words for where the picks came from."""
    topics = profile.get("topics") or {}
    parts = []
    if profile.get("sessions"):
        n = profile["sessions"]
        parts.append(f"{n} conversation{'' if n == 1 else 's'} in the last {profile.get('window_days', 30)} days")
    if any(t.get("memory") for t in topics.values()):
        parts.append("your Hermes memory")
    if any(t.get("skills") for t in topics.values()):
        parts.append("your skills")
    if any(t.get("interests") for t in topics.values()):
        parts.append("what you told me")
    if len(parts) > 1:
        return ", ".join(parts[:-1]) + " and " + parts[-1]
    return parts[0] if parts else "nothing yet"


def _no_signal(profile: dict[str, Any]) -> bool:
    return not profile.get("topics")


def picks_text(picks: list[dict[str, Any]], profile: dict[str, Any]) -> str:
    if _no_signal(profile):
        return ("Plugin Scout: not enough to go on yet. Use Hermes for a few days, or tell me "
                "what you use: /scout interests spotify, notion, travel")
    thin = (profile.get("sessions") or 0) < THIN_HISTORY
    if not picks:
        return (f"Plugin Scout: read {_sources(profile)}. No plugin stands out for what you do yet."
                + ("\n" + COLD_START_TIP if thin else ""))
    lines = [f"Plugin Scout: {len(picks)} pick{'' if len(picks) == 1 else 's'} from {_sources(profile)}."]
    for p in picks:
        lines += [""] + _pick_lines(p)
    if thin:
        lines += ["", COLD_START_TIP]
    return "\n".join(lines)


def profile_text(profile: dict[str, Any], limit: int = 8) -> str:
    """What Scout knows about you and where each piece came from. Counts and names only."""
    topics = profile.get("topics") or {}
    lines = ["What Plugin Scout knows about how you use Hermes",
             "(counted on this computer from your own data; your messages are never stored or sent)", ""]
    sessions = profile.get("sessions") or 0
    if sessions:
        src = ", ".join(f"{k} {v}" for k, v in sorted((profile.get("sources") or {}).items(), key=lambda kv: -kv[1]))
        runs = profile.get("scheduled_runs") or 0
        lines.append(f"History: {sessions} conversation{'' if sessions == 1 else 's'} in the last "
                     f"{profile.get('window_days', 30)} days"
                     + (f", plus {runs} scheduled-task run{'' if runs == 1 else 's'}" if runs else "")
                     + (f" ({src})" if src else ""))
    else:
        lines.append("History: none yet in the last 30 days")
    tools = profile.get("tools") or {}
    if tools:
        top = sorted(tools.items(), key=lambda kv: -kv[1])[:4]
        lines.append("Tools Hermes used for you: " + ", ".join(f"{t} {n}x" for t, n in top))
    if not topics:
        lines += ["", "Topics: nothing yet. Tell me what you use: /scout interests spotify, notion, travel"]
        return "\n".join(lines)

    lines += ["", "Topics, strongest first:"]
    total = sessions
    for topic, st in sorted(topics.items(), key=lambda kv: -usage._weight(kv[1]))[:limit]:
        why = []
        if st.get("sessions"):
            why.append(f"came up in {st['sessions']} of {total} conversation{'' if total == 1 else 's'}")
        if st.get("tool_calls"):
            why.append(f"{st['tool_calls']} tool use{'' if st['tool_calls'] == 1 else 's'}")
        if st.get("scheduled"):
            why.append("in a scheduled task")
        if st.get("memory"):
            why.append("in your memory")
        if st.get("skills"):
            why.append("skill " + ", ".join(st["skills"][:2]))
        if st.get("interests"):
            why.append("you told me")
        lines.append(f"  {LABELS.get(topic, topic)} ({usage.confidence(st)}): " + "; ".join(why))
    lines += ["", "Change it: /scout interests <words> to add, /scout interests clear to reset, "
                  "/scout dismiss <plugin> to skip a pick."]
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

    def add(f):
        lines.append(f"[{_LABEL[f['kind']]}] {f['title']}")
        if f["evidence"]:
            lines.append(f"  - {f['evidence'][0]}")

    # Order: anything pulled for safety, then what is new for you, then heads-ups, then clashes.
    for f in [f for f in to_act if f["kind"] == "pulled"]:
        add(f)
    for p in relevant:
        lines.append(f"[NEW FOR YOU] {p['title']}")
        lines.append(f"  - {p['evidence']}")
        lines.append(f"  - Install: {p['install']}   Not for you: /scout dismiss {p['name']}")
    rest_kinds = [f for f in to_act if f["kind"] in HEADS_UP] + [f for f in to_act if f["kind"] in CLASHES]
    for f in rest_kinds[:5]:
        add(f)
    lines.append(rest)
    return "\n".join(lines)


def welcome_text(findings: list[dict[str, Any]], plugin_count: int, profile: dict[str, Any],
                 picks: list[dict[str, Any]]) -> str:
    """First run: value in the first minute, then one question. No waiting a week to be useful."""
    lines = ["Welcome to Plugin Scout. Here is what I can tell you right now:", ""]
    serious = [f for f in findings if f["kind"] in ("pulled",) + HEADS_UP + CLASHES]
    lines.append("1. Your setup")
    if serious:
        for f in serious[:3]:
            lines.append(f"   [{_LABEL[f['kind']]}] {f['title']}")
        lines.append("   Details: /scout check")
    elif plugin_count:
        lines.append(f"   Your {plugin_count} enabled plugin{'' if plugin_count == 1 else 's'}: all clear.")
    else:
        lines.append("   No other plugins enabled yet, so nothing can clash.")
    lines += ["", "2. What I already know about you"]
    topics = profile.get("topics") or {}
    if topics:
        lines.append(f"   From {_sources(profile)}:")
        for topic, st in sorted(topics.items(), key=lambda kv: -usage._weight(kv[1]))[:3]:
            lines.append(f"   - {LABELS.get(topic, topic)} ({usage.confidence(st)})")
        lines.append("   Full picture: /scout profile")
    else:
        lines.append("   Nothing yet. That is fine; the question below fixes it.")
    lines += ["", "3. Picks so far"]
    if picks:
        for p in picks:
            conf = f" ({p['confidence']})" if p.get("confidence") else ""
            lines.append(f"   - {p['title']}{conf}: {p['install']}")
            if p.get("heads_up"):
                lines.append(f"     Heads up: {p['heads_up']}")
    else:
        lines.append("   None yet.")
    lines += ["", "One question to sharpen this: what do you want Hermes to handle for you?",
              "Reply with numbers, e.g. /scout interests 1, 6"]
    for i, (job, _) in enumerate(usage.JOBS, 1):
        lines.append(f"   {i}. {job}")
    lines += ["", "I get sharper as you use Hermes. Change anything with /scout interests or /scout profile."]
    return "\n".join(lines)
