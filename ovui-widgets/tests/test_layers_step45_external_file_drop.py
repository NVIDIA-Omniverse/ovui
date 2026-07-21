# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 45 — External file drop → Insert Sublayer.

Step 45 extends the ``AbstractItemModel`` drop overrides introduced
in Step 43 to accept an OS-provided file path (or list of paths) as
the drop ``source``. When the payload carries a USD-compatible
extension (``.usd`` / ``.usda`` / ``.usdc``), the model pushes one
:class:`~ovui_widgets.layers.commands.InsertSublayerCommand` per path through
the :class:`~ovui_widgets.common.undo.UndoManager` — wrapping multiple paths in a
single ``"Insert files"`` group so one Ctrl+Z rewinds the entire
batch.

Coverage:

- Path-extension validator (case-insensitive, rejects ``.usdz`` and
  non-USD files, tolerates a list payload).
- ``drop_accepted`` accepts string / list sources that pass the
  extension check and marks the drop visual ``valid``.
- ``drop_accepted`` rejects mixed / non-USD batches and records a
  readable rejection reason on the drop-visual controller.
- ``drop`` routes a single path to a lone ``InsertSublayerCommand``
  and multi-path drops to a grouped push (one undo entry).
- Headless (``app=None``) drop bypasses the undo stack and calls
  :meth:`LayerStackAdapter.insert_sublayer` directly.
- :meth:`LayerModel.request_insert_file_sublayers_at_root` is the
  empty-area drop entry point and lands every path under the root
  layer.
- :class:`LayerWindow`'s empty-area rectangle accept / drop
  callbacks forward to the model method.
"""

from __future__ import annotations

from typing import List

import pytest

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.layers import LayerModel, LayerWindow
from ovui_widgets.layers.commands import InsertSublayerCommand
from ovui_widgets.layers.layer_model import (
    _extract_file_paths,
    _is_valid_usd_path,
)


class _App:
    """Minimal :class:`Application` stand-in for undo-pipeline tests."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    ad = MockLayerStackAdapter(include_session=True)
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./a.usda")
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./b.usda")
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./c.usda")
    return ad


@pytest.fixture
def app() -> _App:
    return _App()


@pytest.fixture
def model(adapter: MockLayerStackAdapter, app: _App) -> LayerModel:
    m = LayerModel(adapter, services=app)
    yield m
    m.destroy()


@pytest.fixture
def headless_model(adapter: MockLayerStackAdapter) -> LayerModel:
    m = LayerModel(adapter, services=None)
    yield m
    m.destroy()


def _root_children(adapter: MockLayerStackAdapter) -> List[str]:
    return adapter.get_sublayer_identifiers(adapter.get_root_layer())


def _a_children(adapter: MockLayerStackAdapter) -> List[str]:
    return adapter.get_sublayer_identifiers(adapter.find_layer("./a.usda"))


# ── Extension validator ─────────────────────────────────────────────


class TestIsValidUsdPath:
    @pytest.mark.parametrize(
        "path",
        [
            "/tmp/file.usda",
            "/tmp/file.usdc",
            "/tmp/file.usd",
            "/tmp/FILE.USDA",
            "./relative/path.Usd",
            "C:\\windows\\file.USDC",
        ],
    )
    def test_accepts_usd_extensions_case_insensitive(self, path: str) -> None:
        assert _is_valid_usd_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/tmp/file.png",
            "/tmp/file.fbx",
            "/tmp/file",
            "/tmp/file.usdz",  # USD package — deliberately out of scope
            "",
            ".usdaX",
        ],
    )
    def test_rejects_non_usd_paths(self, path: str) -> None:
        assert _is_valid_usd_path(path) is False

    def test_rejects_non_string_input(self) -> None:
        assert _is_valid_usd_path(None) is False  # type: ignore[arg-type]
        assert _is_valid_usd_path(42) is False  # type: ignore[arg-type]


# ── Payload normaliser ──────────────────────────────────────────────


