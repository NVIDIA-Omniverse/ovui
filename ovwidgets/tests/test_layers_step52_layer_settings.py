# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 52 — ``LayerSettings`` persistent configuration.

Covers the LAYERS-PLAN Step 52 deliverables:

  * :class:`LayerSettings` property surface + defaults matching
    LAYERS-WINDOW-ARCHITECTURE §15.
  * Getter / setter round-trip through the backing :class:`Settings`
    so values persist via the existing JSON save / load pipeline.
  * ``Settings`` defaults register the ``layers.*`` keys so a fresh
    settings instance hands the same factory values back as
    :class:`LayerSettings`.
  * Save-to-file / load-from-file round-trip: a toggled value
    reloads on a fresh :class:`LayerSettings` paired with a freshly
    loaded :class:`Settings`.
  * ``LayerSettings.subscribe`` fires the callback for every tracked
    key; ``subscribe_tree_rebuild`` narrows to the tree-shape subset.
  * :class:`LayerModel` accepts both the dataclass stand-in and the
    persistent :class:`LayerSettings`.
  * Toggling a tree-shape key on the bound :class:`Settings`
    triggers a ``_item_changed(None)`` repaint.
  * :class:`LayerModel.destroy` cancels every settings subscription
    so later toggles are no-ops on the dead model.
  * :class:`LayerWindow` resolves its own :class:`LayerSettings`
    from ``app.settings`` when a real :class:`Settings` is available
    and falls back to :class:`DefaultLayerSettings` otherwise.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.settings import Settings
from ovwidgets.layers import (
    LAYER_SETTINGS_KEYS,
    DefaultLayerSettings,
    LayerModel,
    LayerSettings,
    LayerWindow,
)
from ovwidgets.layers.layer_settings import TREE_REBUILD_KEYS

# ─── LayerSettings property surface ───────────────────────────────────────────


class TestLayerSettingsProperties:
    def test_defaults_match_arch_section_15(self) -> None:
        s = Settings()
        ls = LayerSettings(s)
        assert ls.show_session_layer is True
        assert ls.show_layer_contents is True
        assert ls.show_missing_reference is True
        assert ls.show_info_notification is True
        assert ls.show_merge_or_flatten_warning is True
        assert ls.show_layer_file_extension is True
        assert ls.show_metricsassembler_layer is False
        assert ls.file_dialog_show_root_layer_location is False
        assert ls.enable_auto_authoring_mode is False
        assert ls.enable_spec_linking_mode is False

    def test_settings_property_returns_backing_store(self) -> None:
        s = Settings()
        ls = LayerSettings(s)
        assert ls.settings is s

    def test_setter_writes_to_backing_store(self) -> None:
        s = Settings()
        ls = LayerSettings(s)
        ls.show_session_layer = False
        assert s.get("layers.show_session_layer") is False
        ls.show_session_layer = True
        assert s.get("layers.show_session_layer") is True

    def test_getter_reads_from_backing_store(self) -> None:
        s = Settings()
        s.set("layers.show_layer_contents", False)
        ls = LayerSettings(s)
        assert ls.show_layer_contents is False

    def test_setter_coerces_to_bool(self) -> None:
        s = Settings()
        ls = LayerSettings(s)
        ls.show_session_layer = 0  # type: ignore[assignment]
        assert s.get("layers.show_session_layer") is False
        ls.show_session_layer = 1  # type: ignore[assignment]
        assert s.get("layers.show_session_layer") is True

    def test_every_key_in_table_has_a_property(self) -> None:
        ls = LayerSettings(Settings())
        for prop_name in LAYER_SETTINGS_KEYS:
            assert hasattr(ls, prop_name)
            # Round-trip through the setter/getter pair — both sides
            # should honour the coercion and the stored value should
            # end up on the backing store.
            current = getattr(ls, prop_name)
            setattr(ls, prop_name, not current)
            assert getattr(ls, prop_name) is (not current)

    def test_two_wrappers_share_backing_state(self) -> None:
        s = Settings()
        a = LayerSettings(s)
        b = LayerSettings(s)
        a.show_session_layer = False
        assert b.show_session_layer is False

    def test_key_namespace_is_layers_prefix(self) -> None:
        for prop_name, (key, _default) in LAYER_SETTINGS_KEYS.items():
            assert key.startswith("layers."), (
                f"{prop_name!r} key {key!r} must live under the "
                "layers.* namespace for JSON round-trip"
            )


# ─── Settings defaults cover every key ────────────────────────────────────────


