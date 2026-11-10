"""Plugin Scout: checks your Hermes plugin setup and finds plugins that fit you.

Registers agent tools, the /scout command and a weekly blueprint.
No network or disk work happens during register(); everything runs on demand.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import catalog, conflicts, installed, report, sanitize, settings, usage

logger = logging.getLogger(__name__)
PLUGIN = "plugin-scout"

CONFLICTS_SCHEMA = {
    "name": "scout_conflicts",
    "description": (
        "Check the user's enabled Hermes plugins for conflicts and overlaps: two plugins "
        "intercepting the same tool, duplicate tool names, several memory plugins, plugins "
        "pulled from the catalog, available updates and known issues. Each finding includes "
        "its evidence. Use when the user asks whether their plugins work well together. Show the user the returned text as written, without summarizing it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "ai_check": {
                "type": "boolean",
                "description": "Ask the model for a second opinion on likely conflicts (small extra cost).",
            },
        },
    },
}

WHATS_NEW_SCHEMA = {
    "name": "scout_whats_new",
    "description": (
        "What changed in the Hermes plugin catalog since the user last looked: new plugins, "
        "updated plugins and removed plugins. Set mark_seen to true after showing the user, "
        "so the next check starts from now."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mark_seen": {"type": "boolean", "description": "Start the next comparison from now."},
        },
    },
}


PICKS_SCHEMA = {
    "name": "scout_picks",
    "description": (
        "Suggest Hermes plugins that fit how the user actually uses Hermes, based on local "
        "counts of the tools they use and the topics in their own messages over the last 30 "
        "days. Each pick includes its evidence and install command. Use when the user asks "
        "which plugins they should install or what would help them. Picks come in priority "
        "order (rank 1 is the best fit); there is no numeric score, so never invent one. Each "
        "pick is labelled 'strong match' or 'early guess'. Show the user the returned text as "
        "written, without summarizing it."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "ai_rank": {
                "type": "boolean",
                "description": "Let the model choose the best few and explain why. Sends topic counts "
                               "and catalog descriptions only, never message text.",
            },
        },
    },
}

DISMISS_SCHEMA = {
    "name": "scout_dismiss",
    "description": "Stop suggesting a plugin. Use when the user says a pick is not for them.",
    "parameters": {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Catalog name of the plugin."}},
        "required": ["name"],
    },
}

WEEKLY_SCHEMA = {
    "name": "scout_weekly",
    "description": (
        "The weekly Plugin Scout note: conflicts or updates for installed plugins, and new "
        "catalog plugins that fit how the user uses Hermes. Use only for the scheduled weekly "
        "note or when the user asks what is new this week; for getting started use "
        "scout_start. Set mark_seen to true when delivering the scheduled weekly note."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mark_seen": {"type": "boolean", "description": "Start next week's comparison from now."},
        },
    },
}

PROFILE_SCHEMA = {
    "name": "scout_profile",
    "description": (
        "Show what Plugin Scout knows about how the user uses Hermes and where each signal came "
        "from: topic counts from recent sessions, topics in Hermes memory, skills they made, and "
        "interests they told Scout. Counts and names only. Use when the user asks why Scout "
        "suggested something or what it knows about them. Show the user the returned text as written, without summarizing it."
    ),
    "parameters": {"type": "object", "properties": {}},
}

START_SCHEMA = {
    "name": "scout_start",
    "description": (
        "Plugin Scout's welcome: checks the user's plugin setup, shows their likely interests "
        "and plugins from the Hermes catalog they may find useful, and ends with one question "
        "about what they want Hermes to handle. Use when the user wants to get started with "
        "Plugin Scout, asks what it does or what it can do for them, or asks for plugin "
        "recommendations for the first time. Show the user the returned text as written, "
        "without summarizing it. If they answer the question, call scout_interests with their "
        "choices."
    ),
    "parameters": {"type": "object", "properties": {}},
}

INTERESTS_SCHEMA = {
    "name": "scout_interests",
    "description": (
        "Save what the user says they use or care about, so Plugin Scout's picks fit them. Use "
        "when the user describes their interests or tools in their own words (\"I'm into "
        "security and AI news\", \"I use Notion and Spotify\") or answers the welcome question "
        "with numbers. Pass short phrases or the numbers they gave. Set clear to true when they "
        "want to start over. Afterwards, offer to show their updated picks with scout_picks."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": {"type": "string"},
                      "description": "Short interests in the user's words, or the numbers they chose, e.g. [\"security\", \"ai news\"] or [\"1\", \"10\"]."},
            "clear": {"type": "boolean", "description": "Forget the interests saved so far."},
        },
    },
}

MAX_SESSIONS = 200


def _data_dir() -> Path:
    from plugins.plugin_storage import plugin_data_dir
    return plugin_data_dir(PLUGIN)


def _plugins_dir() -> Path:
    from hermes_constants import get_hermes_home
    return get_hermes_home() / "plugins"


def _config() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config
        return load_config() or {}
    except Exception:
        return {}


def _load_catalog(force: bool = False) -> dict[str, Any]:
    return catalog.CatalogStore(_data_dir()).load(force=force)


def _installed() -> list[dict[str, Any]]:
    plugins_cfg = _config().get("plugins") or {}
    enabled = plugins_cfg.get("enabled") or [] if isinstance(plugins_cfg, dict) else []
    return installed.installed_plugins(_plugins_dir(), enabled)


def _ask_model(ctx):
    def ask(prompt: str) -> str:
        resp = ctx.llm.complete([{"role": "user", "content": prompt}])
        return str(getattr(resp, "text", resp) or "")
    return ask


def _stale_note(loaded: dict[str, Any]) -> str:
    """Say so when the catalog could not be refreshed, so old data is never passed off as current."""
    if not loaded.get("stale"):
        return ""
    when = datetime.fromtimestamp(loaded.get("fetched_at") or 0).strftime("%b %d")
    return f"\nNote: could not reach the catalog, so this uses the copy from {when}."


def run_conflicts(ctx, ai_check: bool = False) -> dict[str, Any]:
    loaded = _load_catalog()
    idx = catalog.index(loaded["catalog"])
    plugins = [p for p in _installed() if p["name"] != PLUGIN]
    cfg = _config()
    memory_cfg = cfg.get("memory") or {}
    findings = conflicts.check(
        plugins, idx, removed=loaded["catalog"]["removed"],
        active_memory_provider=memory_cfg.get("provider") if isinstance(memory_cfg, dict) else None,
        config=cfg,
    )
    if ai_check and getattr(ctx, "llm", None) is not None:
        findings = conflicts.verify_with_llm(findings, idx, _ask_model(ctx))
    enabled_count = sum(1 for p in plugins if p.get("enabled"))
    return {
        "enabled_plugins": enabled_count,
        "findings": findings,
        "catalog_stale": loaded["stale"],
        "text": report.conflicts_text(findings, enabled_count) + _stale_note(loaded),
    }


def run_whats_new(ctx, mark_seen: bool = False) -> dict[str, Any]:
    loaded = _load_catalog()
    cat = loaded["catalog"]
    baseline = ctx.state.get("baseline")
    baseline_at = ctx.state.get("baseline_at")
    if not baseline:
        # First run: nothing to compare with yet. Save today's catalog as the baseline.
        ctx.state.set("baseline", catalog.snapshot(cat))
        ctx.state.set("baseline_at", time.time())
        text = (f"Plugin Scout: baseline set with {len(cat['entries'])} catalog plugins. "
                "Changes will show from here on.")
        return {"first_run": True, "text": text}
    changes = catalog.diff(baseline, cat)
    since = datetime.fromtimestamp(baseline_at or 0).strftime("%b %d")  # user's local time
    if mark_seen:
        ctx.state.set("baseline", catalog.snapshot(cat))
        ctx.state.set("baseline_at", time.time())
    return {"changes": changes, "since": since,
            "text": report.whats_new_text(changes, since, len(cat["entries"])) + _stale_note(loaded)}


def _recent_sessions():
    """(row, messages) pairs for recent sessions, read-only. Message text stays local."""
    from hermes_state import SessionDB

    db = SessionDB(read_only=True)
    cutoff = time.time() - usage.WINDOW_DAYS * 86400
    for row in db.list_sessions_rich(limit=MAX_SESSIONS, order_by_last_active=True):
        if float(row.get("last_active") or row.get("started_at") or 0) < cutoff:
            continue
        if not row.get("message_count"):
            continue
        yield row, db.get_messages(row["id"])


MAX_MEMORY_BYTES = 64 * 1024
MAX_SKILLS = 50


def _memory_text() -> str:
    """Hermes's memory of you (USER.md, MEMORY.md), read-only. Matched locally, never sent."""
    from hermes_constants import get_hermes_home
    parts = []
    for name in ("USER.md", "MEMORY.md"):
        path = get_hermes_home() / "memories" / name
        try:
            if path.is_file() and path.stat().st_size <= MAX_MEMORY_BYTES:
                parts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(parts)


