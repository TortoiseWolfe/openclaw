#!/usr/bin/env python3
"""Tests for render_video argument handling (props file containment, composition id)."""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_video  # noqa: E402


class TestRenderVideoArgs(unittest.TestCase):
    def _run(self, argv, render_result=None):
        render = mock.Mock(return_value=render_result or {"success": False, "error": "stop"})
        with mock.patch.object(sys, "argv", ["render_video.py"] + argv), \
             mock.patch.object(render_video.remotion_client, "render", render), \
             mock.patch.object(render_video.os, "makedirs"):
            with self.assertRaises(SystemExit) as cm:
                render_video.main()
        return cm.exception.code, render

    def test_props_file_under_tmp_is_read(self):
        with tempfile.NamedTemporaryFile("w", dir="/tmp", suffix=".json", delete=False) as f:
            json.dump({"title": "Let's build it"}, f)
        try:
            code, render = self._run(["--composition", "EpisodeCard", "--props-file", f.name])
        finally:
            os.unlink(f.name)
        self.assertEqual(code, 1)  # stopped by the mocked failed render, after parsing
        self.assertEqual(render.call_args[0][1], {"title": "Let's build it"})

    def test_props_file_outside_allowed_dirs_refused(self):
        code, render = self._run(["--composition", "EpisodeCard", "--props-file", "/etc/hostname"])
        self.assertEqual(code, 2)
        render.assert_not_called()

    def test_bad_composition_refused(self):
        for comp in ("../../x", "Episode Card", "", "x" * 65):
            code, render = self._run(["--composition", comp])
            self.assertEqual(code, 2, comp)
            render.assert_not_called()


if __name__ == "__main__":
    unittest.main()
