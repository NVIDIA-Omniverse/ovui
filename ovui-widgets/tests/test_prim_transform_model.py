# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for PrimTransformModel and _apply_delta."""

import math
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from ovui_widgets.common.snap import GridSnapProvider, SnapSystem
from ovui_widgets.common.testing.mock_transform import MockTransformAdapter
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.viewport.prim_transform_model import (
    PrimTransformModel,
    _apply_delta,
    _apply_scale,
)

_IDENTITY = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]

_TRANSLATION = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [1.0, 2.0, 3.0, 1.0],
]


def _make_mock_stage():
    stage = MagicMock()
    stage.suppress_change_notifications.side_effect = lambda: _cm()
    return stage


@contextmanager
def _cm():
    yield


@pytest.fixture
def transform():
    adapter = MockTransformAdapter(blocked={"/Locked"})
    mat = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [5.0, 0.0, 0.0, 1.0],
    ]
    adapter.set_local_transform("/World/A", mat)
    adapter.set_local_transform("/World/B", [row[:] for row in _IDENTITY])
    return adapter


@pytest.fixture
def model(transform):
    stage = _make_mock_stage()
    undo = UndoManager()
    return PrimTransformModel(transform, stage, undo)


class _RendererSpy:
    def __init__(self, *, raise_on_set: bool = False):
        self.calls = []
        self.raise_on_set = raise_on_set

    @property
    def supports_live_local_transform(self):
        self.calls.append("supports_live_local_transform")
        return True

    def set_live_local_transform(self, path, matrix):
        self.calls.append(("set_live_local_transform", path, matrix))
        if self.raise_on_set:
            raise RuntimeError("preview failed")
        return True

    def clear_live_local_transforms(self, paths):
        self.calls.append(("clear_live_local_transforms", tuple(paths or ())))


class _NoPreviewRenderer:
    pass


class _ParentedTransformAdapter(MockTransformAdapter):
    def __init__(self, parent_world):
        super().__init__()
        self._parent_world = parent_world

    def get_world_transform(self, path):
        return _apply_delta(
            self.get_local_transform(path),
            self._parent_world,
            "world",
        )


def _translate_delta():
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [10.0, 0.0, 0.0, 1.0],
    ]


def _translate_delta_xyz(x, y, z):
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [x, y, z, 1.0],
    ]


def _enabled_grid_snap(grid_size=1.0):
    snap = SnapSystem()
    snap.enable(True)
    snap.add_provider(GridSnapProvider(grid_size))
    return snap


def _assert_translate_final(matrix):
    assert matrix[3][0] == pytest.approx(15.0)
    assert matrix[3][1] == pytest.approx(0.0)
    assert matrix[3][2] == pytest.approx(0.0)


def _assert_rotate_final(matrix):
    assert matrix[0][0] == pytest.approx(0.0, abs=1e-9)
    assert matrix[0][1] == pytest.approx(1.0, abs=1e-9)
    assert matrix[1][0] == pytest.approx(-1.0, abs=1e-9)
    assert matrix[1][1] == pytest.approx(0.0, abs=1e-9)
    assert matrix[3][0] == pytest.approx(5.0)


def _assert_scale_final(matrix):
    assert matrix[0][0] == pytest.approx(2.0)
    assert matrix[1][1] == pytest.approx(1.0)
    assert matrix[2][2] == pytest.approx(1.0)
    assert matrix[3][0] == pytest.approx(5.0)


class TestRendererReference:
    def test_constructor_stores_renderer_without_preview_calls(self, transform):
        renderer = _RendererSpy()
        model = PrimTransformModel(
            transform,
            _make_mock_stage(),
            UndoManager(),
            renderer=renderer,
        )

        assert model.renderer_adapter is renderer
        assert renderer.calls == []

    def test_attach_adapters_replaces_and_clears_renderer(self, transform):
        first = _RendererSpy()
        second = _RendererSpy()
        model = PrimTransformModel(
            transform,
            _make_mock_stage(),
            UndoManager(),
            renderer=first,
        )

        model.attach_adapters(
            transform_adapter=transform,
            stage_adapter=_make_mock_stage(),
            undo=UndoManager(),
            renderer=second,
        )
        assert model.renderer_adapter is second

        model.attach_adapters(
            transform_adapter=transform,
            stage_adapter=_make_mock_stage(),
            undo=UndoManager(),
            renderer=None,
        )
        assert model.renderer_adapter is None
        assert first.calls == []
        assert second.calls == []

    def test_set_renderer_replaces_reference_without_preview_calls(self):
        first = _RendererSpy()
        second = _RendererSpy()
        model = PrimTransformModel(renderer=first)

        model.set_renderer(second)

        assert model.renderer_adapter is second
        assert first.calls == []
        assert second.calls == []


class TestNoRendererPreviewFallback:
    @pytest.mark.parametrize(
        "renderer_factory",
        [
            pytest.param(lambda: None, id="renderer-none"),
            pytest.param(_NoPreviewRenderer, id="renderer-without-preview-methods"),
        ],
    )
    @pytest.mark.parametrize("tool", ["translate", "rotate", "scale"])
    def test_drag_records_without_renderer_and_commits_on_release(
        self,
        renderer_factory,
        tool,
        transform,
    ):
        model = PrimTransformModel(
            transform,
            _make_mock_stage(),
            UndoManager(),
            renderer=renderer_factory(),
        )
        initial = transform.get_local_transform("/World/A")
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])
        model.on_drag_start()

        if tool == "translate":
            model.on_drag_moved(_translate_delta())
            assert_final = _assert_translate_final
        elif tool == "rotate":
            model.on_drag_rotated((0.0, 0.0, 1.0), math.pi / 2)
            assert_final = _assert_rotate_final
        else:
            model.on_drag_scaled((1.0, 0.0, 0.0), 2.0)
            assert_final = _assert_scale_final

        assert transform.get_local_transform("/World/A") == initial
        transform.set_local_transform.assert_not_called()
        model._stage.suppress_change_notifications.assert_not_called()
        model._stage.notify_transform_changed.assert_not_called()
        assert_final(model._live_transforms["/World/A"])

        model.on_drag_ended()

        transform.set_local_transform.assert_called_once()
        assert_final(transform.get_local_transform("/World/A"))
        model._stage.notify_transform_changed.assert_called_once_with(
            ["/World/A"],
            source="viewport-manipulator",
        )
        assert model._live_transforms == {}

    def test_clear_preview_is_safe_when_renderer_missing_or_unsupported(self):
        model = PrimTransformModel(renderer=None)
        model._clear_live_local_transforms(["/World/A"])
        model.set_renderer(_NoPreviewRenderer())
        model._clear_live_local_transforms(["/World/A"])


class TestSetSelection:
    def test_filters_untransformable(self, model):
        model.set_selection(["/World/A", "/Locked"])
        assert model._selected_paths == ["/World/A"]

    def test_keeps_transformable(self, model):
        model.set_selection(["/World/A", "/World/B"])
        assert set(model._selected_paths) == {"/World/A", "/World/B"}

    def test_empty_selection(self, model):
        model.set_selection([])
        assert model._selected_paths == []

    def test_transform_space_exposes_current_mode(self, model):
        assert model.transform_space == "world"

    def test_all_locked(self, model):
        model.set_selection(["/Locked"])
        assert model._selected_paths == []


class TestLivePivotWorld:
    def test_non_drag_selection_uses_usd_world_pivot(self, transform):
        model = PrimTransformModel(transform, _make_mock_stage(), UndoManager())
        transform.get_world_transform = MagicMock(wraps=transform.get_world_transform)
        model.set_selection(["/World/A"])

        assert model.get_pivot_world() == pytest.approx((5.0, 0.0, 0.0))
        transform.get_world_transform.assert_called_once_with("/World/A")

    def test_translate_drag_pivot_follows_live_preview_without_scene_work(
        self,
        transform,
    ):
        stage = _make_mock_stage()
        renderer = _RendererSpy()
        model = PrimTransformModel(transform, stage, UndoManager(), renderer=renderer)
        transform.get_world_transform = MagicMock(wraps=transform.get_world_transform)
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])

        model.on_drag_start()
        transform.get_world_transform.assert_called_once_with("/World/A")
        transform.get_world_transform.reset_mock()
        model.on_drag_moved(_translate_delta())

        assert model.get_pivot_world() == pytest.approx((15.0, 0.0, 0.0))
        transform.get_world_transform.assert_not_called()
        transform.set_local_transform.assert_not_called()
        stage.notify_transform_changed.assert_not_called()
        stage.suppress_change_notifications.assert_not_called()

    def test_translate_drag_pivot_uses_cached_parent_world_transform(self):
        parent_world = _translate_delta_xyz(0.0, 20.0, 0.0)
        transform = _ParentedTransformAdapter(parent_world)
        transform.set_local_transform("/World/A", [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [5.0, 0.0, 0.0, 1.0],
        ])
        stage = _make_mock_stage()
        model = PrimTransformModel(
            transform,
            stage,
            UndoManager(),
            renderer=_RendererSpy(),
        )
        transform.get_world_transform = MagicMock(wraps=transform.get_world_transform)
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])

        model.on_drag_start()
        transform.get_world_transform.assert_called_once_with("/World/A")
        transform.get_world_transform.reset_mock()
        model.on_drag_moved(_translate_delta())

        assert model.get_pivot_world() == pytest.approx((15.0, 20.0, 0.0))
        transform.get_world_transform.assert_not_called()
        transform.set_local_transform.assert_not_called()
        stage.notify_transform_changed.assert_not_called()

    @pytest.mark.parametrize("tool", ["rotate", "scale"])
    def test_rotate_and_scale_drag_pivot_stays_at_selection_origin_without_scene_work(
        self,
        tool,
        transform,
    ):
        stage = _make_mock_stage()
        model = PrimTransformModel(
            transform,
            stage,
            UndoManager(),
            renderer=_RendererSpy(),
        )
        transform.get_world_transform = MagicMock(wraps=transform.get_world_transform)
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])

        model.on_drag_start()
        transform.get_world_transform.reset_mock()
        if tool == "rotate":
            model.on_drag_rotated((0.0, 0.0, 1.0), math.pi / 2)
        else:
            model.on_drag_scaled((1.0, 0.0, 0.0), 2.0)

        assert model.get_pivot_world() == pytest.approx((5.0, 0.0, 0.0))
        transform.get_world_transform.assert_not_called()
        transform.set_local_transform.assert_not_called()
        stage.notify_transform_changed.assert_not_called()
        stage.suppress_change_notifications.assert_not_called()

    def test_release_pivot_matches_committed_world_position(self, transform):
        stage = _make_mock_stage()
        model = PrimTransformModel(
            transform,
            stage,
            UndoManager(),
            renderer=_RendererSpy(),
        )
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        model.on_drag_ended()

        transform.set_local_transform.assert_called_once()
        assert model.get_pivot_world() == pytest.approx((15.0, 0.0, 0.0))

    def test_cancel_pivot_returns_to_original_world_position(self, transform):
        stage = _make_mock_stage()
        model = PrimTransformModel(
            transform,
            stage,
            UndoManager(),
            renderer=_RendererSpy(),
        )
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])
        assert model.get_pivot_world() == pytest.approx((5.0, 0.0, 0.0))

        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        assert model.get_pivot_world() == pytest.approx((15.0, 0.0, 0.0))

        model.on_drag_cancelled()

        transform.set_local_transform.assert_not_called()
        stage.notify_transform_changed.assert_not_called()
        assert model.get_pivot_world() == pytest.approx((5.0, 0.0, 0.0))