def _my_skills() -> list[dict[str, str]]:
    """Skills you made or added. The ones bundled with Hermes say nothing about you, so they are skipped."""
    from hermes_constants import get_hermes_home
    try:
        from tools.skills_tool import find_all_skills
        manifest = get_hermes_home() / "skills" / ".bundled_manifest"
        bundled = {line.split(":", 1)[0].strip() for line in
                   manifest.read_text(encoding="utf-8").splitlines() if line.strip()}
        found = find_all_skills()
    except Exception:  # no manifest means we cannot tell yours from built-in ones: use none
        return []
    mine = []
    for skill in found:
        name = str(skill.get("name") or "")
        if not name or name in bundled or name.rsplit("/", 1)[-1] in bundled:
            continue
        mine.append({"name": sanitize.clean(name, 64),
                     "description": sanitize.clean(skill.get("description"), 300)})
    return mine[:MAX_SKILLS]


def _profile(ctx) -> dict[str, Any]:
    """Everything Scout knows about how you use Hermes, as counts. Built on demand, never stored."""
    profile = usage.build_profile(_recent_sessions())
    try:
        memory = _memory_text()
    except Exception:
        memory = ""
    return usage.add_signals(profile, memory_text=memory, skills=_my_skills(),
                             interests=ctx.state.get("interests") or [])


