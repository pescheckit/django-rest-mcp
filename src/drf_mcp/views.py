from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.permissions import BasePermission
from rest_framework.views import APIView


def get_setting(key, default=None):
    """Read a setting from Django's DRF_MCP settings dict."""
    return getattr(settings, "DRF_MCP", {}).get(key, default)


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
        response = super().handle_exception(exc)
        if response.status_code == 401:
            resource_url = get_setting("RESOURCE_URL")
            if resource_url:
                response["WWW-Authenticate"] = (
                    f'Bearer resource_metadata="{resource_url}/.well-known/oauth-protected-resource"'
                )
        return response

    def post(self, request):
        return self.mcp_server.handle_request(request)

    def get(self, request):
        return self.mcp_server.handle_request(request)

    def delete(self, request):
        return self.mcp_server.handle_request(request)
