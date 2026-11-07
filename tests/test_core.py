"""Tests for the catalog loader, installed-plugin reader and conflict engine.

Standard library only (unittest). Runs without Hermes:
    python3 -m unittest discover -s tests
The fixture is a slice of the real public catalog (Nov 2026).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import catalog  # noqa: E402
import conflicts  # noqa: E402
import installed  # noqa: E402

FIXTURE = json.loads((HERE / "fixtures" / "catalog_subset.json").read_text())


def _cat():
    return catalog.validate(json.loads(json.dumps(FIXTURE)))


def _plugin(name, **kw):
    base = {"name": name, "catalog_name": name, "enabled": True, "version": "",
            "provides_tools": [], "provides_hooks": [], "provides_middleware": [],
            "installed_sha": None}
    base.update(kw)
    return base


class CatalogTests(unittest.TestCase):
    def test_validate_rejects_wrong_shape(self):
        with self.assertRaises(catalog.CatalogError):
            catalog.validate({"plugins": []})
        with self.assertRaises(catalog.CatalogError):
            catalog.validate([])

    def test_validate_drops_nameless_entries(self):
        data = catalog.validate({"entries": [{"name": "a"}, {"title": "no name"}, "junk"]})
        self.assertEqual([e["name"] for e in data["entries"]], ["a"])

    def test_store_uses_fresh_cache_without_network(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            now = [1000.0]
            store = catalog.CatalogStore(Path(tmp), fetcher=lambda: calls.append(1) or _cat(), clock=lambda: now[0])
            first = store.load()
            now[0] += 60
            second = store.load()
        self.assertEqual(first["source"], "network")
        self.assertEqual(second["source"], "cache")
        self.assertEqual(len(calls), 1)

    def test_store_falls_back_to_stale_cache_when_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = [1000.0]
            ok = catalog.CatalogStore(Path(tmp), fetcher=_cat, clock=lambda: now[0])
            ok.load()
            now[0] += catalog.CACHE_TTL_SECONDS + 1

            def offline():
                raise catalog.CatalogError("offline")

            result = catalog.CatalogStore(Path(tmp), fetcher=offline, clock=lambda: now[0]).load()
        self.assertTrue(result["stale"])
        self.assertEqual(len(result["catalog"]["entries"]), len(FIXTURE["entries"]))

    def test_store_raises_with_no_cache_and_no_network(self):
        def offline():
            raise catalog.CatalogError("offline")

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(catalog.CatalogError):
                catalog.CatalogStore(Path(tmp), fetcher=offline).load()

    def test_diff_reports_new_updated_removed(self):
        cat = _cat()
        old = catalog.snapshot(cat)
        old["gone-plugin"] = {"sha": "x", "version": "1"}
        del old["supermemory"]
        old["identity"] = dict(old["identity"], sha="0" * 40, version="0.9.0")
        cat["removed"].append({"name": "gone-plugin", "reason": "Folded into something else."})
        changes = catalog.diff(old, cat)
        self.assertEqual(changes["new"], ["supermemory"])
        self.assertEqual(changes["updated"], [{"name": "identity", "from": "0.9.0", "to": "1.0.1"}])
        self.assertEqual(changes["removed"], [{"name": "gone-plugin", "reason": "Folded into something else."}])


class InstalledTests(unittest.TestCase):
    def test_minimal_yaml_reader(self):
        text = ('name: demo\nversion: "1.2.0"\nprovides_tools:\n  - a_tool\n  - b_tool\n'
                "provides_hooks: [pre_tool_call, post_tool_call]\n")
        data = installed._yaml_minimal(text)
        self.assertEqual(data["name"], "demo")
        self.assertEqual(data["version"], "1.2.0")
        self.assertEqual(data["provides_tools"], ["a_tool", "b_tool"])
        self.assertEqual(data["provides_hooks"], ["pre_tool_call", "post_tool_call"])

    def test_finds_linked_and_nested_plugins_with_sidecar_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugins = root / "plugins"
            (plugins / "memory" / "nested-one").mkdir(parents=True)
            (plugins / "memory" / "nested-one" / "plugin.yaml").write_text("name: nested-one\nversion: 2.0.0\n")
            elsewhere = root / "src" / "linked-one"
            elsewhere.mkdir(parents=True)
            (elsewhere / "plugin.yaml").write_text("name: linked-one\nprovides_hooks:\n  - pre_tool_call\n")
            (plugins / "linked-one").symlink_to(elsewhere, target_is_directory=True)
            (plugins / ".install-metadata.json").write_text(json.dumps({"linked-one": {"sha": "a" * 40}}))
            found = {p["name"]: p for p in installed.installed_plugins(plugins, ["linked-one"])}
        self.assertEqual(set(found), {"linked-one", "nested-one"})
        self.assertTrue(found["linked-one"]["enabled"])
        self.assertFalse(found["nested-one"]["enabled"])
        self.assertEqual(found["linked-one"]["installed_sha"], "a" * 40)
        self.assertEqual(found["linked-one"]["provides_hooks"], ["pre_tool_call"])


class ConflictTests(unittest.TestCase):
    def setUp(self):
        self.cat = _cat()
        self.idx = catalog.index(self.cat)

    def test_memory_shield_and_provenance_gate_flagged_as_likely(self):
        found = conflicts.check([_plugin("memory-shield"), _plugin("provenance-gate")], self.idx)
        likely = [f for f in found if f["kind"] == "likely"]
        self.assertEqual(len(likely), 1)
        self.assertIn("`memory`", likely[0]["title"])
        self.assertEqual(likely[0]["plugins"], ["memory-shield", "provenance-gate"])

    def test_observer_only_plugin_is_not_flagged(self):
        # memory-rewind only observes (post_tool_call, session hooks); it cannot block a save.
        found = conflicts.check([_plugin("memory-shield"), _plugin("memory-rewind")], self.idx)
        self.assertEqual([f for f in found if f["kind"] == "likely"], [])

    def test_disabled_plugins_are_ignored(self):
        found = conflicts.check(
            [_plugin("memory-shield"), _plugin("provenance-gate", enabled=False)], self.idx)
        self.assertEqual([f for f in found if f["kind"] == "likely"], [])

    def test_multiple_memory_plugins_overlap(self):
        found = conflicts.check([_plugin("holographic"), _plugin("supermemory")], self.idx,
                                active_memory_provider="holographic")
        overlap = [f for f in found if f["kind"] == "overlap"]
        self.assertEqual(len(overlap), 1)
        self.assertIn("Your active memory provider is `holographic`.", overlap[0]["evidence"])

    def test_duplicate_tool_name_is_a_conflict(self):
        found = conflicts.check(
            [_plugin("identity"), _plugin("homemade", provides_tools=["identity_view"])], self.idx)
        hard = [f for f in found if f["kind"] == "conflict"]
        self.assertEqual(len(hard), 1)
        self.assertEqual(hard[0]["plugins"], ["homemade", "identity"])
        self.assertEqual(found[0]["kind"], "conflict")  # most severe sorts first

    def test_update_available_and_pulled(self):
        found = conflicts.check(
            [_plugin("identity", installed_sha="b" * 40, version="0.9.0"), _plugin("or-picker")],
            self.idx, removed=self.cat["removed"])
        kinds = {f["kind"] for f in found}
        self.assertIn("update", kinds)
        self.assertIn("pulled", kinds)

    def test_known_issues_are_surfaced(self):
        found = conflicts.check([_plugin("memory-shield")], self.idx)
        issues = [f for f in found if f["kind"] == "known_issue"]
        self.assertEqual(len(issues), 1)  # grouped: one entry per plugin, not per issue
        self.assertLessEqual(len(issues[0]["evidence"][0]), 160)

    def test_llm_no_downgrades_to_overlap_and_keeps_evidence(self):
        found = conflicts.check([_plugin("memory-shield"), _plugin("provenance-gate")], self.idx)
        found = conflicts.verify_with_llm(found, self.idx, ask=lambda prompt: "NO. They watch different things.")
        target = [f for f in found if f["plugins"] == ["memory-shield", "provenance-gate"]][0]
        self.assertEqual(target["kind"], "overlap")
        self.assertTrue(any(e.startswith("AI check:") for e in target["evidence"]))

    def test_llm_failure_leaves_findings_unchanged(self):
        found = conflicts.check([_plugin("memory-shield"), _plugin("provenance-gate")], self.idx)

        def broken(prompt):
            raise RuntimeError("model down")

        again = conflicts.verify_with_llm([dict(f, evidence=list(f["evidence"])) for f in found], self.idx, broken)
        self.assertEqual([f["kind"] for f in again], [f["kind"] for f in found])


if __name__ == "__main__":
    unittest.main()
