from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.permissions import BasePermission
from rest_framework.views import APIView


def get_setting(key, default=None):
    """Read a setting from Django's DRF_MCP settings dict."""
    return getattr(settings, "DRF_MCP", {}).get(key, default)


def base_url(request=None):
    """Return the base URL that OAuth metadata should advertise.

    Prefers an explicit DRF_MCP["RESOURCE_URL"] so a deployment can pin its
    canonical hostname; otherwise derives scheme + host from the request so
    tunnels and staging hosts work without reconfiguration.
    """
    override = get_setting("RESOURCE_URL")
    if override:
        return override.rstrip("/")
    if request is None:
        return ""
    return f"{request.scheme}://{request.get_host()}"


def canonical_resource(request=None):
    """The canonical resource identifier for this MCP server.

    The MCP spec asks implementations to use the form without a trailing
    slash, so RESOURCE_PATH is normalised here even though it conventionally
    carries one (Django route).
    """
    base = base_url(request)
    if not base:
        return ""
    return f"{base}{get_setting('RESOURCE_PATH', '/api/mcp/').rstrip('/')}"


def resource_metadata_url(request=None):
    """Protected Resource Metadata URL for this server (RFC 9728 s3.1).

    The well-known suffix is inserted *between* host and resource path, so a
    server at /api/mcp publishes at /.well-known/oauth-protected-resource
    /api/mcp, not at the bare well-known root.
    """
    base = base_url(request)
    if not base:
        return ""
    path = get_setting("RESOURCE_PATH", "/api/mcp/").rstrip("/")
    return f"{base}/.well-known/oauth-protected-resource{path}"


class IsOAuth2Authenticated(BasePermission):
    """Checks that the request is authenticated via OAuth2 (has an application on the token)."""

    def has_permission(self, request, view):
        return (
            hasattr(request, "user")
            and request.user.is_authenticated
            and request.user.is_active
            and hasattr(request.auth, "application")
        )


@method_decorator(csrf_exempt, name="dispatch")
class MCPView(APIView):
    """
    Base view for MCP protocol handling.

    Set `mcp_server` to your DRFMCP instance. Optionally configure
    DRF_MCP settings in Django settings for automatic WWW-Authenticate headers.

    Usage:
        class MyMCPView(MCPView):
            mcp_server = mcp
            permission_classes = [IsOAuth2Authenticated]
    """

    mcp_server = None

    def handle_exception(self, exc):
        """Attach the RFC 9728 discovery challenge to auth failures.

        Without ``resource_metadata`` a client has to guess where the metadata
        lives, and the guess that the spec mandates (the path-aware URL) is the
        one most deployments forget to serve. ``scope`` is advertised too so a
        client can ask for the right scopes on its first attempt.

        403 carries the same hint for consistency with 401, but deliberately
        does *not* claim ``error="insufficient_scope"``: a 403 here usually
        means the caller authenticated by some means other than OAuth2 (a
        session cookie, say), and sending it round a re-authorisation loop
        would not fix that.
        """
        response = super().handle_exception(exc)
        if response.status_code in (401, 403):
            metadata_url = resource_metadata_url(getattr(self, "request", None))
            if metadata_url:
                challenge = [f'Bearer resource_metadata="{metadata_url}"']
                scopes = get_setting("SCOPES", [])
                if scopes:
                    challenge.append(f'scope="{" ".join(scopes)}"')
                response["WWW-Authenticate"] = ", ".join(challenge)
        return response

    def post(self, request):
        return self.mcp_server.handle_request(request)

    def get(self, request):
        return self.mcp_server.handle_request(request)

    def delete(self, request):
        return self.mcp_server.handle_request(request)
