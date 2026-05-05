"""Per-instance OAuth 2.0 Dynamic Client Registration (RFC 7591) for MCP.

Each ``POST /register`` creates a brand-new :class:`Application` row with
its own ``client_id`` and the redirect_uris from the request. The row
starts unbound (``user`` and ``organisation`` are NULL); it is bound to a
specific (user, organisation) on first successful consent
(:class:`drf_mcp.auth_views.MCPAuthorizationView`).

There is intentionally no shared "MCP Public Client" row — every MCP
client gets its own Application, so ``request.auth.application`` always
resolves to a tenant-scoped row once the client has been used.

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
limiting should subclass :class:`DynamicClientRegistrationView` and apply
their own decorator, or rate-limit at the reverse-proxy layer. Abandoned
registrations (created but never bound by a successful authorization)
should be reaped by a periodic job — see ``cleanup_unbound_mcp_apps`` in
the documentation for an example management command.

Requires :mod:`oauth2_provider`; install ``django-rest-mcp[oauth]``.
"""
import ipaddress
import json
import logging
import secrets
from urllib.parse import urlparse

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from drf_mcp.views import get_setting

logger = logging.getLogger(__name__)


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
class DynamicClientRegistrationView(View):
    """RFC 7591 Dynamic Client Registration creating per-instance Applications.

    Each call creates a new public Application row whose ``client_id`` and
    ``redirect_uris`` are returned to the caller. The row starts unbound
    (no ``user``, no ``organisation``); first successful consent binds it.
    """

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

        client_name = body.get("client_name") or "MCP Client"
        # Tag the row with a short random suffix so admin listings stay
        # readable when a client re-registers (each call yields a fresh row).
        tag = secrets.token_hex(3)
        from oauth2_provider.models import get_application_model
        Application = get_application_model()
        app = Application.objects.create(
            name=f"{client_name} ({tag})"[:255],
            client_type="public",
            authorization_grant_type="authorization-code",
            client_secret="",
            redirect_uris=" ".join(sorted(set(safe))),
            skip_authorization=False,
        )
        logger.info(
            "MCP DCR: created Application %s (client_id=%s, redirects=%s)",
            app.pk, app.client_id, sorted(set(safe)),
        )

        return JsonResponse({
            "client_id": app.client_id,
            "client_name": app.name,
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "redirect_uris": safe,
        }, status=201)


# Backwards-compatible alias for hosts that imported the old name.
StaticClientRegistrationView = DynamicClientRegistrationView
