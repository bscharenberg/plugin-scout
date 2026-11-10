"""'Before you install': restate each plugin's own disclosure, never guess, never call it safe."""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import catalog  # noqa: E402
import report  # noqa: E402
import risk  # noqa: E402
import usage  # noqa: E402
from test_usage import NOW  # noqa: E402


def _entry(name, description, keys=()):
    return catalog.validate({"entries": [{"name": name, "description": description,
                                          "capabilities": {"requires_env": list(keys)}}]})["entries"][0]


RELAY = _entry("anyapi", "Unified model access. Disclosure: sends your prompts, tool results and ANYAPI_API_KEY "
               "to api.anyapi.ai, a third-party relay; billed to your AnyAPI account.", ["ANYAPI_API_KEY"])
FUNDS = _entry("laso-finance", "Laso tools. Disclosure: the tools move real funds from the user's Laso account.")
READ_ONLY = _entry("picks", "Odds. Disclosure: read-only: cannot trade, sign or move money; HTTPS calls go to "
                   "predictionmarketspicks.com.")
LOCAL = _entry("memory-shield", "Protects memory. Disclosure: no network calls, credentials, shell commands or "
               "background processes.")
BRIDGE = _entry("mcp-serve", "Run Hermes as an MCP server. Disclosure: the connecting MCP client reads the active "
                "profile's conversation history and can send messages as your connected accounts; it can spend "
                "provider credits.")
BROWSER = _entry("webmint", "Web capture. Disclosure: on first mint the plugin installs Playwright and Chromium; "
                 "actions may fill, click and submit forms.")
SILENT = _entry("newswire", "A news ticker for Hermes Desktop.")
VAGUE = _entry("ichor", "Feedback store. Disclosure: captures your corrections into a local SQLite store.")


class BeforeYouInstallTests(unittest.TestCase):
    def test_what_is_sent_and_where(self):
        line = risk.before_you_install(RELAY)
        self.assertIn("Sends your prompts, tool results and ANYAPI_API_KEY to api.anyapi.ai", line)
        self.assertIn("can cost money", line)

    def test_money_is_called_out(self):
        self.assertIn("can move real money", risk.before_you_install(FUNDS).lower())

    def test_negations_are_respected(self):
        self.assertNotIn("money", risk.before_you_install(READ_ONLY).replace("predictionmarketspicks", ""))
        self.assertEqual(risk.before_you_install(LOCAL), "Its disclosure says it makes no network calls.")

    def test_access_to_your_conversations(self):
        line = risk.before_you_install(BRIDGE)
        self.assertIn("Can read your conversations", line)
        self.assertIn("can send messages as you", line)

    def test_installs_and_forms(self):
        line = risk.before_you_install(BROWSER)
        self.assertIn("Downloads extra software", line)
        self.assertIn("submit web forms", line)

    def test_never_claims_a_plugin_is_safe(self):
        self.assertIn("no disclosure", risk.before_you_install(SILENT))
        self.assertIn("hermes plugins info newswire", risk.before_you_install(SILENT))
        self.assertTrue(risk.before_you_install(VAGUE).startswith("Nothing specific flagged"))
        fixture = catalog.validate(json.loads((HERE / "fixtures" / "catalog_subset.json").read_text()))
        for e in fixture["entries"]:
            line = risk.before_you_install(e).lower()
            self.assertNotIn("safe", line)
            self.assertNotIn("nothing leaves", line)

    def test_shown_on_picks(self):
        p = usage.add_signals(usage.build_profile([], now=NOW), interests=["ai agents"])
        picks = usage.candidates(p, [BRIDGE], exclude=set())
        self.assertIn("Before you install: Can read your conversations", report.picks_text(picks, p))


if __name__ == "__main__":
    unittest.main()
