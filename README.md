# django-rest-mcp

A thin wrapper around the official `mcp` Python SDK that lets DRF `ViewSet`s
show up as MCP tools. No new protocol, no re-implementation of the MCP server;
this package is glue.

Concretely, it does four small things:

1. Walks a DRF router (or individual ViewSets) and registers one tool per
   action with `mcp.server.fastmcp.FastMCP`.
2. Converts each action's DRF serializer into a pydantic model so the tool has
   a typed input schema.
3. Hosts the MCP streamable-HTTP transport behind a normal Django URL, passing
   the authenticated `request.user` through to your ViewSet so existing
   `permission_classes` and `get_queryset()` filtering still apply.
4. Ships an `IsOAuth2Authenticated` DRF permission plus RFC 8414 / RFC 9728
   `.well-known/` metadata views, for the common case of fronting it with
   `django-oauth-toolkit`.

It owns no domain models, no business logic, no views of its own. If you can
already hit your API with `curl`, this just lets an MCP client hit the same
code.

## Install

```bash
pip install django-rest-mcp
```

Requires Python 3.12+, Django 5.1+, DRF 3.14+, `mcp>=1.26`, `pydantic>=2`.

## Quickstart

Assuming you already have a DRF router with your ViewSets registered, the
minimum is three lines:

```python
# myapp/urls.py
from drf_mcp import DRFMCP
from myapp.urls import router  # your existing DefaultRouter

mcp = DRFMCP("myapp"); mcp.autodiscover(router)

urlpatterns = [path("mcp/", mcp.as_view()), ...]
```

That exposes every standard action on every registered ViewSet as an MCP tool,
with input schemas built from the matching serializer.

### Production shape

Add OAuth discovery and a permission class:

```python
# myapp/urls.py
from django.urls import path
from drf_mcp import (
    DRFMCP, IsOAuth2Authenticated,
    AuthorizationServerMetadataView, ProtectedResourceMetadataView,
)
from myapp.urls import router

mcp = DRFMCP("myapp")
mcp.autodiscover(router)

urlpatterns = [
    path("mcp/", mcp.as_view(permission_classes=[IsOAuth2Authenticated]), name="mcp"),
    path(".well-known/oauth-authorization-server", AuthorizationServerMetadataView.as_view()),
    path(".well-known/oauth-protected-resource",   ProtectedResourceMetadataView.as_view()),
]
```

For a `BookViewSet` registered as `books`, MCP clients see `books_list`,
`books_create`, `books_retrieve`, `books_update`, `books_partial_update`,
`books_destroy`.

## Registering one action at a time

Skip `autodiscover` if you want finer control:

```python
mcp = DRFMCP("myapp")

mcp.register_view(BookViewSet, action="list", name="list_books",
                  description="Return all books the current user can read.")
mcp.register_view(BookViewSet, action="create")
mcp.register_view(BookViewSet, action="retrieve")
```

`include` / `exclude` on `autodiscover` use the router basename:

```python
mcp.autodiscover(router, include=["books"])
mcp.autodiscover(router, exclude=["internal_audit"])
```

## How the input schema is built

For write actions (`create`, `update`, `partial_update`) the package reads the
serializer returned by `view.get_serializer_class()` (falling back to
`view.serializer_class`) and converts each writable field:

| DRF field                                     | Python type           |
| --------------------------------------------- | --------------------- |
| `CharField`, `EmailField`, `URLField`, ...    | `str`                 |
| `IntegerField`                                | `int`                 |
| `FloatField`, `DecimalField`                  | `float`               |
| `BooleanField`                                | `bool`                |
| `Date/DateTime/Time/DurationField`            | `str`                 |
| `ListField`                                   | `list`                |
| `DictField`                                   | `dict`                |
| `JSONField`                                   | `Any`                 |
| nested `Serializer`                           | typed submodel        |
| `Serializer(many=True)` (ListSerializer)      | `List[submodel]`      |
| `PrimaryKeyRelatedField(many=True)`           | `List[int]`           |
| read-only / `HiddenField`                     | skipped               |

`required=False` fields become `Optional[...]`. Callable defaults like
`default=list` / `default=dict` are evaluated so the JSON schema has a
concrete default. Unknown field types fall back to `str` with a debug log.

The generated pydantic model is named `<Serializer>Input`, for example
`BookSerializer` becomes `BookInput`.

## Authentication

`IsOAuth2Authenticated` is a thin DRF permission that accepts the request only
if `request.user` is authenticated and `request.auth` looks like an OAuth2
access token (has a `.scope` attribute). It plays well with
`django-oauth-toolkit`:

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "oauth2_provider.contrib.rest_framework.OAuth2Authentication",
    ],
}
```

Inside a tool, the authenticated request is available via:

```python
from drf_mcp import get_current_request

request = get_current_request()
request.user        # the authenticated user
request.auth        # the OAuth2 access token
```

The package re-uses `request.user` when dispatching to your ViewSet, so your
existing `permission_classes`, object-level permissions, and `get_queryset()`
filtering all run as if the call came in over HTTP.

## Customising the inner request

Pass a `prepare_request` callable if you need to attach extra state (tenant,
feature flags, trace IDs, etc.) before the ViewSet runs:

```python
def attach_tenant(fake_request, original_request):
    fake_request.tenant = original_request.tenant

mcp = DRFMCP("myapp", prepare_request=attach_tenant)
```

## OAuth discovery metadata

The metadata views read their settings from `DRF_MCP` in Django settings:

```python
DRF_MCP = {
    "RESOURCE_PATH": "/mcp/",
    "SCOPES": ["read", "write"],
}
```

The `issuer`, `authorization_endpoint`, `token_endpoint`, and
`registration_endpoint` URLs are built from the incoming request host, so the
same deployment serves correct metadata whether reached via `localhost`, a
tunnel, staging, or production. You do not need to set absolute URLs per env.

## Tool descriptions

Descriptions shown to the model come from, in order of preference:

1. The `description=` kwarg to `register_view`.
2. The docstring of the action method, if defined directly on the ViewSet
   (docstrings inherited from mixins like `ListModelMixin` are ignored).
3. The ViewSet's class docstring, prefixed with the action name.
4. A generated fallback like `"List all Book"`.

Write action docstrings when you want to guide the model on when to use a tool:

```python
class BookViewSet(viewsets.ModelViewSet):
    """Books in the catalogue."""

    def create(self, request):
        """Create a new book.

        Requires title and author_id. Use books_list first to check whether
        the book already exists before creating a duplicate.
        """
        ...
```

## Running the tests

```bash
uv sync
uv run pytest tests/ -v
```

## License

MIT. See `LICENSE`.
