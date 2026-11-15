"""Tests for step 4. No API key needed: a fake model stands in for Gemini.

  python -m unittest discover tests

Code style: no f-strings, lists instead of tuples.
"""
import json
import os
import shutil
import tempfile
import unittest

from pipeline import explainer, cache
from pipeline.personas import make_profile

HERE = os.path.dirname(__file__)
FEED = os.path.join(HERE, "..", "data", "2026_02_IND_KC_feed.json")


def kelce_td():
    with open(FEED) as f:
        for play in json.load(f):
            if int(play["play_id"]) == 663:
                return play


class FakeModel:
    """Replaces the real AI call and counts how often it is used."""
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0
        self.prompts = []

    def __call__(self, prompt, provider, model=None, attempts=4):
        self.calls = self.calls + 1
        self.prompts.append(prompt)
        return json.dumps(self.reply)


GOOD = {
    "headline": "Kelce scores for the Chiefs!",
    "what_happened": "P.Mahomes threw a 13-yard pass to T.Kelce in the end zone for a touchdown.",
    "who": "P.Mahomes threw it and T.Kelce caught it.",
    "why_it_matters": "Kansas City jumps ahead, and their win chance goes up.",
    "pop_culture": "Taylor pointed to her ring and yelled \"That's my husband!\"",
}


class ExplainerTests(unittest.TestCase):
    def setUp(self):
        self.play = kelce_td()
        self.context = explainer.load_context("2026_02_IND_KC")
        self.tmp = tempfile.mkdtemp()
        self.saved_dir = cache.CACHE_DIR
        cache.CACHE_DIR = self.tmp
        self.saved_call = explainer.call_with_retry

    def tearDown(self):
        explainer.call_with_retry = self.saved_call
        cache.CACHE_DIR = self.saved_dir
        shutil.rmtree(self.tmp)

    def run_with(self, reply, persona="swiftie", notes=None):
        fake = FakeModel(reply)
        explainer.call_with_retry = fake
        out = explainer.explain(self.play, make_profile(persona, notes=notes), provider="gemini", context=self.context)
        return [out, fake]

    def test_good_answer_is_used_and_facts_come_from_data(self):
        reply = dict(GOOD)
        reply["verdict"] = "hurt"  # the model saying the wrong thing must not matter
        out, fake = self.run_with(reply)
        self.assertEqual(out["source"], "gemini")
        self.assertEqual(out["verdict"], "helped")
        self.assertEqual([p["name"] for p in out["players"]], ["P.Mahomes", "T.Kelce"])
        self.assertEqual(len(out["read_more"]), 2)
        self.assertIn("husband", out["pop_culture"])

    def test_invented_player_falls_back(self):
        reply = dict(GOOD)
        reply["who"] = "P.Mahomes threw it to R.Rice."
        out, fake = self.run_with(reply)
        self.assertEqual(out["source"], "template (fallback)")
        self.assertIn("unknown player R.Rice", out["checks_failed"])

    def test_invented_number_falls_back(self):
        reply = dict(GOOD)
        reply["what_happened"] = "P.Mahomes threw a 47-yard touchdown to T.Kelce."
        out, fake = self.run_with(reply)
        self.assertEqual(out["source"], "template (fallback)")
        self.assertIn("unknown number 47", out["checks_failed"])

    def test_no_pop_culture_for_viewers_who_did_not_ask(self):
        out, fake = self.run_with(dict(GOOD), persona="new_fan")
        self.assertEqual(out["pop_culture"], "")
        self.assertEqual(out["read_more"], [])
        self.assertNotIn("Pop-culture note", fake.prompts[0])

    def test_chat_note_about_taylor_turns_pop_culture_on(self):
        out, fake = self.run_with(dict(GOOD), persona="new_fan", notes=["I mostly care about Taylor Swift"])
        self.assertIn("Pop-culture note", fake.prompts[0])
        self.assertIn("Viewer note: I mostly care about Taylor Swift", fake.prompts[0])
        self.assertIn("husband", out["pop_culture"])

    def test_second_ask_comes_from_the_cache(self):
        out1, fake = self.run_with(dict(GOOD))
        out2 = explainer.explain(self.play, make_profile("swiftie"), provider="gemini", context=self.context)
        self.assertEqual(fake.calls, 1)
        self.assertEqual(out2["source"], "gemini (cached)")

    def test_new_chat_note_asks_again(self):
        out1, fake = self.run_with(dict(GOOD))
        explainer.explain(self.play, make_profile("swiftie", notes=["explain penalties"]), provider="gemini", context=self.context)
        self.assertEqual(fake.calls, 2)

    def test_template_passes_its_own_checks_on_every_moment(self):
        with open(FEED) as f:
            plays = json.load(f)
        for play in plays:
            note = None
            entry = explainer.context_for(play, self.context)
            if entry:
                note = entry["note"]
            out = explainer.template_explanation(play, note)
            self.assertEqual(explainer.check_explanation(out, play, note), [], play["desc"])


if __name__ == "__main__":
    unittest.main()
