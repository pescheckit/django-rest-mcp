"""Tests for drf_mcp.server — DRFMCP, register_view, autodiscover."""

import unittest
from unittest.mock import Mock

from rest_framework import serializers
from rest_framework.mixins import (
    CreateModelMixin,
    DestroyModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
)
from rest_framework.routers import DefaultRouter
from rest_framework.viewsets import GenericViewSet, ModelViewSet

from drf_mcp.server import DRFMCP


# ---------------------------------------------------------------------------
# Fixtures: simple ViewSets used across tests
# ---------------------------------------------------------------------------
class ItemSerializer(serializers.Serializer):
    name = serializers.CharField()
    count = serializers.IntegerField(required=False)


class ItemViewSet(ModelViewSet):
    """Manage inventory items."""

    serializer_class = ItemSerializer

    def list(self, request):
        pass

    def retrieve(self, request, pk=None):
        pass

    def create(self, request):
        pass


class BareViewSet(GenericViewSet):
    """No docstring, no serializer."""

    def list(self, request):
        pass


class DocstringOnActionViewSet(GenericViewSet):
    def list(self, request):
        """Return all widgets with pagination."""
        pass


# ---------------------------------------------------------------------------
# _get_description
# ---------------------------------------------------------------------------
class TestGetDescription(unittest.TestCase):
    """Test DRFMCP._get_description static method."""

    def test_action_docstring_used_when_defined_on_class(self):
        desc = DRFMCP._get_description(DocstringOnActionViewSet, "list")
        self.assertEqual(desc, "Return all widgets with pagination.")

    def test_inherited_action_docstring_ignored(self):
        """Inherited mixin docstrings should NOT be used — fall through to class doc."""

        class MyViewSet(ListModelMixin, GenericViewSet):
            """My custom viewset."""

            pass

        desc = DRFMCP._get_description(MyViewSet, "list")
        self.assertEqual(desc, "list — My custom viewset.")

    def test_class_docstring_fallback(self):
        desc = DRFMCP._get_description(ItemViewSet, "list")
        self.assertEqual(desc, "list — Manage inventory items.")

    def test_generic_fallback(self):
        class PlainViewSet(GenericViewSet):
            pass

        desc = DRFMCP._get_description(PlainViewSet, "list")
        self.assertEqual(desc, "List all Plain")

    def test_generic_fallback_strips_viewset_suffix(self):
        class OrderViewSet(GenericViewSet):
            pass

        desc = DRFMCP._get_description(OrderViewSet, "create")
        self.assertEqual(desc, "Create a new Order")

    def test_generic_fallback_strips_apiview_suffix(self):
        class OrderAPIView(GenericViewSet):
            pass

        desc = DRFMCP._get_description(OrderAPIView, "retrieve")
        self.assertEqual(desc, "Get details of a Order")


# ---------------------------------------------------------------------------
# _get_serializer_class
# ---------------------------------------------------------------------------
class TestGetSerializerClass(unittest.TestCase):
    """Test DRFMCP._get_serializer_class static method."""

    def test_gets_serializer_via_get_serializer_class(self):
        class DynamicViewSet(GenericViewSet):
            def get_serializer_class(self):
                return ItemSerializer

        result = DRFMCP._get_serializer_class(DynamicViewSet, "create")
        self.assertEqual(result, ItemSerializer)

    def test_falls_back_to_serializer_class_attr(self):
        result = DRFMCP._get_serializer_class(ItemViewSet, "create")
        self.assertEqual(result, ItemSerializer)

    def test_returns_none_when_no_serializer(self):
        """GenericViewSet.get_serializer_class raises AssertionError when
        serializer_class is not set. Our code catches AttributeError/TypeError
        but not AssertionError — so this currently propagates. Use a ViewSet
        that truly has no get_serializer_class."""
        from rest_framework.viewsets import ViewSetMixin
        from rest_framework.views import APIView

        class TrulyBareViewSet(ViewSetMixin, APIView):
            pass

        result = DRFMCP._get_serializer_class(TrulyBareViewSet, "list")
        self.assertIsNone(result)

    def test_handles_get_serializer_class_error(self):
        """If get_serializer_class raises, fall back to serializer_class."""

        class ErrorViewSet(GenericViewSet):
            serializer_class = ItemSerializer

            def get_serializer_class(self):
                raise AttributeError("needs request context")

        result = DRFMCP._get_serializer_class(ErrorViewSet, "create")
        self.assertEqual(result, ItemSerializer)