def run_interests(ctx, raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.lower() in ("clear", "none", "reset"):
        ctx.state.set("interests", [])
        return {"interests": [], "text": "Plugin Scout: cleared what you told me."}
    if not text:
        current = ctx.state.get("interests") or []
        return {"interests": current, "text": (
            "Plugin Scout: tell me what you use or care about, separated by commas, e.g.\n"
            "/scout interests spotify, notion, travel, prompt injection"
            + (f"\nRight now: {', '.join(current)}" if current else ""))}
    items = [i for i in (sanitize.clean(x, 40).lower() for x in text.replace(";", ",").split(",")) if i]
    if len(items) == 1 and " " in items[0] and len(items[0].split()) > 3:
        items = items[0].split()
    if items and all(i.isdigit() for i in items):  # answers to the onboarding question
        items = usage.job_words(int(i) for i in items)
        if not items:
            return {"interests": ctx.state.get("interests") or [],
                    "text": f"Plugin Scout: pick numbers from 1 to {len(usage.JOBS)}, e.g. /scout interests 1, 6"}
    merged = list(dict.fromkeys((ctx.state.get("interests") or []) + items))[:usage.MAX_INTERESTS]
    ctx.state.set("interests", merged)
    return {"interests": merged,
            "text": f"Plugin Scout: noted. I'll weigh {', '.join(usage.label(w) for w in merged)} in your picks. "
                    "Try /scout picks."}


def run_profile(ctx) -> dict[str, Any]:
    profile = _profile(ctx)
    return {"profile": profile, "text": report.profile_text(profile)}


PUBLIC_PICK_FIELDS = ("name", "title", "tier", "confidence", "what", "for_you", "why", "heads_up", "install")


def _public(picks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Picks as the user and agent see them: in priority order, ranked 1, 2, 3.

    The internal ranking weight is left out on purpose. It has no fixed scale, so showing it
    would invite reading it as a score out of 100.
    """
    out = []
    for i, p in enumerate(picks, 1):
        item = {"rank": i, "interest": usage.label(p.get("topic", ""))}
        item.update({k: p[k] for k in PUBLIC_PICK_FIELDS if p.get(k)})
        out.append(item)
    return out


def run_picks(ctx, ai_rank: bool = False, limit: int = 3) -> dict[str, Any]:
    loaded = _load_catalog()
    cat = loaded["catalog"]
    profile = _profile(ctx)
    have = {p.get("catalog_name") or p["name"] for p in _installed()}
    dismissed = set(ctx.state.get("dismissed") or [])
    pulled = {r["name"] for r in cat["removed"]}
    pool = usage.candidates(profile, cat["entries"], exclude=have | dismissed | pulled | {PLUGIN})
    if ai_rank and getattr(ctx, "llm", None) is not None:
        picks = usage.rank_with_llm(profile, pool, catalog.index(cat), _ask_model(ctx), limit=limit)
    else:
        stated = {topic for topic, st in profile["topics"].items() if st.get("interests")}
        picks = usage.diversify(pool, limit, prefer=stated)
    cfg, idx = _config(), catalog.index(cat)
    for p in picks:  # a pick that would not fully work on your setup says so up front
        found = settings.mismatches((idx.get(p["name"]) or {}).get("known_issues") or [], cfg)
        if found:
            p["heads_up"] = found[0]["why"]
    return {"profile": {k: profile.get(k) for k in ("sessions", "window_days", "topics")},
            "picks": _public(picks), "text": report.picks_text(picks, profile) + _stale_note(loaded)}


def run_weekly(ctx, mark_seen: bool = False) -> dict[str, Any]:
    new = run_whats_new(ctx, mark_seen=mark_seen)
    if new.get("first_run"):
        return new
    loaded = _load_catalog()
    cat = loaded["catalog"]
    checked = run_conflicts(ctx)
    profile = _profile(ctx)
    have = {p.get("catalog_name") or p["name"] for p in _installed()}
    dismissed = set(ctx.state.get("dismissed") or [])
    relevant = usage.relevant_new(profile, new["changes"]["new"], cat["entries"],
                                  exclude=have | dismissed | {PLUGIN})
    text = report.digest_text(checked["findings"], relevant, new["changes"], new["since"],
                              len(cat["entries"])) + _stale_note(loaded)
    return {"findings": checked["findings"], "relevant_new": _public(relevant),
            "changes": new["changes"], "since": new["since"], "text": text}


def run_welcome(ctx) -> dict[str, Any]:
    """First run: setup check, what Hermes already knows, picks so far, and one question."""
    picked = run_picks(ctx)
    checked = run_conflicts(ctx)
    ctx.state.set("welcomed", True)
    text = report.welcome_text(checked["findings"], checked["enabled_plugins"], picked["profile"],
                               picked["picks"]) + _stale_note(_load_catalog())
    return {"picks": picked["picks"], "findings": checked["findings"], "text": text}


def run_overview(ctx) -> dict[str, Any]:
    """Default /scout: picks first, then heads-ups and clashes for what you have installed."""
    if not ctx.state.get("welcomed"):
        return run_welcome(ctx)
    picked = run_picks(ctx)
    checked = run_conflicts(ctx)
    profile = picked["profile"]
    loaded = _load_catalog()
    text = report.overview_text(picked["picks"], profile, checked["findings"],
                                checked["enabled_plugins"]) + _stale_note(loaded)
    return {"picks": picked["picks"], "findings": checked["findings"], "text": text}


def run_dismiss(ctx, name: str) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        return {"text": "Plugin Scout: say which plugin, e.g. /scout dismiss spotify"}
    dismissed = list(dict.fromkeys((ctx.state.get("dismissed") or []) + [name]))
    ctx.state.set("dismissed", dismissed)
    return {"dismissed": dismissed, "text": f"Plugin Scout: won't suggest {name} again."}


HELP = (
    "/scout            overview: plugins that fit you, heads-ups, and clashes\n"
    "/scout picks      plugins that fit how you use Hermes (add 'ai' for a smarter shortlist)\n"
    "/scout check      full check of your plugins: clashes, settings, updates, known issues\n"
    "/scout check ai   same, with an AI second opinion on likely clashes\n"
    "/scout start      the welcome again: setup check, what I know, one question\n"
    "/scout profile    what Scout knows about how you use Hermes, and where it came from\n"
    "/scout interests  tell Scout what you use or care about (e.g. spotify, notion, security)\n"
    "/scout dismiss X  stop suggesting plugin X\n"
    "/scout week       this week's note: only what matters to you\n"
    "/scout new        what changed in the catalog since you last looked\n"
    "/scout seen       mark catalog changes as seen\n"
    "/scout refresh    re-download the catalog now"
)


def _safe(fn):
    """Tools and commands always answer; failures become a readable message."""
    try:
        return fn()
    except catalog.CatalogError as exc:
        return {"error": str(exc), "text": f"Plugin Scout: {exc}. Try again later."}
    except Exception as exc:  # never crash the user's session
        logger.exception("plugin-scout failed")  # full details stay in the Hermes log
        return {"error": type(exc).__name__,
                "text": "Plugin Scout hit an error and stopped. Details are in the Hermes log."}


def register(ctx):
    def tool_conflicts(args, **kwargs):
        args = args or {}
        return json.dumps(_safe(lambda: run_conflicts(ctx, bool(args.get("ai_check")))), default=str)

    def tool_whats_new(args, **kwargs):
        args = args or {}
        return json.dumps(_safe(lambda: run_whats_new(ctx, bool(args.get("mark_seen")))), default=str)

    def tool_picks(args, **kwargs):
        args = args or {}
        result = _safe(lambda: run_picks(ctx, bool(args.get("ai_rank"))))
        result.pop("profile", None)  # picks and their evidence are enough; raw profile stays local
        return json.dumps(result, default=str)

    def tool_weekly(args, **kwargs):
        args = args or {}
        return json.dumps(_safe(lambda: run_weekly(ctx, bool(args.get("mark_seen")))), default=str)

    def tool_profile(args, **kwargs):
        result = _safe(lambda: run_profile(ctx))
        result.pop("profile", None)  # the agent gets the summary text, not raw structures
        return json.dumps(result, default=str)

    def tool_start(args, **kwargs):
        result = _safe(lambda: run_welcome(ctx))
        return json.dumps({"text": result["text"]}, default=str)

    def tool_interests(args, **kwargs):
        args = args or {}
        if args.get("clear"):
            return json.dumps(_safe(lambda: run_interests(ctx, "clear")), default=str)
        items = args.get("items") or []
        if isinstance(items, str):
            items = [items]
        raw = ", ".join(str(i) for i in items if str(i).strip())
        return json.dumps(_safe(lambda: run_interests(ctx, raw)), default=str)

    def tool_dismiss(args, **kwargs):
        return json.dumps(_safe(lambda: run_dismiss(ctx, (args or {}).get("name", ""))), default=str)

    def command(raw_args, **kwargs):
        arg = (raw_args or "").strip().lower()
        if arg in ("help", "?"):
            return HELP
        if arg.startswith("picks"):
            return _safe(lambda: run_picks(ctx, ai_rank=arg.endswith(" ai")))["text"]
        if arg.startswith("interests") or arg.startswith("interest "):
            return _safe(lambda: run_interests(ctx, (raw_args or "").strip()[len(arg.split()[0]):]))["text"]
        if arg in ("start", "welcome", "setup"):
            return _safe(lambda: run_welcome(ctx))["text"]
        if arg in ("profile", "me", "why"):
            return _safe(lambda: run_profile(ctx))["text"]
        if arg.startswith("dismiss"):
            return _safe(lambda: run_dismiss(ctx, arg[len("dismiss"):]))["text"]
        if arg == "refresh":
            result = _safe(lambda: _load_catalog(force=True))
            if "error" in result:
                return result["text"]
            return f"Plugin Scout: catalog refreshed, {len(result['catalog']['entries'])} plugins."
        if arg in ("week", "weekly"):
            return _safe(lambda: run_weekly(ctx))["text"]
        if arg == "new":
            return _safe(lambda: run_whats_new(ctx))["text"]
        if arg == "seen":
            return _safe(lambda: run_whats_new(ctx, mark_seen=True))["text"]
        if arg.startswith("check") or arg == "ai":
            return _safe(lambda: run_conflicts(ctx, ai_check=arg.endswith("ai")))["text"]
        return _safe(lambda: run_overview(ctx))["text"]

    ctx.register_tool(name="scout_conflicts", toolset=PLUGIN,
                      schema=CONFLICTS_SCHEMA, handler=tool_conflicts)
    ctx.register_tool(name="scout_whats_new", toolset=PLUGIN,
                      schema=WHATS_NEW_SCHEMA, handler=tool_whats_new)
    ctx.register_tool(name="scout_picks", toolset=PLUGIN,
                      schema=PICKS_SCHEMA, handler=tool_picks)
    ctx.register_tool(name="scout_weekly", toolset=PLUGIN,
                      schema=WEEKLY_SCHEMA, handler=tool_weekly)
    ctx.register_tool(name="scout_profile", toolset=PLUGIN,
                      schema=PROFILE_SCHEMA, handler=tool_profile)
    ctx.register_tool(name="scout_start", toolset=PLUGIN,
                      schema=START_SCHEMA, handler=tool_start)
    ctx.register_tool(name="scout_interests", toolset=PLUGIN,
                      schema=INTERESTS_SCHEMA, handler=tool_interests)
    ctx.register_tool(name="scout_dismiss", toolset=PLUGIN,
                      schema=DISMISS_SCHEMA, handler=tool_dismiss)
    ctx.register_command("scout", handler=command,
                         description="Plugin Scout: plugins that fit you, heads-ups and clashes")
    ctx.register_automation_blueprint(
        "weekly",
        title="Weekly plugin scout",
        description="Once a week: conflicts or updates in your plugins, and new plugins that fit how you use Hermes.",
        category="general",
        schedule_template="{minute} {hour} * * 1",
        prompt_template=(
            "Call scout_weekly with mark_seen true. Send the user its text field as written. "
            "Do not add plugins it did not mention and do not install anything."
        ),
        slots=[
            {"name": "time", "type": "time", "label": "What time on Monday?", "default": "08:00"},
            {"name": "deliver", "type": "enum", "label": "Where to deliver?", "default": "origin",
             "options": ["origin", "local"], "strict": False},
        ],
        tags=["plugins", "weekly"],
    )
