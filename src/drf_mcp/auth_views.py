"""MCP-aware OAuth2 views.

Wraps django-oauth-toolkit's :class:`AuthorizationView` and
:class:`TokenView` so a user can pick which organisation an MCP integration
should operate as. Hosts opt in to multi-tenant behaviour by configuring
two callables in ``DRF_MCP`` settings:

* ``GET_USER_ORGS`` — ``(user) -> iterable`` of objects exposing ``.id`` /
  ``.name``. Drives the org picker on the consent page.
* ``GET_OR_CREATE_PER_ORG_APP`` — ``(user, org_id, shared_app) ->
  Application`` (or ``None``). Used to reassign the issued access/refresh
  tokens to a per-org Application row, so :attr:`request.auth.application`
  resolves to the org the user picked.

Either hook can be omitted; both default to a no-op so single-tenant
deployments inherit standard django-oauth-toolkit behaviour.

Requires :mod:`oauth2_provider` (``django-oauth-toolkit``); install
``django-rest-mcp[oauth]`` to pull it in.
"""
import json
import logging
from urllib.parse import parse_qs, urlparse

from django.utils.module_loading import import_string
from oauth2_provider.models import AccessToken, Grant, RefreshToken
from oauth2_provider.views import AuthorizationView, TokenView

from drf_mcp.views import get_setting

# `oauth2_provider` is required to use these views; install
# `django-rest-mcp[oauth]` to pull it in. The import sits at module level
# because the view classes inherit from oauth2_provider's AuthorizationView
# and TokenView, so the dependency is unconditional.

logger = logging.getLogger(__name__)


def _resolve_hook(setting_key):
    path = get_setting(setting_key)
    if not path:
        return None
    return import_string(path)


