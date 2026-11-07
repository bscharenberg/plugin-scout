"""Installed plugins: what the user has, read from disk and config.

Read-only. Looks at each plugin folder's plugin.yaml (or plugin.json), the
install sidecar Hermes keeps in the plugins folder, and the enabled list
from config. Never imports or runs another plugin's code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    from . import sanitize
except ImportError:  # loaded as a plain module (tests)
    import sanitize

SIDECAR = ".install-metadata.json"
MAX_MANIFEST_BYTES = 256 * 1024
_LIST_KEYS = ("provides_tools", "provides_hooks", "provides_middleware")


def _parse_manifest_text(text: str) -> dict[str, Any]:
    """Read the few manifest fields we need.

    Uses a YAML library when one is importable, otherwise a small reader that
    handles top-level scalars and block or inline lists, which is all a
    plugin.yaml needs for these fields.
    """
    for loader in (_yaml_pyyaml, _yaml_ruamel):
        data = loader(text)
        if isinstance(data, dict):
            return data
    return _yaml_minimal(text)


def _yaml_pyyaml(text: str) -> Optional[dict]:
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except Exception:
        return None


def _yaml_ruamel(text: str) -> Optional[dict]:
    try:
        from ruamel.yaml import YAML  # type: ignore
        return YAML(typ="safe").load(text)
    except Exception:
        return None


def _scalar(value: str) -> str:
    value = value.split(" #", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def _yaml_minimal(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    current_list: Optional[str] = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] not in " \t-":
            current_list = None
            key, _, rest = line.partition(":")
            key, rest = key.strip(), rest.strip()
            if rest.startswith("[") and rest.endswith("]"):
                out[key] = [_scalar(v) for v in rest[1:-1].split(",") if v.strip()]
            elif rest == "":
                out[key] = []
                current_list = key
            else:
                out[key] = _scalar(rest)
        elif current_list and line.strip().startswith("- "):
            out[current_list].append(_scalar(line.strip()[2:]))
    return out


def read_manifest(plugin_dir: Path) -> Optional[dict[str, Any]]:
    """Manifest fields for one plugin folder, or None if it has no manifest."""
    yaml_path, json_path = plugin_dir / "plugin.yaml", plugin_dir / "plugin.json"
    try:
        path = yaml_path if yaml_path.is_file() else json_path if json_path.is_file() else None
        if path is None or path.stat().st_size > MAX_MANIFEST_BYTES:
            return None  # a manifest is a few lines; anything huge is not one
        text = path.read_text(encoding="utf-8-sig")
        data = _parse_manifest_text(text) if path is yaml_path else json.loads(text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    caps = data.get("capabilities") if isinstance(data.get("capabilities"), dict) else {}
    result = {
        "name": sanitize.clean(data.get("name") or plugin_dir.name, 64),
        "version": sanitize.clean(data.get("version"), 64),
        "folder": sanitize.clean(plugin_dir.name, 64),
    }
    for key in _LIST_KEYS:
        value = data.get(key, caps.get(key, []))
        result[key] = sanitize.tool_names(value)
    return result


def _plugin_dirs(plugins_dir: Path) -> Iterable[Path]:
    """Plugin folders, flat or one category level deep, following symlinks.

    Each real folder is listed once, so a link pointing back into the tree
    cannot make one plugin look like two.
    """
    if not plugins_dir.is_dir():
        return
    seen: set[str] = set()

    def has_manifest(d: Path) -> bool:
        return (d / "plugin.yaml").is_file() or (d / "plugin.json").is_file()

    def first_time(d: Path) -> bool:
        try:
            real = str(d.resolve())
        except OSError:
            return False
        if real in seen:
            return False
        seen.add(real)
        return True

    for child in sorted(plugins_dir.iterdir()):
        if child.name.startswith(".") or not child.is_dir():
            continue
        if has_manifest(child):
            if first_time(child):
                yield child
            continue
        try:
            grandchildren = sorted(child.iterdir())
        except OSError:
            continue
        for grandchild in grandchildren:
            if grandchild.is_dir() and not grandchild.name.startswith(".") and has_manifest(grandchild):
                if first_time(grandchild):
                    yield grandchild


def read_sidecar(plugins_dir: Path) -> dict[str, dict[str, Any]]:
    """Install records Hermes keeps for plugins it installed, keyed by folder name."""
    try:
        data = json.loads((plugins_dir / SIDECAR).read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    rows = data.get("plugins", data) if isinstance(data, dict) else {}
    if isinstance(rows, list):
        rows = {str(r.get("name") or r.get("key") or i): r for i, r in enumerate(rows) if isinstance(r, dict)}
    return {str(k): v for k, v in rows.items() if isinstance(v, dict)} if isinstance(rows, dict) else {}


def _installed_sha(row: dict[str, Any]) -> Optional[str]:
    for key in ("sha", "commit", "pinned_sha", "catalog_sha", "ref"):
        value = row.get(key)
        if isinstance(value, str) and len(value) >= 7:
            return value
    return None


def installed_plugins(plugins_dir: Path, enabled: Iterable[str]) -> list[dict[str, Any]]:
    """Every plugin on disk with its manifest fields, enabled flag and install sha."""
    enabled_set = {str(e) for e in enabled or []}
    sidecar = read_sidecar(plugins_dir)
    found = []
    for folder in _plugin_dirs(plugins_dir):
        manifest = read_manifest(folder)
        if not manifest:
            continue
        rel = str(folder.relative_to(plugins_dir))
        row = sidecar.get(rel) or sidecar.get(folder.name) or sidecar.get(manifest["name"]) or {}
        manifest["enabled"] = bool({manifest["name"], folder.name, rel} & enabled_set)
        manifest["installed_sha"] = _installed_sha(row)
        manifest["catalog_name"] = row.get("catalog_name") or row.get("name") or manifest["name"]
        found.append(manifest)
    return found
