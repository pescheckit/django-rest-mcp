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

    Reads ``org_id`` from the consumed :class:`Grant`'s ``claims`` (set by
    :class:`MCPAuthorizationView`), looks up or creates a per-org
    :class:`Application` via :setting:`DRF_MCP["GET_OR_CREATE_PER_ORG_APP"]`,
    and reassigns the freshly issued access/refresh tokens to it. The token
    string returned to the client is unchanged.

    Without the hook configured the view degrades to a vanilla TokenView.
    """

    def post(self, request, *args, **kwargs):
        org_id, grant_user, shared_app = self._read_grant_claims(
            request.POST.get("code")
        )

        response = super().post(request, *args, **kwargs)

        if org_id and response.status_code == 200:
            self._reassign_tokens(response, org_id, grant_user, shared_app)

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
    def _reassign_tokens(response, org_id, grant_user, shared_app):
        get_or_create = _resolve_hook("GET_OR_CREATE_PER_ORG_APP")
        if not get_or_create:
            return
        try:
            body = json.loads(response.content)
        except json.JSONDecodeError as exc:
            logger.warning("MCPTokenView: token response is not JSON: %s", exc)
            return

        access_token_value = body.get("access_token")
        if not access_token_value:
            return

        per_org_app = get_or_create(grant_user, org_id, shared_app)
        if not per_org_app:
            return

        AccessToken.objects.filter(token=access_token_value).update(application=per_org_app)
        refresh_token_value = body.get("refresh_token")
        if refresh_token_value:
            RefreshToken.objects.filter(token=refresh_token_value).update(application=per_org_app)
        logger.info(
            "MCPTokenView: token reassigned to per-org app %s (org_id=%s, user=%s)",
            per_org_app.pk, org_id, grant_user,
        )
