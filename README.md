# django-rest-mcp

Turn the Django REST Framework API you already have into MCP tools, without rewriting a thing.

## Why

You have a DRF API. You want an MCP client (Claude, an agent, your own tooling) to call it.

The usual way is to hand-write an MCP tool for every endpoint, re-describe your
serializers as tool inputs, and re-check your permissions in a second place that
quietly drifts from the real API.

This package skips that. Point it at your existing DRF router and every ViewSet
action becomes an MCP tool, input types pulled straight from your serializers,
every call running through your real permissions and querysets. One source of
truth: your API. If `curl` can hit it, an MCP client can too.

It owns no models, no business logic, no views of its own. It is glue.

## What you get

Register a `BookViewSet` under `books` and an MCP client sees six tools:

```
books_list   books_retrieve   books_create   books_update   books_partial_update   books_destroy
```

For each one:

- **Typed inputs**, generated from the action's serializer, so the model knows
  exactly what fields to send.
- **Runs as the authenticated user**, so your `permission_classes`, OAuth
  scopes, object-level permissions, and `get_queryset()` filtering all apply
  unchanged.
- **Returns** whatever your API already returns.

## Install

```bash
pip install django-rest-mcp
```

Python 3.12+, Django 5.1+, DRF 3.14+, `mcp>=1.26`, `pydantic>=2`.

## How

You already have a router. Three lines:

```python
# myapp/urls.py
from django.urls import path
from drf_mcp import DRFMCP
from myapp.urls import router          # your existing DefaultRouter

mcp = DRFMCP("myapp")
mcp.autodiscover(router)

urlpatterns = [path("mcp/", mcp.as_view()), ...]
```

That exposes every standard action on every registered ViewSet. That's it.

### Pick what to expose

```python
mcp.autodiscover(router, include=["books"])       # only these basenames
mcp.autodiscover(router, exclude=["internal"])     # all but these

# or register one action at a time, with a custom name + description:
mcp.register_view(BookViewSet, action="list", name="list_books",
                  description="Return all books the current user can read.")
```

### Add OAuth (production shape)

Front it with `django-oauth-toolkit` plus a permission class, and serve the
`.well-known/` discovery endpoints so MCP clients can find your auth server:

```python
from drf_mcp import (
    DRFMCP, IsOAuth2Authenticated,
    AuthorizationServerMetadataView, ProtectedResourceMetadataView,
)

mcp = DRFMCP("myapp")
mcp.autodiscover(router)

urlpatterns = [
    path("mcp/", mcp.as_view(permission_classes=[IsOAuth2Authenticated]), name="mcp"),
    path(".well-known/oauth-authorization-server", AuthorizationServerMetadataView.as_view()),
    path(".well-known/oauth-protected-resource",   ProtectedResourceMetadataView.as_view()),
]
```

```bash
pip install 'django-rest-mcp[oauth]'
```

## Authentication

Each tool runs as the request's authenticated user. That works whether you
authenticate with OAuth2 tokens, session/cookie auth, or a custom backend, so
your permissions and querysets behave exactly as they do over HTTP.

`IsOAuth2Authenticated` accepts a request only if `request.user` is
authenticated and `request.auth` looks like an OAuth2 token. Pair it with:

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "oauth2_provider.contrib.rest_framework.OAuth2Authentication",
    ],
}
```

Reach the live request from inside a tool:

```python
from drf_mcp import get_current_request

