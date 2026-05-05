"""MCP-aware OAuth2 views.

Wraps django-oauth-toolkit's :class:`AuthorizationView` and
:class:`TokenView` so a user can pick which organisation an MCP client
should operate as, and so the chosen organisation is *bound to the OAuth2
Application itself* — not to a separate per-(user, org) sidecar row, and
not to individual tokens. The binding happens once, at first successful
consent. Every access token issued for that client_id from then on
inherits ``application.user`` and ``application.organisation`` natively
through django-oauth-toolkit's stock token-issuance path; refresh tokens
keep working without any custom rotation logic.

Hosts opt in by configuring two callables in ``DRF_MCP`` settings:

* ``GET_USER_ORGS`` — ``(user) -> iterable`` of objects exposing ``.id``
  and ``.name``. Drives the org picker on the consent page.
* ``BIND_APPLICATION`` — ``(application, user, org_id) -> None``. Called
  once at consent. Should set ``application.user`` and
  ``application.organisation`` (and persist) after verifying ``user`` has
  access to ``org_id``. Idempotent re-binds for the same (user, org) are
  the host's responsibility; cross-tenant rebinds should be rejected.

Either hook can be omitted; both default to a no-op so single-tenant
deployments inherit standard django-oauth-toolkit behaviour.

Requires :mod:`oauth2_provider`; install ``django-rest-mcp[oauth]``.
"""
import json
import logging
from urllib.parse import parse_qs, urlparse

from django.utils.module_loading import import_string
from oauth2_provider.models import Grant
from oauth2_provider.views import AuthorizationView, TokenView

from drf_mcp.views import get_setting

logger = logging.getLogger(__name__)


def _resolve_hook(setting_key):
    path = get_setting(setting_key)
    if not path:
        return None
    return import_string(path)


class MCPAuthorizationView(AuthorizationView):
    """OAuth2 consent view with an organisation picker.

    Reads :setting:`DRF_MCP["GET_USER_ORGS"]` to populate the org picker.
    On successful consent, calls :setting:`DRF_MCP["BIND_APPLICATION"]` to
    bind the OAuth2 Application that the grant references to (user, org)
    — *before* any token is issued — so the issued access/refresh tokens
    carry the correct ``application.organisation`` natively. Also stores
    ``org_id`` on the issued :class:`Grant`'s ``claims`` as a defensive
    record for debugging and for hosts that prefer to re-verify at
    token-issuance time.
    """

    def dispatch(self, request, *args, **kwargs):
        params = request.GET if request.method == "GET" else request.POST
        logger.info(
            "MCPAuthorizationView.dispatch: method=%s user=%s client_id=%s "
            "redirect_uri=%s response_type=%s scope=%s has_code_challenge=%s",
            request.method,
            request.user if request.user.is_authenticated else "anonymous",
            params.get("client_id") or "<missing>",
            params.get("redirect_uri") or "<missing>",
            params.get("response_type") or "<missing>",
            params.get("scope") or "<missing>",
            bool(params.get("code_challenge")),
        )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not context.get("application"):
            logger.warning(
                "MCPAuthorizationView: consent page rendered with NO application "
                "(client_id=%s)",
                self.request.GET.get("client_id")
                or self.request.POST.get("client_id")
                or "<missing>",
            )
        get_user_orgs = _resolve_hook("GET_USER_ORGS")
        if get_user_orgs and self.request.user.is_authenticated:
            context["organisations"] = get_user_orgs(self.request.user)
        else:
            context["organisations"] = []
        return context

    def form_valid(self, form):
        org_id = self.request.POST.get("organisation")
        logger.info(
            "MCPAuthorizationView.form_valid: user=%s client_id=%s "
            "redirect_uri=%s org_id=%s",
            self.request.user,
            form.cleaned_data.get("client_id"),
            form.cleaned_data.get("redirect_uri"),
            org_id,
        )
        response = super().form_valid(form)

        if not org_id or not hasattr(response, "url"):
            return response

        parsed = urlparse(response.url)
        code = parse_qs(parsed.query).get("code", [None])[0]
        if not code:
            return response

        grant = (
            Grant.objects
            .select_related("user", "application")
            .filter(code=code)
            .first()
        )
        if grant is None:
            logger.warning("MCPAuthorizationView: grant for code=%s... not found", code[:10])
            return response

        # Defensive record on the grant in case binding fails or the host
        # wants to re-verify at token-issuance time.
        Grant.objects.filter(pk=grant.pk).update(claims=json.dumps({"org_id": org_id}))

        bind = _resolve_hook("BIND_APPLICATION")
        if bind:
            try:
                bind(grant.application, grant.user, org_id)
                logger.info(
                    "MCPAuthorizationView: bound Application %s to user=%s org=%s",
                    grant.application.pk, grant.user, org_id,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "MCPAuthorizationView: BIND_APPLICATION hook raised "
                    "(application=%s user=%s org=%s)",
                    grant.application.pk, grant.user, org_id,
                )
        else:
            logger.warning(
                "MCPAuthorizationView: org picked but no BIND_APPLICATION hook "
                "configured; Application %s will remain unbound",
                grant.application.pk,
            )

        return response

    def form_invalid(self, form):
        logger.warning(
            "MCPAuthorizationView.form_invalid: user=%s errors=%s",
            self.request.user, form.errors.as_json(),
        )
        return super().form_invalid(form)


class MCPTokenView(TokenView):
    """OAuth2 token view.

    With per-instance Dynamic Client Registration and binding-at-consent,
    no custom token-issuance logic is needed: django-oauth-toolkit creates
    new tokens with ``application=request.client``, which by then is
    already bound to the correct (user, organisation), so tokens carry
    the right scope natively on both authorization-code and refresh-token
    grants.

    The view is kept as a thin subclass for symmetry with
    :class:`MCPAuthorizationView` and to give hosts a clear extension
    point if they want to reject token requests for unbound Applications
    (e.g. tighten consent's race window between Application creation and
    binding).
    """
