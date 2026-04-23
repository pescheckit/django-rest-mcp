"""Seed the shared `MCP Public Client` OAuth Application row.

This migration replaces `pescheck_api.0018_seed_mcp_public_client`, which
was created before drf_mcp became a Django app. Using `replaces` lets
environments that already ran the pescheck_api version treat this as
applied without re-running the seed.

The operation is idempotent (`get_or_create`) so re-running is safe in
any environment.
"""
from django.conf import settings
from django.db import migrations

MCP_APP_NAME = "MCP Public Client"


def _resolve_application_model():
    return getattr(settings, "OAUTH2_PROVIDER", {}).get(
        "APPLICATION_MODEL", "oauth2_provider.Application"
    )


def _application_model(apps):
    return apps.get_model(*_resolve_application_model().split(".", 1))


def create_mcp_public_client(apps, schema_editor):
    Application = _application_model(apps)
    Application.objects.get_or_create(
        name=MCP_APP_NAME,
        defaults={
            "client_type": "public",
            "authorization_grant_type": "authorization-code",
            "client_secret": "",
            "redirect_uris": "",
            "skip_authorization": False,
        },
    )


def delete_mcp_public_client(apps, schema_editor):
    Application = _application_model(apps)
    Application.objects.filter(name=MCP_APP_NAME).delete()


class Migration(migrations.Migration):

    initial = True

    replaces = [("pescheck_api", "0018_seed_mcp_public_client")]

    dependencies = [
        migrations.swappable_dependency(_resolve_application_model()),
    ]

    operations = [
        migrations.RunPython(create_mcp_public_client, delete_mcp_public_client),
    ]
