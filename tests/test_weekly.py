"""Tests for the weekly note: quiet unless something matters to you."""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import catalog  # noqa: E402
import report  # noqa: E402
import usage  # noqa: E402
from test_usage import NOW, _sample  # noqa: E402

FIXTURE = catalog.validate(json.loads((HERE / "fixtures" / "catalog_subset.json").read_text()))
NO_CHANGES = {"new": [], "updated": [], "removed": []}


class RelevantNewTests(unittest.TestCase):
    def setUp(self):
        self.profile = usage.build_profile(_sample(), now=NOW)

    def test_only_new_plugins_that_fit_are_kept(self):
        new = ["spotify", "memory-shield", "identity"]  # only spotify fits a music user
        rel = usage.relevant_new(self.profile, new, FIXTURE["entries"], exclude=set())
        self.assertEqual([p["name"] for p in rel], ["spotify"])

    def test_old_plugins_never_show_as_new(self):
        rel = usage.relevant_new(self.profile, ["identity"], FIXTURE["entries"], exclude=set())
        self.assertEqual(rel, [])

    def test_installed_or_dismissed_new_plugins_are_skipped(self):
        rel = usage.relevant_new(self.profile, ["spotify", "gmail"], FIXTURE["entries"],
                                 exclude={"spotify", "gmail"})
        self.assertEqual(rel, [])


class DigestTextTests(unittest.TestCase):
    def test_quiet_week(self):
        self.assertIn("all clear. No catalog changes",
                      report.digest_text([], [], NO_CHANGES, "Nov 02", 1063))

    def test_busy_catalog_but_nothing_for_you_is_one_short_note(self):
        changes = {"new": ["a", "b", "c"], "updated": [{"name": "x"}], "removed": []}
        text = report.digest_text([], [], changes, "Nov 02", 1066)
        self.assertEqual(len(text.splitlines()), 2)
        self.assertIn("Nothing new fits", text)
        self.assertIn("3 new, 1 updated, 0 removed", text)

    def test_new_for_you_first_then_heads_ups_and_clashes(self):
        profile = usage.build_profile(_sample(), now=NOW)
        rel = usage.relevant_new(profile, ["spotify"], FIXTURE["entries"], exclude=set())
        clash = {"kind": "likely", "severity": 2, "title": "memory-shield and provenance-gate "
                 "both step in on `memory`", "evidence": ["Both use pre_tool_call."]}
        minor = {"kind": "overlap", "severity": 1, "title": "two memory plugins", "evidence": []}
        text = report.digest_text([clash, minor], rel, {"new": ["spotify"], "updated": [],
                                                        "removed": []}, "Nov 02", 1064)
        lines = text.splitlines()
        self.assertTrue(lines[1].startswith("[NEW FOR YOU] spotify"))
        self.assertLess(text.index("[NEW FOR YOU]"), text.index("[CAUTION]"))
        self.assertNotIn("two memory plugins", text)  # minor overlaps stay out of the weekly note
        self.assertIn("hermes plugins install spotify", text)
        self.assertLess(len(lines), 12)

    def test_pulled_plugin_still_comes_first(self):
        pulled = {"kind": "pulled", "severity": 3, "title": "or-picker was removed from the catalog",
                  "evidence": ["Security."]}
        profile = usage.build_profile(_sample(), now=NOW)
        rel = usage.relevant_new(profile, ["spotify"], FIXTURE["entries"], exclude=set())
        text = report.digest_text([pulled], rel, {"new": ["spotify"], "updated": [], "removed": []},
                                  "Nov 02", 1064)
        self.assertTrue(text.splitlines()[1].startswith("[PULLED]"))


class OverviewTests(unittest.TestCase):
    def setUp(self):
        self.profile = usage.build_profile(_sample(), now=NOW)
        self.picks = usage.candidates(self.profile, FIXTURE["entries"], exclude=set())[:3]
        self.clash = {"kind": "likely", "severity": 2, "title": "A and B both step in on `memory`",
                      "evidence": ["Both register `pre_tool_call`."]}
        self.heads = {"kind": "settings", "severity": 2, "title": "C may not fully work with your settings",
                      "evidence": ["It needs x.y: z. Yours is w."]}

    def test_order_is_picks_then_heads_ups_then_clashes(self):
        text = report.overview_text(self.picks, self.profile, [self.clash, self.heads], 3)
        i_for, i_heads, i_clash = (text.index(h) for h in
                                   ("For you:", "Heads-ups on your plugins:", "Plugins that may clash:"))
        self.assertLess(i_for, i_heads)
        self.assertLess(i_heads, i_clash)
        self.assertIn("/scout check", text)

    def test_all_clear_when_nothing_found(self):
        text = report.overview_text(self.picks, self.profile, [], 2)
        self.assertIn("Your 2 enabled plugins: all clear.", text)
        self.assertNotIn("Plugins that may clash", text)
        self.assertIn("No other plugins enabled yet", report.overview_text(self.picks, self.profile, [], 0))

    def test_pulled_above_picks(self):
        pulled = {"kind": "pulled", "severity": 3, "title": "X was removed from the catalog", "evidence": []}
        text = report.overview_text(self.picks, self.profile, [pulled], 1)
        self.assertLess(text.index("[PULLED]"), text.index("For you:"))

    def test_no_history_yet(self):
        text = report.overview_text([], {"sessions": 0, "window_days": 30}, [], 0)
        self.assertIn("Not enough history yet", text)

if __name__ == "__main__":
    unittest.main()
