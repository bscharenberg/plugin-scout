"""Tests for the extra signals: Hermes memory, skills you made, and interests you tell Scout."""

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import catalog  # noqa: E402
import report  # noqa: E402
import usage  # noqa: E402
from test_usage import NOW, SECRET, _sample  # noqa: E402

FIXTURE = catalog.validate(json.loads((HERE / "fixtures" / "catalog_subset.json").read_text()))
MEMORY = ("Alex likes plain English. Alex follows prompt injection research and MCP servers, "
          f"wants a Monday news briefing, and plays Spotify while working. {SECRET}")
SKILLS = [{"name": "ai-news-digest", "description": "Weekly AI news digest with headlines"}]
EXTRA = [  # small fake entries so custom interests and new topics have something to match
    {"name": "kube-helper", "title": "Kubernetes Helper", "description": "Manage kubernetes clusters.",
     "tier": "community", "known_issues": [], "capabilities": {}},
    {"name": "injection-guard", "title": "Injection Guard", "description": "Blocks prompt injection in tool results.",
     "tier": "community", "known_issues": [], "capabilities": {}},
]


def _cold():
    return usage.build_profile([], now=NOW)


class SignalTests(unittest.TestCase):
    def test_memory_adds_topics_without_storing_text(self):
        p = usage.add_signals(_cold(), memory_text=MEMORY)
        for topic in ("security", "ai agents", "news", "music"):
            self.assertIn(topic, p["topics"])
            self.assertTrue(p["topics"][topic]["memory"])
        blob = json.dumps(p)
        self.assertNotIn("4321", blob)
        self.assertNotIn("Elm", blob)
        self.assertNotIn("plain English", blob)

    def test_skills_you_made_count(self):
        p = usage.add_signals(_cold(), skills=SKILLS)
        self.assertEqual(p["topics"]["news"]["skills"], ["ai-news-digest"])

    def test_interests_map_to_topics_or_become_their_own(self):
        p = usage.add_signals(_cold(), interests=["spotify", "kubernetes"])
        self.assertEqual(p["topics"]["music"]["interests"], ["spotify"])
        self.assertIn("kubernetes", p["topics"])
        self.assertIn("kubernetes", p["custom"])

    def test_cold_start_still_gives_picks(self):
        p = usage.add_signals(_cold(), memory_text=MEMORY, skills=SKILLS, interests=["kubernetes"])
        self.assertTrue(usage.has_signal(p))
        picks = usage.candidates(p, FIXTURE["entries"] + catalog.validate({"entries": EXTRA})["entries"],
                                 exclude=set())
        names = [x["name"] for x in picks]
        self.assertIn("kube-helper", names)
        self.assertIn("injection-guard", names)
        self.assertIn("spotify", names)
        ev = {x["name"]: x["evidence"] for x in picks}
        self.assertIn("you told scout you're into kubernetes", ev["kube-helper"].lower())
        self.assertIn("Hermes memory mentions security", ev["injection-guard"])
        self.assertFalse(ev["kube-helper"].startswith("In the last"))  # no history claimed

    def test_history_and_memory_evidence_together(self):
        p = usage.add_signals(usage.build_profile(_sample(), now=NOW), memory_text=MEMORY)
        music = [x for x in usage.candidates(p, FIXTURE["entries"], exclude=set()) if x["topic"] == "music"]
        self.assertIn("In the last 30 days music came up in 2 of your 2 conversations", music[0]["evidence"])
        self.assertIn("your Hermes memory mentions music", music[0]["evidence"])

    def test_ai_prompt_gets_counts_not_skill_names_or_memory(self):
        p = usage.add_signals(usage.build_profile(_sample(), now=NOW), memory_text=MEMORY, skills=SKILLS)
        pool = usage.candidates(p, FIXTURE["entries"], exclude=set())
        seen = []
        usage.rank_with_llm(p, pool, catalog.index(FIXTURE), ask=lambda q: seen.append(q) or "[]")
        self.assertNotIn("ai-news-digest", seen[0])
        self.assertNotIn("4321", seen[0])
        self.assertNotIn("plain English", seen[0])

    def test_interest_list_is_capped(self):
        p = usage.add_signals(_cold(), interests=[f"thing{i}" for i in range(50)])
        self.assertLessEqual(len(p["custom"]), usage.MAX_INTERESTS)


