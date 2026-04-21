"""OAuth 2.0 metadata views for MCP servers (RFC 8414 / RFC 9728).

URLs in the responses are derived from the incoming request by default,
so the same deployment can be served from multiple hostnames (tunnels,
staging, production) without reconfiguration.

Individual URLs can still be overridden via DRF_MCP in Django settings:

    DRF_MCP = {
        "RESOURCE_URL": "https://example.com",                       # overrides host derivation
        "RESOURCE_PATH": "/api/mcp/",                                # default: /api/mcp/
        "AUTHORIZATION_ENDPOINT": "https://example.com/o/authorize/",
        "TOKEN_ENDPOINT": "https://example.com/o/token/",
        "REGISTRATION_ENDPOINT": "https://example.com/mcp/register/",
        "SCOPES": ["read:api", "create:api"],
    }
"""

from django.http import JsonResponse
from django.views import View

from drf_mcp.views import get_setting


def _base_url(request):
    """Return the base URL the metadata should advertise.

    Prefers an explicit DRF_MCP["RESOURCE_URL"] setting when present so a
    deployment can pin its canonical hostname. Otherwise derives scheme +
    host from the request, matching whatever URL the client used to reach
    the metadata endpoint.
    """
    override = get_setting("RESOURCE_URL")
    if override:
        return override.rstrip("/")
    return f"{request.scheme}://{request.get_host()}"


class ProtectedResourceMetadataView(View):
    """OAuth 2.0 Protected Resource Metadata (RFC 9728).

    Serves /.well-known/oauth-protected-resource
    Tells MCP clients where to find the authorization server.
    """

    def get(self, request):
        base = _base_url(request)
        resource_path = get_setting("RESOURCE_PATH", "/api/mcp/")
        return JsonResponse({
            "resource": f"{base}{resource_path}",
            "authorization_servers": [base],
        })


class AuthorizationServerMetadataView(View):
    """OAuth 2.0 Authorization Server Metadata (RFC 8414).

    Serves /.well-known/oauth-authorization-server
    Tells MCP clients how to authenticate.
    """

    def get(self, request):
        base = _base_url(request)
        return JsonResponse({
            "issuer": base,
            "authorization_endpoint": get_setting("AUTHORIZATION_ENDPOINT") or f"{base}/api/o/authorize/",
            "token_endpoint":         get_setting("TOKEN_ENDPOINT")         or f"{base}/api/o/token/",
            "registration_endpoint":  get_setting("REGISTRATION_ENDPOINT")  or f"{base}/api/mcp/register/",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": get_setting("SCOPES", []),
        })
