# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for DeletePrimCommand (Step 53)."""

from unittest.mock import MagicMock, call, patch

import pytest
from ovui_data_adapters.openusd import DeletePrimCommand


class TestDeletePrimCommandNoUsd:
    """Tests that run without a real USD stage, using mocks."""

    def _make_command(self):
        stage = MagicMock()
        layer = MagicMock()
        stage.GetEditTarget.return_value.GetLayer.return_value = layer
        path = MagicMock()
        return DeletePrimCommand(stage, path), stage, layer, path

    def test_do_creates_anonymous_layer_and_applies_batch(self):
        pytest.importorskip("pxr", reason="pxr not available")
        cmd, stage, layer, path = self._make_command()
        with patch("ovui_data_adapters.openusd.commands.Sdf") as MockSdf:
            tmp_layer = MagicMock()
            MockSdf.Layer.CreateAnonymous.return_value = tmp_layer
            MockSdf.Path.emptyPath = MagicMock()
            cmd.do()
            MockSdf.Layer.CreateAnonymous.assert_called_once()
            MockSdf.CopySpec.assert_called_once_with(layer, path, tmp_layer, path)
            layer.Apply.assert_called_once()

    def test_undo_copies_spec_back(self):
        pytest.importorskip("pxr", reason="pxr not available")
        cmd, stage, layer, path = self._make_command()
        with patch("ovui_data_adapters.openusd.commands.Sdf") as MockSdf:
            tmp_layer = MagicMock()
            MockSdf.Layer.CreateAnonymous.return_value = tmp_layer
            MockSdf.Path.emptyPath = MagicMock()
            cmd.do()
            cmd.undo()
            # Second CopySpec call is the undo restoration
            assert MockSdf.CopySpec.call_count == 2
            last = MockSdf.CopySpec.call_args_list[1]
            assert last == call(tmp_layer, path, layer, path)

    def test_undo_without_do_does_not_raise(self):
        cmd, stage, layer, path = self._make_command()
        cmd.undo()  # captured_layer is None, should do nothing


