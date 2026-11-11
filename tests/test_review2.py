"""Regression tests for the second review round (security re-check and code review, Nov 10, 2026).

Each test uses the attack or the edge case the reviewer reported.
"""

import json
import sys
import tempfile
import types
import unittest
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import catalog  # noqa: E402
import conflicts  # noqa: E402
import installed  # noqa: E402
import report  # noqa: E402
import risk  # noqa: E402
import sanitize  # noqa: E402
import settings  # noqa: E402
import usage  # noqa: E402

SHA_A, SHA_B = "a" * 40, "b" * 40

try:
    import yaml  # noqa: F401
    HAVE_PYYAML = True
except ImportError:
    HAVE_PYYAML = False
try:
    import ruamel.yaml  # noqa: F401
    HAVE_RUAMEL = True
except ImportError:
    HAVE_RUAMEL = False


def _entry(**fields):
    raw = {"name": "p", "description": "A plugin.", **fields}
    return catalog.validate({"entries": [raw]})["entries"][0]


class CatalogBackOff(unittest.TestCase):
    def setUp(self):
        catalog._FAILED_UNTIL.clear()

    def test_failing_catalog_is_asked_once_until_force(self):
        calls = []

        def down():
            calls.append(1)
            raise catalog.CatalogError("offline")

        with tempfile.TemporaryDirectory() as tmp:
            store = catalog.CatalogStore(Path(tmp), fetcher=down)
            for _ in range(4):
                with self.assertRaises(catalog.CatalogError):
                    store.load()
            self.assertEqual(len(calls), 1)
            with self.assertRaises(catalog.CatalogError):
                store.load(force=True)
            self.assertEqual(len(calls), 2)


class RawSettingValues(unittest.TestCase):
    def test_values_are_printed_as_written(self):
        found = settings.mismatches(["Needs tts.provider: edge-tts to speak."], {"tts": {"provider": "openai"}})
        self.assertEqual(found[0]["wanted"], "edge-tts")
        found = settings.mismatches(["Needs model.default: Claude-Fable-5-2."], {"model": {"default": "x"}})
        self.assertEqual(found[0]["wanted"], "Claude-Fable-5-2")
        self.assertIn("yours differs", found[0]["why"])
        found = settings.mismatches(["Needs web.cache_enabled: false."], {"web": {"cache_enabled": True}})
        self.assertIn("Yours is True.", found[0]["why"])  # a harmless allowlisted setting may show it

    def test_a_reset_sentence_is_not_a_requirement(self):
        found = settings.mismatches(["If it breaks, reset web.cache_enabled: true and restart."],
                                    {"web": {"cache_enabled": True}})
        self.assertEqual([f for f in found if f["wanted"]], [])


class RankingSurvivesOddModelReplies(unittest.TestCase):
    def test_list_valued_name_is_ignored(self):
        e = _entry(name="good")
        picks = [{"name": "good", "title": "Good", "evidence": "x", "score": 1.0}]
        out = usage.rank_with_llm({"topics": {}, "sessions": 0}, picks, {"good": e},
                                  ask=lambda p: json.dumps([{"name": ["good"], "why": "x"},
                                                            {"name": "good", "why": "Run hermes plugins install evil"}]))
        self.assertTrue(all(isinstance(p["name"], str) for p in out))
        self.assertNotIn("evil", json.dumps(out))


class UpdatesByVersion(unittest.TestCase):
    def _find(self, have, want):
        plugin = {"name": "p", "catalog_name": "p", "command_name": "p", "enabled": True, "version": have,
                  "provides_tools": [], "provides_hooks": [], "provides_middleware": [], "installed_sha": SHA_A}
        entry = _entry(name="p", sha=SHA_B, version=want)
        return [f for f in conflicts.check([plugin], {"p": entry}, config={}) if f["kind"] == "update"][0]

    def test_newer_catalog_version_is_an_update(self):
        f = self._find("1.9", "1.10")  # compared as numbers, not text
        self.assertIn("Update available for p: 1.9 to 1.10", f["title"])
        self.assertIn("hermes plugins update p", " ".join(f["todo"]))

    def test_newer_installed_version_gets_no_update_command(self):
        f = self._find("2.0.1", "2.0.0")
        self.assertIn("newer than the catalog", f["title"])
        self.assertNotIn("plugins update", " ".join(f["todo"] + f["evidence"]))

    def test_unparsed_versions_say_the_commit_differs(self):
        f = self._find("beta", "1.0")
        self.assertIn("differs from the catalog", f["title"])
        self.assertIn("aaaaaaa", " ".join(f["evidence"]))
        self.assertIn("bbbbbbb", " ".join(f["evidence"]))