class TestExtractFilePaths:
    def test_single_string_path(self) -> None:
        assert _extract_file_paths("/tmp/x.usda") == ["/tmp/x.usda"]

    def test_newline_separated_paths(self) -> None:
        payload = "/tmp/a.usda\n/tmp/b.usdc"
        assert _extract_file_paths(payload) == [
            "/tmp/a.usda",
            "/tmp/b.usdc",
        ]

    def test_list_of_paths(self) -> None:
        assert _extract_file_paths(
            ["/tmp/a.usda", "/tmp/b.usd"]
        ) == ["/tmp/a.usda", "/tmp/b.usd"]

    def test_strips_whitespace_and_drops_empties(self) -> None:
        assert _extract_file_paths(
            ["  /tmp/a.usda  ", "", "/tmp/b.usdc"]
        ) == ["/tmp/a.usda", "/tmp/b.usdc"]

    def test_empty_payload_returns_none(self) -> None:
        assert _extract_file_paths("") is None
        assert _extract_file_paths("   ") is None
        assert _extract_file_paths([]) is None
        assert _extract_file_paths(["", "   "]) is None

    def test_non_string_non_list_returns_none(self) -> None:
        assert _extract_file_paths(None) is None
        assert _extract_file_paths(42) is None
        assert _extract_file_paths({"a": "b"}) is None


# ── drop_accepted ───────────────────────────────────────────────────


