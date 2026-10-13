# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Private viewport defaults survive real setting edits, reset, and history."""

from contextlib import nullcontext
from copy import deepcopy
import re
from types import SimpleNamespace

import pytest

from ovui_data_adapters.ovstage import _authoring
from ovui_data_adapters.ovstage import renderer_adapter as renderer_module
from ovui_data_adapters.ovstage._native import NativePathAttributeRecord
from ovui_data_adapters.services.undo import UndoManager
from test_renderer_livestream import _FakeScene, _patch_adapter_construction


QUALITY = "omni:rtx:quality"


class _NativeStage:
    """In-memory native boundary; production code owns validation and history."""

    def __init__(self):
        self.current_ordinal = 0
        self.columns = {}
        self.fail_next_write = False

    def begin_frame(self):
        return self.current_ordinal + 1

    def end_frame(self, ordinal):
        self.current_ordinal = ordinal

    def abort_frame(self, ordinal):
        pass

    def get_child_paths(self, parent):
        return [path for path in self.columns if path.rsplit("/", 1)[0] == parent]

    def query_from_path_list(self, paths):
        return SimpleNamespace(paths=paths, release=lambda: None)

    def write_attributes(self, query, descriptors, ordinal, *, prim_mode):
        if self.fail_next_write:
            self.fail_next_write = False
            raise RuntimeError("native quality write refused")
        for descriptor in descriptors:
            for path, value in zip(query.paths, descriptor.values):
                self.columns[path][descriptor.name] = int(value)

    def delete_attributes(self, query, names, ordinal):
        for path in query.paths:
            for name in names:
                self.columns[path].pop(name, None)


class _PathDictionary:
    def __init__(self, stage):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        pass

    def create_path_list_from_strings(self, paths):
        return tuple(paths)

    def destroy_path_list(self, paths):
        pass


@pytest.fixture(params=[False, True], ids=["native-column", "builtin-default-100"])
def viewport_factory(monkeypatch, request):
    """Keep the public settings API and command transaction pipeline real."""
    schema_fields = (
        "_RENDER_SETTINGS_PROVIDER_ID", "_RENDER_SETTINGS_PROVIDER_LABEL",
        "_RENDER_SETTINGS_PUBLIC_NAMESPACES", "_RENDER_SETTINGS_GROUP_FALLBACK",
        "_RENDER_SETTINGS_GROUP_LABEL_FALLBACK", "_RENDER_SETTINGS_BUILTIN_SPECS",
        "_RENDER_SETTINGS_BUILTIN_SPEC_INDEX",
    )
    for name in schema_fields:
        monkeypatch.setattr(renderer_module, name, getattr(renderer_module, name))
    renderer_module.configure_render_settings_schema(
        provider_id="test", provider_label="Test",
        public_namespaces=("omni:rtx:",), group_fallback="rtx",
        group_label_fallback="RTX",
        builtin_specs=({"attr_name": QUALITY, "usd_type": "int", "default": 100},)
        if request.param else (),
    )
    build_layer = renderer_module._build_runtime_layer
    _patch_adapter_construction(monkeypatch)
    monkeypatch.setattr(renderer_module, "_build_runtime_layer", build_layer)
    monkeypatch.setattr(renderer_module, "_query_records", lambda _stage: {})
    monkeypatch.setattr(renderer_module, "_select_runtime_root_path", lambda scene: scene.root)
    monkeypatch.setenv("OVGEAR_LIVESTREAM", "0")

    def populate(_population, stage, usda, *, prefix_path):
        if 'def RenderProduct "Viewport"' in usda:
            quality = int(re.search(r"custom int omni:rtx:quality = (\d+)", usda)[1])
            stage.columns[prefix_path + "/Render/Viewport"] = {QUALITY: quality}
        return object()

    def read_records(stage, path, names=None):
        return {
            name: NativePathAttributeRecord(name, (0, 32, 1), 0, False, value)
            for name, value in stage.columns.get(path, {}).items()
            if names is None or name in names
        }

    monkeypatch.setattr(renderer_module, "_add_runtime_layer", populate)
    monkeypatch.setattr(renderer_module, "read_path_attribute_records", read_records)
    monkeypatch.setattr(
        renderer_module, "native_catalog_snapshot",
        lambda scene: SimpleNamespace(prim=lambda path: (
            SimpleNamespace(type_name="RenderProduct")
            if path in scene._stage.columns else None
        )),
    )
    native = SimpleNamespace(
        PathDictionary=_PathDictionary,
        DLDataType=lambda **kwargs: SimpleNamespace(**kwargs),
        make_dltensor=lambda values, **kwargs: values.copy(),
        WriteDesc=lambda name, values, **kwargs: SimpleNamespace(name=name, values=values, **kwargs),
        PrimMode=SimpleNamespace(UPSERT="upsert"),
    )
    monkeypatch.setattr(_authoring, "import_ovstage_runtime_module", lambda _name: native)
    adapters = []

    def create(quality=0, root="/_OvuiRuntime"):
        scene = _FakeScene()
        scene.root = root
        scene._stage = _NativeStage()
        scene.change_stream = SimpleNamespace(
            suppress_notifications=nullcontext,
            committed_edge_publication=nullcontext,
            publish_attribute_change=lambda *_args, **_kwargs: None,
        )
        undo = UndoManager()
        adapter = renderer_module.OvstageRendererAdapter(undo_manager=undo, viewport_quality=quality)
        adapters.append(adapter)
        adapter.load_stage(scene)
        return SimpleNamespace(
            adapter=adapter, stage=scene._stage, undo=undo,
            product=root + "/Render/Viewport", builtin=request.param,
        )

    yield create
    for adapter in reversed(adapters):
        adapter.shutdown()


