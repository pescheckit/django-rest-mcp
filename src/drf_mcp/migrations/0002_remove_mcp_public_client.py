"""Remove the shared ``MCP Public Client`` Application row.

The original seed migration (0001) created a single shared OAuth2
Application named ``MCP Public Client`` that all RFC 7591 registrations
appended their redirect_uris to. That model has been replaced by
per-instance Dynamic Client Registration: each ``POST /register`` now
creates its own Application, bound to a specific (user, organisation) at
first successful consent.

The shared row is no longer used. This migration deletes it so the
``oauth2_provider_application`` table never carries an unbound
``user=None / organisation=None`` row. The forward op is idempotent
(``filter(...).delete()``); the reverse op is a no-op because the seeded
row no longer has a meaningful purpose to recreate (operators that need
the previous behaviour should reset migration state on 0001 directly).
"""
from django.conf import settings
from django.db import migrations

MCP_APP_NAME = "MCP Public Client"


def _application_model(apps):
    label = getattr(settings, "OAUTH2_PROVIDER", {}).get(
        "APPLICATION_MODEL", "oauth2_provider.Application"
    )
    return apps.get_model(*label.split(".", 1))


def remove_mcp_public_client(apps, schema_editor):
    Application = _application_model(apps)
    Application.objects.filter(name=MCP_APP_NAME).delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("drf_mcp", "0001_seed_mcp_public_client"),
    ]

    operations = [
        migrations.RunPython(remove_mcp_public_client, noop),
    ]
