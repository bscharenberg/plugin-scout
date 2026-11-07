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

from . import catalog, conflicts, installed, report, settings, usage

logger = logging.getLogger(__name__)
PLUGIN = "plugin-scout"

CONFLICTS_SCHEMA = {
    "name": "scout_conflicts",
    "description": (
        "Check the user's enabled Hermes plugins for conflicts and overlaps: two plugins "
        "intercepting the same tool, duplicate tool names, several memory plugins, plugins "
        "pulled from the catalog, available updates and known issues. Each finding includes "
        "its evidence. Use when the user asks whether their plugins work well together."
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
        "which plugins they should install or what would help them."
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
        "The user's weekly plugin note in one call: conflicts or updates for their installed "
        "plugins, and only the new catalog plugins that fit how they use Hermes. Quiet when "
        "nothing matters. Set mark_seen to true when delivering the scheduled weekly note."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mark_seen": {"type": "boolean", "description": "Start next week's comparison from now."},
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


def run_picks(ctx, ai_rank: bool = False, limit: int = 3) -> dict[str, Any]:
    loaded = _load_catalog()
    cat = loaded["catalog"]
    profile = usage.build_profile(_recent_sessions())
    have = {p.get("catalog_name") or p["name"] for p in _installed()}
    dismissed = set(ctx.state.get("dismissed") or [])
    pulled = {r["name"] for r in cat["removed"]}
    pool = usage.candidates(profile, cat["entries"], exclude=have | dismissed | pulled | {PLUGIN})
    if ai_rank and getattr(ctx, "llm", None) is not None:
        picks = usage.rank_with_llm(profile, pool, catalog.index(cat), _ask_model(ctx), limit=limit)
    else:
        picks = pool[:limit]
    cfg, idx = _config(), catalog.index(cat)
    for p in picks:  # a pick that would not fully work on your setup says so up front
        found = settings.mismatches((idx.get(p["name"]) or {}).get("known_issues") or [], cfg)
        if found:
            p["heads_up"] = found[0]["why"]
    return {"profile": {k: profile[k] for k in ("sessions", "window_days", "topics")},
            "picks": picks, "text": report.picks_text(picks, profile) + _stale_note(loaded)}


def run_weekly(ctx, mark_seen: bool = False) -> dict[str, Any]:
    new = run_whats_new(ctx, mark_seen=mark_seen)
    if new.get("first_run"):
        return new
    loaded = _load_catalog()
    cat = loaded["catalog"]
    checked = run_conflicts(ctx)
    profile = usage.build_profile(_recent_sessions())
    have = {p.get("catalog_name") or p["name"] for p in _installed()}
    dismissed = set(ctx.state.get("dismissed") or [])
    relevant = usage.relevant_new(profile, new["changes"]["new"], cat["entries"],
                                  exclude=have | dismissed | {PLUGIN})
    text = report.digest_text(checked["findings"], relevant, new["changes"], new["since"],
                              len(cat["entries"])) + _stale_note(loaded)
    return {"findings": checked["findings"], "relevant_new": relevant,
            "changes": new["changes"], "since": new["since"], "text": text}


def run_overview(ctx) -> dict[str, Any]:
    """Default /scout: picks first, then heads-ups and clashes for what you have installed."""
    picked = run_picks(ctx)
    checked = run_conflicts(ctx)
    profile = {"sessions": picked["profile"]["sessions"], "window_days": picked["profile"]["window_days"]}
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
        return json.dumps(_safe(lambda: run_picks(ctx, bool(args.get("ai_rank")))), default=str)

    def tool_weekly(args, **kwargs):
        args = args or {}
        return json.dumps(_safe(lambda: run_weekly(ctx, bool(args.get("mark_seen")))), default=str)

    def tool_dismiss(args, **kwargs):
        return json.dumps(_safe(lambda: run_dismiss(ctx, (args or {}).get("name", ""))), default=str)

    def command(raw_args, **kwargs):
        arg = (raw_args or "").strip().lower()
        if arg in ("help", "?"):
            return HELP
        if arg.startswith("picks"):
            return _safe(lambda: run_picks(ctx, ai_rank=arg.endswith(" ai")))["text"]
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
