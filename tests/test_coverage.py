"""Topics added after the catalog passed 2,100 plugins: real wording matches, look-alike wording does not.

Every look-alike below was a wrong match found by scanning the live catalog on Nov 12, 2026.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import usage  # noqa: E402
from test_usage import NOW  # noqa: E402


def _entry(description, name="example", category="tools"):
    return {"name": name, "title": "", "description": description, "category": category}


def _topics(entry):
    return {t for t in usage.TOPICS if usage._match_strength(t, entry)}


def _session(text):
    return ({"id": "s1", "last_active": NOW - 86400, "source": "cli"},
            [{"role": "user", "content": text}])


class CatalogMatches(unittest.TestCase):
    def test_new_topics_find_their_plugins(self):
        cases = {
            "games": "Lets Hermes agents drive a live Godot 4 editor through a local MCP server.",
            "design": "Read and comment on Figma files, and turn frames into mockups.",
            "audio": "Offline sound effects generation and QA. Writes WAV files.",
            "data": "Ask questions in plain words and get SQL against your own warehouse.",
            "business": "Kleos, the AI marketing team for small businesses.",
            "legal": "Japanese laws for Hermes Agent, built on the e-Gov Law API.",
            "health": "Considerate health context: barometric pressure and medication reminders.",
            "food": "Compare restaurants using local recommendations.",
            "weather": "Weather data, radar imagery and forecasts.",
            "models": "TeamoRouter as Hermes model providers on one key.",
            "token costs": "Live token usage, model-aware USD cost and prompt-cache savings.",
            "tasks": "A day and week planner for people whose discipline cannot be the plan.",
            "coding": "Run tests in Docker before every deploy.",
            "security": "Deterministic allow/approve/block tool-call policies for Hermes.",
        }
        for topic, text in cases.items():
            self.assertIn(topic, _topics(_entry(text)), topic)

    def test_catalog_category_counts_for_hermes_plugins(self):
        self.assertIn("hermes desktop", _topics(_entry("A calmer chat list.", category="desktop")))
        self.assertIn("models", _topics(_entry("Serves Claude over one key.", category="models")))
        self.assertNotIn("hermes desktop", _topics(_entry("A calmer chat list.", category="tools")))

    def test_look_alike_wording_is_not_a_match(self):
        cases = {
            "legal": "Native TUI tabs when the public core capability contract is advertised.",
            "business": "Resolve environment variables at startup from one encrypted file.",
            "health": "Run hermes doctor and report topic health and provider health checks.",
            "data": "Local-first memory layer backed by SQLite with hybrid recall.",
            "tasks": "Habits gives Hermes reflexes: the tool calls it repeats, grouped.",
            "food": "Genealogy research recipes for family history.",
            "coding": "One durable memory shared by Hermes, Claude Code and Codex.",
            "security": "Messenger gateway with media attachments and allowlists.",
        }
        for topic, text in cases.items():
            self.assertNotIn(topic, _topics(_entry(text)), f"{topic}: {text}")


class UserWording(unittest.TestCase):
    def test_new_topics_read_real_sentences(self):
        cases = {
            "games": "help me make a level in godot",
            "design": "make a logo for my bakery in figma",
            "audio": "edit my podcast intro",
            "data": "write a sql query for my sales table",
            "business": "draft a marketing plan for my small business",
            "legal": "when are my taxes due",
            "health": "track my sleep tracking data and diet",
            "food": "find a recipe for dinner",
            "weather": "will it rain tomorrow",
            "models": "should I use ollama or openrouter",
            "token costs": "my token usage is too high this week",
            "hermes desktop": "can I get dark mode in hermes desktop",
            "tasks": "plan my week around my goals",
        }
        for topic, text in cases.items():
            self.assertIn(topic, usage.build_profile([_session(text)], now=NOW)["topics"], topic)

    def test_everyday_words_stay_out(self):
        quiet = usage.build_profile([_session("I baked cookies and the server health check passed")], now=NOW)
        self.assertNotIn("food", quiet["topics"])
        self.assertNotIn("health", quiet["topics"])


class Onboarding(unittest.TestCase):
    def test_every_choice_at_once_fits(self):
        words = usage.job_words(range(1, len(usage.JOBS) + 1))
        self.assertLessEqual(len(words), usage.MAX_INTERESTS)

    def test_choices_reach_the_new_topics(self):
        topics = usage.add_signals(usage.build_profile([], now=NOW),
                                   interests=usage.job_words(range(1, len(usage.JOBS) + 1)))["topics"]
        for t in ("design", "games", "health", "models", "hermes desktop", "food", "legal", "data", "token costs"):
            self.assertIn(t, topics, t)


if __name__ == "__main__":
    unittest.main()