class TestDeletePrimCommandRealStage:
    """End-to-end Delete+Undo against a real ``Usd.Stage`` — backstops
    the Codex Step 28 final-QA blocker.

    The mock-only tests above mocked ``Sdf`` entirely, so they did not
    exercise ``Sdf.CopySpec``'s "destination must already have parent
    prim specs" precondition. Codex's user-like UI delete on
    ``tests/data/simple_scene.usda`` hit this with
    ``Failed verification: ' i != _data.end() ' -- No spec at </World>
    when trying to set field 'primChildren'``. These tests reproduce
    the real layer-stack behaviour and verify the fix
    (``Sdf.CreatePrimInLayer`` on the parent path before
    ``Sdf.CopySpec``).
    """

    def _open_simple_scene(self):
        """Open the repo's ``tests/data/simple_scene.usda`` regardless of
        the checkout location. ``__file__`` is ``tests/test_delete_prim_command.py``,
        so the fixture lives at ``../tests/data/simple_scene.usda``.
        """
        import os

        from pxr import Usd

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        fixture = os.path.join(repo_root, "tests", "data", "simple_scene.usda")
        assert os.path.isfile(fixture), f"missing fixture: {fixture}"
        return Usd.Stage.Open(fixture)

    def test_delete_cube_from_simple_scene_round_trips(self):
        """Delete /World/Cube, verify it's gone, undo, verify it's back
        with its original ``size`` + ``xformOp:translate`` values.
        """
        pytest.importorskip("pxr", reason="pxr not available")
        from pxr import Sdf

        stage = self._open_simple_scene()
        cube_path = Sdf.Path("/World/Cube")

        # Pre-condition: Cube exists and has the simple_scene baseline values.
        cube = stage.GetPrimAtPath(cube_path)
        assert cube.IsValid()
        assert cube.GetAttribute("size").Get() == 2.0
        assert tuple(cube.GetAttribute("xformOp:translate").Get()) == (-1.5, 0, 0)

        cmd = DeletePrimCommand(stage, cube_path)
        cmd.do()

        # Cube is gone; siblings remain.
        assert not stage.GetPrimAtPath(cube_path).IsValid()
        world_children = [p.GetName() for p in stage.GetPrimAtPath("/World").GetChildren()]
        assert "Cube" not in world_children
        assert set(world_children) == {"Sphere", "Pyramid", "Pillar"}

        cmd.undo()

        # Cube is back with full attributes.
        cube = stage.GetPrimAtPath(cube_path)
        assert cube.IsValid()
        assert cube.GetAttribute("size").Get() == 2.0
        assert tuple(cube.GetAttribute("xformOp:translate").Get()) == (-1.5, 0, 0)
        world_children = [p.GetName() for p in stage.GetPrimAtPath("/World").GetChildren()]
        assert set(world_children) == {"Cube", "Sphere", "Pyramid", "Pillar"}

    def test_delete_does_not_raise_sdfdata_error(self):
        """The original failure mode: ``Sdf.CopySpec`` raised because the
        captured anonymous layer had no parent prim spec. The fix is
        that ``do()`` now pre-creates the parent path on ``tmp`` via
        ``Sdf.CreatePrimInLayer``. This test pins that ``cmd.do()`` no
        longer raises the ``Tf.ErrorException`` Codex captured.
        """
        pytest.importorskip("pxr", reason="pxr not available")
        from pxr import Sdf, Tf

        stage = self._open_simple_scene()
        cmd = DeletePrimCommand(stage, Sdf.Path("/World/Cube"))
        # Should not raise.
        try:
            cmd.do()
        except Tf.ErrorException as exc:
            pytest.fail(
                f"DeletePrimCommand.do() raised the regression: {exc!r}"
            )

    def test_delete_top_level_prim_does_not_need_parent_creation(self):
        """When the prim is a top-level child of the pseudo-root, the
        parent path is ``/`` (the pseudo-root) and we must NOT try to
        ``Sdf.CreatePrimInLayer`` it — the pseudo-root already exists.
        Pins the ``parent_path != Sdf.Path.absoluteRootPath`` guard.
        """
        pytest.importorskip("pxr", reason="pxr not available")
        from pxr import Sdf, Usd, UsdGeom

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Cube.Define(stage, "/SoloCube")
        assert stage.GetPrimAtPath("/SoloCube").IsValid()

        cmd = DeletePrimCommand(stage, Sdf.Path("/SoloCube"))
        cmd.do()
        assert not stage.GetPrimAtPath("/SoloCube").IsValid()

        cmd.undo()
        assert stage.GetPrimAtPath("/SoloCube").IsValid()

    def test_delete_deeply_nested_prim_creates_full_ancestor_chain(self):
        """``Sdf.CreatePrimInLayer`` creates the prim AND ancestors. A
        deeper path like ``/A/B/C/Target`` round-trips without an
        ``Sdf.CopySpec`` ancestor-missing failure. Future-proofs the
        fix for non-trivial scene hierarchies.
        """
        pytest.importorskip("pxr", reason="pxr not available")
        from pxr import Sdf, Usd, UsdGeom

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/A")
        UsdGeom.Xform.Define(stage, "/A/B")
        UsdGeom.Xform.Define(stage, "/A/B/C")
        UsdGeom.Cube.Define(stage, "/A/B/C/Target")

        cmd = DeletePrimCommand(stage, Sdf.Path("/A/B/C/Target"))
        cmd.do()
        assert not stage.GetPrimAtPath("/A/B/C/Target").IsValid()

        cmd.undo()
        assert stage.GetPrimAtPath("/A/B/C/Target").IsValid()


