"""Tests for drf_mcp.views — IsOAuth2Authenticated."""

import unittest
from unittest.mock import Mock

from drf_mcp.views import IsOAuth2Authenticated


class TestIsOAuth2Authenticated(unittest.TestCase):
    """Test the IsOAuth2Authenticated permission class."""

    def setUp(self):
        self.permission = IsOAuth2Authenticated()
        self.view = Mock()

    def _make_request(self, is_authenticated=True, is_active=True, has_app=True):
        request = Mock()
        request.user.is_authenticated = is_authenticated
        request.user.is_active = is_active
        if has_app:
            request.auth.application = Mock()
        else:
            request.auth = Mock(spec=[])  # no .application attr
        return request

    def test_allows_authenticated_oauth_user(self):
        request = self._make_request()
        self.assertTrue(self.permission.has_permission(request, self.view))

    def test_denies_unauthenticated_user(self):
        request = self._make_request(is_authenticated=False)
        self.assertFalse(self.permission.has_permission(request, self.view))

    def test_denies_inactive_user(self):
        request = self._make_request(is_active=False)
        self.assertFalse(self.permission.has_permission(request, self.view))

    def test_denies_user_without_oauth_application(self):
        request = self._make_request(has_app=False)
        self.assertFalse(self.permission.has_permission(request, self.view))

    def test_denies_anonymous_user(self):
        request = Mock()
        request.user.is_authenticated = False
        request.user.is_active = False
        request.auth = None
        self.assertFalse(self.permission.has_permission(request, self.view))