class TestOnDragStart:
    def test_captures_initial_transforms(self, model, transform):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        assert "/World/A" in model._initial_transforms
        assert model._initial_transforms["/World/A"][3][0] == pytest.approx(5.0)

    def test_calls_begin_undo_group(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model._stage.begin_undo_group.assert_called_once_with("Move Prims")

    def test_captures_all_selected(self, model):
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()
        assert "/World/A" in model._initial_transforms
        assert "/World/B" in model._initial_transforms


class TestOnDragMoved:
    def test_previews_delta_from_initial_without_scene_write(self, model, transform):
        renderer = _RendererSpy()
        model.set_renderer(renderer)
        initial = transform.get_local_transform("/World/A")
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        delta = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [10.0, 0.0, 0.0, 1.0],
        ]
        model.on_drag_moved(delta)

        result = transform.get_local_transform("/World/A")
        assert result == initial
        transform.set_local_transform.assert_not_called()
        preview = renderer.calls[-1]
        assert preview[0] == "set_live_local_transform"
        assert preview[1] == "/World/A"
        assert preview[2][3][0] == pytest.approx(15.0)
        assert model._live_transforms["/World/A"][3][0] == pytest.approx(15.0)

    def test_does_not_suppress_notifications_during_move(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved([row[:] for row in _IDENTITY])
        model._stage.suppress_change_notifications.assert_not_called()

    def test_does_not_notify_live_transform_before_drag_end(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        delta = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [10.0, 0.0, 0.0, 1.0],
        ]
        model.on_drag_moved(delta)
        model._stage.notify_transform_changed.assert_not_called()

    def test_repeated_move_uses_initial(self, model, transform):
        renderer = _RendererSpy()
        model.set_renderer(renderer)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        delta1 = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [1.0, 0.0, 0.0, 1.0],
        ]
        delta2 = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [2.0, 0.0, 0.0, 1.0],
        ]
        model.on_drag_moved(delta1)
        model.on_drag_moved(delta2)

        result = transform.get_local_transform("/World/A")
        assert result[3][0] == pytest.approx(5.0)
        assert model._live_transforms["/World/A"][3][0] == pytest.approx(7.0)
        assert renderer.calls[-1][2][3][0] == pytest.approx(7.0)


class TestOnDragEnded:
    def test_clears_initial_transforms(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        assert model._initial_transforms
        model.on_drag_ended()
        assert model._initial_transforms == {}
        assert model._live_transforms == {}

    def test_calls_end_undo_group(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_ended()
        model._stage.end_undo_group.assert_called_once()

    def test_notifies_final_transform_after_drag_end(self, model):
        renderer = _RendererSpy()
        model.set_renderer(renderer)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        delta = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [10.0, 0.0, 0.0, 1.0],
        ]
        model.on_drag_moved(delta)
        model._stage.notify_transform_changed.reset_mock()

        model.on_drag_ended()

        model._stage.notify_transform_changed.assert_called_once_with(
            ["/World/A"],
            source="viewport-manipulator",
        )

    def test_release_authors_final_once_and_clears_preview(self, model, transform):
        renderer = _RendererSpy()
        model.set_renderer(renderer)
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        delta = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [10.0, 0.0, 0.0, 1.0],
        ]
        model.on_drag_moved(delta)
        transform.set_local_transform.assert_not_called()
        model._stage.suppress_change_notifications.assert_not_called()
        model._stage.notify_transform_changed.assert_not_called()

        model.on_drag_ended()

        transform.set_local_transform.assert_called_once()
        result = transform.get_local_transform("/World/A")
        assert result[3][0] == pytest.approx(15.0)
        model._stage.suppress_change_notifications.assert_called_once()
        model._stage.notify_transform_changed.assert_called_once_with(
            ["/World/A"],
            source="viewport-manipulator",
        )
        assert renderer.calls[-1] == (
            "clear_live_local_transforms",
            ("/World/A",),
        )

    def test_preview_exception_still_records_and_commits_final(self, model, transform):
        renderer = _RendererSpy(raise_on_set=True)
        model.set_renderer(renderer)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        delta = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [10.0, 0.0, 0.0, 1.0],
        ]

        model.on_drag_moved(delta)
        assert model._live_transforms["/World/A"][3][0] == pytest.approx(15.0)
        assert transform.get_local_transform("/World/A")[3][0] == pytest.approx(5.0)

        model.on_drag_ended()

        assert transform.get_local_transform("/World/A")[3][0] == pytest.approx(15.0)
        model._stage.notify_transform_changed.assert_called_once_with(
            ["/World/A"],
            source="viewport-manipulator",
        )

    def test_skips_final_notify_when_drag_does_not_change_transform(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_ended()
        model._stage.notify_transform_changed.assert_not_called()


class TestReleaseCommitsFinalTransformOnce:
    def test_multi_prim_release_notifies_once_with_all_changed_paths(
        self,
        transform,
    ):
        model = PrimTransformModel(
            transform,
            _make_mock_stage(),
            UndoManager(),
            renderer=_RendererSpy(),
        )
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        transform.set_local_transform.assert_not_called()

        model.on_drag_ended()

        assert transform.set_local_transform.call_count == 2
        assert transform.get_local_transform("/World/A")[3][0] == pytest.approx(15.0)
        assert transform.get_local_transform("/World/B")[3][0] == pytest.approx(10.0)
        model._stage.notify_transform_changed.assert_called_once()
        paths_arg = model._stage.notify_transform_changed.call_args.args[0]
        assert set(paths_arg) == {"/World/A", "/World/B"}
        assert (
            model._stage.notify_transform_changed.call_args.kwargs["source"]
            == "viewport-manipulator"
        )

    def test_multi_prim_release_is_one_undoable_group(self, transform):
        stage = _make_mock_stage()
        undo = UndoManager()
        undo.begin_group = MagicMock(wraps=undo.begin_group)
        undo.end_group = MagicMock(wraps=undo.end_group)
        model = PrimTransformModel(transform, stage, undo, renderer=_RendererSpy())
        initial_a = transform.get_local_transform("/World/A")
        initial_b = transform.get_local_transform("/World/B")
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        model.on_drag_ended()

        undo.begin_group.assert_called_once_with("Move Prims")
        undo.end_group.assert_called_once()
        assert len(undo._undo_stack) == 1
        assert transform.get_local_transform("/World/A")[3][0] == pytest.approx(15.0)
        assert transform.get_local_transform("/World/B")[3][0] == pytest.approx(10.0)

        assert undo.undo() is True
        assert transform.get_local_transform("/World/A") == initial_a
        assert transform.get_local_transform("/World/B") == initial_b

    def test_release_notify_lists_only_changed_paths(self, transform):
        model = PrimTransformModel(
            transform,
            _make_mock_stage(),
            UndoManager(),
            renderer=_RendererSpy(),
        )
        initial_b = transform.get_local_transform("/World/B")
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        model._live_transforms["/World/B"] = [row[:] for row in initial_b]

        model.on_drag_ended()

        assert transform.set_local_transform.call_count == 2
        assert transform.get_local_transform("/World/A")[3][0] == pytest.approx(15.0)
        assert transform.get_local_transform("/World/B") == initial_b
        model._stage.notify_transform_changed.assert_called_once_with(
            ["/World/A"],
            source="viewport-manipulator",
        )

    def test_empty_release_does_not_notify_or_commit(self, transform):
        model = PrimTransformModel(transform, _make_mock_stage(), UndoManager())
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)

        model.on_drag_ended()

        transform.set_local_transform.assert_not_called()
        model._stage.notify_transform_changed.assert_not_called()
        assert model._undo._undo_stack == []


