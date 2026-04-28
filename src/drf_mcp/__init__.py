"""Public API of drf_mcp.

Top-level imports are deferred via PEP 562 `__getattr__` so that adding
`drf_mcp` to `INSTALLED_APPS` does not trigger DRF/auth imports before
the Django app registry has finished loading.
"""
from importlib import import_module

__all__ = [
    "AuthorizationServerMetadataView",
    "DRFMCP",
    "IsOAuth2Authenticated",
    "MCPAuthorizationView",
    "MCPTokenView",
    "MCPView",
    "ProtectedResourceMetadataView",
    "StaticClientRegistrationView",
    "get_current_request",
    "serializer_to_model",
]

_EXPORTS = {
    "AuthorizationServerMetadataView": "drf_mcp.metadata",
    "ProtectedResourceMetadataView": "drf_mcp.metadata",
    "serializer_to_model": "drf_mcp.schema",
    "DRFMCP": "drf_mcp.server",
    "get_current_request": "drf_mcp.server",
    "IsOAuth2Authenticated": "drf_mcp.views",
    "MCPView": "drf_mcp.views",
    "MCPAuthorizationView": "drf_mcp.auth_views",
    "MCPTokenView": "drf_mcp.auth_views",
    "StaticClientRegistrationView": "drf_mcp.registration",
}


def __getattr__(name):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