class TestStageAdapterExpiredPrimResilience:
    """Codex final-UI-QA rerun (2026-05-08) caught a separate symptom:
    the Stage delegate still holds ``Usd.Prim`` handles in cached row
    items the frame after a delete, and per-frame ``build_branch`` /
    ``build_widget`` paths called ``StageAdapter.get_children`` /
    ``get_type_category`` / ``can_edit_visibility`` on the now-expired
    handles, raising ``RuntimeError: Accessed invalid expired
    '<name>' prim``. The fix routes those three methods through
    ``_is_live_prim`` and returns safe defaults for any non-live
    handle.
    """

    def _stage_with_cube(self):
        pytest.importorskip("pxr", reason="pxr not available")
        from pxr import Sdf, Usd, UsdGeom

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Cube.Define(stage, "/World/Cube")
        return stage

    def test_get_children_on_expired_prim_returns_empty_list(self):
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Sdf

        stage = self._stage_with_cube()
        adapter = UsdStageAdapter(stage)
        cube = stage.GetPrimAtPath("/World/Cube")
        assert cube.IsValid()
        # Capture a handle the way the Stage tree's HierarchyItem does,
        # then delete the prim from the live stage.
        captured = cube
        layer = stage.GetEditTarget().GetLayer()
        batch = Sdf.BatchNamespaceEdit()
        batch.Add(Sdf.Path("/World/Cube"), Sdf.Path.emptyPath)
        layer.Apply(batch)
        # Now ``captured`` is expired. ``get_children`` must not raise.
        assert adapter.get_children(captured) == []

    def test_get_type_category_on_expired_prim_returns_other(self):
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Sdf

        stage = self._stage_with_cube()
        adapter = UsdStageAdapter(stage)
        captured = stage.GetPrimAtPath("/World/Cube")
        layer = stage.GetEditTarget().GetLayer()
        batch = Sdf.BatchNamespaceEdit()
        batch.Add(Sdf.Path("/World/Cube"), Sdf.Path.emptyPath)
        layer.Apply(batch)
        assert adapter.get_type_category(captured) == "Other"

    def test_can_edit_visibility_on_expired_prim_returns_false(self):
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Sdf

        stage = self._stage_with_cube()
        adapter = UsdStageAdapter(stage)
        captured = stage.GetPrimAtPath("/World/Cube")
        layer = stage.GetEditTarget().GetLayer()
        batch = Sdf.BatchNamespaceEdit()
        batch.Add(Sdf.Path("/World/Cube"), Sdf.Path.emptyPath)
        layer.Apply(batch)
        assert adapter.can_edit_visibility(captured) is False

    def test_get_children_on_none_returns_empty_list(self):
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter

        stage = self._stage_with_cube()
        adapter = UsdStageAdapter(stage)
        # Defensive: callers that mishandle their cache may pass None.
        assert adapter.get_children(None) == []


class TestPropertyAdapterInvalidPrimResilience:
    """Codex final-UI-QA rerun (2026-05-08) third symptom: after Delete,
    the still-subscribed ``UsdPropertyAdapter`` for the deleted path
    fired a stage-change notice flush whose ``get_value`` callback hit
    ``prim.GetAttribute`` on a now-null prim. The PropertyWindow
    rebuild swaps the adapter for the cleared selection a frame later,
    but the fired notice runs first. Fix: ``UsdPropertyAdapter.get_value``
    returns the property's default sentinel when the prim is no
    longer valid, so the AttributeModel rebuild quietly absorbs the
    missing prim.
    """

    def test_get_value_on_deleted_prim_returns_default_sentinel(self):
        pytest.importorskip("pxr", reason="pxr not available")
        from ovui_data_adapters.openusd.property_adapter import UsdPropertyAdapter
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Sdf, Usd, UsdGeom

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Cube.Define(stage, "/World/Cube")
        cube_path = Sdf.Path("/World/Cube")
        stage_adapter = UsdStageAdapter(stage)
        prop_adapter = UsdPropertyAdapter(stage, [cube_path], None, stage_adapter)

        # Sanity: the Cube has a ``size`` attribute at construction time.
        assert "size" in prop_adapter._props

        # Delete the Cube via the same machinery the app uses.
        cmd = DeletePrimCommand(stage, cube_path)
        cmd.do()
        assert not stage.GetPrimAtPath(cube_path).IsValid()

        # ``get_value`` MUST NOT raise. It returns the property type's
        # documented default sentinel.
        value = prop_adapter.get_value("size")
        # ``size`` is ``double`` — default sentinel is 0.0.
        assert value == 0.0