class TestDropAcceptedFileSource:
    def test_accepts_valid_usda_onto_layer_row(
        self, model: LayerModel
    ) -> None:
        a = model._items_by_id["./a.usda"]
        assert model.drop_accepted(a, "/tmp/new.usda", -1) is True
        dv = model.drop_visual
        assert dv.current_target is a
        assert dv.is_valid is True

    def test_accepts_valid_usdc_onto_root(
        self, model: LayerModel
    ) -> None:
        assert (
            model.drop_accepted(model.root_item, "/tmp/new.usdc", -1)
            is True
        )

    def test_accepts_valid_between_drop(self, model: LayerModel) -> None:
        a = model._items_by_id["./a.usda"]
        # Drop "between" a and b — drop_location == 1 under root.
        assert model.drop_accepted(a, "/tmp/new.usda", 1) is True

    def test_accepts_list_payload(self, model: LayerModel) -> None:
        a = model._items_by_id["./a.usda"]
        assert (
            model.drop_accepted(
                a, ["/tmp/one.usda", "/tmp/two.usdc"], -1
            )
            is True
        )

    def test_rejects_non_usd_extension(self, model: LayerModel) -> None:
        a = model._items_by_id["./a.usda"]
        assert model.drop_accepted(a, "/tmp/image.png", -1) is False
        dv = model.drop_visual
        assert dv.is_valid is False
        assert dv.rejection_reason == (
            "Cannot drop: only .usd, .usda and .usdc files are supported"
        )

    def test_rejects_usdz_package(self, model: LayerModel) -> None:
        a = model._items_by_id["./a.usda"]
        assert model.drop_accepted(a, "/tmp/pkg.usdz", -1) is False

    def test_rejects_mixed_batch(self, model: LayerModel) -> None:
        a = model._items_by_id["./a.usda"]
        # Mixed batch rejects the whole drop rather than committing a
        # partial one — the user needs to see the red indicator.
        assert (
            model.drop_accepted(
                a, ["/tmp/one.usda", "/tmp/two.png"], -1
            )
            is False
        )

    def test_rejects_drop_onto_locked_target(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        adapter.set_lock("./a.usda", True)
        model._items_by_id["./a.usda"].invalidate_flags()
        a = model._items_by_id["./a.usda"]
        assert model.drop_accepted(a, "/tmp/new.usda", -1) is False
        assert model.drop_visual.rejection_reason == (
            "Cannot drop: target layer is locked"
        )

    def test_rejects_between_drop_on_top_level(
        self, model: LayerModel
    ) -> None:
        # Root has no parent, so drop_location >= 0 targets nothing.
        assert (
            model.drop_accepted(model.root_item, "/tmp/new.usda", 0)
            is False
        )


# ── drop — single file ──────────────────────────────────────────────


class TestDropSingleFile:
    def test_drop_onto_row_inserts_as_child(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        a = model._items_by_id["./a.usda"]
        model.drop(a, "/tmp/new.usda", -1)
        # ./a.usda gains a new sublayer (appended, position=-1).
        assert _a_children(adapter) == ["/tmp/new.usda"]

    def test_drop_onto_root_appends_at_end(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        model.drop(model.root_item, "/tmp/new.usda", -1)
        assert _root_children(adapter) == [
            "./a.usda",
            "./b.usda",
            "./c.usda",
            "/tmp/new.usda",
        ]

    def test_between_drop_inserts_at_slot(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        a = model._items_by_id["./a.usda"]
        # Slot 1 under root — between ./a.usda and ./b.usda.
        model.drop(a, "/tmp/new.usda", 1)
        assert _root_children(adapter) == [
            "./a.usda",
            "/tmp/new.usda",
            "./b.usda",
            "./c.usda",
        ]

    def test_pushes_insert_sublayer_command(
        self, model: LayerModel, app: _App
    ) -> None:
        a = model._items_by_id["./a.usda"]
        model.drop(a, "/tmp/new.usda", -1)
        history = app.undo_manager._undo_stack
        assert len(history) == 1
        assert isinstance(history[-1], InsertSublayerCommand)

    def test_undo_removes_the_inserted_sublayer(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
        app: _App,
    ) -> None:
        a = model._items_by_id["./a.usda"]
        model.drop(a, "/tmp/new.usda", -1)
        assert _a_children(adapter) == ["/tmp/new.usda"]
        app.undo_manager.undo()
        assert _a_children(adapter) == []

    def test_redo_reapplies_the_insert(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
        app: _App,
    ) -> None:
        a = model._items_by_id["./a.usda"]
        model.drop(a, "/tmp/new.usda", -1)
        app.undo_manager.undo()
        app.undo_manager.redo()
        assert _a_children(adapter) == ["/tmp/new.usda"]

    def test_invalid_drop_pushes_no_command(
        self, model: LayerModel, app: _App
    ) -> None:
        a = model._items_by_id["./a.usda"]
        model.drop(a, "/tmp/bad.png", -1)
        assert app.undo_manager.can_undo() is False


# ── drop — multi file ───────────────────────────────────────────────


class TestDropMultipleFiles:
    def test_multi_drop_inserts_all_files(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        a = model._items_by_id["./a.usda"]
        model.drop(a, ["/tmp/one.usda", "/tmp/two.usdc"], -1)
        assert _a_children(adapter) == [
            "/tmp/one.usda",
            "/tmp/two.usdc",
        ]

    def test_multi_drop_preserves_order_at_positive_slot(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        a = model._items_by_id["./a.usda"]
        # Drop at slot 1 under root — new files land between ./a.usda
        # and ./b.usda in the order supplied.
        model.drop(a, ["/tmp/one.usda", "/tmp/two.usdc"], 1)
        assert _root_children(adapter) == [
            "./a.usda",
            "/tmp/one.usda",
            "/tmp/two.usdc",
            "./b.usda",
            "./c.usda",
        ]

    def test_multi_drop_uses_single_undo_group(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
        app: _App,
    ) -> None:
        a = model._items_by_id["./a.usda"]
        model.drop(a, ["/tmp/one.usda", "/tmp/two.usdc"], -1)
        # One Ctrl+Z rewinds the whole batch.
        assert len(app.undo_manager._undo_stack) == 1
        app.undo_manager.undo()
        assert _a_children(adapter) == []

    def test_multi_drop_redo_reapplies_whole_batch(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
        app: _App,
    ) -> None:
        a = model._items_by_id["./a.usda"]
        model.drop(a, ["/tmp/one.usda", "/tmp/two.usdc"], -1)
        app.undo_manager.undo()
        app.undo_manager.redo()
        assert _a_children(adapter) == [
            "/tmp/one.usda",
            "/tmp/two.usdc",
        ]

    def test_multi_drop_newline_string_payload(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        # Windows-style newline-separated multi-file drop.
        a = model._items_by_id["./a.usda"]
        model.drop(a, "/tmp/one.usda\n/tmp/two.usdc", -1)
        assert _a_children(adapter) == [
            "/tmp/one.usda",
            "/tmp/two.usdc",
        ]


# ── Headless fallback ───────────────────────────────────────────────


class TestHeadlessFileDrop:
    def test_drop_without_app_calls_adapter_directly(
        self,
        adapter: MockLayerStackAdapter,
        headless_model: LayerModel,
    ) -> None:
        a = headless_model._items_by_id["./a.usda"]
        headless_model.drop(a, "/tmp/new.usda", -1)
        assert _a_children(adapter) == ["/tmp/new.usda"]

    def test_multi_drop_without_app_calls_adapter_per_path(
        self,
        adapter: MockLayerStackAdapter,
        headless_model: LayerModel,
    ) -> None:
        a = headless_model._items_by_id["./a.usda"]
        headless_model.drop(
            a, ["/tmp/one.usda", "/tmp/two.usdc"], -1
        )
        assert _a_children(adapter) == [
            "/tmp/one.usda",
            "/tmp/two.usdc",
        ]


# ── Empty-area drop (root insert) ───────────────────────────────────


class TestRequestInsertFileSublayersAtRoot:
    def test_drop_on_empty_area_appends_under_root(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        handled = model.request_insert_file_sublayers_at_root(
            "/tmp/new.usda"
        )
        assert handled is True
        assert _root_children(adapter)[-1] == "/tmp/new.usda"

    def test_multi_file_empty_area_drop_appends_in_order(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        handled = model.request_insert_file_sublayers_at_root(
            ["/tmp/one.usda", "/tmp/two.usdc"]
        )
        assert handled is True
        assert _root_children(adapter)[-2:] == [
            "/tmp/one.usda",
            "/tmp/two.usdc",
        ]

    def test_invalid_extension_is_rejected(
        self, model: LayerModel, app: _App
    ) -> None:
        handled = model.request_insert_file_sublayers_at_root(
            "/tmp/image.png"
        )
        assert handled is False
        assert app.undo_manager.can_undo() is False

    def test_empty_payload_is_rejected(
        self, model: LayerModel, app: _App
    ) -> None:
        assert (
            model.request_insert_file_sublayers_at_root("")
            is False
        )
        assert app.undo_manager.can_undo() is False

    def test_empty_area_drop_is_undoable(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
        app: _App,
    ) -> None:
        before = list(_root_children(adapter))
        model.request_insert_file_sublayers_at_root("/tmp/new.usda")
        app.undo_manager.undo()
        assert _root_children(adapter) == before


# ── LayerWindow plumbing ────────────────────────────────────────────


class TestLayerWindowEmptyAreaWiring:
    def test_accept_drop_predicate_true_for_usd_path(
        self, adapter: MockLayerStackAdapter, app: _App
    ) -> None:
        win = LayerWindow(services=app, adapter=adapter)
        # ManagedWindow defers ``_build_ui`` until the frame is shown,
        # which doesn't happen in a headless test. ``set_adapter`` is
        # the documented way to force the model to exist.
        win.set_adapter(adapter)
        try:
            assert (
                win._on_empty_area_accept_drop("/tmp/x.usda") is True
            )
        finally:
            win.destroy()

    def test_accept_drop_predicate_false_for_non_usd(
        self, adapter: MockLayerStackAdapter, app: _App
    ) -> None:
        win = LayerWindow(services=app, adapter=adapter)
        # ManagedWindow defers ``_build_ui`` until the frame is shown,
        # which doesn't happen in a headless test. ``set_adapter`` is
        # the documented way to force the model to exist.
        win.set_adapter(adapter)
        try:
            assert (
                win._on_empty_area_accept_drop("/tmp/x.png") is False
            )
        finally:
            win.destroy()

    def test_drop_fn_routes_to_model(
        self,
        adapter: MockLayerStackAdapter,
        app: _App,
    ) -> None:
        win = LayerWindow(services=app, adapter=adapter)
        # ManagedWindow defers ``_build_ui`` until the frame is shown,
        # which doesn't happen in a headless test. ``set_adapter`` is
        # the documented way to force the model to exist.
        win.set_adapter(adapter)
        try:
            win._on_empty_area_dropped("/tmp/new.usda")
            assert _root_children(adapter)[-1] == "/tmp/new.usda"
        finally:
            win.destroy()

    def test_accept_drop_unwraps_event_like_payload(
        self, adapter: MockLayerStackAdapter, app: _App
    ) -> None:
        class _Event:
            def __init__(self, path: str) -> None:
                self.mime_data = path

        win = LayerWindow(services=app, adapter=adapter)
        # ManagedWindow defers ``_build_ui`` until the frame is shown,
        # which doesn't happen in a headless test. ``set_adapter`` is
        # the documented way to force the model to exist.
        win.set_adapter(adapter)
        try:
            assert (
                win._on_empty_area_accept_drop(_Event("/tmp/x.usda"))
                is True
            )
        finally:
            win.destroy()
