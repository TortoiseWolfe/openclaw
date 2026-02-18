#!/usr/bin/env python3
"""Tests for today_date.py"""

import unittest
from datetime import datetime, timezone
from unittest.mock import patch


class TestTodayDate(unittest.TestCase):
    @patch("today_date.datetime")
    def test_default_format_is_iso_date(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 2, 4, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        import today_date
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with patch("sys.argv", ["today_date.py"]), redirect_stdout(f):
            today_date.main()
        self.assertEqual(f.getvalue().strip(), "2026-02-04")

    @patch("today_date.datetime")
    def test_custom_format(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 2, 4, 12, 0, 0, tzinfo=timezone.utc)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        import today_date
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with patch("sys.argv", ["today_date.py", "--format", "%B %d, %Y"]), redirect_stdout(f):
            today_date.main()
        self.assertEqual(f.getvalue().strip(), "February 04, 2026")


if __name__ == "__main__":
    unittest.main()
