"""Tests for the settings check, using real catalog warnings."""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import catalog  # noqa: E402
import conflicts  # noqa: E402
import report  # noqa: E402
import settings  # noqa: E402

FIXTURE = catalog.validate(json.loads((HERE / "fixtures" / "catalog_subset.json").read_text()))
SHIELD = FIXTURE and catalog.index(FIXTURE)["memory-shield"]["known_issues"]
HOST = {"plugins": {"isolation": "host"}, "web": {"cache_enabled": True}}
IN_PROCESS = {"plugins": {"isolation": "in_process"}, "web": {"cache_enabled": True}}


class MismatchTests(unittest.TestCase):
    def test_needs_in_process_but_you_run_host(self):
        found = settings.mismatches(SHIELD, HOST)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["wanted"], "in_process")
        self.assertIn("yours differs", found[0]["why"])
        self.assertNotIn("host", found[0]["why"])  # a core setting's value is never echoed

    def test_silent_when_your_setting_matches(self):
        self.assertEqual(settings.mismatches(SHIELD, IN_PROCESS), [])

    def test_warning_about_your_exact_value(self):
        issue = ["Under plugins.isolation: host the hermes day terminal command is not available."]
        self.assertEqual(len(settings.mismatches(issue, HOST)), 1)
        self.assertEqual(settings.mismatches(issue, IN_PROCESS), [])

    def test_set_instruction(self):
        issue = ["Set web.cache_enabled: false in every profile using this backend."]
        found = settings.mismatches(issue, HOST)
        self.assertEqual(found[0]["wanted"], "false")
        self.assertEqual(settings.mismatches(issue, {"web": {"cache_enabled": False}}), [])

    def test_unknown_settings_and_plain_prose_are_ignored(self):
        issue = ["Reads cron.jobs and cron.scheduler: they keep approvals blocked.",
                 "Needs foo.bar: baz, which you do not have."]
        self.assertEqual(settings.mismatches(issue, {"cron": {"scheduler": "default"}}), [])

    def test_dict_style_issues_are_read(self):
        self.assertEqual(settings.issue_texts([{"Licence": "non-commercial"}]), ["Licence: non-commercial"])


class FindingTests(unittest.TestCase):
    def test_finding_and_report_line(self):
        plugin = {"name": "memory-shield", "enabled": True, "provides_tools": [], "provides_hooks": []}
        found = conflicts.check([plugin], catalog.index(FIXTURE), config=HOST)
        mine = [f for f in found if f["kind"] == "settings"]
        self.assertEqual(len(mine), 1)
        text = report.conflicts_text(found, 1)
        self.assertIn("[YOUR SETTINGS] Memory Shield may not fully work with your settings", text)
        # plugins.isolation guards the user, so Scout never hands out a command to change it
        self.assertNotIn("hermes config set", text)
        self.assertIn("Scout does not suggest changing plugins.isolation", text)
        self.assertEqual([f for f in conflicts.check([plugin], catalog.index(FIXTURE), config=IN_PROCESS)
                          if f["kind"] == "settings"], [])


if __name__ == "__main__":
    unittest.main()
