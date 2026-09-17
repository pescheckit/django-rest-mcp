"""Tests for drf_mcp.views — IsOAuth2Authenticated and the 401/403 challenge."""

import unittest
from unittest.mock import Mock

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import NotAuthenticated, PermissionDenied
from rest_framework.test import APIRequestFactory

from drf_mcp.views import (
    IsOAuth2Authenticated,
    MCPView,
    resource_metadata_url,
)


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


class TestResourceMetadataURL(unittest.TestCase):
    """RFC 9728 s3.1 puts the well-known suffix between host and path."""

    def test_inserts_suffix_between_host_and_resource_path(self):
        self.assertEqual(
            resource_metadata_url(),
            "https://example.com/.well-known/oauth-protected-resource/api/mcp",
        )


class TestAuthChallenge(unittest.TestCase):
    """The 401/403 responses must tell a client where the metadata lives.

    Without this header a client has to guess the metadata URL, and the guess
    that RFC 9728 mandates is the path-aware one most servers never serve.
    """

    def setUp(self):
        self.factory = APIRequestFactory()

    def _challenge(self, exc):
        # DRF downgrades a 401 to 403 unless some authenticator offers a
        # challenge header, so stand in for the OAuth2 authenticator that
        # a real deployment configures.
        class _BearerAuth(BaseAuthentication):
            def authenticate(self, request):
                return None

            def authenticate_header(self, request):
                return 'Bearer realm="api"'

        class _View(MCPView):
            authentication_classes = [_BearerAuth]

        view = _View()
        view.request = self.factory.post("/api/mcp/")
        view.headers = {}
        response = view.handle_exception(exc)
        return response.status_code, response.get("WWW-Authenticate", "")

    def test_401_points_at_path_aware_metadata(self):
        status, challenge = self._challenge(NotAuthenticated())
        self.assertEqual(status, 401)
        self.assertIn(
            'resource_metadata="https://example.com'
            '/.well-known/oauth-protected-resource/api/mcp"',
            challenge,
        )

    def test_401_advertises_scopes(self):
        _, challenge = self._challenge(NotAuthenticated())
        self.assertIn('scope="read write"', challenge)

    def test_403_carries_the_same_hint(self):
        status, challenge = self._challenge(PermissionDenied())
        self.assertEqual(status, 403)
        self.assertIn("resource_metadata=", challenge)

    def test_403_does_not_claim_insufficient_scope(self):
        """A 403 here is usually non-OAuth2 auth, which re-authorising cannot fix."""
        _, challenge = self._challenge(PermissionDenied())
        self.assertNotIn("insufficient_scope", challenge)
