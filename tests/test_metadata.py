"""Tests for drf_mcp.metadata — OAuth metadata views."""

import json
import unittest

from django.test import RequestFactory

from drf_mcp.metadata import (
    AuthorizationServerMetadataView,
    ProtectedResourceMetadataView,
)


class TestProtectedResourceMetadata(unittest.TestCase):
    """Test ProtectedResourceMetadataView (RFC 9728)."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_returns_resource_and_auth_server(self):
        request = self.factory.get("/.well-known/oauth-protected-resource")
        response = ProtectedResourceMetadataView.as_view()(request)
        data = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        # No trailing slash: the MCP spec asks for that form for
        # interoperability, even though RESOURCE_PATH carries one.
        self.assertEqual(data["resource"], "https://example.com/api/mcp")
        self.assertEqual(data["authorization_servers"], ["https://example.com"])

    def test_advertises_supported_scopes(self):
        request = self.factory.get("/.well-known/oauth-protected-resource")
        response = ProtectedResourceMetadataView.as_view()(request)
        data = json.loads(response.content)

        self.assertEqual(data["scopes_supported"], ["read", "write"])

    def test_path_aware_url_echoes_requested_path(self):
        """RFC 9728 s3.3: ``resource`` must equal the identifier the client used.

        A client configured with the trailing-slash spelling inserts the
        well-known suffix into that spelling, so the document served there has
        to echo it back or the client rejects the document.
        """
        for requested, expected in [
            ("api/mcp", "https://example.com/api/mcp"),
            ("api/mcp/", "https://example.com/api/mcp/"),
        ]:
            with self.subTest(requested=requested):
                request = self.factory.get(
                    f"/.well-known/oauth-protected-resource/{requested}"
                )
                response = ProtectedResourceMetadataView.as_view()(
                    request, resource_path=requested
                )
                data = json.loads(response.content)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(data["resource"], expected)
                self.assertEqual(
                    data["authorization_servers"], ["https://example.com"]
                )

    def test_content_type_is_json(self):
        request = self.factory.get("/.well-known/oauth-protected-resource")
        response = ProtectedResourceMetadataView.as_view()(request)
        self.assertEqual(response["Content-Type"], "application/json")


class TestAuthorizationServerMetadata(unittest.TestCase):
    """Test AuthorizationServerMetadataView (RFC 8414)."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_returns_all_required_fields(self):
        request = self.factory.get("/.well-known/oauth-authorization-server")
        response = AuthorizationServerMetadataView.as_view()(request)
        data = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["issuer"], "https://example.com")
        self.assertEqual(
            data["authorization_endpoint"], "https://example.com/o/authorize/"
        )
        self.assertEqual(data["token_endpoint"], "https://example.com/o/token/")
        self.assertEqual(
            data["registration_endpoint"], "https://example.com/mcp/register/"
        )
        self.assertEqual(data["response_types_supported"], ["code"])
        self.assertEqual(
            data["grant_types_supported"], ["authorization_code", "refresh_token"]
        )
        self.assertEqual(data["code_challenge_methods_supported"], ["S256"])
        self.assertEqual(data["token_endpoint_auth_methods_supported"], ["none"])
        self.assertEqual(data["scopes_supported"], ["read", "write"])
