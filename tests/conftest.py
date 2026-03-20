"""Pytest configuration for drf-mcp tests."""

import django
from django.conf import settings


def pytest_configure(config):
    settings.configure(
        DEBUG=True,
        DATABASES={
            "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
        },
        SECRET_KEY="test-secret-key",
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "rest_framework",
        ],
        ROOT_URLCONF="tests.urls",
        DRF_MCP={
            "RESOURCE_URL": "https://example.com",
            "RESOURCE_PATH": "/api/mcp/",
            "AUTHORIZATION_ENDPOINT": "https://example.com/o/authorize/",
            "TOKEN_ENDPOINT": "https://example.com/o/token/",
            "REGISTRATION_ENDPOINT": "https://example.com/mcp/register/",
            "SCOPES": ["read", "write"],
        },
    )
    django.setup()
