"""Tests for path_utils."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from path_utils import require_date, require_slug, safe_join


class TestSafeJoin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = os.path.realpath(self.tmp.name)
        self.outside = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()
        self.outside.cleanup()

    def test_normal_join(self):
        self.assertEqual(safe_join(self.base, "a", "b.mp4"), os.path.join(self.base, "a", "b.mp4"))

    def test_dotdot_escape(self):
        with self.assertRaises(ValueError):
            safe_join(self.base, "..", "etc")
        with self.assertRaises(ValueError):
            safe_join(self.base, "a/../../x")

    def test_inner_dotdot_ok(self):
        self.assertEqual(safe_join(self.base, "a/../b"), os.path.join(self.base, "b"))

    def test_absolute_part(self):
        with self.assertRaises(ValueError):
            safe_join(self.base, "/etc/passwd")

    def test_symlink_outside(self):
        os.symlink(self.outside.name, os.path.join(self.base, "link"))
        with self.assertRaises(ValueError):
            safe_join(self.base, "link", "file.txt")


class TestValidators(unittest.TestCase):
    def test_slug_accept(self):
        for v in ("a", "episode-1", "0abc", "a" * 64):
            self.assertEqual(require_slug(v, "series"), v)

    def test_slug_reject(self):
        for v in ("", "-a", "A", "a/b", "../x", "a b", "a" * 65, "a_b", "a\n"):
            with self.assertRaises(ValueError, msg=repr(v)) as cm:
                require_slug(v, "series")
            self.assertIn("series", str(cm.exception))

    def test_date(self):
        self.assertEqual(require_date("2026-10-24"), "2026-10-24")
        for v in ("2026-1-24", "../../x", "2026-10-24\n", "20261024", ""):
            with self.assertRaises(ValueError, msg=repr(v)):
                require_date(v)


if __name__ == "__main__":
    unittest.main()
