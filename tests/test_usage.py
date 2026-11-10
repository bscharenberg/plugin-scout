"""Tests for the usage profiler and plugin picks. Standard library only."""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import catalog  # noqa: E402
import usage  # noqa: E402

FIXTURE = catalog.validate(json.loads((HERE / "fixtures" / "catalog_subset.json").read_text()))
NOW = 1_800_000_000.0
SECRET = "my bank PIN is 4321 and I live at 12 Elm St"


def _session(sid, messages, days_ago=1, source="cli"):
    return ({"id": sid, "last_active": NOW - days_ago * 86400, "source": source}, messages)


def _sample():
    return [
        _session("a", [
            {"role": "user", "content": "play something on spotify, then check my email"},
            {"role": "assistant", "tool_calls": [{"function": {"name": "web_search"}}] * 4},
            {"role": "tool", "tool_name": "web_search", "content": "results"},
            {"role": "user", "content": f"another email question. {SECRET}"},
        ]),
        _session("b", [{"role": "user", "content": "queue my spotify playlist"}]),
        _session("old", [{"role": "user", "content": "spotify spotify spotify"}], days_ago=90),
        _session("empty", [], source="oneshot"),
    ]


class ProfileTests(unittest.TestCase):
    def test_counts_recent_sessions_with_user_messages_only(self):
        p = usage.build_profile(_sample(), now=NOW)
        self.assertEqual(p["sessions"], 2)          # "old" is outside the window, "empty" has no user turn
        self.assertEqual(p["sources"], {"cli": 2})

    def test_topics_tools_and_terms(self):
        p = usage.build_profile(_sample(), now=NOW)
        self.assertEqual(p["topics"]["music"]["mentions"], 3)  # spotify x2 + playlist
        self.assertEqual(p["topics"]["music"]["sessions"], 2)
        self.assertIn("spotify", p["topics"]["music"]["terms"])
        self.assertEqual(p["topics"]["email"]["mentions"], 2)
        self.assertEqual(p["tools"]["web_search"], 4)
        self.assertEqual(p["topics"]["web"]["tool_calls"], 4)

    def test_profile_holds_counts_not_message_text(self):
        p = usage.build_profile(_sample(), now=NOW)
        self.assertNotIn("4321", json.dumps(p))
        self.assertNotIn("Elm", json.dumps(p))


class PickTests(unittest.TestCase):
    def setUp(self):
        self.profile = usage.build_profile(_sample(), now=NOW)

    def test_named_official_plugin_wins_for_its_topic(self):
        picks = usage.candidates(self.profile, FIXTURE["entries"], exclude=set())
        music = [p["name"] for p in picks if p["topic"] == "music"]
        self.assertEqual(music[0], "spotify")
        self.assertIn("music came up in 2 of your 2 conversations", music_evidence(picks))

    def test_ambiguous_names_do_not_match(self):
        # "inbox" is a work-status plugin, not email.
        picks = usage.candidates(self.profile, FIXTURE["entries"], exclude=set())
        self.assertNotIn("inbox", [p["name"] for p in picks])
        self.assertIn("gmail", [p["name"] for p in picks])

    def test_installed_and_dismissed_are_excluded(self):
        picks = usage.candidates(self.profile, FIXTURE["entries"], exclude={"spotify", "gmail"})
        names = [p["name"] for p in picks]
        self.assertNotIn("spotify", names)
        self.assertNotIn("gmail", names)

    def test_every_pick_has_evidence_and_install_command(self):
        for p in usage.candidates(self.profile, FIXTURE["entries"], exclude=set()):
            self.assertTrue(p["evidence"].startswith("In the last 30 days"))
            self.assertEqual(p["install"], f"hermes plugins install {p['name']}")


def music_evidence(picks):
    return " ".join(p["evidence"] for p in picks if p["topic"] == "music")


class LlmRankTests(unittest.TestCase):
    def setUp(self):
        self.profile = usage.build_profile(_sample(), now=NOW)
        self.picks = usage.candidates(self.profile, FIXTURE["entries"], exclude=set())
        self.idx = catalog.index(FIXTURE)

    def test_prompt_never_contains_message_text(self):
        seen = []
        usage.rank_with_llm(self.profile, self.picks, self.idx, ask=lambda p: seen.append(p) or "[]")
        self.assertTrue(seen)
        self.assertNotIn("4321", seen[0])
        self.assertNotIn("play something", seen[0])

    def test_uses_model_choice_and_reason(self):
        answer = 'Sure: [{"name": "gmail", "why": "You handle email a lot."}, {"name": "made-up", "why": "x"}]'
        ranked = usage.rank_with_llm(self.profile, self.picks, self.idx, ask=lambda p: answer)
        self.assertEqual([r["name"] for r in ranked], ["gmail"])
        self.assertEqual(ranked[0]["why"], "You handle email a lot.")

    def test_falls_back_to_rule_order_on_bad_output_or_error(self):
        garbage = usage.rank_with_llm(self.profile, self.picks, self.idx, ask=lambda p: "no idea")
        self.assertEqual([r["name"] for r in garbage], [p["name"] for p in self.picks[:3]])

        def broken(prompt):
            raise RuntimeError("model down")

        failed = usage.rank_with_llm(self.profile, self.picks, self.idx, ask=broken)
        self.assertEqual([r["name"] for r in failed], [p["name"] for p in self.picks[:3]])


if __name__ == "__main__":
    unittest.main()