class TestFramePaths:
    """Tests for ViewportWidget.frame_paths()."""

    def _make_viewport(self):
        from ovwidgets.viewport.viewport_widget import ViewportWidget
        vp = ViewportWidget.__new__(ViewportWidget)
        from ovwidgets.viewport.camera_controller import CameraController
        vp._camera = CameraController()
        # Step 11.3: stage adapter is provided through the explicit
        # ``stage_adapter_provider`` callable; default to None for the
        # bare-test case.
        vp._stage_adapter_provider = None
        return vp

    def test_empty_paths_returns_immediately(self):
        vp = self._make_viewport()
        initial_target = list(vp._camera.state.target)
        initial_dist = vp._camera.state.distance
        vp.frame_paths([])
        assert vp._camera.state.target == initial_target
        assert vp._camera.state.distance == initial_dist

    def test_paths_without_adapter_uses_default_focus(self):
        vp = self._make_viewport()
        vp.frame_paths(["/Sphere"])
        assert vp._camera.state.target == [0.0, 0.0, 0.0]
        assert vp._camera.state.distance == 5.0

    def test_paths_with_provider_returning_none_uses_default_focus(self):
        vp = self._make_viewport()
        # Step 11.3: simulate "Application up but no stage adapter" by
        # binding a provider that returns None (formerly tested via
        # ``app._stage_adapter = None``).
        vp._stage_adapter_provider = lambda: None
        vp.frame_paths(["/Sphere"])
        assert vp._camera.state.target == [0.0, 0.0, 0.0]
        assert vp._camera.state.distance == 5.0

    def test_root_path_expands_to_pseudo_root_children(self):
        """Phase A QA — ``frame_paths(["/"])`` used to pass the pseudo-root to
        ``ComputeWorldBound`` which returns an empty bound. The fix iterates
        the pseudo-root's top-level children so an initial ``_load_stage`` can
        actually frame the scene.

        Step 17 routed this through ``StageAdapter.compute_world_aabb`` —
        the adapter handles the pseudo-root pre-pass internally, so the
        test now uses a real ``UsdStageAdapter`` instead of a MagicMock."""
        pxr = pytest.importorskip("pxr", reason="pxr not available")
        Usd, UsdGeom = pxr.Usd, pxr.UsdGeom
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter

        stage = Usd.Stage.CreateInMemory()
        sphere = UsdGeom.Sphere.Define(stage, "/World/Sphere")
        sphere.GetRadiusAttr().Set(3.0)
        world = stage.GetPrimAtPath("/World")
        assert world.IsValid()

        vp = self._make_viewport()
        adapter = UsdStageAdapter(stage)
        vp._stage_adapter_provider = lambda: adapter

        # Pseudo-root has one child ("/World"); the computed bound must be
        # non-empty so distance gets bumped up from the 5.0 fallback.
        vp.frame_paths(["/"])
        assert vp._camera.state.distance > 5.0

    # Step 17: the per-path bound expansion (pseudo-root → top-level
    # children, every other path → the prim at that path) is now an
    # internal helper of ``UsdStageAdapter`` (its private static
    # ``_prims_to_bound``), driven by ``compute_world_aabb``. The widget
    # no longer carries this helper. The three tests below cover the
    # helper at its new home so the behavioral guarantee survives the
    # relocation.

    def test_prims_to_bound_for_root_returns_children(self):
        pxr = pytest.importorskip("pxr", reason="pxr not available")
        Usd, UsdGeom = pxr.Usd, pxr.UsdGeom
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Sphere.Define(stage, "/A")
        UsdGeom.Cube.Define(stage, "/B")
        prims = UsdStageAdapter._prims_to_bound(stage, "/")
        paths = sorted(str(p.GetPath()) for p in prims)
        assert paths == ["/A", "/B"]

    def test_prims_to_bound_for_specific_path(self):
        pxr = pytest.importorskip("pxr", reason="pxr not available")
        Usd, UsdGeom = pxr.Usd, pxr.UsdGeom
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Sphere.Define(stage, "/World/Sphere")
        prims = UsdStageAdapter._prims_to_bound(stage, "/World/Sphere")
        assert len(prims) == 1
        assert str(prims[0].GetPath()) == "/World/Sphere"

    def test_prims_to_bound_for_invalid_path_returns_empty(self):
        pxr = pytest.importorskip("pxr", reason="pxr not available")
        Usd = pxr.Usd
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        stage = Usd.Stage.CreateInMemory()
        prims = UsdStageAdapter._prims_to_bound(stage, "/does/not/exist")
        assert prims == []


