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


def noop(apps, schema_editor):
    """Historical seed retained for migration name compatibility only.

    Earlier versions of this package created a single shared Application
    named ``MCP Public Client``. That row is no longer used: registrations
    now create per-instance Applications via
    :class:`drf_mcp.registration.DynamicClientRegistrationView`, and the
    Application is bound to a (user, organisation) at first consent. Fresh
    environments must not seed the shared row, so the operation is a no-op.

    Existing environments where this migration was previously applied
    already have the row; deleting it is a deployment-time operational
    decision (per-environment, with stakeholder confirmation) and is
    therefore not handled by a follow-up data migration.
    """


class Migration(migrations.Migration):

    initial = True

    replaces = [("pescheck_api", "0018_seed_mcp_public_client")]

    dependencies = [
        migrations.swappable_dependency(_resolve_application_model()),
    ]

    operations = [
        migrations.RunPython(noop, noop),
    ]