class TestSettingsDefaults:
    def test_defaults_registered_for_every_key(self) -> None:
        s = Settings()
        for _prop_name, (key, default) in LAYER_SETTINGS_KEYS.items():
            assert s.get(key) == default, (
                f"{key!r} default {s.get(key)!r} does not match "
                f"expected {default!r}"
            )

    def test_save_to_file_writes_layer_keys(self, tmp_path) -> None:
        s = Settings()
        path = str(tmp_path / "settings.json")
        s.save_to_file(path)
        with open(path) as fh:
            data = json.load(fh)
        for _prop_name, (key, _default) in LAYER_SETTINGS_KEYS.items():
            assert key in data


# ─── Persistence round-trip ───────────────────────────────────────────────────


class TestPersistence:
    def test_round_trip_toggled_value(self, tmp_path) -> None:
        s1 = Settings()
        LayerSettings(s1).show_session_layer = False
        path = str(tmp_path / "settings.json")
        s1.save_to_file(path)

        s2 = Settings()
        s2.load_from_file(path)
        assert LayerSettings(s2).show_session_layer is False

    def test_round_trip_preserves_defaults_when_not_touched(
        self, tmp_path
    ) -> None:
        s1 = Settings()
        path = str(tmp_path / "settings.json")
        s1.save_to_file(path)

        s2 = Settings()
        s2.load_from_file(path)
        ls2 = LayerSettings(s2)
        assert ls2.show_session_layer is True
        assert ls2.show_metricsassembler_layer is False

    def test_multiple_keys_persist(self, tmp_path) -> None:
        s1 = Settings()
        ls1 = LayerSettings(s1)
        ls1.show_session_layer = False
        ls1.show_layer_contents = False
        ls1.enable_auto_authoring_mode = True
        path = str(tmp_path / "settings.json")
        s1.save_to_file(path)

        s2 = Settings()
        s2.load_from_file(path)
        ls2 = LayerSettings(s2)
        assert ls2.show_session_layer is False
        assert ls2.show_layer_contents is False
        assert ls2.enable_auto_authoring_mode is True


# ─── Subscription helpers ─────────────────────────────────────────────────────


class TestSubscribe:
    def test_subscribe_fires_for_tracked_keys(self) -> None:
        s = Settings()
        ls = LayerSettings(s)
        calls = []
        subs = ls.subscribe(lambda k, v: calls.append((k, v)))
        try:
            ls.show_session_layer = False
            assert ("layers.show_session_layer", False) in calls
            ls.enable_auto_authoring_mode = True
            assert ("layers.enable_auto_authoring_mode", True) in calls
        finally:
            for sub in subs:
                sub.cancel()

    def test_subscribe_returns_one_sub_per_key(self) -> None:
        s = Settings()
        ls = LayerSettings(s)
        subs = ls.subscribe(lambda k, v: None)
        try:
            assert len(subs) == len(LAYER_SETTINGS_KEYS)
        finally:
            for sub in subs:
                sub.cancel()

    def test_cancel_stops_callback(self) -> None:
        s = Settings()
        ls = LayerSettings(s)
        calls = []
        subs = ls.subscribe(lambda k, v: calls.append(k))
        for sub in subs:
            sub.cancel()
        ls.show_session_layer = False
        assert calls == []

    def test_subscribe_tree_rebuild_only_fires_for_tree_keys(self) -> None:
        s = Settings()
        ls = LayerSettings(s)
        calls = []
        subs = ls.subscribe_tree_rebuild(lambda k, v: calls.append(k))
        try:
            # Non-tree key — should not fire.
            ls.show_info_notification = False
            assert calls == []
            # Tree-shape key — should fire.
            ls.show_session_layer = False
            assert "layers.show_session_layer" in calls
            ls.show_layer_contents = False
            assert "layers.show_layer_contents" in calls
        finally:
            for sub in subs:
                sub.cancel()

    def test_tree_rebuild_keys_subset(self) -> None:
        # Every TREE_REBUILD_KEYS entry must have a mapped property.
        values = {key for _, (key, _) in LAYER_SETTINGS_KEYS.items()}
        for key in TREE_REBUILD_KEYS:
            assert key in values


# ─── LayerModel accepts both settings variants ───────────────────────────────


