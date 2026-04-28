"""Tests for drf_mcp.registration — DCR allow-list helper."""

import unittest

from drf_mcp.registration import _is_allowed_redirect_uri


class TestIsAllowedRedirectUri(unittest.TestCase):
    """Loopback HTTP plus HTTPS hosts matching the allow-list."""

    SUFFIXES = ("claude.ai", "anthropic.com")

    def test_allows_localhost_any_port(self):
        self.assertTrue(_is_allowed_redirect_uri("http://localhost", self.SUFFIXES))
        self.assertTrue(_is_allowed_redirect_uri("http://localhost:5678/cb", self.SUFFIXES))

    def test_allows_loopback_ipv4(self):
        self.assertTrue(_is_allowed_redirect_uri("http://127.0.0.1:8000/cb", self.SUFFIXES))

    def test_allows_loopback_ipv6(self):
        self.assertTrue(_is_allowed_redirect_uri("http://[::1]:8000/cb", self.SUFFIXES))

    def test_rejects_non_loopback_http(self):
        self.assertFalse(_is_allowed_redirect_uri("http://example.com/cb", self.SUFFIXES))
        self.assertFalse(_is_allowed_redirect_uri("http://10.0.0.1/cb", self.SUFFIXES))

    def test_allows_https_exact_host(self):
        self.assertTrue(_is_allowed_redirect_uri("https://claude.ai/cb", self.SUFFIXES))

    def test_allows_https_subdomain(self):
        self.assertTrue(_is_allowed_redirect_uri("https://app.claude.ai/cb", self.SUFFIXES))
        self.assertTrue(_is_allowed_redirect_uri("https://foo.bar.anthropic.com/cb", self.SUFFIXES))

    def test_rejects_https_lookalike(self):
        # "evilclaude.ai" must not be accepted just because it ends with "claude.ai"
        self.assertFalse(_is_allowed_redirect_uri("https://evilclaude.ai/cb", self.SUFFIXES))

    def test_rejects_https_unknown_host(self):
        self.assertFalse(_is_allowed_redirect_uri("https://example.com/cb", self.SUFFIXES))

    def test_rejects_unknown_scheme(self):
        self.assertFalse(_is_allowed_redirect_uri("ftp://localhost/cb", self.SUFFIXES))

    def test_rejects_empty_suffix_list_for_https(self):
        self.assertFalse(_is_allowed_redirect_uri("https://claude.ai/cb", ()))

    def test_loopback_allowed_even_with_empty_suffix_list(self):
        self.assertTrue(_is_allowed_redirect_uri("http://localhost:1234/cb", ()))
