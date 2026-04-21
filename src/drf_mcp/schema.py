"""Convert DRF serializer fields to Pydantic models for MCP tool schemas."""

import logging
from typing import Any, List, Optional

from pydantic import BaseModel, create_model
from rest_framework import serializers
from rest_framework.relations import ManyRelatedField
from rest_framework.serializers import ListSerializer

logger = logging.getLogger(__name__)

# Map DRF field classes to Python types
FIELD_TYPE_MAP = {
    serializers.CharField: str,
    serializers.EmailField: str,
    serializers.URLField: str,
    serializers.SlugField: str,
    serializers.UUIDField: str,
    serializers.IPAddressField: str,
    serializers.IntegerField: int,
    serializers.FloatField: float,
    serializers.DecimalField: float,
    serializers.BooleanField: bool,
    serializers.DateField: str,
    serializers.DateTimeField: str,
    serializers.TimeField: str,
    serializers.DurationField: str,
    serializers.ListField: list,
    serializers.DictField: dict,
    serializers.JSONField: Any,
}


def serializer_to_model(serializer_class, action="create"):
    """
    Convert a DRF serializer class into a Pydantic model.

    For create/update actions, includes writable fields.
    For list/retrieve actions, this isn't typically needed
    (those return data, they don't accept structured input).

    Returns a Pydantic model class.
    """
    # Instantiate the serializer to get resolved fields
    # (some serializers define fields in __init__)
    serializer = serializer_class()
    fields = {}

    for field_name, field in serializer.fields.items():
        # Skip read-only fields for create/update (the AI doesn't send those)
        if field.read_only:
            continue

        # Skip hidden fields
        if isinstance(field, serializers.HiddenField):
            continue

        python_type = _get_python_type(field)
        default = _get_default(field)

        if field.required and default is ...:
            # Required field, no default
            fields[field_name] = (python_type, ...)
        else:
            # Optional field with default
            if default is ...:
                default = None
                python_type = Optional[python_type]
            fields[field_name] = (python_type, default)

    model_name = serializer_class.__name__.replace("Serializer", "") + "Input"
    return create_model(model_name, **fields)


def _get_python_type(field):
    """Map a DRF field instance to a Python type."""
    # many=True on a related field wraps it in ManyRelatedField -> List[int]
    if isinstance(field, ManyRelatedField):
        return List[int]

    # many=True on a nested serializer wraps it in ListSerializer -> List[<child model>]
    if isinstance(field, ListSerializer):
        child_model = serializer_to_model(type(field.child))
        return List[child_model]

    for field_class, python_type in FIELD_TYPE_MAP.items():
        if isinstance(field, field_class):
            if field.allow_null:
                return Optional[python_type]
            return python_type

    # Nested serializer -> recursively build a Pydantic model
    if isinstance(field, serializers.Serializer):
        return serializer_to_model(type(field))

    # SerializerMethodField -> read-only, but just in case
    if isinstance(field, serializers.SerializerMethodField):
        return Any

    # Fallback
    logger.debug("Unknown field type %s for schema, using str", type(field).__name__)
    return str


def _get_default(field):
    """Get the default value for a field, or ... (no default) if required."""
    if field.required:
        return ...

    if field.default is not serializers.empty:
        # DRF uses callables (e.g. `list`, `dict`) as factory defaults; evaluate them.
        return field.default() if callable(field.default) else field.default

    # Not required but no explicit default
    return ...
