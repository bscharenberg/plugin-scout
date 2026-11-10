"""Dashboard routes: choices save, dismissals are validated, failures degrade to a readable page."""

import importlib.util
import json
import logging
import sys
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


class _Router:  # stand-in for fastapi.APIRouter: routes are plain functions here
    def get(self, *_a, **_k):
        return lambda fn: fn

    post = get


class _State(dict):
    def set(self, k, v):
        self[k] = v


STATE = _State()


def _load_api():
    sys.modules.setdefault("fastapi", types.SimpleNamespace(APIRouter=_Router))
    ps = types.ModuleType("hermes_cli.plugins_state")
    ps.PluginState = lambda plugin_id: STATE
    sys.modules.setdefault("hermes_cli", types.ModuleType("hermes_cli"))
    sys.modules["hermes_cli.plugins_state"] = ps
    spec = importlib.util.spec_from_file_location("scout_dashboard_api", ROOT / "dashboard" / "plugin_api.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DashboardApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = _load_api()
        logging.disable(logging.CRITICAL)  # expected "catalog unavailable" errors stay out of the output

    @classmethod
    def tearDownClass(cls):
        logging.disable(logging.NOTSET)

    def setUp(self):
        STATE.clear()

    def test_choice_buttons_replace_earlier_answers(self):
        STATE.set("interests", ["kubernetes"])
        out = self.api.set_interests({"jobs": [1, 10]})
        self.assertEqual(out["selected_jobs"], [1, 10])
        self.assertNotIn("kubernetes", STATE["interests"])
        self.api.set_interests({"jobs": ["99", "x"]})  # junk is ignored, not stored
        self.assertEqual(STATE.get("interests"), [])

    def test_dismiss_only_accepts_real_plugin_names(self):
        self.api.dismiss({"name": "spotify"})
        self.api.dismiss({"name": "../../etc; rm -rf ~"})
        self.assertEqual(STATE.get("dismissed"), ["spotify"])

    def test_page_still_renders_without_catalog(self):
        out = self.api.overview()  # outside Hermes the catalog cannot load
        self.assertEqual(out["picks"], [])
        self.assertTrue(out["error"])
        self.assertEqual(len(out["jobs"]), 10)
        json.dumps(out)  # everything the page gets is plain JSON


class DashboardFilesTests(unittest.TestCase):
    def test_manifest_and_page(self):
        manifest = json.loads((ROOT / "dashboard" / "manifest.json").read_text())
        self.assertEqual(manifest["name"], "plugin-scout")
        self.assertEqual(manifest["api"], "plugin_api.py")
        self.assertEqual(manifest["css"], "dist/style.css")
        css = (ROOT / "dashboard" / "dist" / "style.css").read_text()
        self.assertIn("var(--color-border)", css)  # follows the active Hermes theme
        self.assertNotIn(".ha-", css)  # its own class names; never restyles other tabs
        page = (ROOT / "dashboard" / "dist" / "index.js").read_text()
        self.assertIn('register("plugin-scout"', page)
        self.assertNotIn("dangerouslySetInnerHTML", page)  # text only, never raw HTML
        self.assertNotIn("innerHTML", page)


if __name__ == "__main__":
    unittest.main()