class TestFramePathsContract:
    """Step 17 review correction: ``frame_paths`` returns ``bool`` and is
    no-throw against adapter failures.

    Contract:
      - Empty ``paths`` returns ``False`` without touching the camera.
      - No adapter / no provider returns ``False`` and applies default
        focus (center=(0,0,0), distance=5.0).
      - Adapter returns ``None`` returns ``False`` and applies default
        focus.
      - Adapter raises returns ``False`` and applies default focus.
      - Adapter returns real bounds returns ``True`` and applies the
        computed center/distance.
    """

    def _make_viewport(self):
        from ovwidgets.viewport.camera_controller import CameraController
        from ovwidgets.viewport.viewport_widget import ViewportWidget
        vp = ViewportWidget.__new__(ViewportWidget)
        vp._camera = CameraController()
        vp._stage_adapter_provider = None
        return vp

    def test_empty_paths_returns_false_without_focus_change(self):
        vp = self._make_viewport()
        initial_target = list(vp._camera.state.target)
        initial_dist = vp._camera.state.distance
        result = vp.frame_paths([])
        assert result is False
        assert vp._camera.state.target == initial_target
        assert vp._camera.state.distance == initial_dist

    def test_no_adapter_returns_false_with_default_focus(self):
        vp = self._make_viewport()
        result = vp.frame_paths(["/Sphere"])
        assert result is False
        assert vp._camera.state.target == [0.0, 0.0, 0.0]
        assert vp._camera.state.distance == 5.0

    def test_provider_returning_none_returns_false_with_default_focus(self):
        vp = self._make_viewport()
        vp._stage_adapter_provider = lambda: None
        result = vp.frame_paths(["/Sphere"])
        assert result is False
        assert vp._camera.state.target == [0.0, 0.0, 0.0]
        assert vp._camera.state.distance == 5.0

    def test_adapter_returns_none_returns_false_with_default_focus(self):
        vp = self._make_viewport()

        class _FakeAdapterReturnsNone:
            def compute_world_aabb(self, paths):
                return None

        vp._stage_adapter_provider = lambda: _FakeAdapterReturnsNone()
        result = vp.frame_paths(["/anything"])
        assert result is False
        assert vp._camera.state.target == [0.0, 0.0, 0.0]
        assert vp._camera.state.distance == 5.0

    def test_adapter_raises_returns_false_with_default_focus(self):
        vp = self._make_viewport()

        class _FakeAdapterRaises:
            def compute_world_aabb(self, paths):
                raise RuntimeError("adapter exploded")

        vp._stage_adapter_provider = lambda: _FakeAdapterRaises()
        result = vp.frame_paths(["/anything"])
        assert result is False
        assert vp._camera.state.target == [0.0, 0.0, 0.0]
        assert vp._camera.state.distance == 5.0

    def test_adapter_returns_real_bounds_returns_true_and_frames(self):
        vp = self._make_viewport()

        class _FakeAdapterRealBounds:
            def compute_world_aabb(self, paths):
                return ((-2.0, -2.0, -2.0), (2.0, 2.0, 2.0))

        vp._stage_adapter_provider = lambda: _FakeAdapterRealBounds()
        result = vp.frame_paths(["/sphere"])
        assert result is True
        assert vp._camera.state.target == [0.0, 0.0, 0.0]
        # 4-unit cube → max-extent 4 → distance 4*2 = 8.0
        assert vp._camera.state.distance == 8.0

    def test_adapter_returns_offset_bounds_returns_true_and_centers(self):
        """Center is the bounds midpoint, not always origin."""
        vp = self._make_viewport()

        class _FakeAdapterOffsetBounds:
            def compute_world_aabb(self, paths):
                return ((10.0, 10.0, 10.0), (12.0, 12.0, 12.0))

        vp._stage_adapter_provider = lambda: _FakeAdapterOffsetBounds()
        result = vp.frame_paths(["/cube"])
        assert result is True
        assert vp._camera.state.target == [11.0, 11.0, 11.0]
        # 2-unit cube → max-extent 2 → distance 2*2 = 4.0
        assert vp._camera.state.distance == 4.0

    def test_usd_translated_prim_bounds_center_camera_on_world_position(self):
        """Regression: F-frame must use transformed USD bounds, not local extent."""
        pxr = pytest.importorskip("pxr", reason="pxr not available")
        Usd, UsdGeom = pxr.Usd, pxr.UsdGeom
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter

        stage = Usd.Stage.CreateInMemory()
        sphere = UsdGeom.Sphere.Define(stage, "/World/Sphere")
        sphere.GetRadiusAttr().Set(0.8)
        sphere.AddTranslateOp().Set((1.5, 0.0, 0.0))

        vp = self._make_viewport()
        adapter = UsdStageAdapter(stage)
        vp._stage_adapter_provider = lambda: adapter

        result = vp.frame_paths(["/World/Sphere"])

        assert result is True
        assert vp._camera.state.target == [1.5, 0.0, 0.0]
        assert vp._camera.state.distance == pytest.approx(3.2)