class DiversityTests(unittest.TestCase):
    def test_one_topic_cannot_fill_the_list(self):
        picks = [{"name": f"sec{i}", "topic": "security", "score": 10 - i} for i in range(5)]
        picks += [{"name": "news1", "topic": "news", "score": 3}, {"name": "web1", "topic": "web", "score": 2}]
        self.assertEqual([p["name"] for p in usage.diversify(picks, 3)], ["sec0", "news1", "web1"])

    def test_what_you_said_and_strong_matches_come_first(self):
        picks = [{"name": "wiki", "topic": "knowledge", "score": 30, "confidence": "early guess"},
                 {"name": "sec", "topic": "security", "score": 20, "confidence": "strong match"},
                 {"name": "wire", "topic": "news", "score": 10, "confidence": "strong match"},
                 {"name": "web", "topic": "web", "score": 25, "confidence": "strong match"}]
        got = [p["name"] for p in usage.diversify(picks, 3, prefer={"news", "security"})]
        self.assertEqual(got, ["sec", "wire", "web"])  # guess drops out; stated topics lead

    def test_fills_from_the_top_when_topics_run_out(self):
        picks = [{"name": f"sec{i}", "topic": "security", "score": 10 - i} for i in range(4)]
        self.assertEqual([p["name"] for p in usage.diversify(picks, 3)], ["sec0", "sec1", "sec2"])


class TextTests(unittest.TestCase):
    def test_picks_header_names_sources_and_tip_when_thin(self):
        p = usage.add_signals(_cold(), memory_text=MEMORY, skills=SKILLS)
        picks = usage.candidates(p, FIXTURE["entries"], exclude=set())[:3]
        text = report.picks_text(picks, p)
        self.assertIn("from your Hermes memory and your skills", text)
        self.assertIn("/scout interests", text)

    def test_profile_view_shows_where_each_signal_came_from(self):
        p = usage.add_signals(usage.build_profile(_sample(), now=NOW), memory_text=MEMORY,
                              skills=SKILLS, interests=["kubernetes"])
        text = report.profile_text(p)
        self.assertIn("History: 2 conversations", text)
        self.assertIn("music (strong signal): came up in 2 of 2 conversations; in your memory", text)
        self.assertIn("skill ai-news-digest", text)
        self.assertIn("kubernetes (strong signal): you told me", text)
        self.assertNotIn("4321", text)
        self.assertNotIn("play something", text)

    def test_nothing_at_all(self):
        self.assertIn("not enough to go on", report.picks_text([], _cold()))
        self.assertIn("nothing yet", report.profile_text(_cold()))


class InterestCommandTests(unittest.TestCase):
    def setUp(self):
        from test_hostile import _load_plugin_package
        self.plugin = _load_plugin_package()

        class State(dict):
            def set(self, k, v):
                self[k] = v
        import types
        self.ctx = types.SimpleNamespace(state=State(), llm=None)

    def test_add_list_and_clear(self):
        out = self.plugin.run_interests(self.ctx, " Spotify, Notion ,prompt injection")
        self.assertEqual(out["interests"], ["spotify", "notion", "prompt injection"])
        self.plugin.run_interests(self.ctx, "travel")
        self.assertEqual(self.ctx.state["interests"][-1], "travel")
        self.assertIn("cleared", self.plugin.run_interests(self.ctx, "clear")["text"])
        self.assertEqual(self.ctx.state["interests"], [])

    def test_hostile_interest_text_is_cleaned(self):
        out = self.plugin.run_interests(self.ctx, "music\x1b[2J, " + "x" * 500)
        self.assertTrue(all("\x1b" not in i and len(i) <= 40 for i in out["interests"]))


if __name__ == "__main__":
    unittest.main()