def _quality_descriptor(adapter, path):
    return next(item for item in adapter.list_render_settings(path).settings
                if item.property_name == "quality")


@pytest.mark.parametrize("quality", [0, 37, 100])
@pytest.mark.parametrize("root", ["/_OvuiRuntime", "/_OvuiRuntime_2"])
def test_reset_restores_configured_private_quality(viewport_factory, quality, root):
    viewport = viewport_factory(quality, root)
    adapter, path = viewport.adapter, viewport.product
    assert adapter.apply_render_setting(QUALITY, 61).accepted

    result = adapter.reset_render_setting(QUALITY)

    assert result.accepted, result.message
    assert "no change" not in result.message.lower()
    assert viewport.stage.columns[path].get(QUALITY) == quality
    assert result.reset_value == quality
    assert result.value_state.current_value == quality
    assert result.value_state.authored is False
    assert adapter.read_render_setting_value(QUALITY) == quality


@pytest.mark.parametrize("quality", [0, 37, 100])
def test_private_quality_metadata_tracks_configured_default(viewport_factory, quality):
    viewport = viewport_factory(quality)
    adapter, path = viewport.adapter, viewport.product
    initial = _quality_descriptor(adapter, path)
    assert initial.has_default is True
    assert initial.default_value == quality
    assert initial.value_state.has_default is True
    assert initial.value_state.default_value == quality
    assert initial.value_state.current_value == quality
    assert initial.value_state.authored is False
    assert adapter.read_render_setting_value(QUALITY) == quality

    edited = adapter.apply_render_setting(QUALITY, 61)
    assert edited.accepted, edited.message
    assert edited.value_state.current_value == 61
    assert edited.value_state.authored is True
    assert edited.value_state.default_value == quality
    assert adapter.read_render_setting_value(QUALITY) == 61

    restored = adapter.apply_render_setting(QUALITY, quality)
    assert restored.accepted, restored.message
    assert restored.value_state.authored is False
    assert restored.value_state.current_value == quality


@pytest.mark.parametrize("path", [
    "/Render/AuthoredProduct", "/_OvuiRuntime/Render/Viewport",
    "/_OvuiRuntime_2/Render/ViewportBackup",
])
def test_other_products_keep_native_default_and_delete_on_reset(viewport_factory, path):
    viewport = viewport_factory(37, "/_OvuiRuntime_2")
    viewport.stage.columns[path] = {QUALITY: 72}
    descriptor = _quality_descriptor(viewport.adapter, path)
    assert descriptor.default_value == (100 if viewport.builtin else None)
    assert descriptor.has_default is viewport.builtin
    assert descriptor.value_state.current_value == 72
    assert descriptor.value_state.authored is True

    result = viewport.adapter.reset_render_setting(QUALITY, render_product_path=path)

    assert result.accepted, result.message
    assert QUALITY not in viewport.stage.columns[path]
    assert viewport.stage.columns[viewport.product][QUALITY] == 37
    assert viewport.adapter.read_render_setting_value(QUALITY, render_product_path=path) == (
        100 if viewport.builtin else None
    )