request = get_current_request()
request.user   # the authenticated user
request.auth   # the OAuth2 access token
```

## Tool inputs

For write actions (`create`, `update`, `partial_update`) the input schema is
built from the serializer (`get_serializer_class()`, falling back to
`serializer_class`). Each writable field maps to a Python type:

| DRF field                                  | Python type      |
| ------------------------------------------ | ---------------- |
| `CharField`, `EmailField`, `URLField`, ... | `str`            |
| `IntegerField`                             | `int`            |
| `FloatField`, `DecimalField`               | `float`          |
| `BooleanField`                             | `bool`           |
| `ListField`                                | `list`           |
| `DictField`                                | `dict`           |
| `JSONField`                                | `Any`            |
| nested `Serializer`                        | typed submodel   |
| `Serializer(many=True)`                    | `List[submodel]` |

`required=False` fields become `Optional[...]`; read-only and hidden fields are
skipped. The generated model is named `<Serializer>Input`.

## Tool descriptions

What the model reads as a tool's description comes from, in order:

1. The `description=` you pass to `register_view`.
2. The action method's docstring (only if defined on the ViewSet itself, not
   inherited from a mixin).
3. The ViewSet's class docstring.
4. A generated fallback like `"List all Book"`.

Write docstrings to steer the model on when to use a tool:

```python
class BookViewSet(viewsets.ModelViewSet):
    """Books in the catalogue."""

    def create(self, request):
        """Create a book. Call books_list first to avoid duplicates."""
        ...
```

## Multi-tenant OAuth

For "one user belongs to many orgs, and each MCP connection binds to exactly
one of them", the package ships drop-in replacements for django-oauth-toolkit's
authorize and token views, a Dynamic Client Registration endpoint (RFC 7591),
and a consent page with an org picker.

```python
# settings.py
INSTALLED_APPS = [..., "oauth2_provider", "drf_mcp"]

DRF_MCP = {
    "RESOURCE_PATH": "/api/mcp/",
    "SCOPES": ["read:api", "create:api"],

    # Org picker on the consent page. Returns objects with `.id` and `.name`.
    "GET_USER_ORGS": "myapp.mcp_hooks.get_user_orgs",

    # Bind the issued token's Application to the org the user picked, so
    # `request.auth.application.organisation` resolves to that org.
    "GET_OR_CREATE_PER_ORG_APP": "myapp.mcp_hooks.get_or_create_per_org_app",

    # HTTPS hosts allowed to register a redirect_uri via DCR (loopback HTTP is
    # always allowed).
    "REGISTRATION_HTTPS_HOST_SUFFIXES": ["claude.ai", "anthropic.com"],
}
```

```python
# urls.py
from drf_mcp import (
    DRFMCP, IsOAuth2Authenticated, MCPView,
    MCPAuthorizationView, MCPTokenView, StaticClientRegistrationView,
    AuthorizationServerMetadataView, ProtectedResourceMetadataView,
)

mcp = DRFMCP("myapi")
mcp.autodiscover(router)

class MyMCPView(MCPView):
    mcp_server = mcp
    permission_classes = [IsOAuth2Authenticated]

urlpatterns = [
    path("o/authorize/",  MCPAuthorizationView.as_view(), name="authorize"),
    path("o/token/",      MCPTokenView.as_view(),         name="token"),
    path("mcp/",          MyMCPView.as_view(),            name="mcp"),
    path("mcp/register/", StaticClientRegistrationView.as_view()),
    path(".well-known/oauth-authorization-server", AuthorizationServerMetadataView.as_view()),
    path(".well-known/oauth-protected-resource",   ProtectedResourceMetadataView.as_view()),
]
```

Both hooks are optional: omit `GET_USER_ORGS` for a consent page without an org
picker; omit `GET_OR_CREATE_PER_ORG_APP` to leave tokens on the shared
Application. The `.well-known/` metadata URLs are built from the incoming
request host, so one deployment serves correct values via localhost, a tunnel,
staging, or production with no per-env config.

## Customising the request

Attach extra state (tenant, feature flags, trace ids) before the ViewSet runs:

```python
def attach_tenant(request, original_request):
    request.tenant = original_request.tenant

mcp = DRFMCP("myapp", prepare_request=attach_tenant)
```

## Running the tests

```bash
uv sync
uv run pytest
```

## License

MIT. See `LICENSE`.