class TestCommitAndCancelReleasePreview:
    def test_commit_releases_exact_preview_paths_and_clears_live_state(
        self,
        transform,
    ):
        renderer = _RendererSpy()
        model = PrimTransformModel(
            transform,
            _make_mock_stage(),
            UndoManager(),
            renderer=renderer,
        )
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        model.on_drag_ended()

        assert renderer.calls[-1] == (
            "clear_live_local_transforms",
            ("/World/A", "/World/B"),
        )
        assert model._live_transforms == {}

    def test_cancel_releases_preview_without_committing(self, transform):
        renderer = _RendererSpy()
        undo = UndoManager()
        stage = _make_mock_stage()
        model = PrimTransformModel(transform, stage, undo, renderer=renderer)
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        model.on_drag_cancelled()

        assert renderer.calls[-1] == (
            "clear_live_local_transforms",
            ("/World/A",),
        )
        assert model._live_transforms == {}
        assert model._initial_transforms == {}
        transform.set_local_transform.assert_not_called()
        stage.suppress_change_notifications.assert_not_called()
        stage.notify_transform_changed.assert_not_called()
        assert undo._undo_stack == []
        assert undo._group_stack == []

    def test_cancel_balances_stage_undo_group(self, transform):
        stage = _make_mock_stage()
        model = PrimTransformModel(
            transform,
            stage,
            UndoManager(),
            renderer=_RendererSpy(),
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        model.on_drag_cancelled()

        stage.begin_undo_group.assert_called_once_with("Move Prims")
        stage.end_undo_group.assert_called_once()

    def test_cancel_no_active_drag_is_safe(self, transform):
        renderer = _RendererSpy()
        stage = _make_mock_stage()
        model = PrimTransformModel(
            transform,
            stage,
            UndoManager(),
            renderer=renderer,
        )

        model.on_drag_cancelled()

        assert renderer.calls == []
        stage.end_undo_group.assert_not_called()
        stage.notify_transform_changed.assert_not_called()
        assert model._live_transforms == {}
        assert model._initial_transforms == {}

    def test_cancel_empty_selection_balances_without_preview_clear(self, transform):
        renderer = _RendererSpy()
        stage = _make_mock_stage()
        model = PrimTransformModel(
            transform,
            stage,
            UndoManager(),
            renderer=renderer,
        )
        model.set_selection([])
        model.on_drag_start()

        model.on_drag_cancelled()

        assert renderer.calls == []
        stage.begin_undo_group.assert_called_once_with("Move Prims")
        stage.end_undo_group.assert_called_once()
        stage.notify_transform_changed.assert_not_called()
        assert model._live_transforms == {}
        assert model._initial_transforms == {}

    def test_multi_prim_cancel_releases_all_preview_paths(self, transform):
        renderer = _RendererSpy()
        undo = UndoManager()
        stage = _make_mock_stage()
        model = PrimTransformModel(transform, stage, undo, renderer=renderer)
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        model.on_drag_cancelled()

        assert renderer.calls[-1] == (
            "clear_live_local_transforms",
            ("/World/A", "/World/B"),
        )
        transform.set_local_transform.assert_not_called()
        stage.notify_transform_changed.assert_not_called()
        assert undo._undo_stack == []
        assert model._live_transforms == {}


class TestUndoRedoSingleEntry:
    def test_single_prim_drag_round_trips_as_one_undo_redo_entry(
        self,
        transform,
    ):
        undo = UndoManager()
        model = PrimTransformModel(
            transform,
            _make_mock_stage(),
            undo,
            renderer=_RendererSpy(),
        )
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        initial = transform.get_local_transform("/World/A")
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        model.on_drag_ended()

        assert len(undo._undo_stack) == 1
        assert undo.can_undo() is True
        assert undo.can_redo() is False
        assert transform.get_local_transform("/World/A")[3][0] == pytest.approx(15.0)

        assert undo.undo() is True
        assert transform.get_local_transform("/World/A") == initial
        assert len(undo._undo_stack) == 0
        assert undo.can_undo() is False
        assert undo.can_redo() is True

        assert undo.redo() is True
        assert transform.get_local_transform("/World/A")[3][0] == pytest.approx(15.0)
        assert len(undo._undo_stack) == 1
        assert undo.can_undo() is True
        assert undo.can_redo() is False

        assert undo.undo() is True
        assert transform.get_local_transform("/World/A") == initial

    def test_multi_prim_drag_redo_reapplies_both_finals_from_one_entry(
        self,
        transform,
    ):
        undo = UndoManager()
        model = PrimTransformModel(
            transform,
            _make_mock_stage(),
            undo,
            renderer=_RendererSpy(),
        )
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        initial_a = transform.get_local_transform("/World/A")
        initial_b = transform.get_local_transform("/World/B")
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        model.on_drag_ended()

        assert len(undo._undo_stack) == 1
        assert transform.get_local_transform("/World/A")[3][0] == pytest.approx(15.0)
        assert transform.get_local_transform("/World/B")[3][0] == pytest.approx(10.0)

        assert undo.undo() is True
        assert transform.get_local_transform("/World/A") == initial_a
        assert transform.get_local_transform("/World/B") == initial_b
        assert len(undo._undo_stack) == 0
        assert len(undo._redo_stack) == 1

        assert undo.redo() is True
        assert transform.get_local_transform("/World/A")[3][0] == pytest.approx(15.0)
        assert transform.get_local_transform("/World/B")[3][0] == pytest.approx(10.0)
        assert len(undo._undo_stack) == 1
        assert undo.can_undo() is True
        assert undo.can_redo() is False

    def test_new_drag_clears_redo_stack(self, transform):
        undo = UndoManager()
        model = PrimTransformModel(
            transform,
            _make_mock_stage(),
            undo,
            renderer=_RendererSpy(),
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        model.on_drag_ended()
        assert undo.undo() is True
        assert undo.can_redo() is True

        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        model.on_drag_ended()

        assert undo.can_redo() is False
        assert undo._redo_stack == []
        assert len(undo._undo_stack) == 1
        assert transform.get_local_transform("/World/A")[3][0] == pytest.approx(15.0)

    def test_empty_selection_drag_pushes_no_undo_entry(self, transform):
        undo = UndoManager()
        model = PrimTransformModel(
            transform,
            _make_mock_stage(),
            undo,
            renderer=_RendererSpy(),
        )
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection([])
        model.on_drag_start()

        model.on_drag_ended()

        assert undo._undo_stack == []
        assert undo.can_undo() is False
        assert undo.can_redo() is False
        transform.set_local_transform.assert_not_called()
        model._stage.notify_transform_changed.assert_not_called()


class TestCancelLeavesSceneUntouched:
    def test_single_prim_cancel_leaves_scene_unchanged_and_restores_preview(
        self,
        transform,
    ):
        renderer = _RendererSpy()
        undo = UndoManager()
        stage = _make_mock_stage()
        model = PrimTransformModel(transform, stage, undo, renderer=renderer)
        initial = transform.get_local_transform("/World/A")
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])
        model.on_drag_start()

        model.on_drag_moved(_translate_delta())
        assert renderer.calls[-1][0] == "set_live_local_transform"
        assert renderer.calls[-1][1] == "/World/A"
        assert model._live_transforms["/World/A"][3][0] == pytest.approx(15.0)
        assert transform.get_local_transform("/World/A") == initial

        model.on_drag_cancelled()

        assert transform.get_local_transform("/World/A") == initial
        transform.set_local_transform.assert_not_called()
        stage.notify_transform_changed.assert_not_called()
        assert undo._undo_stack == []
        assert renderer.calls[-1] == (
            "clear_live_local_transforms",
            ("/World/A",),
        )

    def test_multi_prim_cancel_leaves_all_scene_transforms_unchanged(
        self,
        transform,
    ):
        renderer = _RendererSpy()
        undo = UndoManager()
        stage = _make_mock_stage()
        model = PrimTransformModel(transform, stage, undo, renderer=renderer)
        initial_a = transform.get_local_transform("/World/A")
        initial_b = transform.get_local_transform("/World/B")
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()

        model.on_drag_moved(_translate_delta())
        assert model._live_transforms["/World/A"][3][0] == pytest.approx(15.0)
        assert model._live_transforms["/World/B"][3][0] == pytest.approx(10.0)

        model.on_drag_cancelled()

        assert transform.get_local_transform("/World/A") == initial_a
        assert transform.get_local_transform("/World/B") == initial_b
        transform.set_local_transform.assert_not_called()
        stage.notify_transform_changed.assert_not_called()
        assert undo._undo_stack == []
        assert renderer.calls[-1] == (
            "clear_live_local_transforms",
            ("/World/A", "/World/B"),
        )

    def test_cancel_after_multiple_moves_still_leaves_scene_at_initial(
        self,
        transform,
    ):
        renderer = _RendererSpy()
        undo = UndoManager()
        stage = _make_mock_stage()
        model = PrimTransformModel(transform, stage, undo, renderer=renderer)
        initial = transform.get_local_transform("/World/A")
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        second_delta = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [20.0, 0.0, 0.0, 1.0],
        ]

        model.on_drag_moved(_translate_delta())
        model.on_drag_moved(second_delta)
        assert model._live_transforms["/World/A"][3][0] == pytest.approx(25.0)

        model.on_drag_cancelled()

        assert transform.get_local_transform("/World/A") == initial
        transform.set_local_transform.assert_not_called()
        stage.notify_transform_changed.assert_not_called()
        assert undo._undo_stack == []
        assert renderer.calls[-1] == (
            "clear_live_local_transforms",
            ("/World/A",),
        )


