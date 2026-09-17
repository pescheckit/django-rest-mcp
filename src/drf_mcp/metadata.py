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

from drf_mcp.views import base_url, canonical_resource, get_setting


def _base_url(request):
    """Backwards-compatible alias for :func:`drf_mcp.views.base_url`."""
    return base_url(request)


class ProtectedResourceMetadataView(View):
    """OAuth 2.0 Protected Resource Metadata (RFC 9728).

    Serves both

    * /.well-known/oauth-protected-resource/<resource_path> - the path-aware
      URL required by RFC 9728 s3.1 whenever the resource identifier has a
      path component, and
    * /.well-known/oauth-protected-resource - the bare well-known root, kept
      for clients that only probe there.

    RFC 9728 s3.3 requires the ``resource`` value to be identical to the
    identifier into which the well-known suffix was inserted, and clients
    reject the document outright when it is not. So the path-aware route
    echoes back exactly the path it was asked for rather than a configured
    constant: that keeps both ``/api/mcp`` and ``/api/mcp/`` valid for
    whichever spelling a client was configured with.
    """

    def get(self, request, resource_path=None):
        base = _base_url(request)
        if resource_path is None:
            resource = canonical_resource(request)
        else:
            resource = f"{base}/{resource_path}"
        return JsonResponse({
            "resource": resource,
            "authorization_servers": [base],
            "scopes_supported": get_setting("SCOPES", []),
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
