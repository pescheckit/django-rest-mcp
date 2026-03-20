"""Tests for drf_mcp.schema — serializer-to-Pydantic conversion."""

import unittest
from typing import Optional

from pydantic import BaseModel
from rest_framework import serializers

from drf_mcp.schema import serializer_to_model


class TestSerializerToModel(unittest.TestCase):
    """Test serializer_to_model with a realistic serializer."""

    def test_realistic_serializer(self):
        """A single serializer exercising multiple field types, required/optional,
        read-only, hidden, nullable, and defaults — all at once."""

        class CheckSerializer(serializers.Serializer):
            id = serializers.IntegerField(read_only=True)
            created = serializers.DateTimeField(read_only=True)
            secret = serializers.HiddenField(default="hidden")
            name = serializers.CharField()
            email = serializers.EmailField()
            score = serializers.FloatField(required=False)
            active = serializers.BooleanField(default=True)
            middle_name = serializers.CharField(allow_null=True, required=False)
            tags = serializers.ListField(required=False)
            metadata = serializers.DictField(required=False)

        model = serializer_to_model(CheckSerializer)

        # Read-only and hidden fields excluded
        self.assertNotIn("id", model.model_fields)
        self.assertNotIn("created", model.model_fields)
        self.assertNotIn("secret", model.model_fields)

        # Writable fields included with correct types
        self.assertEqual(model.model_fields["name"].annotation, str)
        self.assertEqual(model.model_fields["email"].annotation, str)
        self.assertEqual(model.model_fields["score"].annotation, Optional[float])
        self.assertEqual(model.model_fields["active"].annotation, bool)
        self.assertEqual(model.model_fields["tags"].annotation, Optional[list])
        self.assertEqual(model.model_fields["metadata"].annotation, Optional[dict])

        # Required vs optional
        self.assertTrue(model.model_fields["name"].is_required())
        self.assertTrue(model.model_fields["email"].is_required())
        self.assertFalse(model.model_fields["score"].is_required())
        self.assertFalse(model.model_fields["active"].is_required())
        self.assertEqual(model.model_fields["active"].default, True)

        # Nullable
        self.assertEqual(model.model_fields["middle_name"].annotation, Optional[str])

        # Naming: "CheckSerializer" → "CheckInput"
        self.assertEqual(model.__name__, "CheckInput")

        # It's a real Pydantic model that works
        self.assertTrue(issubclass(model, BaseModel))
        instance = model(name="Alice", email="a@b.com")
        self.assertEqual(instance.model_dump(exclude_unset=True), {"name": "Alice", "email": "a@b.com"})

    def test_unknown_field_falls_back_to_str(self):
        class CustomField(serializers.Field):
            pass

        class S(serializers.Serializer):
            custom = CustomField()

        model = serializer_to_model(S)
        self.assertEqual(model.model_fields["custom"].annotation, str)

    def test_nested_serializer_becomes_dict(self):
        class Inner(serializers.Serializer):
            x = serializers.CharField()

        class S(serializers.Serializer):
            nested = Inner()

        model = serializer_to_model(S)
        self.assertEqual(model.model_fields["nested"].annotation, dict)

    def test_all_readonly_produces_empty_model(self):
        class S(serializers.Serializer):
            id = serializers.IntegerField(read_only=True)
            created = serializers.DateTimeField(read_only=True)

        model = serializer_to_model(S)
        self.assertEqual(len(model.model_fields), 0)