class TestSnapPreviewCommitParity:
    def test_renderer_receives_snapped_preview_and_commit_matches_it(
        self,
        transform,
    ):
        renderer = _RendererSpy()
        model = PrimTransformModel(
            transform,
            _make_mock_stage(),
            UndoManager(),
            snap_system=_enabled_grid_snap(),
            renderer=renderer,
        )
        initial = transform.get_local_transform("/World/B")
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/B"])
        model.on_drag_start()

        model.on_drag_moved(_translate_delta_xyz(0.7, 0.3, 0.9))

        preview_call = renderer.calls[-1]
        assert preview_call[0] == "set_live_local_transform"
        assert preview_call[1] == "/World/B"
        renderer_preview = [row[:] for row in preview_call[2]]
        live_preview = [row[:] for row in model._live_transforms["/World/B"]]
        assert renderer_preview == live_preview
        assert renderer_preview[3][0] == pytest.approx(1.0)
        assert renderer_preview[3][1] == pytest.approx(0.0)
        assert renderer_preview[3][2] == pytest.approx(1.0)
        assert renderer_preview[3][0] != pytest.approx(0.7)
        assert renderer_preview[3][1] != pytest.approx(0.3)
        assert renderer_preview[3][2] != pytest.approx(0.9)
        assert transform.get_local_transform("/World/B") == initial
        transform.set_local_transform.assert_not_called()

        model.on_drag_ended()

        assert transform.get_local_transform("/World/B") == live_preview

    def test_multi_prim_commit_matches_each_snapped_preview(self, transform):
        renderer = _RendererSpy()
        model = PrimTransformModel(
            transform,
            _make_mock_stage(),
            UndoManager(),
            snap_system=_enabled_grid_snap(),
            renderer=renderer,
        )
        initial_a = transform.get_local_transform("/World/A")
        initial_b = transform.get_local_transform("/World/B")
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()

        model.on_drag_moved(_translate_delta_xyz(0.7, 0.3, 0.9))

        set_calls = {
            call[1]: [row[:] for row in call[2]]
            for call in renderer.calls
            if isinstance(call, tuple) and call[0] == "set_live_local_transform"
        }
        live_a = [row[:] for row in model._live_transforms["/World/A"]]
        live_b = [row[:] for row in model._live_transforms["/World/B"]]
        assert set_calls["/World/A"] == live_a
        assert set_calls["/World/B"] == live_b
        assert live_a[3][0] == pytest.approx(6.0)
        assert live_a[3][1] == pytest.approx(0.0)
        assert live_a[3][2] == pytest.approx(1.0)
        assert live_b[3][0] == pytest.approx(1.0)
        assert live_b[3][1] == pytest.approx(0.0)
        assert live_b[3][2] == pytest.approx(1.0)
        assert transform.get_local_transform("/World/A") == initial_a
        assert transform.get_local_transform("/World/B") == initial_b
        transform.set_local_transform.assert_not_called()

        model.on_drag_ended()

        assert transform.get_local_transform("/World/A") == live_a
        assert transform.get_local_transform("/World/B") == live_b


class TestPreviewToCommitEndState:
    def test_release_authors_all_paths_before_clearing_renderer_preview(
        self,
        transform,
    ):
        renderer = _RendererSpy()
        model = PrimTransformModel(
            transform,
            _make_mock_stage(),
            UndoManager(),
            renderer=renderer,
        )
        events = []
        original_set_local_transform = transform.set_local_transform
        original_clear_live = renderer.clear_live_local_transforms

        def _record_author(path, matrix):
            events.append(("author", path, [row[:] for row in matrix]))
            original_set_local_transform(path, matrix)

        def _record_clear(paths):
            events.append(("clear", tuple(paths or ())))
            original_clear_live(paths)

        transform.set_local_transform = MagicMock(side_effect=_record_author)
        renderer.clear_live_local_transforms = MagicMock(side_effect=_record_clear)
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        model.on_drag_ended()

        clear_indices = [
            index for index, event in enumerate(events) if event[0] == "clear"
        ]
        assert clear_indices == [2]
        clear_index = clear_indices[0]
        author_events = [event for event in events if event[0] == "author"]
        assert [event[1] for event in author_events] == ["/World/A", "/World/B"]
        assert all(
            index < clear_index
            for index, event in enumerate(events)
            if event[0] == "author"
        )
        assert events[clear_index] == (
            "clear",
            ("/World/A", "/World/B"),
        )
        assert renderer.calls[-1] == (
            "clear_live_local_transforms",
            ("/World/A", "/World/B"),
        )

    def test_snapped_release_end_state_has_no_residual_preview_or_snap_back(
        self,
        transform,
    ):
        renderer = _RendererSpy()
        model = PrimTransformModel(
            transform,
            _make_mock_stage(),
            UndoManager(),
            snap_system=_enabled_grid_snap(),
            renderer=renderer,
        )
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta_xyz(0.7, 0.3, 0.9))
        preview_a = [row[:] for row in model._live_transforms["/World/A"]]
        preview_b = [row[:] for row in model._live_transforms["/World/B"]]

        model.on_drag_ended()

        assert transform.get_local_transform("/World/A") == preview_a
        assert transform.get_local_transform("/World/B") == preview_b
        assert preview_a[3][0] == pytest.approx(6.0)
        assert preview_b[3][0] == pytest.approx(1.0)
        assert transform.set_local_transform.call_count == 2
        assert renderer.calls[-1] == (
            "clear_live_local_transforms",
            ("/World/A", "/World/B"),
        )
        assert model._initial_transforms == {}
        assert model._live_transforms == {}
        assert model._drag_active is False

    def test_failed_multi_prim_commit_compensates_and_clears_preview(
        self,
        transform,
    ):
        renderer = _RendererSpy()
        undo = UndoManager()
        stage = _make_mock_stage()
        model = PrimTransformModel(
            transform,
            stage,
            undo,
            renderer=renderer,
        )
        initial_a = transform.get_local_transform("/World/A")
        initial_b = transform.get_local_transform("/World/B")
        original_set = transform.set_local_transform

        def fail_second_path(path, matrix):
            if path == "/World/B":
                raise RuntimeError("injected durable transform failure")
            original_set(path, matrix)

        transform.set_local_transform = MagicMock(side_effect=fail_second_path)
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        with pytest.raises(RuntimeError, match="injected durable transform failure"):
            model.on_drag_ended()

        assert transform.get_local_transform("/World/A") == initial_a
        assert transform.get_local_transform("/World/B") == initial_b
        assert undo.can_undo() is False
        assert undo._group_stack == []
        stage.end_undo_group.assert_called_once_with()
        assert renderer.calls[-1] == (
            "clear_live_local_transforms",
            ("/World/A", "/World/B"),
        )
        assert model._initial_transforms == {}
        assert model._live_transforms == {}
        assert model._drag_active is False