class TestComputeWorldBboxContract:
    """Step 17 review correction: ``_compute_world_bbox`` is no-throw
    against adapter failures and returns ``None`` for any failure case.
    """

    def _make_viewport(self):
        from ovwidgets.viewport.viewport_widget import ViewportWidget
        vp = ViewportWidget.__new__(ViewportWidget)
        vp._stage_adapter_provider = None
        return vp

    def test_no_provider_returns_none(self):
        vp = self._make_viewport()
        assert vp._compute_world_bbox("/anything") is None

    def test_provider_returning_none_returns_none(self):
        vp = self._make_viewport()
        vp._stage_adapter_provider = lambda: None
        assert vp._compute_world_bbox("/anything") is None

    def test_adapter_returns_none_returns_none(self):
        vp = self._make_viewport()

        class _FakeAdapterReturnsNone:
            def compute_prim_world_aabb_with_extent_fallback(self, path):
                return None

        vp._stage_adapter_provider = lambda: _FakeAdapterReturnsNone()
        assert vp._compute_world_bbox("/anything") is None

    def test_adapter_raises_returns_none(self):
        vp = self._make_viewport()

        class _FakeAdapterRaises:
            def compute_prim_world_aabb_with_extent_fallback(self, path):
                raise RuntimeError("adapter exploded")

        vp._stage_adapter_provider = lambda: _FakeAdapterRaises()
        assert vp._compute_world_bbox("/anything") is None

    def test_adapter_returns_real_bounds_passes_through(self):
        vp = self._make_viewport()

        class _FakeAdapterRealBounds:
            def compute_prim_world_aabb_with_extent_fallback(self, path):
                return ((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))

        vp._stage_adapter_provider = lambda: _FakeAdapterRealBounds()
        bounds = vp._compute_world_bbox("/sphere")
        assert bounds == ((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))