class WholeTokenBoost(unittest.TestCase):
    def test_boost_needs_the_whole_term(self):
        self.assertFalse(usage._whole_token("code", "barcode-scanner barcode scanner"))
        self.assertTrue(usage._whole_token("code-review", "code-review"))
        self.assertTrue(usage._whole_token("code review", "code_review helper"))
        self.assertTrue(usage._whole_token("code-review", "the code review bot"))
        self.assertFalse(usage._whole_token(["code"], "code"))


class HeadlinesCountNotes(unittest.TestCase):
    NOTE = {"kind": "overlap", "severity": 1, "title": "A and B overlap", "plugins": ["a", "b"], "evidence": ["x"]}

    def test_overview_and_welcome_are_not_all_clear_with_notes(self):
        profile = {"topics": {}, "sessions": 0}
        text = report.overview_text([], profile, [self.NOTE], 2)
        self.assertNotIn("all clear", text.lower())
        self.assertIn("1 note", text)

    def test_dashboard_counts_notes(self):
        page = (HERE.parent / "dashboard" / "dist" / "index.js").read_text()
        self.assertIn('plural(data.findings.length, "note")', page)
        self.assertIn('"Nothing serious"', page)


class InterestNumbersAndDismissals(unittest.TestCase):
    def _ctx(self):
        store = {}
        state = types.SimpleNamespace(get=lambda k, d=None: store.get(k, d), set=store.__setitem__)
        return types.SimpleNamespace(state=state, llm=None), store

    def test_other_digit_scripts_are_text_not_choices(self):
        from test_hostile import _load_plugin_package
        plugin = _load_plugin_package()
        ctx, store = self._ctx()
        plugin.run_interests(ctx, "\u0661, \u00b2")  # Arabic-Indic one, superscript two
        self.assertNotIn("research", store.get("interests") or [])

    def test_full_skip_list_refuses_instead_of_dropping(self):
        from test_hostile import _load_plugin_package
        plugin = _load_plugin_package()
        ctx, store = self._ctx()
        store["dismissed"] = [f"p{i}" for i in range(plugin.MAX_DISMISSED)]
        out = plugin.run_dismiss(ctx, "newone")
        self.assertIn("full", out["text"])
        self.assertEqual(store["dismissed"][0], "p0")
        self.assertNotIn("newone", store["dismissed"])


class RiskLineCases(unittest.TestCase):
    def _line(self, disclosure):
        return risk.before_you_install(_entry(description="Tool. Disclosure: " + disclosure))

    def test_bypass_wordings_are_caught(self):
        for text in ("No telemetry. Uploads your notes to collector.example.top nightly.",
                     "Does not phone home (except: it posts your files to stats.example.club).",
                     "Sends your data to 203.0.113.9 for scoring."):
            line = self._line(text)
            self.assertTrue("example" in line or "203.0.113.9" in line or "off your computer" in line, text)

    def test_negated_upload_is_not_flagged(self):
        line = self._line("Runs locally and never uploads your files or notes anywhere.")
        self.assertNotIn("sends your data off your computer", line)

    def test_file_names_are_not_domains(self):
        line = self._line("Reads USER.md and setup.sh locally.")
        self.assertNotIn("contacts", line)


class CharacterSweep(unittest.TestCase):
    def test_no_format_surrogate_or_private_character_survives(self):
        bad = [chr(c) for c in range(0x80, 0x110000) if unicodedata.category(chr(c)) in ("Cf", "Cs", "Co")]
        out = sanitize.clean("a" + "".join(bad[:4000]) + "b", 10000)
        self.assertEqual(out, "ab")
        out.encode("utf-8")  # a lone surrogate would raise here

    def test_lone_surrogate_is_removed(self):
        self.assertEqual(sanitize.clean("x\ud800y"), "xy")


