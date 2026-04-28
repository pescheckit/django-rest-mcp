"""Dynamic OAuth 2.0 Client Registration (RFC 7591) for MCP clients.

All MCP clients share a single :class:`Application` row whose name is
``"MCP Public Client"`` (seeded by the package's initial migration). Each
registration call merges the requested ``redirect_uris`` into that row's
allow-list so subsequent ``/o/authorize`` calls accept them under
django-oauth-toolkit's exact-match check.

Configuration via Django settings:

.. code-block:: python

    DRF_MCP = {
        # HTTPS hosts permitted to register a redirect_uri. A request's
        # hostname must equal one of the entries or end with "." + entry.
        # Loopback HTTP URIs (localhost / 127.0.0.1 / ::1) are always
        # allowed regardless of this list.
        "REGISTRATION_HTTPS_HOST_SUFFIXES": ["claude.ai", "anthropic.com"],
    }

The endpoint is intentionally open per RFC 7591. Hosts that want rate
limiting should subclass :class:`StaticClientRegistrationView` and apply
their own decorator, or rate-limit at the reverse-proxy layer.

Requires :mod:`oauth2_provider`; install ``django-rest-mcp[oauth]``.
"""
import ipaddress
import json
import logging
from urllib.parse import urlparse

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from drf_mcp.views import get_setting

logger = logging.getLogger(__name__)

MCP_APP_NAME = "MCP Public Client"


def _is_allowed_redirect_uri(uri, https_host_suffixes):
    """Allow loopback HTTP plus HTTPS to any host matching the allow-list."""
    try:
        parsed = urlparse(uri)
    except ValueError:
        return False
    scheme, host = parsed.scheme, parsed.hostname
    if not scheme or not host:
        return False
    if scheme == "http":
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False
    return scheme == "https" and any(
        host == s or host.endswith("." + s) for s in https_host_suffixes
    )


@method_decorator(csrf_exempt, name="dispatch")
class StaticClientRegistrationView(View):
    """RFC 7591 Dynamic Client Registration against a shared public app."""

    def post(self, request):
        try:
            body = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            return JsonResponse(
                {"error": "invalid_client_metadata",
                 "error_description": "Request body must be JSON"},
                status=400,
            )

        requested = body.get("redirect_uris") or []
        if not isinstance(requested, list) or not requested:
            return JsonResponse(
                {"error": "invalid_redirect_uri",
                 "error_description": "redirect_uris must be a non-empty array"},
                status=400,
            )

        suffixes = tuple(get_setting("REGISTRATION_HTTPS_HOST_SUFFIXES", ()))
        safe = [
            u for u in requested
            if isinstance(u, str) and _is_allowed_redirect_uri(u, suffixes)
        ]
        if not safe:
            logger.warning(
                "MCP registration rejected: no allowed redirect_uris in %r", requested
            )
            return JsonResponse(
                {"error": "invalid_redirect_uri",
                 "error_description": "No redirect_uri matched the allow-list"},
                status=400,
            )

        from oauth2_provider.models import get_application_model

        Application = get_application_model()
        app, created = Application.objects.get_or_create(
            name=MCP_APP_NAME,
            defaults={
                "client_type": "public",
                "authorization_grant_type": "authorization-code",
                "client_secret": "",
                "redirect_uris": "",
                "skip_authorization": False,
            },
        )
        if created:
            logger.warning(
                "MCP Public Client auto-created (drf_mcp seed migration did not run)"
            )

        existing = set(app.redirect_uris.split()) if app.redirect_uris else set()
        merged = existing | set(safe)
        if merged != existing:
            app.redirect_uris = " ".join(sorted(merged))
            app.save(update_fields=["redirect_uris"])
            logger.info(
                "MCP Public Client redirect_uris extended with %s",
                sorted(set(safe) - existing),
            )

        return JsonResponse({
            "client_id": app.client_id,
            "client_name": app.name,
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "redirect_uris": safe,
        }, status=201)