class TestLayerModelIntegration:
    def test_model_accepts_default_layer_settings(self) -> None:
        adapter = MockLayerStackAdapter()
        settings = DefaultLayerSettings(show_session_layer=False)
        model = LayerModel(adapter, settings=settings)
        try:
            assert model.settings is settings
            children = model.get_item_children(None)
            assert children == [model.root_item]
        finally:
            model.destroy()

    def test_model_accepts_layer_settings(self) -> None:
        adapter = MockLayerStackAdapter()
        s = Settings()
        ls = LayerSettings(s)
        ls.show_session_layer = False
        model = LayerModel(adapter, settings=ls)
        try:
            assert model.settings is ls
            children = model.get_item_children(None)
            assert children == [model.root_item]
        finally:
            model.destroy()

    def test_model_subscribes_to_tree_rebuild_keys(self) -> None:
        adapter = MockLayerStackAdapter()
        ls = LayerSettings(Settings())
        model = LayerModel(adapter, settings=ls)
        try:
            assert len(model._settings_subs) == len(TREE_REBUILD_KEYS)
        finally:
            model.destroy()

    def test_dataclass_settings_no_subscription(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter, settings=DefaultLayerSettings())
        try:
            assert model._settings_subs == []
        finally:
            model.destroy()

    def test_session_toggle_reshapes_tree(self) -> None:
        adapter = MockLayerStackAdapter(include_session=True)
        ls = LayerSettings(Settings())
        model = LayerModel(adapter, settings=ls)
        try:
            # Default: session visible.
            assert len(model.get_item_children(None)) == 2
            # Flip → session hidden.
            ls.show_session_layer = False
            assert model.get_item_children(None) == [model.root_item]
            # Flip back → session reappears.
            ls.show_session_layer = True
            assert len(model.get_item_children(None)) == 2
        finally:
            model.destroy()

    def test_settings_change_fires_item_changed(self) -> None:
        adapter = MockLayerStackAdapter(include_session=True)
        ls = LayerSettings(Settings())
        model = LayerModel(adapter, settings=ls)
        try:
            calls: list = []
            sub = model.subscribe_item_changed_fn(
                lambda _m, item: calls.append(item)
            )
            try:
                ls.show_session_layer = False
                # A ``None`` entry means "top-level rebuild" — the
                # ``ui.TreeView`` re-queries :meth:`get_item_children`
                # against the new flag state.
                assert None in calls
            finally:
                sub.unsubscribe()
        finally:
            model.destroy()

    def test_destroy_cancels_settings_subs(self) -> None:
        adapter = MockLayerStackAdapter()
        s = Settings()
        ls = LayerSettings(s)
        model = LayerModel(adapter, settings=ls)
        assert len(model._settings_subs) == len(TREE_REBUILD_KEYS)
        model.destroy()
        # After destroy the list has been released.
        assert model._settings_subs == []
        # And toggles do not blow up on the dead model — the Settings
        # key simply has no live subscriber.
        ls.show_session_layer = False  # must not raise

    def test_show_layer_contents_flip_invalidates_prim_specs(self) -> None:

        adapter = MockLayerStackAdapter()
        from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/Kitten", type_name="Xform"
        )
        s = Settings()
        ls = LayerSettings(s)
        # Start with contents visible so the cache actually populates.
        ls.show_layer_contents = True
        model = LayerModel(adapter, settings=ls)
        try:
            children_visible = model.get_item_children(model.root_item)
            # Root has no sublayers but now carries a prim spec row.
            assert any(
                getattr(c, "path", None) == "/Kitten"
                for c in children_visible
            )
            # Flip off — cached spec list must be dropped so the next
            # read returns an empty list.
            ls.show_layer_contents = False
            children_hidden = model.get_item_children(model.root_item)
            assert children_hidden == []
        finally:
            model.destroy()


# ─── LayerWindow resolves settings ────────────────────────────────────────────


class TestLayerWindowResolution:
    def test_window_wraps_app_settings_when_real(self) -> None:
        class FakeApp:
            def __init__(self) -> None:
                self.settings = Settings()
                self.undo_manager = MagicMock()

        app = FakeApp()
        adapter = MockLayerStackAdapter()
        w = LayerWindow(services=app, adapter=adapter)
        try:
            assert isinstance(w.settings, LayerSettings)
            assert w.settings.settings is app.settings
        finally:
            w.destroy()

    def test_window_falls_back_to_default_when_no_settings(self) -> None:
        # MagicMock ``app.settings`` is NOT a real :class:`Settings` —
        # the window must not blow up or mistake it for one.
        w = LayerWindow(services=MagicMock(), adapter=MockLayerStackAdapter())
        try:
            assert isinstance(w.settings, DefaultLayerSettings)
        finally:
            w.destroy()

    def test_window_accepts_explicit_settings(self) -> None:
        explicit = DefaultLayerSettings(show_session_layer=False)
        w = LayerWindow(
            services=MagicMock(),
            adapter=MockLayerStackAdapter(),
            settings=explicit,
        )
        try:
            assert w.settings is explicit
        finally:
            w.destroy()

    def test_window_passes_settings_into_model(self) -> None:
        class FakeApp:
            def __init__(self) -> None:
                self.settings = Settings()
                self.undo_manager = MagicMock()

        app = FakeApp()
        adapter = MockLayerStackAdapter()
        w = LayerWindow(services=app, adapter=adapter)
        try:
            # Model is constructed lazily on first frame rebuild —
            # call :meth:`_build_ui` directly so the test does not
            # depend on a rendered frame.
            w._build_ui()
            assert w._model is not None
            assert w._model.settings is w.settings
        finally:
            w.destroy()
