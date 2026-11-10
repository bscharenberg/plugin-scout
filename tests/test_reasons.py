"""Pick descriptions: say what the plugin does and why it fits this user, specifically."""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import catalog  # noqa: E402
import report  # noqa: E402
import usage  # noqa: E402
from test_usage import NOW  # noqa: E402

MCP = {"name": "mcp-serve", "title": "mcp-serve", "tier": "official", "description":
       "Run Hermes as an MCP server: `hermes mcp-serve` lets any MCP client (Claude Code, Claude Desktop, "
       "Cursor, Codex) list and read your messaging conversations, poll live events, send messages."}
LABELLED = {"name": "elevenlabs-music", "description": "ElevenLabs Music for Hermes: compose songs and "
            "instrumentals from a prompt. Disclosure: sends prompts to elevenlabs.io."}
DASHED = {"name": "remote", "description": "Spotify Connect remote for Hermes Desktop \u2014 status-bar mini player."}


def _chat(sid, text, source="cli"):
    return ({"id": sid, "last_active": NOW - 86400, "source": source}, [{"role": "user", "content": text}])


class WhatItDoesTests(unittest.TestCase):
    def test_first_sentence_in_the_authors_words(self):
        e = catalog.validate({"entries": [MCP]})["entries"][0]
        what = usage.what_it_does(e)
        self.assertTrue(what.startswith("Run Hermes as an MCP server"))
        self.assertNotIn("`", what)
        self.assertLessEqual(len(what), 163)

    def test_skips_a_bare_label_and_dashes(self):
        e = catalog.validate({"entries": [LABELLED, DASHED]})["entries"]
        self.assertEqual(usage.what_it_does(e[0]), "Compose songs and instrumentals from a prompt.")
        self.assertNotIn("\u2014", usage.what_it_does(e[1]))
        self.assertTrue(usage.what_it_does(e[1]).startswith("Status-bar mini player"))


class ForYouTests(unittest.TestCase):
    def setUp(self):
        self.profile = usage.build_profile([
            _chat("a", "How do I use Claude for context engineering?"),
            _chat("b", "multi-agent setups with Claude and MCP"),
            _chat("c", "what's new in AI news"),
        ], now=NOW)
        self.entry = catalog.validate({"entries": [MCP]})["entries"][0]

    def test_names_and_phrases_you_used_come_first(self):
        reasons = usage.for_you("ai agents", self.profile["topics"]["ai agents"], self.profile, self.entry)
        self.assertEqual(len(reasons), 2)
        self.assertIn("It works with Claude", reasons[0])
        self.assertIn("context engineering", reasons[1])

    def test_words_added_by_a_choice_are_not_claimed_as_yours(self):
        p = usage.add_signals(usage.build_profile([], now=NOW), interests=usage.job_words([4]))  # adds "github"
        entry = {"name": "repo-review", "description": "Reviews a GitHub repository."}
        reasons = usage.for_you("github", p["topics"]["github"], p, entry)
        self.assertFalse(any("GitHub" in r for r in reasons))

    def test_tool_use_reads_naturally(self):
        p = {"sessions": 1, "tools": {"web_search": 36, "memory": 2}, "topics": {}}
        self.assertIn("Hermes did 36 web searches for you",
                      usage.for_you("web", {"tool_calls": 36}, p, {"name": "x", "description": "d"}))
        self.assertIn("Hermes did 2 memory saves for you",
                      usage.for_you("knowledge", {"tool_calls": 2}, p, {"name": "y", "description": "d"}))

    def test_counts_only_when_nothing_specific(self):
        p = usage.build_profile([_chat("x", "security question"), _chat("y", "more on security")], now=NOW)
        entry = {"name": "guard", "description": "Blocks risky tool calls."}
        reasons = usage.for_you("security", p["topics"]["security"], p, entry)
        self.assertEqual(reasons, ["Security came up in 2 of your 2 chats"])

    def test_pick_layout(self):
        picks = usage.candidates(self.profile, [self.entry], exclude=set())
        text = report.picks_text(picks, self.profile)
        self.assertIn("What it does: Run Hermes as an MCP server", text)
        self.assertIn("For you: It works with Claude", text)
        self.assertNotIn("Why:", text)
        self.assertNotIn("numeric score", text)

    def test_ai_reason_leads_when_present(self):
        picks = usage.candidates(self.profile, [self.entry], exclude=set())
        picks[0]["why"] = "Lets Claude Code drive your Hermes."
        self.assertIn("For you: Lets Claude Code drive your Hermes. It works with Claude",
                      report.picks_text(picks, self.profile))


if __name__ == "__main__":
    unittest.main()
