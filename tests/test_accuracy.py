"""Accuracy and first-minute value: counting conversations, confidence, and the welcome."""

import json
import sys
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import catalog  # noqa: E402
import report  # noqa: E402
import usage  # noqa: E402
from test_usage import NOW  # noqa: E402

FIXTURE = catalog.validate(json.loads((HERE / "fixtures" / "catalog_subset.json").read_text()))
ARTICLE = ("security " * 40) + "prompt injection " * 20  # one long pasted document


def _s(sid, text, source="cli", days_ago=1):
    return ({"id": sid, "last_active": NOW - days_ago * 86400, "source": source},
            [{"role": "user", "content": text}])


class CountingTests(unittest.TestCase):
    def test_one_pasted_document_cannot_dominate(self):
        burst = usage.build_profile([_s("a", ARTICLE)], now=NOW)
        spread = usage.build_profile([_s(str(i), "play my spotify playlist") for i in range(3)], now=NOW)
        self.assertLessEqual(burst["topics"]["security"]["mentions"], usage.MAX_HITS_PER_CONVERSATION)
        self.assertEqual(burst["topics"]["security"]["sessions"], 1)
        # three separate chats about music outweigh sixty hits in one paste
        self.assertGreater(usage._weight(spread["topics"]["music"]), usage._weight(burst["topics"]["security"]))

    def test_scheduled_runs_are_labelled_not_counted_as_conversations(self):
        p = usage.build_profile([_s("c1", ARTICLE, source="cron"), _s("c2", ARTICLE, source="cron"),
                                 _s("me", "what's the weather")], now=NOW)
        self.assertEqual(p["sessions"], 1)
        self.assertEqual(p["scheduled_runs"], 2)
        sec = p["topics"]["security"]
        self.assertTrue(sec["scheduled"])
        self.assertEqual((sec["sessions"], sec["mentions"]), (0, 0))
        picks = usage.candidates(p, FIXTURE["entries"] + catalog.validate({"entries": [
            {"name": "guard", "title": "Prompt Injection Guard", "description": "security"}]})["entries"],
            exclude=set())
        ev = [x["evidence"] for x in picks if x["topic"] == "security"][0]
        self.assertIn("scheduled tasks covers security", ev)
        self.assertNotIn("came up in", ev)

    def test_evidence_counts_conversations_not_words(self):
        p = usage.build_profile([_s("a", ARTICLE), _s("b", "is my password safe? security question")], now=NOW)
        ev = usage._evidence("security", p["topics"]["security"], p)
        self.assertIn("security came up in 2 of your 2 conversations", ev)


class ConfidenceTests(unittest.TestCase):
    def test_single_weak_signal_is_an_early_guess(self):
        self.assertEqual(usage.confidence({"sessions": 1}), "early guess")
        self.assertEqual(usage.confidence({"memory": 1}), "early guess")
        # memory plus a scheduled task plus one chat, with nothing direct, is still a guess
        self.assertEqual(usage.confidence({"sessions": 1, "memory": 1, "scheduled": True}), "early guess")

    def test_scheduled_task_counts_only_for_its_main_topics(self):
        text = "news " * 10 + "security " * 8 + "claude mcp " * 6 + "python code once"
        p = usage.build_profile([_s("c", text, source="cron")], now=NOW)
        self.assertTrue(p["topics"]["news"]["scheduled"])
        self.assertNotIn("coding", p["topics"])

    def test_voice_needs_a_voice_phrase(self):
        self.assertNotIn("voice", usage.build_profile([_s("a", "I'm building a public voice on AI")], now=NOW)["topics"])
        self.assertIn("voice", usage.build_profile([_s("a", "read it aloud as a voice message")], now=NOW)["topics"])

    def test_agreeing_signals_are_a_strong_match(self):
        self.assertEqual(usage.confidence({"sessions": 2, "memory": 1}), "strong match")
        self.assertEqual(usage.confidence({"interests": ["spotify"]}), "strong match")
        self.assertEqual(usage.confidence({"scheduled": True, "skills": ["ai-news-digest"]}), "strong match")
        self.assertEqual(usage.confidence({"sessions": 2, "scheduled": True}), "strong match")

    def test_picks_carry_and_show_confidence(self):
        p = usage.add_signals(usage.build_profile([_s("a", "play spotify")], now=NOW), interests=["spotify"])
        picks = usage.candidates(p, FIXTURE["entries"], exclude=set())
        self.assertEqual(picks[0]["confidence"], "strong match")
        self.assertIn("(strong match)", report.picks_text(picks[:1], p))


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        from test_hostile import _load_plugin_package
        self.plugin = _load_plugin_package()

        class State(dict):
            def set(self, k, v):
                self[k] = v
        self.ctx = types.SimpleNamespace(state=State(), llm=None)

    def test_every_job_maps_to_real_topics(self):
        for job, words in usage.JOBS:
            p = usage.add_signals(usage.build_profile([], now=NOW), interests=words)
            self.assertFalse(p["custom"], f"{job}: {words} should all match known topics")

    def test_each_job_lands_on_its_own_topics(self):
        expect = {2: "writing", 5: "automation", 6: "knowledge", 8: "shopping", 1: "learning"}
        for n, topic in expect.items():
            p = usage.add_signals(usage.build_profile([], now=NOW), interests=usage.job_words([n]))
            self.assertIn(topic, p["topics"], f"choice {n} should add {topic}")

    def test_new_topics_read_real_sentences(self):
        cases = {"writing": "help me draft a LinkedIn post", "learning": "explain how MCP works, teach me",
                 "shopping": "which standing desk should I buy, compare prices",
                 "automation": "automate this workflow every morning",
                 "knowledge": "remember that I prefer tables"}
        for topic, text in cases.items():
            self.assertIn(topic, usage.build_profile([_s("a", text)], now=NOW)["topics"], topic)

    def test_numbered_answers(self):
        out = self.plugin.run_interests(self.ctx, "1, 10")
        self.assertEqual(out["interests"], ["news", "research", "learning", "security", "privacy"])
        bad = self.plugin.run_interests(self.ctx, "99")
        self.assertIn("pick numbers", bad["text"])

    def test_welcome_gives_value_before_asking(self):
        p = usage.add_signals(usage.build_profile([_s("a", "check the news"), _s("b", "news on AI")], now=NOW))
        picks = usage.candidates(p, FIXTURE["entries"], exclude=set())[:2]
        clash = {"kind": "likely", "severity": 2, "title": "A and B both step in on `memory`", "evidence": []}
        text = report.welcome_text([clash], 2, p, picks)
        self.assertLess(text.index("1. Your setup"), text.index("One question"))
        self.assertIn("[CAUTION] A and B", text)
        self.assertIn("news (", text)
        self.assertIn("/scout interests 1, 6", text)
        self.assertIn("10. Security and privacy", text)
        self.assertIn("2. Writing and social posts", text)
        pick = {"name": "cloudflare-web-search", "title": "Cloudflare Web Search", "confidence": "strong match",
                "install": "hermes plugins install cloudflare-web-search",
                "heads_up": "It needs web.cache_enabled: false. Yours is true."}
        self.assertIn("Heads up: It needs web.cache_enabled", report.welcome_text([], 0, p, [pick]))

    def test_welcome_with_nothing_known(self):
        text = report.welcome_text([], 0, usage.build_profile([], now=NOW), [])
        self.assertIn("No other plugins enabled yet", text)
        self.assertIn("the question below fixes it", text)


if __name__ == "__main__":
    unittest.main()
