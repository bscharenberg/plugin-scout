"""Dashboard routes for Plugin Scout: the same data as /scout, as JSON for the dashboard tab.

Read-only except for the two things you can change from the page: your interests and
dismissed picks, both kept in Scout's own plugin state. Nothing here installs anything.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

from fastapi import APIRouter

router = APIRouter()
_ROOT = Path(__file__).resolve().parent.parent
_PKG = "plugin_scout_dashboard_core"


def _core():
    """The plugin package itself, loaded once (its register() is not called here)."""
    mod = sys.modules.get(_PKG)
    if mod is None:
        spec = importlib.util.spec_from_file_location(_PKG, _ROOT / "__init__.py",
                                                      submodule_search_locations=[str(_ROOT)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_PKG] = mod
        spec.loader.exec_module(mod)
    return mod


def _ctx():
    from hermes_cli.plugins_state import PluginState
    return types.SimpleNamespace(state=PluginState("plugin-scout"), llm=None)


def _topics(core, profile: dict[str, Any], limit: int = 6) -> list[dict[str, Any]]:
    usage = core.usage
    out = []
    for topic, st in sorted(profile.get("topics", {}).items(), key=lambda kv: -usage._weight(kv[1]))[:limit]:
        why = []
        if st.get("sessions"):
            why.append(f"came up in {st['sessions']} of {profile.get('sessions', 0)} chats")
        if st.get("tool_calls"):
            why.append(f"{st['tool_calls']} tool use{'' if st['tool_calls'] == 1 else 's'}")
        if st.get("scheduled"):
            why.append("in a scheduled task")
        if st.get("memory"):
            why.append("in your memory")
        if st.get("skills"):
            why.append("your skill " + ", ".join(st["skills"][:2]))
        if st.get("interests"):
            why.append("you said so")
        strong = usage.confidence(st) == "strong match"
        out.append({"topic": usage.label(topic), "signal": "strong signal" if strong else "early guess",
                    "why": why})
    return out


def _findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from_label = {"conflict": "Conflict", "pulled": "Pulled", "likely": "Caution", "settings": "Your settings",
                  "overlap": "Overlap", "update": "Update", "known_issue": "Known issue"}
    return [{"kind": f["kind"], "label": from_label.get(f["kind"], f["kind"]), "title": f["title"],
             "evidence": f["evidence"][:3], "severity": f["severity"]} for f in findings[:8]]


def _overview() -> dict[str, Any]:
    core, ctx = _core(), _ctx()
    picked = core._safe(lambda: core.run_picks(ctx, limit=4))
    checked = core._safe(lambda: core.run_conflicts(ctx))
    profile = core._profile(ctx) if "error" not in picked else {"topics": {}, "sessions": 0}
    return {
        "picks": picked.get("picks", []),
        "error": picked.get("error") or checked.get("error"),
        "topics": _topics(core, profile),
        "sessions": profile.get("sessions", 0),
        "sources": core.report._sources(profile) if profile.get("topics") else "",
        "findings": _findings(checked.get("findings", [])),
        "enabled_plugins": checked.get("enabled_plugins", 0),
        "jobs": [job for job, _ in core.usage.JOBS],
        "selected_jobs": [i for i, (_, words) in enumerate(core.usage.JOBS, 1)
                          if words and all(w in (ctx.state.get("interests") or []) for w in words)],
        "interests": [core.usage.label(w) for w in (ctx.state.get("interests") or [])],
    }


@router.get("/overview")
def overview():
    return _overview()


@router.post("/interests")
def set_interests(body: dict):
    core, ctx = _core(), _ctx()
    if body.get("clear"):
        core.run_interests(ctx, "clear")
    elif isinstance(body.get("jobs"), list):  # the page's choice buttons replace earlier answers
        jobs = [int(j) for j in body["jobs"] if str(j).isdigit() and 1 <= int(j) <= len(core.usage.JOBS)]
        core.run_interests(ctx, "clear")
        if jobs:
            core.run_interests(ctx, ", ".join(str(j) for j in jobs))
    else:
        items = [str(i) for i in (body.get("items") or []) if str(i).strip()][:40]
        core.run_interests(ctx, ", ".join(items))
    return _overview()


@router.post("/dismiss")
def dismiss(body: dict):
    core, ctx = _core(), _ctx()
    name = core.sanitize.name(body.get("name"))
    if name:
        core.run_dismiss(ctx, name)
    return _overview()
