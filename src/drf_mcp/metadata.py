"""OAuth 2.0 metadata views for MCP servers (RFC 8414 / RFC 9728).

Configure via DRF_MCP in Django settings:

    DRF_MCP = {
        "RESOURCE_URL": "https://example.com",
        "AUTHORIZATION_ENDPOINT": "https://example.com/o/authorize/",
        "TOKEN_ENDPOINT": "https://example.com/o/token/",
        "REGISTRATION_ENDPOINT": "https://example.com/mcp/register/",
        "SCOPES": ["read:api", "create:api"],
    }
"""

from django.http import JsonResponse
from django.views import View

from drf_mcp.views import get_setting


class ProtectedResourceMetadataView(View):
    """OAuth 2.0 Protected Resource Metadata (RFC 9728).

    Serves /.well-known/oauth-protected-resource
    Tells MCP clients where to find the authorization server.
    """

    def get(self, request):
        resource_url = get_setting("RESOURCE_URL")
        resource_path = get_setting("RESOURCE_PATH", "/api/mcp/")
        return JsonResponse({
            "resource": f"{resource_url}{resource_path}",
            "authorization_servers": [resource_url],
        })


class AuthorizationServerMetadataView(View):
    """OAuth 2.0 Authorization Server Metadata (RFC 8414).

    Serves /.well-known/oauth-authorization-server
    Tells MCP clients how to authenticate.
    """

    def get(self, request):
        resource_url = get_setting("RESOURCE_URL")
        return JsonResponse({
            "issuer": resource_url,
            "authorization_endpoint": get_setting("AUTHORIZATION_ENDPOINT"),
            "token_endpoint": get_setting("TOKEN_ENDPOINT"),
            "registration_endpoint": get_setting("REGISTRATION_ENDPOINT"),
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": get_setting("SCOPES", []),
        })
