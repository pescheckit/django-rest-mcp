import contextvars
import json
import logging

from asgiref.sync import async_to_sync, sync_to_async
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from rest_framework.test import APIRequestFactory, force_authenticate

from drf_mcp.schema import serializer_to_model

logger = logging.getLogger(__name__)

# Stores the authenticated Django request for the current MCP invocation.
# Tool functions read this to get request.user / request.auth.
_django_request_ctx = contextvars.ContextVar("django_request")


def get_current_request():
    """Get the Django request for the current MCP tool invocation."""
    return _django_request_ctx.get()


class DRFMCP:
    """
    MCP server that exposes DRF views as tools.

    Usage:
        mcp = DRFMCP("myapi")
        mcp.register_view(CheckViewSet, action="list", name="list_checks")

        # In urls.py:
        path("mcp/", mcp.as_view(permission_classes=[...]), name="mcp"),
    """

    def __init__(self, name, prepare_request=None):
        self.name = name
        self.prepare_request = prepare_request
        self._fastmcp = FastMCP(name=name)
        self._factory = APIRequestFactory()

    def register_view(self, view_class, *, action, name=None, description=None):
        """
        Register a DRF ViewSet action as an MCP tool.

        Args:
            view_class: DRF ViewSet class (e.g. CheckViewSet)
            action: ViewSet action name ("list", "retrieve", "create")
            name: Tool name (default: "{action}_{viewset_basename}")
            description: Tool description for the AI
        """
        # Derive default tool name from class name
        # CheckViewSet → "check", ScreeningViewSet → "screening"
        basename = (
            view_class.__name__
            .replace("ViewSet", "")
            .replace("APIView", "")
            .lower()
        )
        tool_name = name or f"{action}_{basename}"
        tool_description = description or f"{action} via {view_class.__name__}"

        # Map action to HTTP method and ViewSet action dict
        action_map = {
            "list": ("get", {"get": "list"}),
            "retrieve": ("get", {"get": "retrieve"}),
            "create": ("post", {"post": "create"}),
            "update": ("put", {"put": "update"}),
            "partial_update": ("patch", {"patch": "partial_update"}),
            "destroy": ("delete", {"delete": "destroy"}),
        }

        if action not in action_map:
            raise ValueError(f"Unknown action: {action}. Must be one of {list(action_map)}")

        http_method, viewset_actions = action_map[action]
        factory = self._factory

        # For create/update, try to get a Pydantic model from the serializer
        # so the AI knows exactly what fields to send.
        input_model = None
        if action in ("create", "update", "partial_update"):
            serializer_class = self._get_serializer_class(view_class, action)
            if serializer_class:
                try:
                    input_model = serializer_to_model(serializer_class, action=action)
                    logger.info("Generated schema for %s from %s", tool_name, serializer_class.__name__)
                except (AttributeError, TypeError, KeyError) as e:
                    logger.warning("Could not generate schema for %s: %s", tool_name, e)

        # Build the tool function with the right signature per action.
        # FastMCP infers the tool's input schema from the function signature,
        # so we create different functions depending on what params the action needs.
        prepare_request = self.prepare_request

        def _make_request(fake_request, original_request):
            force_authenticate(fake_request, user=original_request.user)
            if prepare_request:
                prepare_request(fake_request, original_request)

        def _call_view(fake_request, **kwargs):
            view = view_class.as_view(viewset_actions, permission_classes=[])
            resp = view(fake_request, **kwargs)
            if hasattr(resp, "render"):
                resp.render()
            return resp.data

        if action == "list":
            async def tool_fn() -> dict:
                request = _django_request_ctx.get()
                def _invoke():
                    fake_request = factory.get("/")
                    _make_request(fake_request, request)
                    return _call_view(fake_request)
                return await sync_to_async(_invoke)()

        elif action in ("retrieve", "destroy"):
            async def tool_fn(id: str) -> dict:
                request = _django_request_ctx.get()
                def _invoke():
                    fake_request = getattr(factory, http_method)("/")
                    _make_request(fake_request, request)
                    return _call_view(fake_request, pk=id)
                return await sync_to_async(_invoke)()

        elif action == "create":
            if input_model:
                async def tool_fn(data: input_model) -> dict:
                    request = _django_request_ctx.get()
                    def _invoke():
                        fake_request = factory.post("/", data.model_dump(exclude_unset=True), format="json")
                        _make_request(fake_request, request)
                        return _call_view(fake_request)
                    return await sync_to_async(_invoke)()
            else:
                async def tool_fn(data: dict) -> dict:
                    request = _django_request_ctx.get()
                    def _invoke():
                        fake_request = factory.post("/", data, format="json")
                        _make_request(fake_request, request)
                        return _call_view(fake_request)
                    return await sync_to_async(_invoke)()

        elif action in ("update", "partial_update"):
            if input_model:
                async def tool_fn(id: str, data: input_model) -> dict:
                    request = _django_request_ctx.get()
                    def _invoke():
                        fake_request = getattr(factory, http_method)("/", data.model_dump(exclude_unset=True), format="json")
                        _make_request(fake_request, request)
                        return _call_view(fake_request, pk=id)
                    return await sync_to_async(_invoke)()
            else:
                async def tool_fn(id: str, data: dict) -> dict:
                    request = _django_request_ctx.get()
                    def _invoke():
                        fake_request = getattr(factory, http_method)("/", data, format="json")
                        _make_request(fake_request, request)
                        return _call_view(fake_request, pk=id)
                    return await sync_to_async(_invoke)()

        # FastMCP uses the function name + docstring for tool metadata
        tool_fn.__name__ = tool_name
        tool_fn.__doc__ = tool_description
        self._fastmcp.add_tool(tool_fn, name=tool_name, description=tool_description)

        logger.info("Registered MCP tool: %s → %s.%s", tool_name, view_class.__name__, action)

    # Standard DRF actions and which mixin provides them
    _STANDARD_ACTIONS = {
        "list": "list",
        "create": "create",
        "retrieve": "retrieve",
        "update": "update",
        "partial_update": "partial_update",
        "destroy": "destroy",
    }

    def autodiscover(self, router, *, include=None, exclude=None):
        """
        Auto-discover ViewSets from a DRF router and register them as MCP tools.

        Args:
            router: A DRF router instance (e.g. DefaultRouter)
            include: Optional list of basenames to include (default: all)
            exclude: Optional list of basenames to exclude (default: none)
        """
        exclude = set(exclude or [])

        for prefix, viewset_class, basename in router.registry:
            if include and basename not in include:
                continue
            if basename in exclude:
                continue

            for action in self._STANDARD_ACTIONS:
                if not hasattr(viewset_class, action):
                    continue

                tool_name = f"{basename}_{action}"
                description = self._get_description(viewset_class, action)

                self.register_view(
                    viewset_class,
                    action=action,
                    name=tool_name,
                    description=description,
                )

    @staticmethod
    def _get_description(view_class, action):
        """Generate a tool description from the ViewSet's docstrings."""
        # Try action method docstring, but only if defined on the ViewSet itself
        # (not inherited from mixins like ListModelMixin or LimitedListMixin)
        if action in view_class.__dict__:
            method = view_class.__dict__[action]
            if method.__doc__:
                return method.__doc__.strip()

        # Fall back to class docstring
        if view_class.__doc__:
            doc = view_class.__doc__.strip()
            return f"{action} — {doc}"

        # Generic fallback
        basename = (
            view_class.__name__
            .replace("ViewSet", "")
            .replace("APIView", "")
        )
        action_verbs = {
            "list": "List all",
            "create": "Create a new",
            "retrieve": "Get details of a",
            "update": "Update a",
            "partial_update": "Partially update a",
            "destroy": "Delete a",
        }
        verb = action_verbs.get(action, action)
        return f"{verb} {basename}"

    @staticmethod
    def _get_serializer_class(view_class, action):
        """Get the serializer class a ViewSet uses for a given action."""
        # If it has get_serializer_class, fake the action attribute
        if hasattr(view_class, "get_serializer_class"):
            fake_view = view_class()
            fake_view.action = action
            fake_view.request = None
            fake_view.format_kwarg = None
            try:
                return fake_view.get_serializer_class()
            except (AttributeError, TypeError) as e:
                logger.debug("Could not call get_serializer_class on %s: %s", view_class.__name__, e)

        # Fall back to serializer_class attribute
        return getattr(view_class, "serializer_class", None)

    def handle_request(self, django_request):
        """
        Handle an MCP protocol request.

        Call this from your Django view's get/post/delete method.
        Returns a Django HttpResponse with the MCP protocol response.
        """
        return async_to_sync(self._handle_request_async)(django_request)

    async def _handle_request_async(self, django_request):
        """Translate Django request → ASGI → MCP server → Django response."""
        _django_request_ctx.set(django_request)

        body = json.dumps(django_request.data, cls=DjangoJSONEncoder).encode("utf-8")

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": django_request.method,
            "headers": [
                (k.lower().encode("latin-1"), v.encode("latin-1"))
                for k, v in django_request.headers.items()
                if k.lower() != "content-length"
            ] + [(b"content-length", str(len(body)).encode("latin-1"))],
            "path": django_request.path,
            "raw_path": django_request.get_full_path().encode("utf-8"),
            "query_string": django_request.META.get("QUERY_STRING", "").encode("latin-1"),
            "scheme": "https" if django_request.is_secure() else "http",
            "client": (django_request.META.get("REMOTE_ADDR"), 0),
            "server": (django_request.get_host(), django_request.get_port()),
        }

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        response_started = {}
        response_body = bytearray()

        async def send(message):
            if message["type"] == "http.response.start":
                response_started["status"] = message["status"]
                response_started["headers"] = [
                    (k.decode("latin-1"), v.decode("latin-1"))
                    for k, v in message.get("headers", [])
                ]
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))

        session_manager = StreamableHTTPSessionManager(
            app=self._fastmcp._mcp_server,
            json_response=True,
            stateless=True,
        )
        async with session_manager.run():
            await session_manager.handle_request(scope, receive, send)

        status_code = response_started.get("status", 500)
        http_response = HttpResponse(bytes(response_body), status=status_code)
        for key, value in response_started.get("headers", []):
            http_response[key] = value
        return http_response

    def as_view(self, **view_kwargs):
        """
        Return a Django view function for this MCP server.

        Accepts any APIView class attributes as kwargs:
            permission_classes, authentication_classes, etc.

        Usage:
            path("mcp/", mcp.as_view(permission_classes=[IsAuthenticated]), name="mcp")
        """
        from django.utils.decorators import method_decorator
        from django.views.decorators.csrf import csrf_exempt
        from rest_framework.views import APIView

        drfmcp = self

        @method_decorator(csrf_exempt, name="dispatch")
        class GeneratedMCPView(APIView):
            def post(self, request):
                return drfmcp.handle_request(request)

            def get(self, request):
                return drfmcp.handle_request(request)

            def delete(self, request):
                return drfmcp.handle_request(request)

        # Apply user-provided view configuration
        for attr, value in view_kwargs.items():
            setattr(GeneratedMCPView, attr, value)

        return GeneratedMCPView.as_view()
