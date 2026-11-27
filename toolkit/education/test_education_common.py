#!/usr/bin/env python3
"""Tests for education_common.py URL allowlist."""

import unittest
from unittest import mock

import education_common
from education_common import _AllowlistRedirect, fetch_page, validate_url


class TestValidateUrl(unittest.TestCase):
    def test_allowed_hosts(self):
        for url in (
            "https://www.babypips.com/learn/forex/x",
            "https://babypips.com/a",
            "https://www.investopedia.com/terms/a/atr.asp",
            "https://www.tradingview.com/support/solutions/1",
        ):
            self.assertEqual(validate_url(url), url)

    def test_rejects_http(self):
        with self.assertRaises(ValueError):
            validate_url("http://www.babypips.com/a")

    def test_rejects_other_hosts(self):
        for url in (
            "https://evil.example/a",
            "https://www.babypips.com.evil.example/a",
            "https://evil.example/www.babypips.com",
            "https://user@evil.example/",
            "file:///etc/passwd",
            "https://169.254.169.254/latest/meta-data",
        ):
            with self.assertRaises(ValueError, msg=url):
                validate_url(url)


class TestFetchPage(unittest.TestCase):
    def test_disallowed_url_never_opened(self):
        with mock.patch.object(education_common, "_opener") as opener:
            with self.assertRaises(ValueError):
                fetch_page("https://evil.example/a", respect_robots=False)
        opener.open.assert_not_called()

    def test_redirect_off_allowlist_refused(self):
        handler = _AllowlistRedirect()
        with self.assertRaises(ValueError):
            handler.redirect_request(mock.Mock(), None, 302, "Found", {}, "https://evil.example/")
        with self.assertRaises(ValueError):
            handler.redirect_request(mock.Mock(), None, 302, "Found", {}, "http://www.babypips.com/")


if __name__ == "__main__":
    unittest.main()