class TestOnDragStartLabel:
    def test_default_label_is_move(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model._stage.begin_undo_group.assert_called_once_with("Move Prims")

    def test_custom_label_forwarded(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start(label="Rotate Prims")
        model._stage.begin_undo_group.assert_called_once_with("Rotate Prims")

    def test_label_is_persisted_for_ended(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start(label="Rotate Prims")
        model.on_drag_ended()
        # The UndoGroup label should match what was begun.
        undo_group = model._undo._undo_stack[-1]
        assert undo_group.label == "Rotate Prims"


class TestOnDragRotated:
    def test_previews_rotation_without_scene_write(self, model, transform):
        renderer = _RendererSpy()
        model.set_renderer(renderer)
        initial = transform.get_local_transform("/World/A")
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_rotated((0.0, 0.0, 1.0), math.pi / 2)

        assert transform.get_local_transform("/World/A") == initial
        transform.set_local_transform.assert_not_called()
        model._stage.suppress_change_notifications.assert_not_called()
        model._stage.notify_transform_changed.assert_not_called()
        mat = model._live_transforms["/World/A"]
        # 90° around Z with identity upper-3×3: +X row becomes (0, 1, 0).
        assert mat[0][0] == pytest.approx(0.0, abs=1e-9)
        assert mat[0][1] == pytest.approx(1.0, abs=1e-9)
        assert mat[1][0] == pytest.approx(-1.0, abs=1e-9)
        assert mat[1][1] == pytest.approx(0.0, abs=1e-9)
        # Translation row stays put — rotation "in place".
        assert mat[3][0] == pytest.approx(5.0)
        assert mat[3][1] == pytest.approx(0.0)
        assert mat[3][2] == pytest.approx(0.0)
        assert renderer.calls[-1][0] == "set_live_local_transform"
        assert renderer.calls[-1][1] == "/World/A"
        assert renderer.calls[-1][2][0][1] == pytest.approx(1.0, abs=1e-9)

    def test_does_not_suppress_notifications_during_rotation(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_rotated((0.0, 0.0, 1.0), 0.5)
        model._stage.suppress_change_notifications.assert_not_called()

    def test_does_not_notify_live_transform_before_rotation_drag_end(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_rotated((0.0, 0.0, 1.0), 0.5)
        model._stage.notify_transform_changed.assert_not_called()

    def test_rotation_rebases_on_initial_not_current(self, model, transform):
        # Repeated calls to ``on_drag_rotated`` during one drag always rotate
        # the *initial* transform, not the previous frame's output — otherwise
        # a multi-frame drag would compound rotations and overshoot.
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_rotated((0.0, 0.0, 1.0), math.pi / 2)
        model.on_drag_rotated((0.0, 0.0, 1.0), math.pi / 2)
        assert transform.get_local_transform("/World/A")[0][0] == pytest.approx(1.0)
        mat = model._live_transforms["/World/A"]
        # Two calls with π/2 should match a single call with π/2 — not π.
        assert mat[0][0] == pytest.approx(0.0, abs=1e-9)
        assert mat[0][1] == pytest.approx(1.0, abs=1e-9)

    def test_zero_angle_is_noop(self, model, transform):
        model.set_selection(["/World/A"])
        initial = transform.get_local_transform("/World/A")
        model.on_drag_start()
        model.on_drag_rotated((0.0, 0.0, 1.0), 0.0)
        after = model._live_transforms["/World/A"]
        assert transform.get_local_transform("/World/A") == initial
        for i in range(4):
            for j in range(4):
                assert after[i][j] == pytest.approx(initial[i][j], abs=1e-12)

    def test_multi_prim_rotation(self, model, transform):
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()
        model.on_drag_rotated((0.0, 0.0, 1.0), math.pi / 2)
        a = model._live_transforms["/World/A"]
        b = model._live_transforms["/World/B"]
        assert transform.get_local_transform("/World/A")[0][0] == pytest.approx(1.0)
        assert transform.get_local_transform("/World/B")[0][0] == pytest.approx(1.0)
        # Each prim rotated in place around its own origin. Translations
        # stay put (A at x=5, B at origin); upper-3×3 is the same rotation.
        assert a[3][0] == pytest.approx(5.0)
        assert b[3][0] == pytest.approx(0.0)
        for mat in (a, b):
            assert mat[0][1] == pytest.approx(1.0, abs=1e-9)
            assert mat[1][0] == pytest.approx(-1.0, abs=1e-9)

    def test_release_authors_rotation_once_and_clears_preview(self, model, transform):
        renderer = _RendererSpy()
        model.set_renderer(renderer)
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_rotated((0.0, 0.0, 1.0), math.pi / 2)
        transform.set_local_transform.assert_not_called()

        model.on_drag_ended()

        transform.set_local_transform.assert_called_once()
        mat = transform.get_local_transform("/World/A")
        assert mat[0][1] == pytest.approx(1.0, abs=1e-9)
        assert mat[1][0] == pytest.approx(-1.0, abs=1e-9)
        model._stage.notify_transform_changed.assert_called_once_with(
            ["/World/A"],
            source="viewport-manipulator",
        )
        assert renderer.calls[-1] == (
            "clear_live_local_transforms",
            ("/World/A",),
        )

    def test_rotation_preview_exception_still_commits_final(self, model, transform):
        renderer = _RendererSpy(raise_on_set=True)
        model.set_renderer(renderer)
        model.set_selection(["/World/A"])
        model.on_drag_start()

        model.on_drag_rotated((0.0, 0.0, 1.0), math.pi / 2)
        assert model._live_transforms["/World/A"][0][1] == pytest.approx(1.0)
        assert transform.get_local_transform("/World/A")[0][0] == pytest.approx(1.0)

        model.on_drag_ended()

        assert transform.get_local_transform("/World/A")[0][1] == pytest.approx(1.0)


class TestOnDragScaled:
    def test_previews_axis_scale_without_scene_write(self, model, transform):
        # Axis mask (1,0,0) with factor 2.0 → row 0 doubles, rows 1/2
        # untouched, translation preserved.
        renderer = _RendererSpy()
        model.set_renderer(renderer)
        initial = transform.get_local_transform("/World/A")
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_scaled((1.0, 0.0, 0.0), 2.0)

        assert transform.get_local_transform("/World/A") == initial
        transform.set_local_transform.assert_not_called()
        model._stage.suppress_change_notifications.assert_not_called()
        model._stage.notify_transform_changed.assert_not_called()
        mat = model._live_transforms["/World/A"]
        assert mat[0][0] == pytest.approx(2.0)
        assert mat[1][1] == pytest.approx(1.0)
        assert mat[2][2] == pytest.approx(1.0)
        # Translation row stays put — scale about prim's own origin.
        assert mat[3][0] == pytest.approx(5.0)
        assert renderer.calls[-1][0] == "set_live_local_transform"
        assert renderer.calls[-1][1] == "/World/A"
        assert renderer.calls[-1][2][0][0] == pytest.approx(2.0)

    def test_uniform_scales_all_rows(self, model, transform):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_scaled((1.0, 1.0, 1.0), 2.0)
        mat = model._live_transforms["/World/A"]
        assert transform.get_local_transform("/World/A")[0][0] == pytest.approx(1.0)
        assert mat[0][0] == pytest.approx(2.0)
        assert mat[1][1] == pytest.approx(2.0)
        assert mat[2][2] == pytest.approx(2.0)
        assert mat[3][0] == pytest.approx(5.0)

    def test_does_not_suppress_notifications_during_scale(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_scaled((1.0, 0.0, 0.0), 2.0)
        model._stage.suppress_change_notifications.assert_not_called()

    def test_does_not_notify_live_transform_before_scale_drag_end(self, model):
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_scaled((1.0, 0.0, 0.0), 2.0)
        model._stage.notify_transform_changed.assert_not_called()

    def test_factor_rebases_on_initial_not_current(self, model, transform):
        # Repeated scale_drag calls rebase on the initial transform, not
        # compound — otherwise a multi-frame drag would overshoot.
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_scaled((1.0, 0.0, 0.0), 2.0)
        model.on_drag_scaled((1.0, 0.0, 0.0), 2.0)
        mat = model._live_transforms["/World/A"]
        assert transform.get_local_transform("/World/A")[0][0] == pytest.approx(1.0)
        # Two calls with factor 2 should match a single call with factor 2
        # — not factor 4.
        assert mat[0][0] == pytest.approx(2.0)

    def test_factor_one_is_noop(self, model, transform):
        model.set_selection(["/World/A"])
        initial = transform.get_local_transform("/World/A")
        model.on_drag_start()
        model.on_drag_scaled((1.0, 1.0, 1.0), 1.0)
        after = model._live_transforms["/World/A"]
        assert transform.get_local_transform("/World/A") == initial
        for i in range(4):
            for j in range(4):
                assert after[i][j] == pytest.approx(initial[i][j], abs=1e-12)

    def test_multi_prim_scale(self, model, transform):
        model.set_selection(["/World/A", "/World/B"])
        model.on_drag_start()
        model.on_drag_scaled((1.0, 1.0, 1.0), 3.0)
        a = model._live_transforms["/World/A"]
        b = model._live_transforms["/World/B"]
        assert transform.get_local_transform("/World/A")[0][0] == pytest.approx(1.0)
        assert transform.get_local_transform("/World/B")[0][0] == pytest.approx(1.0)
        # Each prim scaled independently around its own origin.
        assert a[0][0] == pytest.approx(3.0)
        assert a[3][0] == pytest.approx(5.0)
        assert b[0][0] == pytest.approx(3.0)
        assert b[3][0] == pytest.approx(0.0)

    def test_release_authors_scale_once_and_clears_preview(self, model, transform):
        renderer = _RendererSpy()
        model.set_renderer(renderer)
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_scaled((1.0, 0.0, 0.0), 2.0)
        transform.set_local_transform.assert_not_called()

        model.on_drag_ended()

        transform.set_local_transform.assert_called_once()
        mat = transform.get_local_transform("/World/A")
        assert mat[0][0] == pytest.approx(2.0)
        model._stage.notify_transform_changed.assert_called_once_with(
            ["/World/A"],
            source="viewport-manipulator",
        )
        assert renderer.calls[-1] == (
            "clear_live_local_transforms",
            ("/World/A",),
        )

    def test_scale_preview_exception_still_commits_final(self, model, transform):
        renderer = _RendererSpy(raise_on_set=True)
        model.set_renderer(renderer)
        model.set_selection(["/World/A"])
        model.on_drag_start()

        model.on_drag_scaled((1.0, 0.0, 0.0), 2.0)
        assert model._live_transforms["/World/A"][0][0] == pytest.approx(2.0)
        assert transform.get_local_transform("/World/A")[0][0] == pytest.approx(1.0)

        model.on_drag_ended()

        assert transform.get_local_transform("/World/A")[0][0] == pytest.approx(2.0)


class TestApplyScale:
    def test_identity_factor_returns_copy(self):
        result = _apply_scale(_IDENTITY, 1.0, 1.0, 1.0)
        for i in range(4):
            for j in range(4):
                expected = 1.0 if i == j else 0.0
                assert result[i][j] == pytest.approx(expected)

    def test_x_scale_only_scales_row_0(self):
        result = _apply_scale(_IDENTITY, 3.0, 1.0, 1.0)
        assert result[0][0] == pytest.approx(3.0)
        assert result[1][1] == pytest.approx(1.0)
        assert result[2][2] == pytest.approx(1.0)

    def test_translation_row_preserved(self):
        result = _apply_scale(_TRANSLATION, 5.0, 5.0, 5.0)
        # _TRANSLATION has (1, 2, 3) in row 3 — scale must not touch it.
        assert result[3][0] == pytest.approx(1.0)
        assert result[3][1] == pytest.approx(2.0)
        assert result[3][2] == pytest.approx(3.0)
        assert result[3][3] == pytest.approx(1.0)

    def test_result_is_4x4(self):
        result = _apply_scale(_IDENTITY, 2.0, 2.0, 2.0)
        assert len(result) == 4
        assert all(len(row) == 4 for row in result)

    def test_scales_full_row_not_just_diagonal(self):
        # Off-diagonal entries in a row should scale too: a row like
        # [a, b, c, 0] under factor f becomes [fa, fb, fc, 0].
        rotated = [
            [0.0, 1.0, 0.0, 0.0],  # row 0: old local +X axis points at +Y
            [-1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        result = _apply_scale(rotated, 2.0, 1.0, 1.0)
        assert result[0][0] == pytest.approx(0.0)
        assert result[0][1] == pytest.approx(2.0)
        # Row 1 untouched.
        assert result[1][0] == pytest.approx(-1.0)


class TestApplyDelta:
    def test_identity_times_translation(self):
        result = _apply_delta(_IDENTITY, _TRANSLATION, "world")
        assert result[3][0] == pytest.approx(1.0)
        assert result[3][1] == pytest.approx(2.0)
        assert result[3][2] == pytest.approx(3.0)

    def test_translation_times_identity(self):
        result = _apply_delta(_TRANSLATION, _IDENTITY, "world")
        assert result[3][0] == pytest.approx(1.0)
        assert result[3][1] == pytest.approx(2.0)
        assert result[3][2] == pytest.approx(3.0)

    def test_identity_times_identity(self):
        result = _apply_delta(_IDENTITY, _IDENTITY, "world")
        for i in range(4):
            for j in range(4):
                expected = 1.0 if i == j else 0.0
                assert result[i][j] == pytest.approx(expected)

    def test_result_is_4x4(self):
        result = _apply_delta(_IDENTITY, _TRANSLATION, "world")
        assert len(result) == 4
        assert all(len(row) == 4 for row in result)

    def test_translation_composed(self):
        t1 = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [1.0, 0.0, 0.0, 1.0],
        ]
        t2 = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [2.0, 0.0, 0.0, 1.0],
        ]
        result = _apply_delta(t1, t2, "world")
        assert result[3][0] == pytest.approx(3.0)


class TestCancelRestoresPreviewChannel:
    """Cancel re-publishes drag-start transforms through the preview channel.

    Renderers whose live previews advance native scene state (ovstage
    BORROW writes ``omni:xform`` directly) have no separate overlay for
    ``clear_live_local_transforms`` to drop, so a cancelled drag must
    write the initial matrices back or the prim stays at its held
    position on screen even though USD was never touched.
    """

    @pytest.fixture
    def transform(self):
        return MockTransformAdapter()

    def test_cancel_republishes_initial_transform_before_clear(self, transform):
        renderer = _RendererSpy()
        model = PrimTransformModel(
            transform,
            _make_mock_stage(),
            UndoManager(),
            renderer=renderer,
        )
        model.set_selection(["/World/A"])
        initial = [row[:] for row in transform.get_local_transform("/World/A")]
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        model.on_drag_cancelled()

        set_calls = [
            c for c in renderer.calls
            if isinstance(c, tuple) and c[0] == "set_live_local_transform"
        ]
        # last preview write is the restore back to the initial matrix
        assert set_calls[-1] == ("set_live_local_transform", "/World/A", initial)
        # and the restore happens before the final clear
        assert renderer.calls[-1] == (
            "clear_live_local_transforms",
            ("/World/A",),
        )
        assert model._live_transforms == {}

    def test_multi_prim_cancel_republishes_every_initial_transform(self, transform):
        renderer = _RendererSpy()
        model = PrimTransformModel(
            transform,
            _make_mock_stage(),
            UndoManager(),
            renderer=renderer,
        )
        model.set_selection(["/World/A", "/World/B"])
        initials = {
            path: [row[:] for row in transform.get_local_transform(path)]
            for path in ("/World/A", "/World/B")
        }
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        model.on_drag_cancelled()

        restores = [
            c for c in renderer.calls
            if isinstance(c, tuple) and c[0] == "set_live_local_transform"
        ][-2:]
        assert {
            (call[1], tuple(tuple(row) for row in call[2])) for call in restores
        } == {
            (path, tuple(tuple(row) for row in initial))
            for path, initial in initials.items()
        }
        assert renderer.calls[-1] == (
            "clear_live_local_transforms",
            ("/World/A", "/World/B"),
        )


class _RestoreFailingRenderer(_RendererSpy):
    """RendererSpy whose restore-phase preview writes fail on demand."""

    def __init__(self, fail_paths=(), raise_paths=()):
        super().__init__()
        self.fail_paths = set(fail_paths)
        self.raise_paths = set(raise_paths)
        self.restoring = False

    def set_live_local_transform(self, path, matrix):
        self.calls.append(("set_live_local_transform", path, matrix))
        if self.restoring and path in self.raise_paths:
            raise RuntimeError("native restore failed")
        if self.restoring and path in self.fail_paths:
            return False
        return True


class TestCancelRestoreFailurePolicy:
    """Failed cancel rollbacks are recorded, retried, and never silent.

    A cancel that cannot restore a renderer preview (native write failure
    or adapter exception) must not pretend it succeeded: the owed restores
    stay in :attr:`failed_preview_restores`, the stage is notified so
    listeners can resync those paths from authoritative USD, and the
    restores are retried on the next drag start or explicit retry — all
    while cancellation still authors no USD and leaves the drag lifecycle
    coherent for subsequent interactions.
    """

    @pytest.fixture
    def transform(self):
        return MockTransformAdapter()

    def _model(self, transform, renderer, stage=None):
        return PrimTransformModel(
            transform,
            stage if stage is not None else _make_mock_stage(),
            UndoManager(),
            renderer=renderer,
        )

    def test_single_prim_restore_failure_is_recorded(self, transform):
        renderer = _RestoreFailingRenderer(fail_paths={"/World/A"})
        stage = _make_mock_stage()
        model = self._model(transform, renderer, stage)
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])
        initial = [row[:] for row in transform.get_local_transform("/World/A")]
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        renderer.restoring = True

        model.on_drag_cancelled()

        assert model.failed_preview_restores == {"/World/A": initial}
        # drag lifecycle still fully wound down, and no USD was authored
        assert model._drag_active is False
        assert model._live_transforms == {}
        transform.set_local_transform.assert_not_called()
        stage.notify_transform_changed.assert_not_called()

    def test_partial_multi_prim_failure_records_only_failed_paths(self, transform):
        renderer = _RestoreFailingRenderer(fail_paths={"/World/B"})
        model = self._model(transform, renderer)
        model.set_selection(["/World/A", "/World/B"])
        initial_b = [row[:] for row in transform.get_local_transform("/World/B")]
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        renderer.restoring = True

        model.on_drag_cancelled()

        assert model.failed_preview_restores == {"/World/B": initial_b}

    def test_exception_during_restore_is_recorded_not_raised(self, transform):
        renderer = _RestoreFailingRenderer(raise_paths={"/World/A"})
        model = self._model(transform, renderer)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        renderer.restoring = True

        model.on_drag_cancelled()

        assert list(model.failed_preview_restores) == ["/World/A"]
        assert model._drag_active is False

    def test_unsupported_adapter_reports_no_phantom_failures(self, transform):
        model = self._model(transform, _NoPreviewRenderer())
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        model.on_drag_cancelled()

        assert model.failed_preview_restores == {}

    def test_explicit_retry_recovers_and_clears_registry(self, transform):
        renderer = _RestoreFailingRenderer(fail_paths={"/World/A"})
        model = self._model(transform, renderer)
        model.set_selection(["/World/A"])
        initial = [row[:] for row in transform.get_local_transform("/World/A")]
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        renderer.restoring = True
        model.on_drag_cancelled()
        assert model.failed_preview_restores

        renderer.restoring = False  # native path recovered
        assert model.retry_failed_preview_restores() is True
        assert model.failed_preview_restores == {}
        # the recovery write carried the drag-start matrix
        restore_calls = [
            c for c in renderer.calls
            if isinstance(c, tuple) and c[0] == "set_live_local_transform"
        ]
        assert restore_calls[-1] == ("set_live_local_transform", "/World/A", initial)

    def test_next_drag_start_retries_outstanding_restores(self, transform):
        renderer = _RestoreFailingRenderer(fail_paths={"/World/A"})
        model = self._model(transform, renderer)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        renderer.restoring = True
        model.on_drag_cancelled()
        assert model.failed_preview_restores

        renderer.restoring = False
        model.on_drag_start()
        assert model.failed_preview_restores == {}
        model.on_drag_cancelled()

    def test_subsequent_drag_and_commit_work_after_failure(self, transform):
        renderer = _RestoreFailingRenderer(fail_paths={"/World/A"})
        undo = UndoManager()
        model = PrimTransformModel(
            transform, _make_mock_stage(), undo, renderer=renderer
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        renderer.restoring = True
        model.on_drag_cancelled()
        assert undo._undo_stack == []

        renderer.restoring = False
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        model.on_drag_ended()
        assert model._drag_active is False
        assert len(undo._undo_stack) == 1
        assert model.failed_preview_restores == {}

    def test_retry_with_still_failing_renderer_keeps_registry(self, transform):
        renderer = _RestoreFailingRenderer(fail_paths={"/World/A"})
        model = self._model(transform, renderer)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        renderer.restoring = True
        model.on_drag_cancelled()

        assert model.retry_failed_preview_restores() is False
        assert list(model.failed_preview_restores) == ["/World/A"]


class TestGenerationBoundaries:
    """Stage/renderer generation changes atomically resolve drag state.

    A renderer or stage swap is one lifecycle boundary: an in-flight drag
    is resolved against the outgoing generation while it is still bound,
    pending cancel restores are discarded with the generation that owed
    them (never applied to a successor), and retries within a live
    generation always target the CURRENT authoritative transform.
    """

    @pytest.fixture
    def transform(self):
        return MockTransformAdapter()

    def test_renderer_change_discards_pending_and_never_touches_successor(
        self, transform
    ):
        failing = _RestoreFailingRenderer(fail_paths={"/World/A"})
        model = PrimTransformModel(
            transform, _make_mock_stage(), UndoManager(), renderer=failing
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        failing.restoring = True
        model.on_drag_cancelled()
        assert model.failed_preview_restores

        successor = _RendererSpy()
        model.set_renderer(successor)

        assert model.failed_preview_restores == {}
        # neither the discarded restore nor a later drag start replays
        # old-generation state into the successor
        model.on_drag_start()
        model.on_drag_cancelled()
        replayed = [
            c for c in successor.calls
            if isinstance(c, tuple) and c[0] == "set_live_local_transform"
        ]
        assert replayed == []

    def test_renderer_change_mid_drag_cancels_against_old_renderer(self, transform):
        old_renderer = _RendererSpy()
        model = PrimTransformModel(
            transform, _make_mock_stage(), UndoManager(), renderer=old_renderer
        )
        model.set_selection(["/World/A"])
        initial = [row[:] for row in transform.get_local_transform("/World/A")]
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        successor = _RendererSpy()
        model.set_renderer(successor)

        assert model._drag_active is False
        assert model._live_transforms == {}
        # rollback went to the OLD renderer, none to the successor
        old_sets = [
            c for c in old_renderer.calls
            if isinstance(c, tuple) and c[0] == "set_live_local_transform"
        ]
        assert old_sets[-1] == ("set_live_local_transform", "/World/A", initial)
        assert all(
            not (isinstance(c, tuple) and c[0] == "set_live_local_transform")
            for c in successor.calls
        )

    def test_attach_adapters_mid_drag_cancels_and_discards_pending(self, transform):
        failing = _RestoreFailingRenderer(fail_paths={"/World/A"})
        model = PrimTransformModel(
            transform, _make_mock_stage(), UndoManager(), renderer=failing
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        failing.restoring = True

        model.attach_adapters(
            transform_adapter=MockTransformAdapter(),
            stage_adapter=_make_mock_stage(),
            undo=UndoManager(),
            renderer=_RendererSpy(),
        )

        assert model._drag_active is False
        assert model.failed_preview_restores == {}

    def test_same_renderer_reassignment_keeps_state(self, transform):
        failing = _RestoreFailingRenderer(fail_paths={"/World/A"})
        model = PrimTransformModel(
            transform, _make_mock_stage(), UndoManager(), renderer=failing
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        failing.restoring = True
        model.on_drag_cancelled()
        pending = model.failed_preview_restores

        model.set_renderer(failing)  # same generation: not a boundary

        assert model.failed_preview_restores == pending

    def test_retry_targets_current_authoritative_transform(self, transform):
        failing = _RestoreFailingRenderer(fail_paths={"/World/A"})
        model = PrimTransformModel(
            transform, _make_mock_stage(), UndoManager(), renderer=failing
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        failing.restoring = True
        model.on_drag_cancelled()
        assert model.failed_preview_restores

        # USD moved on after the failed cancel (undo/redo, property edit…)
        newer = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [42.0, 0.0, 0.0, 1.0],
        ]
        transform.set_local_transform("/World/A", newer)
        failing.restoring = False

        assert model.retry_failed_preview_restores() is True
        restore = [
            c for c in failing.calls
            if isinstance(c, tuple) and c[0] == "set_live_local_transform"
        ][-1]
        assert restore == ("set_live_local_transform", "/World/A", newer)

    def test_selection_change_retries_pending_restores(self, transform):
        failing = _RestoreFailingRenderer(fail_paths={"/World/A"})
        model = PrimTransformModel(
            transform, _make_mock_stage(), UndoManager(), renderer=failing
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        failing.restoring = True
        model.on_drag_cancelled()
        assert model.failed_preview_restores

        failing.restoring = False
        model.set_selection(["/World/B"])

        assert model.failed_preview_restores == {}


class _RaisingStage:
    """Mock stage whose undo-group closure raises."""

    def __init__(self):
        self.begin_calls = 0
        self.end_calls = 0

    def begin_undo_group(self, label):
        self.begin_calls += 1

    def end_undo_group(self):
        self.end_calls += 1
        raise RuntimeError("undo close failed")


class _ClearRaisingRenderer(_RendererSpy):
    def clear_live_local_transforms(self, paths):
        super().clear_live_local_transforms(paths)
        raise RuntimeError("clear failed")


class TestExceptionSafeCancellation:
    """Cancellation finalizes drag state on every failure path.

    Whatever raises — preview restore, renderer clear, undo-group
    closure — the drag can never remain falsely active, live state can
    never stay stranded, the error stays observable (propagated from the
    model; logged and truthfully reported by gesture/widget callers),
    and cancellation never authors USD.
    """

    @pytest.fixture
    def transform(self):
        return MockTransformAdapter()

    def test_undo_close_failure_finalizes_and_propagates(self, transform):
        stage = _RaisingStage()
        model = PrimTransformModel(
            transform, stage, UndoManager(), renderer=_RendererSpy()
        )
        transform.set_local_transform = MagicMock(wraps=transform.set_local_transform)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        with pytest.raises(RuntimeError, match="undo close failed"):
            model.on_drag_cancelled()

        assert model._drag_active is False
        assert model._live_transforms == {}
        assert model._initial_transforms == {}
        assert model._preview_applied_paths == set()
        transform.set_local_transform.assert_not_called()

    def test_clear_failure_finalizes_without_masking_state(self, transform):
        model = PrimTransformModel(
            transform, _make_mock_stage(), UndoManager(),
            renderer=_ClearRaisingRenderer(),
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        # the model-level clear helper swallows renderer clear errors
        model.on_drag_cancelled()

        assert model._drag_active is False
        assert model._live_transforms == {}

    def test_gesture_cancel_is_truthful_when_model_raises(self, transform):
        from ovui_widgets.viewport.transform_manipulator import (
            TransformGestureBase,
        )

        stage = _RaisingStage()
        model = PrimTransformModel(
            transform, stage, UndoManager(), renderer=_RendererSpy()
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        gesture = TransformGestureBase.__new__(TransformGestureBase)
        gesture._active = True
        gesture._model = model

        assert gesture.cancel_active_drag() is True
        # truthful: the drag really is finalized despite the error
        assert model._drag_active is False
        assert model._live_transforms == {}
        # a later mouse-up cannot commit: gesture deactivated
        assert gesture._active is False

    def test_undo_close_failure_after_restore_failure_still_records_pending(
        self, transform
    ):
        class _FailingBoth(_RestoreFailingRenderer):
            pass

        stage = _RaisingStage()
        renderer = _FailingBoth(fail_paths={"/World/A"})
        model = PrimTransformModel(transform, stage, UndoManager(), renderer=renderer)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        renderer.restoring = True

        with pytest.raises(RuntimeError):
            model.on_drag_cancelled()

        assert list(model.failed_preview_restores) == ["/World/A"]
        assert model._drag_active is False

    def test_renderer_replacement_with_raising_cancel_still_swaps(self, transform):
        stage = _RaisingStage()
        model = PrimTransformModel(
            transform, stage, UndoManager(), renderer=_RendererSpy()
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        successor = _RendererSpy()
        model.set_renderer(successor)  # cancel raises internally; logged

        assert model._renderer is successor
        assert model._drag_active is False
        assert model.failed_preview_restores == {}

    def test_attach_adapters_with_raising_cancel_still_swaps(self, transform):
        stage = _RaisingStage()
        model = PrimTransformModel(
            transform, stage, UndoManager(), renderer=_RendererSpy()
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())

        new_transform = MockTransformAdapter()
        new_stage = _make_mock_stage()
        model.attach_adapters(
            transform_adapter=new_transform,
            stage_adapter=new_stage,
            undo=UndoManager(),
            renderer=_RendererSpy(),
        )

        assert model._transform is new_transform
        assert model._stage is new_stage
        assert model._drag_active is False


class TestSameGenerationReattachment:
    """Same-object reattachment is not a generation boundary."""

    @pytest.fixture
    def transform(self):
        return MockTransformAdapter()

    def test_same_object_reattach_preserves_pending_recovery(self, transform):
        stage = _make_mock_stage()
        undo = UndoManager()
        renderer = _RestoreFailingRenderer(fail_paths={"/World/A"})
        model = PrimTransformModel(transform, stage, undo, renderer=renderer)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        renderer.restoring = True
        model.on_drag_cancelled()
        pending = model.failed_preview_restores
        assert pending
        writes_before = len([
            c for c in renderer.calls
            if isinstance(c, tuple) and c[0] == "set_live_local_transform"
        ])

        model.attach_adapters(
            transform_adapter=transform,
            stage_adapter=stage,
            undo=undo,
            renderer=renderer,
        )

        assert model.failed_preview_restores == pending
        # and no stale/incorrect write was issued by the reattachment
        writes_after = len([
            c for c in renderer.calls
            if isinstance(c, tuple) and c[0] == "set_live_local_transform"
        ])
        assert writes_after == writes_before

    def test_same_object_reattach_keeps_active_drag_untouched(self, transform):
        stage = _make_mock_stage()
        undo = UndoManager()
        renderer = _RendererSpy()
        model = PrimTransformModel(transform, stage, undo, renderer=renderer)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        assert model._drag_active is True

        model.attach_adapters(
            transform_adapter=transform,
            stage_adapter=stage,
            undo=undo,
            renderer=renderer,
        )

        assert model._drag_active is True
        assert "/World/A" in model._live_transforms
        model.on_drag_cancelled()

    def test_any_owner_change_is_a_boundary(self, transform):
        stage = _make_mock_stage()
        undo = UndoManager()
        renderer = _RestoreFailingRenderer(fail_paths={"/World/A"})
        model = PrimTransformModel(transform, stage, undo, renderer=renderer)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        renderer.restoring = True
        model.on_drag_cancelled()
        assert model.failed_preview_restores

        # one owner (the transform wrapper) recreated => true boundary
        model.attach_adapters(
            transform_adapter=MockTransformAdapter(),
            stage_adapter=stage,
            undo=undo,
            renderer=renderer,
        )

        assert model.failed_preview_restores == {}


class TestUndoOwnerContamination:
    """An unproven undo-group close blocks the owning lifecycle.

    Closure that raises is ambiguous (it may or may not have completed),
    so it is never retried — a second close on a completed group corrupts
    depth. Transform work on any contaminated owner (the real shared undo
    owner or its wrapper) stays blocked until the owning lifecycle is
    replaced with different objects; contamination is never displaced,
    never closes an unrelated owner's group, and never authors USD.
    """

    class _DepthStage:
        def __init__(self):
            self.depth = 0
            self.fail_close = True

        def begin_undo_group(self, label):
            self.depth += 1

        def end_undo_group(self):
            if self.fail_close:
                raise RuntimeError("close failed")
            self.depth -= 1

    class _AmbiguousStage:
        """Close COMPLETES and then raises — outcome unprovable."""

        def __init__(self):
            self.depth = 0

        def begin_undo_group(self, label):
            self.depth += 1

        def end_undo_group(self):
            self.depth -= 1
            raise RuntimeError("late failure after close")

    @pytest.fixture
    def transform(self):
        return MockTransformAdapter()

    def _leaked_model(self, transform, stage=None):
        stage = stage if stage is not None else self._DepthStage()
        model = PrimTransformModel(
            transform, stage, UndoManager(), renderer=_RendererSpy()
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        with pytest.raises(RuntimeError):
            model.on_drag_cancelled()
        return model, stage

    def test_failed_close_is_disclosed_and_blocks(self, transform):
        model, stage = self._leaked_model(transform)
        assert stage in model.contaminated_undo_owners
        assert stage.depth == 1  # group really is still open
        with pytest.raises(RuntimeError, match="blocked"):
            model.on_drag_start()
        # blocked means blocked: no second close attempt, no new group
        assert stage.depth == 1
        assert model._drag_active is False

    def test_ambiguous_close_is_never_retried(self, transform):
        stage = self._AmbiguousStage()
        model, _ = self._leaked_model(transform, stage)
        assert stage.depth == 0  # the close actually completed
        with pytest.raises(RuntimeError, match="blocked"):
            model.on_drag_start()
        # a blind retry would have driven depth negative
        assert stage.depth == 0

    def test_wrapper_swap_over_same_real_owner_stays_blocked(self, transform):
        class _SharedOwner:
            def __init__(self):
                self.depth = 0

            def begin_group(self, label):
                self.depth += 1

            def end_group(self):
                raise RuntimeError("close failed")

        class _Wrapper:
            def __init__(self, owner):
                self._undo_manager = owner

            def begin_undo_group(self, label):
                self._undo_manager.begin_group(label)

            def end_undo_group(self):
                self._undo_manager.end_group()

        shared = _SharedOwner()
        w1, w2 = _Wrapper(shared), _Wrapper(shared)
        model = PrimTransformModel(
            transform, w1, UndoManager(), renderer=_RendererSpy()
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        with pytest.raises(RuntimeError):
            model.on_drag_cancelled()
        assert shared.depth == 1

        # a NEW wrapper over the SAME real owner cannot bypass the block
        model.attach_adapters(
            transform_adapter=MockTransformAdapter(),
            stage_adapter=w2,
            undo=model._undo,
            renderer=_RendererSpy(),
        )
        model.set_selection(["/World/A"])
        with pytest.raises(RuntimeError, match="blocked"):
            model.on_drag_start()
        assert shared.depth == 1  # never nested

    def test_replaced_lifecycle_recovers_and_old_owner_stays_recorded(
        self, transform
    ):
        model, stage = self._leaked_model(transform)
        clean_stage = _make_mock_stage()
        model.attach_adapters(
            transform_adapter=MockTransformAdapter(),
            stage_adapter=clean_stage,
            undo=UndoManager(),
            renderer=_RendererSpy(),
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()  # clean owners: drags proceed
        model.on_drag_cancelled()
        # the contaminated owner stays recorded (never forgotten) and its
        # group was never touched again
        assert stage in model.contaminated_undo_owners
        assert stage.depth == 1
        # the clean owner's groups were never cross-closed
        assert clean_stage.end_undo_group.call_count == 1  # its own cancel

    def test_two_contaminated_owners_both_recorded(self, transform):
        model, s1 = self._leaked_model(transform)
        s2 = self._DepthStage()
        model.attach_adapters(
            transform_adapter=MockTransformAdapter(),
            stage_adapter=s2,
            undo=UndoManager(),
            renderer=_RendererSpy(),
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        model.on_drag_moved(_translate_delta())
        with pytest.raises(RuntimeError):
            model.on_drag_cancelled()
        owners = model.contaminated_undo_owners
        assert s1 in owners and s2 in owners
        assert s1.depth == 1 and s2.depth == 1  # neither nested nor re-closed


class TestUndoBeginContamination:
    """A begin that may have mutated the shared owner before raising is
    as ambiguous as a failed close: it contaminates the owner so later
    begins can never nest on it."""

    def test_begin_that_mutates_then_raises_contaminates_owner(self):
        class BeginStage:
            def __init__(self):
                self.depth = 0

            def begin_undo_group(self, label):
                self.depth += 1
                raise KeyboardInterrupt()

            def end_undo_group(self):
                self.depth -= 1

        stage = BeginStage()
        model = PrimTransformModel(
            MockTransformAdapter(), stage, UndoManager(),
            renderer=_RendererSpy(),
        )
        model.set_selection(["/World/A"])
        with pytest.raises(KeyboardInterrupt):
            model.on_drag_start()
        assert model.contaminated_undo_owners
        assert model._drag_active is False
        # even a now-working begin on the contaminated owner is blocked
        stage.begin_undo_group = (
            lambda label: setattr(stage, "depth", stage.depth + 1)
        )
        with pytest.raises(RuntimeError, match="blocked"):
            model.on_drag_start()
        assert stage.depth == 1


    def test_failed_begin_leaves_no_effecting_state(self):
        class BeginStage:
            def __init__(self):
                self.depth = 0
                self.suppressed = 0

            def begin_undo_group(self, label):
                self.depth += 1
                raise KeyboardInterrupt()

            def end_undo_group(self):
                self.depth -= 1

            def suppress_change_notifications(self):
                from contextlib import nullcontext
                return nullcontext()

        stage = BeginStage()
        spy = _RendererSpy()
        undo = UndoManager()
        model = PrimTransformModel(
            MockTransformAdapter(), stage, undo, renderer=spy
        )
        model.set_selection(["/World/A"])
        with pytest.raises(KeyboardInterrupt):
            model.on_drag_start()
        assert model._initial_transforms == {}
        # queued movement callbacks can no longer preview
        model.on_drag_moved(_translate_delta())
        assert [c for c in spy.calls if isinstance(c, tuple)] == []
        # queued release/cancel callbacks author nothing and push no history
        model.on_drag_ended()
        assert undo._undo_stack == []
        model.on_drag_cancelled()
        assert [c for c in spy.calls if isinstance(c, tuple) and c[0] == "set_live_local_transform"] == []
        assert stage.depth == 1  # contaminated owner; never re-closed


    def test_bookkeeping_failure_still_fail_closed(self):
        class BeginStage:
            def __init__(self):
                self.depth = 0

            def begin_undo_group(self, label):
                self.depth += 1
                raise KeyboardInterrupt()

            def end_undo_group(self):
                self.depth -= 1

        class ExplodingList(list):
            def append(self, item):
                raise MemoryError("contamination storage failed")

        stage = BeginStage()
        model = PrimTransformModel(
            MockTransformAdapter(), stage, UndoManager(),
            renderer=_RendererSpy(),
        )
        model._contaminated_undo_owners = ExplodingList()
        model.set_selection(["/World/A"])
        with pytest.raises(KeyboardInterrupt):
            model.on_drag_start()
        # identity recording failed, but the latch fail-closes anyway
        assert len(model._contaminated_undo_owners) == 0
        stage.begin_undo_group = (
            lambda label: setattr(stage, "depth", stage.depth + 1)
        )
        with pytest.raises(RuntimeError, match="blocked"):
            model.on_drag_start()
        assert stage.depth == 1
        # queued callbacks stay inert
        model.on_drag_moved(_translate_delta())
        assert model._live_transforms == {}
        # unrelated model with clean owners stays usable
        other = PrimTransformModel(
            MockTransformAdapter(), _make_mock_stage(), UndoManager(),
            renderer=_RendererSpy(),
        )
        other.set_selection(["/World/B"])
        other.on_drag_start()
        assert other._drag_active is True
        # sanctioned recovery: replacing the undo owners clears the latch
        model.attach_adapters(
            transform_adapter=MockTransformAdapter(),
            stage_adapter=_make_mock_stage(),
            undo=UndoManager(),
            renderer=_RendererSpy(),
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        assert model._drag_active is True