class TestRadiusRecomputationBackstop:
    """Step 17 QA backstop: the F-frame visual sub-action of
    pre-planning §10.3 scenario 5 is blocked by the headless
    ``omni.ui.testing.press_key`` delivery limitation. This automated
    test backstops the same behavioral contract: when the user edits a
    Sphere's ``radius``, the next viewport AABB query must reflect the
    new extent.

    The chain exercised end-to-end:
      Stage edit → ``UsdGeom.Boundable.ComputeExtentFromPlugins`` →
      ``UsdStageAdapter.compute_prim_world_aabb_with_extent_fallback`` →
      ``ViewportWidget._compute_world_bbox`` → ``ViewportWidget.frame_paths``.
    """

    def test_sphere_radius_change_updates_viewport_bbox(self):
        pxr = pytest.importorskip("pxr", reason="pxr not available")
        Usd, UsdGeom = pxr.Usd, pxr.UsdGeom
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter

        from ovwidgets.viewport.viewport_widget import ViewportWidget

        stage = Usd.Stage.CreateInMemory()
        sphere = UsdGeom.Sphere.Define(stage, "/World/Sphere")
        sphere.GetRadiusAttr().Set(1.0)

        adapter = UsdStageAdapter(stage)
        vp = ViewportWidget.__new__(ViewportWidget)
        vp._stage_adapter_provider = lambda: adapter

        # Viewport bbox path: _compute_world_bbox calls the adapter method.
        # At radius 1 the unit-sphere bbox is ±1.
        bounds_r1 = vp._compute_world_bbox("/World/Sphere")
        assert bounds_r1 is not None
        (min_r1, max_r1) = bounds_r1
        assert min_r1 == (-1.0, -1.0, -1.0)
        assert max_r1 == (1.0, 1.0, 1.0)

        # User edits radius (drag-edit on the Property panel field, or
        # direct attribute Set in this automated path). The viewport bbox
        # must reflect the new size on the next query. This is exactly
        # what the F-frame visual scenario should verify, but cannot in
        # headless because press_key doesn't dispatch.
        sphere.GetRadiusAttr().Set(3.0)

        bounds_r3 = vp._compute_world_bbox("/World/Sphere")
        assert bounds_r3 is not None
        (min_r3, max_r3) = bounds_r3
        assert min_r3 == (-3.0, -3.0, -3.0)
        assert max_r3 == (3.0, 3.0, 3.0)

        # And frame_paths consumes the same updated bound through
        # compute_world_aabb (which uses the cached ComputeExtent path
        # under the hood). After the radius edit, the framing distance
        # must scale up.
        from ovwidgets.viewport.camera_controller import CameraController
        vp._camera = CameraController()
        result = vp.frame_paths(["/World/Sphere"])
        assert result is True
        # 6-unit cube (radius 3 sphere) → max-extent 6 → distance 12.0.
        assert vp._camera.state.distance == 12.0


class TestBeginRenameSelected:
    """Tests for StageWidget.begin_rename_selected()."""

    def test_no_selection_does_nothing(self):
        from ovwidgets.stage.stage_widget import StageWidget
        sw = StageWidget.__new__(StageWidget)
        sw._model = MagicMock()
        sw._model._selected_items = []
        sw._rename_controller = MagicMock()
        sw.begin_rename_selected()
        sw._rename_controller.request_rename_f2.assert_not_called()

    def test_calls_request_rename_f2_on_first_item(self):
        from ovwidgets.stage.stage_widget import StageWidget
        sw = StageWidget.__new__(StageWidget)
        sw._model = MagicMock()
        item = MagicMock()
        sw._model._selected_items = [item]
        sw._rename_controller = MagicMock()
        sw.begin_rename_selected()
        sw._rename_controller.request_rename_f2.assert_called_once_with(item)

    def test_no_rename_controller_does_not_raise(self):
        from ovwidgets.stage.stage_widget import StageWidget
        sw = StageWidget.__new__(StageWidget)
        sw._model = MagicMock()
        item = MagicMock()
        sw._model._selected_items = [item]
        sw._rename_controller = None
        sw.begin_rename_selected()  # should not raise