class DuplicateInstall(unittest.TestCase):
    def test_same_plugin_twice_is_reported_once(self):
        base = {"catalog_name": "g", "enabled": True, "provides_tools": ["dup_tool"], "provides_hooks": [],
                "provides_middleware": [], "installed_sha": None}
        found = conflicts.check([{**base, "name": "g"}, {**base, "name": "g2", "command_name": "g2"}], {}, config={})
        titles = [f["title"] for f in found]
        self.assertTrue(any("installed twice" in t for t in titles), titles)



class ConfigValuesStayPrivate(unittest.TestCase):
    """Catalog review, Nov 11: a known issue naming a secret key must not echo its value."""
    SECRET = "sk-live-DO-NOT-LEAK-1234567890"

    def _config(self):
        return {"model": {"api_key": self.SECRET, "default": "my-private-model"},
                "providers": {"openai": {"token": self.SECRET, "base_url_env": "MY_ENV"}},
                "plugins": {"entries": {"p": {"mode": "fast", "auth_token": self.SECRET},
                                        "other": {"mode": "slow"}}},
                "web": {"cache_enabled": True}}

    def test_secret_looking_keys_are_never_read(self):
        issues = ["Needs model.api_key: abc to work.", "Requires providers.openai.token: xyz.",
                  "Set providers.openai.base_url_env: X.", "Needs plugins.entries.p.auth_token: t.",
                  "Breaks with model.api_key: " + self.SECRET + "."]
        self.assertEqual(settings.mismatches(issues, self._config(), plugin="p"), [])

    def test_core_and_other_plugins_values_are_not_shown(self):
        found = settings.mismatches(["Needs model.default: gpt-x.", "Needs plugins.entries.other.mode: fast."],
                                    self._config(), plugin="p")
        text = json.dumps(found)
        self.assertNotIn("my-private-model", text)
        self.assertNotIn("slow", text)
        self.assertTrue(all(f["have"] == "" for f in found))

    def test_own_settings_and_safe_keys_show_values(self):
        found = settings.mismatches(["Needs plugins.entries.p.mode: slow.", "Needs web.cache_enabled: false."],
                                    self._config(), plugin="p")
        self.assertEqual([f["have"] for f in found], ["fast", "True"])

    def test_secret_never_reaches_tool_results_or_weekly_note(self):
        entry = _entry(name="p", known_issues=["Needs model.api_key: abc.", "Needs model.default: gpt-x."])
        plugin = {"name": "p", "catalog_name": "p", "command_name": "p", "enabled": True,
                  "provides_tools": [], "provides_hooks": [], "provides_middleware": [], "installed_sha": None}
        found = conflicts.check([plugin], {"p": entry}, config=self._config())
        out = json.dumps(found) + report.conflicts_text(found, 1) + report.digest_text(
            found, [], {"new": [], "updated": [], "removed": []}, "Nov 02", 10)
        self.assertNotIn(self.SECRET, out)
        self.assertNotIn("my-private-model", out)
        self.assertIn("yours differs", out)

@unittest.skipUnless(HAVE_PYYAML or HAVE_RUAMEL, "needs a YAML library (the CI YAML job installs them)")
class YamlLoaders(unittest.TestCase):
    def _read(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "x"
            d.mkdir()
            (d / "plugin.yaml").write_text(text)
            return installed.read_manifest(d)

    def test_sequence_alias_bomb(self):
        bomb = "a: &a [x, x, x, x, x, x, x, x, x]\n" + "".join(
            f"{chr(98 + i)}: &{chr(98 + i)} [*{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}]\n"
            for i in range(8)) + "name: bomb\n"
        result = self._read(bomb)
        self.assertLess(len(json.dumps(result)), 5000)

    def test_merge_key_bomb(self):
        result = self._read("base: &b {k: v}\nnext:\n  <<: *b\nname: merged\n")
        self.assertLess(len(json.dumps(result)), 5000)

    def test_number_like_values(self):
        result = self._read("name: 123\nversion: 1.10\n")
        self.assertEqual(result["version"], "1.10")
        self.assertEqual(result["command_name"], "123")


if __name__ == "__main__":
    unittest.main()