@pytest.mark.parametrize("root", ["/_OvuiRuntime", "/_OvuiRuntime_2"])
def test_private_default_follows_generated_product_not_active_product(
    viewport_factory, monkeypatch, root
):
    viewport = viewport_factory(37, root)
    adapter = viewport.adapter
    authored = "/Render/AuthoredProduct"
    viewport.stage.columns[authored] = {QUALITY: 72}
    # The fake native stage stores columns but has no prim-type query.
    monkeypatch.setattr(
        adapter, "_path_has_type",
        lambda path, _types: path in viewport.stage.columns,
    )

    assert adapter.set_active_render_product_path(authored)
    assert adapter.get_active_render_product_path() == authored
    other = _quality_descriptor(adapter, None)
    assert other.has_default is viewport.builtin
    assert other.default_value == (100 if viewport.builtin else None)
    assert adapter.reset_render_setting(QUALITY).accepted
    assert QUALITY not in viewport.stage.columns[authored]

    private = _quality_descriptor(adapter, viewport.product)
    assert private.has_default is True
    assert private.default_value == 37
    assert adapter.apply_render_setting(
        QUALITY, 61, render_product_path=viewport.product
    ).accepted
    assert adapter.reset_render_setting(
        QUALITY, render_product_path=viewport.product
    ).accepted
    assert viewport.stage.columns[viewport.product][QUALITY] == 37
    assert QUALITY not in viewport.stage.columns[authored]

    assert adapter.set_active_render_product_path(None)
    assert adapter.get_active_render_product_path() == viewport.product
    assert _quality_descriptor(adapter, None).default_value == 37


def test_other_private_product_settings_still_delete_on_reset(viewport_factory):
    viewport = viewport_factory(37)
    other_setting = "omni:rtx:unrelated"
    viewport.stage.columns[viewport.product][other_setting] = 12

    result = viewport.adapter.reset_render_setting(other_setting)

    assert result.accepted, result.message
    assert other_setting not in viewport.stage.columns[viewport.product]
    assert viewport.stage.columns[viewport.product][QUALITY] == 37


def test_defaults_do_not_leak_between_adapters_or_builtin_registry(viewport_factory):
    original_specs = deepcopy(renderer_module._RENDER_SETTINGS_BUILTIN_SPECS)
    original_index = deepcopy(renderer_module._RENDER_SETTINGS_BUILTIN_SPEC_INDEX)
    progressive = viewport_factory(0)
    capture = viewport_factory(100)
    intermediate = viewport_factory(37)

    for viewport, expected in ((progressive, 0), (capture, 100), (intermediate, 37), (progressive, 0)):
        assert viewport.adapter.apply_render_setting(QUALITY, 61).accepted
        assert viewport.adapter.reset_render_setting(QUALITY).accepted
        assert _quality_descriptor(viewport.adapter, viewport.product).default_value == expected
        assert viewport.stage.columns[viewport.product].get(QUALITY) == expected
    assert renderer_module._RENDER_SETTINGS_BUILTIN_SPECS == original_specs
    assert renderer_module._RENDER_SETTINGS_BUILTIN_SPEC_INDEX == original_index


def test_reset_undo_redo_preserves_quality_and_authorship(viewport_factory):
    viewport = viewport_factory(37)
    adapter, undo = viewport.adapter, viewport.undo
    assert adapter.apply_render_setting(QUALITY, 61).accepted
    assert adapter.reset_render_setting(QUALITY).accepted
    assert viewport.stage.columns[viewport.product].get(QUALITY) == 37

    assert undo.undo()
    assert adapter.read_render_setting(QUALITY).current_value == 61
    assert adapter.read_render_setting(QUALITY).authored is True
    assert undo.redo()
    assert viewport.stage.columns[viewport.product].get(QUALITY) == 37
    assert adapter.read_render_setting(QUALITY).authored is False
    assert undo.undo()
    assert undo.undo()
    assert viewport.stage.columns[viewport.product].get(QUALITY) == 37
    assert undo.can_undo() is False
    assert undo.redo()
    assert undo.redo()
    assert viewport.stage.columns[viewport.product].get(QUALITY) == 37
    assert undo.can_redo() is False


def test_reset_at_configured_default_is_a_noop(viewport_factory):
    viewport = viewport_factory(37)
    adapter, undo = viewport.adapter, viewport.undo
    before_ordinal = viewport.stage.current_ordinal
    notifications = []
    subscription = adapter.subscribe_render_settings_changes(lambda: notifications.append(True))

    result = adapter.reset_render_setting(QUALITY)

    assert result.accepted, result.message
    assert "no change" in result.message.lower()
    assert result.reset_value == 37
    assert result.value_state.authored is False
    assert viewport.stage.current_ordinal == before_ordinal
    assert undo.can_undo() is False
    assert notifications == []
    subscription.cancel()


def test_failed_reset_preserves_value_and_history(viewport_factory):
    viewport = viewport_factory(0)
    adapter, undo = viewport.adapter, viewport.undo
    assert adapter.apply_render_setting(QUALITY, 61).accepted
    viewport.stage.fail_next_write = True

    result = adapter.reset_render_setting(QUALITY)

    assert result.accepted is False
    assert result.warning_code == "reset_failed"
    assert viewport.stage.columns[viewport.product][QUALITY] == 61
    assert undo.undo()
    assert viewport.stage.columns[viewport.product][QUALITY] == 0
    assert undo.can_undo() is False