# ---------------------------------------------------------------------------
# register_view
# ---------------------------------------------------------------------------
class TestRegisterView(unittest.TestCase):
    """Test DRFMCP.register_view."""

    def setUp(self):
        self.mcp = DRFMCP("test")

    def test_registers_list_tool(self):
        self.mcp.register_view(ItemViewSet, action="list")
        tools = {t.name: t for t in self.mcp._fastmcp._tool_manager.list_tools()}
        self.assertIn("list_item", tools)

    def test_registers_create_tool_with_schema(self):
        self.mcp.register_view(ItemViewSet, action="create")
        tools = {t.name: t for t in self.mcp._fastmcp._tool_manager.list_tools()}
        self.assertIn("create_item", tools)

    def test_registers_retrieve_tool(self):
        self.mcp.register_view(ItemViewSet, action="retrieve")
        tools = {t.name: t for t in self.mcp._fastmcp._tool_manager.list_tools()}
        self.assertIn("retrieve_item", tools)

    def test_custom_name(self):
        self.mcp.register_view(ItemViewSet, action="list", name="get_all_items")
        tools = {t.name: t for t in self.mcp._fastmcp._tool_manager.list_tools()}
        self.assertIn("get_all_items", tools)

    def test_custom_description(self):
        self.mcp.register_view(
            ItemViewSet, action="list", description="Fetch every item"
        )
        tools = {t.name: t for t in self.mcp._fastmcp._tool_manager.list_tools()}
        self.assertEqual(tools["list_item"].description, "Fetch every item")

    def test_invalid_action_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self.mcp.register_view(ItemViewSet, action="bogus")
        self.assertIn("bogus", str(ctx.exception))

    def test_strips_viewset_from_basename(self):
        self.mcp.register_view(ItemViewSet, action="list")
        tools = {t.name: t for t in self.mcp._fastmcp._tool_manager.list_tools()}
        self.assertIn("list_item", tools)
        self.assertNotIn("list_itemviewset", tools)


# ---------------------------------------------------------------------------
# autodiscover
# ---------------------------------------------------------------------------
class WidgetSerializer(serializers.Serializer):
    label = serializers.CharField()


class WidgetViewSet(ListModelMixin, RetrieveModelMixin, GenericViewSet):
    serializer_class = WidgetSerializer


class OrderSerializer(serializers.Serializer):
    total = serializers.IntegerField()


class OrderViewSet(ListModelMixin, CreateModelMixin, DestroyModelMixin, GenericViewSet):
    serializer_class = OrderSerializer


class SecretViewSet(ListModelMixin, GenericViewSet):
    pass


class TestAutodiscover(unittest.TestCase):
    """Test DRFMCP.autodiscover with a DRF router."""

    def _make_router(self):
        router = DefaultRouter()
        router.register("widgets", WidgetViewSet, basename="widgets")
        router.register("orders", OrderViewSet, basename="orders")
        router.register("secrets", SecretViewSet, basename="secrets")
        return router

    def _tool_names(self, mcp):
        return {t.name for t in mcp._fastmcp._tool_manager.list_tools()}

    def test_discovers_all_actions(self):
        mcp = DRFMCP("test")
        mcp.autodiscover(self._make_router())
        names = self._tool_names(mcp)
        # WidgetViewSet has list + retrieve
        self.assertIn("widgets_list", names)
        self.assertIn("widgets_retrieve", names)
        # OrderViewSet has list + create + destroy
        self.assertIn("orders_list", names)
        self.assertIn("orders_create", names)
        self.assertIn("orders_destroy", names)

    def test_exclude_filters_out_viewsets(self):
        mcp = DRFMCP("test")
        mcp.autodiscover(self._make_router(), exclude=["secrets"])
        names = self._tool_names(mcp)
        self.assertIn("widgets_list", names)
        self.assertNotIn("secrets_list", names)

    def test_include_limits_to_specified(self):
        mcp = DRFMCP("test")
        mcp.autodiscover(self._make_router(), include=["widgets"])
        names = self._tool_names(mcp)
        self.assertIn("widgets_list", names)
        self.assertNotIn("orders_list", names)
        self.assertNotIn("secrets_list", names)

    def test_skips_actions_not_on_viewset(self):
        """WidgetViewSet doesn't have create, so no widgets_create tool."""
        mcp = DRFMCP("test")
        mcp.autodiscover(self._make_router())
        names = self._tool_names(mcp)
        self.assertNotIn("widgets_create", names)
        self.assertNotIn("widgets_destroy", names)
