#!/usr/bin/env python3
"""Tests for rpg_state.py CP and crawl input validation (temp state dir)."""

import argparse
import json
import os
import tempfile
import unittest
from unittest import mock

import rpg_state


class _StateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        state_dir = os.path.join(self.tmp.name, "state")
        os.makedirs(state_dir)
        self.state_file = os.path.join(state_dir, "game-state.json")
        for name, val in (("STATE_DIR", state_dir), ("STATE_FILE", self.state_file)):
            p = mock.patch.object(rpg_state, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.write({
            "session": {"scene": "x"},
            "players": {"viewer1": {"character": "Kira Voss", "character_points": 5}},
        })

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, state):
        with open(self.state_file, "w") as f:
            json.dump(state, f)

    def read(self):
        with open(self.state_file) as f:
            return json.load(f)


class TestCpAmounts(_StateCase):
    def _args(self, points):
        return argparse.Namespace(character="Kira Voss", points=points)

    def test_award_ok(self):
        rpg_state.cmd_award_cp(self._args(3))
        self.assertEqual(self.read()["players"]["viewer1"]["character_points"], 8)

    def test_spend_ok(self):
        rpg_state.cmd_spend_cp(self._args(2))
        self.assertEqual(self.read()["players"]["viewer1"]["character_points"], 3)

    def test_award_rejects_bad_amounts(self):
        for pts in (0, -5, rpg_state._MAX_CP_CHANGE + 1, 10**9):
            with self.assertRaises(SystemExit, msg=str(pts)):
                rpg_state.cmd_award_cp(self._args(pts))
        self.assertEqual(self.read()["players"]["viewer1"]["character_points"], 5)

    def test_spend_rejects_negative_and_zero(self):
        for pts in (0, -3, rpg_state._MAX_CP_CHANGE + 1):
            with self.assertRaises(SystemExit, msg=str(pts)):
                rpg_state.cmd_spend_cp(self._args(pts))
        self.assertEqual(self.read()["players"]["viewer1"]["character_points"], 5)

    def test_award_at_cap_ok(self):
        rpg_state.cmd_award_cp(self._args(rpg_state._MAX_CP_CHANGE))
        self.assertEqual(self.read()["players"]["viewer1"]["character_points"], 55)


class TestSetCrawl(_StateCase):
    def _args(self, **kw):
        base = dict(title=None, subtitle=None, episode=None, episode_title=None, text=None)
        base.update(kw)
        return argparse.Namespace(**base)

    def test_normal_crawl(self):
        rpg_state.cmd_set_crawl(self._args(title="T", text="one | two"))
        crawl = self.read()["crawl"]
        self.assertEqual(crawl["title"], "T")
        self.assertEqual(crawl["paragraphs"], ["one", "two"])

    def test_too_long_rejected_and_state_untouched(self):
        with self.assertRaises(SystemExit):
            rpg_state.cmd_set_crawl(self._args(text="x" * 2001))
        self.assertNotIn("crawl", self.read())

    def test_total_across_fields_counted(self):
        with self.assertRaises(SystemExit):
            rpg_state.cmd_set_crawl(self._args(title="a" * 1000, text="b" * 1001))

    def test_at_limit_ok(self):
        rpg_state.cmd_set_crawl(self._args(text="x" * 2000))
        self.assertIn("crawl", self.read())


class TestNameValidators(unittest.TestCase):
    def test_slug_rejects_trailing_newline_and_separators(self):
        self.assertEqual(rpg_state._validate_slug("mos-eisley", "x"), "mos-eisley")
        for bad in ("mos-eisley\n", "../x", "a/b", "", "a b"):
            with self.assertRaises(SystemExit, msg=repr(bad)):
                rpg_state._validate_slug(bad, "x")

    def test_map_filename_checks_extension_too(self):
        for ok in ("mos-eisley-streets.svg", "cantina.png", "mos-eisley-streets-1.png"):
            self.assertEqual(rpg_state._validate_map_filename(ok, "map"), ok)
        for bad in ("map.svg/../../x", "map.svg\n", "../map.svg", "map", "map.exe", "a.b.svg"):
            with self.assertRaises(SystemExit, msg=repr(bad)):
                rpg_state._validate_map_filename(bad, "map")


if __name__ == "__main__":
    unittest.main()