class MCPAuthorizationView(AuthorizationView):
    """OAuth2 consent view with an optional organisation picker.

    Reads :setting:`DRF_MCP["GET_USER_ORGS"]`. When set, the resulting
    iterable is added to the template context as ``organisations`` and the
    selected ``organisation`` POST value is stored on the issued
    :class:`Grant` as JSON in :attr:`Grant.claims`. :class:`MCPTokenView`
    consumes that claim during token exchange.
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

        if org_id and hasattr(response, "url"):
            parsed = urlparse(response.url)
            code = parse_qs(parsed.query).get("code", [None])[0]
            if code:
                Grant.objects.filter(code=code).update(
                    claims=json.dumps({"org_id": org_id})
                )
                logger.info(
                    "MCPAuthorizationView: stored org_id=%s on grant code=%s...",
                    org_id, code[:10],
                )

        return response

    def form_invalid(self, form):
        logger.warning(
            "MCPAuthorizationView.form_invalid: user=%s errors=%s",
            self.request.user, form.errors.as_json(),
        )
        return super().form_invalid(form)


class MCPTokenView(TokenView):
    """OAuth2 token view that reassigns issued tokens to a per-org Application.

    On ``authorization_code`` grants, reads ``org_id`` from the consumed
    :class:`Grant`'s ``claims`` (set by :class:`MCPAuthorizationView`), looks
    up or creates a per-org :class:`Application` via
    :setting:`DRF_MCP["GET_OR_CREATE_PER_ORG_APP"]`, and reassigns the
    freshly issued access/refresh tokens to it.

    On ``refresh_token`` grants, reads the per-org Application off the
    refresh token being consumed and reassigns the newly issued tokens to
    the same Application. This is required because django-oauth-toolkit
    creates new tokens with ``application=request.client`` (the shared
    public client), which would otherwise wipe the per-org binding on every
    refresh.

    The token string returned to the client is unchanged. Without the hook
    configured (auth-code flow) or without a per-org binding on the prior
    refresh token (refresh flow) the view degrades to a vanilla TokenView.
    """

    def post(self, request, *args, **kwargs):
        grant_type = request.POST.get("grant_type")

        # Auth-code flow: read org_id from the grant claims.
        org_id, grant_user, shared_app = self._read_grant_claims(
            request.POST.get("code")
        )

        # Refresh flow: capture the existing refresh token's per-org app
        # *before* super().post() rotates/revokes it. Defensive lookup —
        # super().post() is still the source of truth for validating the
        # refresh token; we only read the .application FK as metadata.
        prior_per_org_app = None
        if grant_type == "refresh_token":
            prior_per_org_app = self._read_refresh_token_per_org_app(
                request.POST.get("refresh_token")
            )

        response = super().post(request, *args, **kwargs)

        if response.status_code != 200:
            return response

        if org_id:
            self._reassign_tokens(response, org_id, grant_user, shared_app)
        elif prior_per_org_app is not None:
            self._reassign_tokens_to_app(response, prior_per_org_app)

        return response

    @staticmethod
    def _read_grant_claims(code):
        if not code:
            return None, None, None
        try:
            grant = Grant.objects.select_related("user", "application").get(code=code)
        except Grant.DoesNotExist:
            return None, None, None
        try:
            org_id = json.loads(grant.claims).get("org_id") if grant.claims else None
        except json.JSONDecodeError:
            return None, None, None
        return org_id, grant.user, grant.application

    @staticmethod
    def _read_refresh_token_per_org_app(refresh_value):
        """Return the per-org Application bound to ``refresh_value``, or None.

        Returns None when the refresh token is missing, unknown, bound to no
        application, bound to an application that has no organisation
        (i.e. the shared public client — nothing to preserve), or bound to
        an application whose user differs from the refresh token's user
        (defense-in-depth; this should not happen but if it ever does we
        refuse to use it as a binding source).

        This method is *not* an authentication step. The returned
        Application is only used as a destination for tokens that
        ``super().post()`` has already validated and issued.
        """
        if not refresh_value:
            return None
        try:
            rt = RefreshToken.objects.select_related("application").get(token=refresh_value)
        except RefreshToken.DoesNotExist:
            return None
        app = rt.application
        if app is None or app.organisation_id is None:
            return None
        if app.user_id and app.user_id != rt.user_id:
            logger.error(
                "MCPTokenView: refresh token %s has app.user mismatch "
                "(rt.user=%s, app.user=%s); refusing to preserve binding",
                rt.pk, rt.user_id, app.user_id,
            )
            return None
        return app

    @staticmethod
    def _reassign_tokens(response, org_id, grant_user, shared_app):
        get_or_create = _resolve_hook("GET_OR_CREATE_PER_ORG_APP")
        if not get_or_create:
            return
        per_org_app = get_or_create(grant_user, org_id, shared_app)
        if not per_org_app:
            return
        try:
            body = json.loads(response.content)
        except json.JSONDecodeError as exc:
            logger.warning("MCPTokenView: token response is not JSON: %s", exc)
            return

        access_token_value = body.get("access_token")
        if not access_token_value:
            return

        AccessToken.objects.filter(token=access_token_value).update(application=per_org_app)
        refresh_token_value = body.get("refresh_token")
        if refresh_token_value:
            RefreshToken.objects.filter(token=refresh_token_value).update(application=per_org_app)
        logger.info(
            "MCPTokenView: token reassigned to per-org app %s (org_id=%s, user=%s)",
            per_org_app.pk, org_id, grant_user,
        )

    @staticmethod
    def _reassign_tokens_to_app(response, per_org_app):
        """Reassign the newly issued access/refresh tokens to ``per_org_app``.

        Used on the refresh flow to preserve the per-org binding that was
        established at initial authorization. Verifies that the new access
        token belongs to the same user as ``per_org_app`` before binding
        (defense in depth: prevents us from ever moving tokens across users
        even if the refresh-token-to-app mapping were corrupted).
        """
        try:
            body = json.loads(response.content)
        except json.JSONDecodeError as exc:
            logger.warning("MCPTokenView: token response is not JSON: %s", exc)
            return

        access_token_value = body.get("access_token")
        if not access_token_value:
            return

        new_at = (
            AccessToken.objects.select_related("user")
            .filter(token=access_token_value)
            .first()
        )
        if new_at is None:
            return
        if per_org_app.user_id and new_at.user_id != per_org_app.user_id:
            logger.error(
                "MCPTokenView refresh: user mismatch — refusing to reassign "
                "(new token user=%s, per-org app user=%s)",
                new_at.user_id, per_org_app.user_id,
            )
            return

        AccessToken.objects.filter(token=access_token_value).update(application=per_org_app)
        refresh_token_value = body.get("refresh_token")
        if refresh_token_value:
            RefreshToken.objects.filter(token=refresh_token_value).update(application=per_org_app)
        logger.info(
            "MCPTokenView: refresh-issued tokens reassigned to per-org app %s "
            "(org_id=%s, user=%s)",
            per_org_app.pk, per_org_app.organisation_id, new_at.user_id,
        )
