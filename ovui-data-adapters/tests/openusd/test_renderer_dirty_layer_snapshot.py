# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovrtx root loading must render the composed live layer, not the disk file.

Regression coverage for the real-user reopen desync: hide a prim, replace the
document (File > New), reopen the same file (Recent Files). ``Usd.Stage.Open``
returns the still-dirty cached root layer, so USD, the Stage Browser eye, and
the hidden-count footer all report the prim invisible — but ``load_stage``
handed ovrtx ``root_layer.realPath`` and the freshly attached renderer drew
the stale on-disk state until the next visibility edit. A dirty file-backed
root layer must always reach ovrtx through a live-layer snapshot; a clean
layer must keep loading from its real path so relative asset paths retain
their resolver context.
"""

from __future__ import annotations

import glob as _glob
import os
import tempfile as _tempfile

import pytest

pxr = pytest.importorskip("pxr")
from pxr import Sdf, Usd, UsdGeom  # noqa: E402

from ovui_data_adapters.openusd.renderer_adapter import (  # noqa: E402
    OvRtxRendererAdapter,
)


def _live_snapshot_files() -> set:
    """Every live-root snapshot file currently in the temp dir.

    Covers BOTH the visible ``ovui_widgets_live_*`` prefix (tempdir
    fallback) and the dot-prefixed ``.ovui_widgets_live_*`` prefix (written
    beside a writable root). A leading-dot file is not matched by a ``*``
    glob, so both patterns are enumerated explicitly.
    """
    tmp = _tempfile.gettempdir()
    return set(
        _glob.glob(os.path.join(tmp, "*ovui_widgets_live_*"))
    ) | set(
        _glob.glob(os.path.join(tmp, ".ovui_widgets_live_*"))
    )


@pytest.fixture(autouse=True)
def _no_snapshot_residue():
    """Guarantee ZERO net live-root snapshot residue from every test.

    These tests build ``__new__``-based adapters and call ``load_stage`` on
    dirty stages, each of which writes a relocated snapshot to the temp dir.
    A single-load test that never reaches a second load or ``shutdown``
    would otherwise orphan its owned snapshot (Codex finding 7). This
    fixture reclaims any snapshot file a test created but did not itself
    tear down, so the whole suite leaves zero net residue. The teardown
    contract of production code is verified explicitly and independently by
    ``TestCleanupFaultRecovery`` and
    ``TestNativeTransitionAtomicity``/``TestCompleteStateTransaction`` (which
    drive real ``shutdown``/``_remove_ovrtx_layers`` and assert the files
    are gone) — this fixture is only test-artifact hygiene.
    """
    before = _live_snapshot_files()
    yield
    for path in _live_snapshot_files() - before:
        try:
            os.unlink(path)
        except OSError:
            pass

_SCENE = """#usda 1.0
(
    defaultPrim = "World"
    upAxis = "Y"
)

def Xform "World"
{
    def Sphere "Sphere"
    {
        double radius = 0.8
    }
}
"""


class _RecordingRenderer:
    """Minimal ovrtx stand-in: records how the root scene is opened."""

    def __init__(self) -> None:
        self.opened_paths: list[str] = []

    def open_usd(self, path):
        self.opened_paths.append(str(path))
        return object()

    def remove_usd(self, handle):  # pragma: no cover - teardown path
        return None


def _make_adapter(renderer: _RecordingRenderer) -> OvRtxRendererAdapter:
    """Build the adapter without ovrtx, keeping the load-path logic real.

    ``load_stage``'s path-resolution block, ``_root_layer_has_session_
    scaffolding``, and ``_export_live_root_layer_snapshot`` stay genuine;
    only the constructor's ovrtx probe and the post-resolution ovrtx/session
    plumbing are replaced with inert recorders.
    """

    adapter = object.__new__(OvRtxRendererAdapter)
    adapter._renderer = renderer
    adapter._stage = None
    adapter._usd_handle = None
    adapter._session_handle = None
    adapter._live_resync_handles = []
    adapter._owned_tmp_path = None
    adapter._last_resolution = (64, 64)
    adapter._pending_resolution = (64, 64)
    adapter._release_retained_output = lambda: None
    adapter._dispatch_pending_pick_misses = lambda: None
    adapter._mark_selection_outline_state_stale = lambda **kwargs: None
    adapter._uses_owned_render_product = lambda: False
    adapter._author_owned_session_render_product_resolution = lambda res: None
    adapter._session_render_product_setting_lines = lambda: ()
    adapter._remove_ovrtx_layers = lambda: None
    adapter._reset_render_timing_state = lambda: None
    adapter._open_ovrtx_root = lambda path, root_layer_content=None: (
        renderer.open_usd(path) if path is not None else object()
    )
    adapter._add_ovrtx_session_layer = lambda usda: object()
    return adapter


def _write_scene(tmp_path, name: str) -> str:
    scene = tmp_path / name
    scene.write_text(_SCENE, encoding="utf-8")
    return str(scene)


def _snapshot_text(path: str) -> str:
    layer = Sdf.Layer.FindOrOpen(path)
    assert layer is not None, f"snapshot must be a readable layer: {path}"
    return layer.ExportToString()


class TestDirtyRootLayerSnapshot:
    def test_dirty_file_backed_stage_loads_live_snapshot_not_disk_file(
        self, tmp_path
    ) -> None:
        scene_path = _write_scene(tmp_path, "dirty_stage_object.usda")
        stage = Usd.Stage.Open(scene_path)
        UsdGeom.Imageable(
            stage.GetPrimAtPath("/World/Sphere")
        ).GetVisibilityAttr().Set(UsdGeom.Tokens.invisible)
        assert stage.GetRootLayer().dirty

        renderer = _RecordingRenderer()
        adapter = _make_adapter(renderer)
        adapter.load_stage(stage)

        assert len(renderer.opened_paths) == 1
        opened = renderer.opened_paths[0]
        real_path = stage.GetRootLayer().realPath
        assert os.path.abspath(opened) != os.path.abspath(real_path), (
            "a dirty root layer must not be loaded from the stale disk file"
        )
        assert "invisible" in _snapshot_text(opened), (
            "the live snapshot must carry the unsaved visibility opinion"
        )
        # The stale file on disk genuinely lacks the opinion — the snapshot
        # is the only truthful source for the renderer.
        assert "invisible" not in open(real_path, encoding="utf-8").read()

    def test_clean_file_backed_stage_keeps_real_path(self, tmp_path) -> None:
        scene_path = _write_scene(tmp_path, "clean_stage_object.usda")
        stage = Usd.Stage.Open(scene_path)
        assert not stage.GetRootLayer().dirty

        renderer = _RecordingRenderer()
        adapter = _make_adapter(renderer)
        adapter.load_stage(stage)

        assert len(renderer.opened_paths) == 1
        assert os.path.abspath(renderer.opened_paths[0]) == os.path.abspath(
            stage.GetRootLayer().realPath
        ), "clean file-backed stages keep resolver-context file loading"

    def test_reopen_by_path_with_cached_dirty_layer_loads_live_snapshot(
        self, tmp_path
    ) -> None:
        """The exact user sequence: edit, replace document, reopen by path."""

        scene_path = _write_scene(tmp_path, "reopen_by_path.usda")
        first_open = Usd.Stage.Open(scene_path)
        UsdGeom.Imageable(
            first_open.GetPrimAtPath("/World/Sphere")
        ).GetVisibilityAttr().Set(UsdGeom.Tokens.invisible)
        # The document is "replaced", but the dirty root layer stays
        # registered in the Sdf layer cache because application components
        # (undo history, document bookkeeping) still reference the outgoing
        # document — exactly the File > New followed by Recent Files
        # sequence. A plain Sdf.Layer python handle is weak (it expires with
        # the stage), so the retained document reference is what genuinely
        # models the application here.
        retained_document = first_open  # noqa: F841 — keeps the layer cached

        renderer = _RecordingRenderer()
        adapter = _make_adapter(renderer)
        adapter.load_stage(scene_path)

        assert len(renderer.opened_paths) == 1
        opened = renderer.opened_paths[0]
        assert os.path.abspath(opened) != os.path.abspath(scene_path), (
            "reopening a cached dirty layer by path must not hand ovrtx "
            "the stale disk file"
        )
        assert "invisible" in _snapshot_text(opened)
        # And the adapter's own stage view composes the same opinion the
        # renderer received — no split-brain between USD and viewport.
        vis = (
            UsdGeom.Imageable(
                adapter._stage.GetPrimAtPath("/World/Sphere")
            )
            .GetVisibilityAttr()
            .Get()
        )
        assert vis == UsdGeom.Tokens.invisible

    def test_snapshot_is_owned_and_replaced_on_next_load(self, tmp_path) -> None:
        """Dirty-layer snapshots must not leak across successive loads."""

        scene_path = _write_scene(tmp_path, "owned_snapshot.usda")
        stage = Usd.Stage.Open(scene_path)
        UsdGeom.Imageable(
            stage.GetPrimAtPath("/World/Sphere")
        ).GetVisibilityAttr().Set(UsdGeom.Tokens.invisible)

        renderer = _RecordingRenderer()
        adapter = _make_adapter(renderer)
        adapter.load_stage(stage)
        first_snapshot = renderer.opened_paths[0]
        assert adapter._owned_tmp_path == first_snapshot
        assert os.path.exists(first_snapshot)

        adapter.load_stage(stage)
        assert not os.path.exists(first_snapshot), (
            "the previous owned snapshot must be dropped by the next load"
        )


_ORIGINAL_MKSTEMP = _tempfile.mkstemp
_FORCED_RELOCATION_DIR: str | None = None


def _force_snapshot_relocation(path) -> None:
    """Make same-directory snapshot creation fail on every supported OS.

    A read-only directory is a suitable real-world trigger on POSIX, but
    ``os.chmod(..., 0o555)`` does not prevent file creation on Windows.  Patch
    the exact ``tempfile.mkstemp(dir=<root directory>)`` boundary instead so
    the production fallback and path-anchoring code run deterministically.
    Calls without that directory still use the real ``mkstemp`` and therefore
    create the genuine relocated snapshot that each test inspects.
    """

    global _FORCED_RELOCATION_DIR
    assert _FORCED_RELOCATION_DIR is None, "snapshot relocation is already forced"
    forced_dir = os.path.normcase(os.path.realpath(os.fspath(path)))
    _FORCED_RELOCATION_DIR = forced_dir

    def _relocating_mkstemp(*args, **kwargs):
        candidate = kwargs.get("dir")
        if candidate is not None:
            candidate_dir = os.path.normcase(
                os.path.realpath(os.fspath(candidate))
            )
            if candidate_dir == forced_dir:
                raise PermissionError(
                    "forced same-directory snapshot creation failure"
                )
        return _ORIGINAL_MKSTEMP(*args, **kwargs)

    _tempfile.mkstemp = _relocating_mkstemp


def _restore_snapshot_creation(path) -> None:
    global _FORCED_RELOCATION_DIR
    expected_dir = os.path.normcase(os.path.realpath(os.fspath(path)))
    assert _FORCED_RELOCATION_DIR == expected_dir
    _tempfile.mkstemp = _ORIGINAL_MKSTEMP
    _FORCED_RELOCATION_DIR = None


def _write(path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


_CHILD = """#usda 1.0
(
    defaultPrim = "Child"
)

def Xform "Child"
{
    def Cube "Geo"
    {
        double size = 1.0
    }
}
"""


class TestSnapshotCompositionFidelity:
    """A dirty-root snapshot must compose exactly what the live stage does.

    Reviewer finding: when the snapshot cannot be created beside the
    original root (non-writable directory) and falls back elsewhere,
    relative composition arcs silently stopped resolving and ovrtx received
    an incomplete scene. These tests pin the guarantee for relative
    references, payloads, and sublayers under a non-writable anchor, keep
    the writable-anchor behavior intact, and require atomic truthful
    failure when a faithful snapshot cannot be produced.
    """

    def _dirty_scene(self, scene_dir, body: str, extra: dict | None = None):
        scene_dir.mkdir()
        for name, text in (extra or {}).items():
            _write(scene_dir / name, text)
        _write(scene_dir / "parent.usda", body)
        stage = Usd.Stage.Open(str(scene_dir / "parent.usda"))
        UsdGeom.Imageable(
            stage.GetPrimAtPath("/World/Sphere")
        ).GetVisibilityAttr().Set(UsdGeom.Tokens.invisible)
        assert stage.GetRootLayer().dirty
        return stage

    def _load_and_open_snapshot(self, stage):
        renderer = _RecordingRenderer()
        adapter = _make_adapter(renderer)
        adapter.load_stage(stage)
        assert len(renderer.opened_paths) == 1
        snap_path = renderer.opened_paths[0]
        snap_stage = Usd.Stage.Open(snap_path)
        assert snap_stage is not None
        return snap_path, snap_stage

    def test_nonwritable_anchor_preserves_relative_reference(self, tmp_path):
        scene_dir = tmp_path / "scene_ref"
        stage = self._dirty_scene(
            scene_dir,
            """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Sphere "Sphere"
    {
    }

    def Xform "Ref" (
        prepend references = @./child.usda@
    )
    {
    }
}
""",
            extra={"child.usda": _CHILD},
        )
        assert stage.GetPrimAtPath("/World/Ref/Geo").IsValid()
        _force_snapshot_relocation(scene_dir)
        try:
            snap_path, snap_stage = self._load_and_open_snapshot(stage)
        finally:
            _restore_snapshot_creation(scene_dir)
        assert snap_stage.GetPrimAtPath("/World/Ref/Geo").IsValid(), (
            "the fallback snapshot lost the relative reference arc"
        )
        vis = (
            UsdGeom.Imageable(snap_stage.GetPrimAtPath("/World/Sphere"))
            .GetVisibilityAttr()
            .Get()
        )
        assert vis == UsdGeom.Tokens.invisible

    def test_nonwritable_anchor_preserves_relative_payload(self, tmp_path):
        scene_dir = tmp_path / "scene_payload"
        stage = self._dirty_scene(
            scene_dir,
            """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Sphere "Sphere"
    {
    }

    def Xform "Pay" (
        prepend payload = @./child.usda@
    )
    {
    }
}
""",
            extra={"child.usda": _CHILD},
        )
        assert stage.GetPrimAtPath("/World/Pay/Geo").IsValid()
        _force_snapshot_relocation(scene_dir)
        try:
            snap_path, snap_stage = self._load_and_open_snapshot(stage)
        finally:
            _restore_snapshot_creation(scene_dir)
        assert snap_stage.GetPrimAtPath("/World/Pay/Geo").IsValid(), (
            "the fallback snapshot lost the relative payload arc"
        )

    def test_nonwritable_anchor_preserves_relative_sublayer(self, tmp_path):
        scene_dir = tmp_path / "scene_sublayer"
        stage = self._dirty_scene(
            scene_dir,
            """#usda 1.0
(
    defaultPrim = "World"
    subLayers = [
        @./sub.usda@
    ]
)

def Xform "World"
{
    def Sphere "Sphere"
    {
    }
}
""",
            extra={
                "sub.usda": (
                    "#usda 1.0\n\nover \"World\"\n{\n"
                    "    def Cube \"FromSub\"\n    {\n    }\n}\n"
                )
            },
        )
        assert stage.GetPrimAtPath("/World/FromSub").IsValid()
        _force_snapshot_relocation(scene_dir)
        try:
            snap_path, snap_stage = self._load_and_open_snapshot(stage)
        finally:
            _restore_snapshot_creation(scene_dir)
        assert snap_stage.GetPrimAtPath("/World/FromSub").IsValid(), (
            "the fallback snapshot lost the relative sublayer arc"
        )

    def test_writable_anchor_still_composes_relative_arcs(self, tmp_path):
        scene_dir = tmp_path / "scene_writable"
        stage = self._dirty_scene(
            scene_dir,
            """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Sphere "Sphere"
    {
    }

    def Xform "Ref" (
        prepend references = @./child.usda@
    )
    {
    }
}
""",
            extra={"child.usda": _CHILD},
        )
        snap_path, snap_stage = self._load_and_open_snapshot(stage)
        assert snap_stage.GetPrimAtPath("/World/Ref/Geo").IsValid()

    def test_unfaithful_snapshot_fails_atomically(self, tmp_path, monkeypatch):
        """If a faithful snapshot cannot be produced, loading must fail
        truthfully before any ovrtx root is opened, leak no snapshot file,
        and leave prior renderer handles untouched."""

        scene_dir = tmp_path / "scene_atomic"
        stage = self._dirty_scene(
            scene_dir,
            """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Sphere "Sphere"
    {
    }

    def Xform "Ref" (
        prepend references = @./child.usda@
    )
    {
    }
}
""",
            extra={"child.usda": _CHILD},
        )
        renderer = _RecordingRenderer()
        adapter = _make_adapter(renderer)
        sentinel = object()
        adapter._usd_handle = sentinel
        monkeypatch.setattr(
            OvRtxRendererAdapter,
            "_anchor_asset_path",
            lambda self, layer, asset_path: (_ for _ in ()).throw(
                RuntimeError("unanchorable asset path")
            ),
        )
        _force_snapshot_relocation(scene_dir)
        try:
            with pytest.raises(RuntimeError, match="unanchorable"):
                adapter.load_stage(stage)
        finally:
            _restore_snapshot_creation(scene_dir)
        assert renderer.opened_paths == [], (
            "no ovrtx root may be opened from an unfaithful snapshot"
        )
        assert adapter._usd_handle is sentinel, (
            "the previous renderer scene must remain untouched"
        )
        owned = adapter._owned_tmp_path
        assert owned is None or not os.path.exists(owned), (
            "a failed snapshot must not leak its temp file"
        )


def _make_tracking_adapter(renderer: _RecordingRenderer) -> OvRtxRendererAdapter:
    """Like ``_make_adapter`` but records ownership-mutation calls."""

    adapter = _make_adapter(renderer)
    adapter._released_outputs = []
    adapter._dispatched_pick_misses = []
    adapter._release_retained_output = (
        lambda: adapter._released_outputs.append(1)
    )
    adapter._dispatch_pending_pick_misses = (
        lambda: adapter._dispatched_pick_misses.append(1)
    )
    return adapter


_REF_SCENE = """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Sphere "Sphere"
    {
    }

    def Xform "Ref" (
        prepend references = @./child.usda@
    )
    {
    }
}
"""


class TestAtomicPreparationOwnership:
    """Failed prospective loads must not mutate current ownership.

    Reviewer finding: preparation of a prospective dirty-stage load released
    the retained output, dispatched pending picks, deleted the previous
    owned snapshot, and reassigned ``_stage`` BEFORE the prospective inputs
    were proven usable — a failure left the adapter split-brained (old
    renderer scene, new stage identity, old resources gone). Preparation is
    now side-effect-free; commit happens only after success; cleanup covers
    every ``BaseException``.
    """

    def _load_old_dirty_scene(self, tmp_path):
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        _write(old_dir / "old.usda", _SCENE)
        stage = Usd.Stage.Open(str(old_dir / "old.usda"))
        UsdGeom.Imageable(
            stage.GetPrimAtPath("/World/Sphere")
        ).GetVisibilityAttr().Set(UsdGeom.Tokens.invisible)
        renderer = _RecordingRenderer()
        adapter = _make_tracking_adapter(renderer)
        _force_snapshot_relocation(old_dir)
        try:
            adapter.load_stage(stage)
        finally:
            _restore_snapshot_creation(old_dir)
        assert adapter._owned_tmp_path and os.path.exists(adapter._owned_tmp_path)
        adapter._released_outputs.clear()
        adapter._dispatched_pick_misses.clear()
        return adapter, renderer, stage

    def _prospective_dirty_scene(self, tmp_path):
        new_dir = tmp_path / "new"
        new_dir.mkdir()
        _write(new_dir / "child.usda", _CHILD)
        _write(new_dir / "new.usda", _REF_SCENE)
        stage = Usd.Stage.Open(str(new_dir / "new.usda"))
        UsdGeom.Imageable(
            stage.GetPrimAtPath("/World/Sphere")
        ).GetVisibilityAttr().Set(UsdGeom.Tokens.invisible)
        return new_dir, stage

    def _assert_old_state_intact(self, adapter, renderer, old_stage,
                                 old_snapshot, old_handle, old_open_count):
        assert adapter._stage is old_stage, (
            "a failed preparation must not reassign the current stage"
        )
        assert adapter._owned_tmp_path == old_snapshot
        assert os.path.exists(old_snapshot), (
            "the previous owned snapshot must survive a failed preparation"
        )
        assert adapter._usd_handle is old_handle, (
            "the live renderer scene handle must stay untouched"
        )
        assert adapter._released_outputs == [], (
            "retained output must not be released during failed preparation"
        )
        assert adapter._dispatched_pick_misses == [], (
            "pending picks must not be dispatched during failed preparation"
        )
        assert len(renderer.opened_paths) == old_open_count, (
            "no new ovrtx root may be opened"
        )

    def test_failed_preparation_preserves_all_current_ownership(
        self, tmp_path
    ) -> None:
        adapter, renderer, old_stage = self._load_old_dirty_scene(tmp_path)
        old_snapshot = adapter._owned_tmp_path
        old_handle = adapter._usd_handle
        new_dir, new_stage = self._prospective_dirty_scene(tmp_path)

        adapter._anchor_asset_path = lambda layer, p: (_ for _ in ()).throw(
            RuntimeError("prospective preparation failure")
        )
        _force_snapshot_relocation(new_dir)
        try:
            with pytest.raises(RuntimeError, match="prospective preparation"):
                adapter.load_stage(new_stage)
        finally:
            _restore_snapshot_creation(new_dir)
        self._assert_old_state_intact(
            adapter, renderer, old_stage, old_snapshot, old_handle, 1
        )

    def test_keyboardinterrupt_during_preparation_leaks_nothing(
        self, tmp_path
    ) -> None:
        adapter, renderer, old_stage = self._load_old_dirty_scene(tmp_path)
        old_snapshot = adapter._owned_tmp_path
        old_handle = adapter._usd_handle
        new_dir, new_stage = self._prospective_dirty_scene(tmp_path)

        import glob as _glob
        import tempfile as _tempfile

        def _live_snapshots():
            tmp = _tempfile.gettempdir()
            return (
                set(_glob.glob(os.path.join(tmp, "*ovui_widgets_live_*")))
                | set(_glob.glob(os.path.join(tmp, ".ovui_widgets_live_*")))
                | set(_glob.glob(str(new_dir / "*ovui_widgets_live_*")))
                | set(_glob.glob(str(new_dir / ".ovui_widgets_live_*")))
            )

        before = _live_snapshots()
        adapter._anchor_asset_path = lambda layer, p: (_ for _ in ()).throw(
            KeyboardInterrupt()
        )
        _force_snapshot_relocation(new_dir)
        try:
            with pytest.raises(KeyboardInterrupt):
                adapter.load_stage(new_stage)
        finally:
            _restore_snapshot_creation(new_dir)
        assert _live_snapshots() - before == set(), (
            "a BaseException during preparation must not leak a partial "
            "snapshot"
        )
        self._assert_old_state_intact(
            adapter, renderer, old_stage, old_snapshot, old_handle, 1
        )

    def test_failed_stage_open_by_path_preserves_ownership(
        self, tmp_path
    ) -> None:
        adapter, renderer, old_stage = self._load_old_dirty_scene(tmp_path)
        old_snapshot = adapter._owned_tmp_path
        old_handle = adapter._usd_handle

        with pytest.raises(Exception):
            adapter.load_stage(str(tmp_path / "does_not_exist.usda"))
        self._assert_old_state_intact(
            adapter, renderer, old_stage, old_snapshot, old_handle, 1
        )


_URI_SCENE = """#usda 1.0
(
    defaultPrim = "World"
    subLayers = [
        @./sub.usda@
    ]
)

def Xform "World"
{
    def Sphere "Sphere"
    {
    }

    def Xform "HttpsRef" (
        prepend references = @https://assets.example.test/a.usda@
    )
    {
    }

    def Xform "OmniRef" (
        prepend references = @omniverse://server/path/b.usda@
    )
    {
    }

    def Xform "FileUriPay" (
        prepend payload = @file:///abs/c.usda@
    )
    {
    }

    def Xform "AbsRef" (
        prepend references = @/abs/d.usda@
    )
    {
    }

    def Xform "WeirdScheme" (
        prepend references = @x-custom+v1.0://weird/path.usda@
    )
    {
    }

    def Xform "RelRef" (
        prepend references = @./child.usda@
    )
    {
    }
}
"""


class TestUriIdentifierPreservation:
    """Relocated snapshots must not corrupt URI/resolver identifiers.

    Reviewer finding: ``ComputeAbsolutePath`` "normalized"
    ``https://assets.example.test/a.usda`` into
    ``https:/assets.example.test/a.usda``. Already-absolute URI and
    resolver identifiers must be preserved byte-for-byte; only genuinely
    relative paths are anchored.
    """

    def _snapshot_asset_paths(self, tmp_path):
        import re as _re

        scene_dir = tmp_path / "uri_scene"
        scene_dir.mkdir()
        _write(scene_dir / "child.usda", _CHILD)
        _write(
            scene_dir / "sub.usda",
            "#usda 1.0\n\nover \"World\"\n{\n    def Cube \"FromSub\"\n"
            "    {\n    }\n}\n",
        )
        _write(scene_dir / "parent.usda", _URI_SCENE)
        stage = Usd.Stage.Open(str(scene_dir / "parent.usda"))
        UsdGeom.Imageable(
            stage.GetPrimAtPath("/World/Sphere")
        ).GetVisibilityAttr().Set(UsdGeom.Tokens.invisible)
        original_text = stage.GetRootLayer().ExportToString()

        renderer = _RecordingRenderer()
        adapter = _make_adapter(renderer)
        _force_snapshot_relocation(scene_dir)
        try:
            adapter.load_stage(stage)
        finally:
            _restore_snapshot_creation(scene_dir)
        snap_path = renderer.opened_paths[0]
        snap_text = open(snap_path, encoding="utf-8").read()
        arcs = dict(
            zip(
                _re.findall(r'def Xform "(\w+)"', snap_text),
                [None] * 100,
            )
        )
        found = {}
        for prim, ident in _re.findall(
            r'def Xform "(\w+)" \(\s*prepend (?:references|payload) = @([^@]*)@',
            snap_text,
        ):
            found[prim] = ident
        sublayers = _re.search(r"subLayers = \[\s*@([^@]*)@", snap_text)
        return stage, original_text, scene_dir, found, sublayers, snap_path

    def test_uri_and_absolute_identifiers_preserved_byte_for_byte(
        self, tmp_path
    ) -> None:
        stage, original_text, scene_dir, found, sublayers, snap_path = (
            self._snapshot_asset_paths(tmp_path)
        )
        assert found["HttpsRef"] == "https://assets.example.test/a.usda"
        assert found["OmniRef"] == "omniverse://server/path/b.usda"
        assert found["FileUriPay"] == "file:///abs/c.usda"
        assert found["AbsRef"] == "/abs/d.usda"
        assert found["WeirdScheme"] == "x-custom+v1.0://weird/path.usda"

    def test_relative_arcs_still_anchor_and_compose(self, tmp_path) -> None:
        stage, original_text, scene_dir, found, sublayers, snap_path = (
            self._snapshot_asset_paths(tmp_path)
        )
        rel = found["RelRef"]
        assert os.path.isabs(rel), "genuinely relative refs must be anchored"
        expected_rel = stage.GetRootLayer().ComputeAbsolutePath("./child.usda")
        assert rel == expected_rel
        assert sublayers is not None and os.path.isabs(sublayers.group(1)), (
            "relative sublayers must be anchored too"
        )
        snap_stage = Usd.Stage.Open(snap_path)
        assert snap_stage.GetPrimAtPath("/World/RelRef/Geo").IsValid()
        assert snap_stage.GetPrimAtPath("/World/FromSub").IsValid()

    def test_live_layer_is_never_mutated_by_snapshotting(self, tmp_path) -> None:
        stage, original_text, scene_dir, found, sublayers, snap_path = (
            self._snapshot_asset_paths(tmp_path)
        )
        assert stage.GetRootLayer().ExportToString() == original_text, (
            "snapshot rewriting must operate on a copy, never the live layer"
        )


class _SingleRootFakeOvrtx:
    """Single-root native API shape (like real ovrtx): ``open_usd`` tears
    down the current root, session, and overlays; session layers return
    handles. Only the renderer OBJECT is fake — every adapter method under
    test (open/add/remove/rollback/reload) is the real implementation."""

    def __init__(self) -> None:
        self.current_root = None
        self.layers: dict = {}
        self._next = 0
        self.fail_unless = None
        self.raise_on_session: BaseException | None = None

    def open_usd(self, path):
        if self.fail_unless is not None and str(path) != str(self.fail_unless):
            raise RuntimeError(f"native root open failed: {path}")
        self.current_root = str(path)
        self.layers.clear()
        return None

    def add_usd_reference_from_string(self, usda, prefix):
        if self.raise_on_session is not None:
            exc = self.raise_on_session
            self.raise_on_session = None
            raise exc
        self._next += 1
        handle = f"h{self._next}"
        self.layers[handle] = prefix
        return handle

    def remove_usd(self, handle):
        self.layers.pop(handle, None)


class _HandleFakeOvrtx:
    """Handle-based native API shape (``add_usd``): layers compose side by
    side; nothing is implicitly destroyed."""

    def __init__(self) -> None:
        self.layers: dict = {}
        self._next = 0
        self.fail_root_adds_except: str | None = None

    def add_usd(self, path):
        if (
            self.fail_root_adds_except is not None
            and str(path) != str(self.fail_root_adds_except)
        ):
            raise RuntimeError(f"native root add failed: {path}")
        self._next += 1
        handle = f"r{self._next}"
        self.layers[handle] = ("root", str(path))
        return handle

    def add_usd_reference_from_string(self, usda, prefix):
        self._next += 1
        handle = f"s{self._next}"
        self.layers[handle] = ("session", prefix)
        return handle

    def remove_usd(self, handle):
        self.layers.pop(handle, None)


def _make_native_adapter(renderer) -> OvRtxRendererAdapter:
    """Adapter with the FULL real load/teardown/rollback path.

    Unlike ``_make_adapter``, no destructive method is stubbed; only the
    constructor's ovrtx probe is bypassed and the instance attributes the
    real methods read are initialized (as ``__init__`` would)."""

    import collections

    a = object.__new__(OvRtxRendererAdapter)
    a._renderer = renderer
    a._stage = None
    a._usd_handle = None
    a._session_handle = None
    a._live_resync_handles = []
    a._owned_tmp_path = None
    a._last_resolution = (64, 64)
    a._pending_resolution = (64, 64)
    a._last_render_product_resolution = None
    a._last_pushed_camera_intrinsics = None
    a._dt_clock = 0.0
    a._clock = lambda: 0.0
    a._last_big_delta_time = float("-inf")
    a._last_reinject_time = float("-inf")
    a._selected_paths = []
    a._selection_outline_previous_paths = set()
    a._selection_outline_styles_configured = False
    a._selection_outline_style_calls = 0
    a._selection_outline_attribute_writes = 0
    a._selection_outline_generation = 0
    a._selection_outline_last_write = {}
    a._in_flight_pick_queries = __import__("collections").deque()
    a._last_pick_path = None
    a._last_pick_world_point = None
    a._latest_point_cloud_frames = {}
    a._render_product_path = "/OvGearSession/Render/Viewport"
    a._default_render_product_path = "/OvGearSession/Render/Viewport"
    a._default_camera_path = "/OvGearSession/Cameras/Main"
    a._camera_path = "/OvGearSession/Cameras/Main"
    return a


class TestNativeTransitionAtomicity:
    """The whole load transition — including fallible NATIVE root/session
    installation — must be atomic for every Exception and BaseException.

    Reviewer finding: preparation was atomic but the commit phase mutated
    ownership (released output, drained picks, destroyed old native layers,
    dropped the old snapshot, swapped the stage) BEFORE the fallible native
    open/session calls; ``_reload_live_root_snapshot`` therefore converted a
    failed transition into a corrupted ``False``. These tests drive the REAL
    native-boundary methods against fake renderer objects of both API
    shapes."""

    def _dirty_scene(self, tmp_path, tag):
        d = tmp_path / tag
        d.mkdir()
        _write(d / f"{tag}.usda", _SCENE)
        stage = Usd.Stage.Open(str(d / f"{tag}.usda"))
        UsdGeom.Imageable(
            stage.GetPrimAtPath("/World/Sphere")
        ).GetVisibilityAttr().Set(UsdGeom.Tokens.invisible)
        _force_snapshot_relocation(d)
        return d, stage

    def _loaded(self, tmp_path, renderer, tag="old"):
        adapter = _make_native_adapter(renderer)
        d, stage = self._dirty_scene(tmp_path, tag)
        try:
            adapter.load_stage(stage)
        finally:
            _restore_snapshot_creation(d)
        adapter._in_flight_pick_queries.append(
            [1, "rect", "probe", lambda hits: None, None, None]
        )
        return adapter, stage

    def _state(self, adapter, renderer):
        return (
            adapter._stage,
            adapter._owned_tmp_path,
            os.path.exists(adapter._owned_tmp_path or ""),
            len(adapter._in_flight_pick_queries),
            getattr(renderer, "current_root", None),
            len(renderer.layers),
        )

    def test_single_root_open_failure_rolls_back_atomically(self, tmp_path):
        renderer = _SingleRootFakeOvrtx()
        adapter, old_stage = self._loaded(tmp_path, renderer)
        before = self._state(adapter, renderer)
        d_new, new_stage = self._dirty_scene(tmp_path, "new")
        renderer.fail_unless = renderer.current_root  # only old payload opens
        try:
            with pytest.raises(RuntimeError, match="native root open failed"):
                adapter.load_stage(new_stage)
        finally:
            _restore_snapshot_creation(d_new)
            renderer.fail_unless = None
        assert self._state(adapter, renderer) == before, (
            "a failed native root open must leave stage identity, owned "
            "snapshot, pending picks, and the restored native scene intact"
        )

    def test_single_root_session_keyboardinterrupt_rolls_back(self, tmp_path):
        renderer = _SingleRootFakeOvrtx()
        adapter, old_stage = self._loaded(tmp_path, renderer)
        before = self._state(adapter, renderer)
        d_new, new_stage = self._dirty_scene(tmp_path, "new")
        renderer.raise_on_session = KeyboardInterrupt()
        try:
            with pytest.raises(KeyboardInterrupt):
                adapter.load_stage(new_stage)
        finally:
            _restore_snapshot_creation(d_new)
        assert self._state(adapter, renderer) == before, (
            "a BaseException during native session setup must restore the "
            "previous native scene and leave every old resource intact"
        )

    def test_live_snapshot_reload_failure_is_truthful_not_corrupting(
        self, tmp_path
    ):
        renderer = _SingleRootFakeOvrtx()
        adapter, old_stage = self._loaded(tmp_path, renderer)
        before = self._state(adapter, renderer)
        old_handles = (adapter._usd_handle, adapter._session_handle)
        renderer.fail_unless = renderer.current_root
        assert adapter._reload_live_root_snapshot() is False
        renderer.fail_unless = None
        assert self._state(adapter, renderer) == before
        assert adapter._usd_handle == old_handles[0]
        assert adapter._session_handle is not None, (
            "a failed reload must not clear the session handle"
        )

    def test_handle_api_trial_never_destroys_old_scene(self, tmp_path):
        renderer = _HandleFakeOvrtx()
        adapter, old_stage = self._loaded(tmp_path, renderer)
        old_layers = dict(renderer.layers)
        before_picks = len(adapter._in_flight_pick_queries)
        d_new, new_stage = self._dirty_scene(tmp_path, "new")
        # The old root was itself added from a live snapshot; scope the
        # injected failure to NEW root adds by allowlisting the old payload.
        old_snapshot = adapter._owned_tmp_path
        renderer.fail_root_adds_except = old_snapshot
        try:
            with pytest.raises(RuntimeError, match="native root add failed"):
                adapter.load_stage(new_stage)
        finally:
            _restore_snapshot_creation(d_new)
            renderer.fail_root_adds_except = None
        assert dict(renderer.layers) == old_layers, (
            "the handle-API trial must not remove or replace any old layer "
            "on failure"
        )
        assert adapter._owned_tmp_path == old_snapshot
        assert os.path.exists(old_snapshot)
        assert len(adapter._in_flight_pick_queries) == before_picks

    def test_successful_transition_commits_once_and_releases_old(self, tmp_path):
        renderer = _HandleFakeOvrtx()
        adapter, old_stage = self._loaded(tmp_path, renderer)
        old_layer_handles = set(renderer.layers)
        old_snapshot = adapter._owned_tmp_path
        d_new, new_stage = self._dirty_scene(tmp_path, "new")
        try:
            adapter.load_stage(new_stage)
        finally:
            _restore_snapshot_creation(d_new)
        assert adapter._stage is new_stage
        assert not (set(renderer.layers) & old_layer_handles), (
            "old native layers must be released after a successful commit"
        )
        assert adapter._owned_tmp_path != old_snapshot
        assert not os.path.exists(old_snapshot), (
            "the old owned snapshot must be reclaimed on successful commit"
        )
        assert os.path.exists(adapter._owned_tmp_path)
        assert len(adapter._in_flight_pick_queries) == 0, (
            "pending picks drain as misses exactly once, at commit"
        )


class _DestructiveSingleRootOvrtx:
    """Real-ovrtx-shaped single-root double: ``open_usd`` implicitly tears
    down the current root, session, AND overlay layers; session/overlay
    layers are handle-based. Only the renderer object is a double — every
    adapter transition method under test is production code."""

    def __init__(self) -> None:
        self.current_root = None
        self.layers: dict = {}
        self._next = 0
        self.fail_open_unless = None
        self.raise_on_session: BaseException | None = None
        self.fail_remove_handles: set = set()
        self.open_count = 0
        self.fail_opens_from: int | None = None

    def open_usd(self, path):
        self.open_count += 1
        if self.fail_opens_from is not None and self.open_count >= self.fail_opens_from:
            raise RuntimeError(f"native root open failed: {path}")
        if self.fail_open_unless is not None and str(path) != str(
            self.fail_open_unless
        ):
            raise RuntimeError(f"native root open failed: {path}")
        self.current_root = str(path)
        self.layers.clear()
        return None

    def add_usd_reference_from_string(self, usda, prefix):
        if self.raise_on_session is not None:
            exc = self.raise_on_session
            self.raise_on_session = None
            raise exc
        self._next += 1
        handle = f"s{self._next}"
        self.layers[handle] = ("session", prefix)
        return handle

    def add_usd_layer(self, usda, path_prefix=None):
        self._next += 1
        handle = f"o{self._next}"
        self.layers[handle] = ("overlay", path_prefix)
        return handle

    def remove_usd(self, handle):
        if handle in self.fail_remove_handles:
            raise RuntimeError(f"native remove failed: {handle}")
        self.layers.pop(handle, None)


class _HandleApiOvrtxFull(_DestructiveSingleRootOvrtx):
    """Handle-based root API double (layers compose side by side)."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_add_root_unless = None

    open_usd = None  # type: ignore[assignment] — no single-root API

    def add_usd(self, path):
        if self.fail_add_root_unless is not None and str(path) != str(
            self.fail_add_root_unless
        ):
            raise RuntimeError(f"native root add failed: {path}")
        self._next += 1
        handle = f"r{self._next}"
        self.layers[handle] = ("root", str(path))
        return handle


def _rich_adapter(renderer):
    adapter = _make_native_adapter(renderer)
    adapter._latest_point_cloud_frames = {}
    adapter._scene_has_lights = False
    return adapter


class TestCompleteStateTransaction:
    """Complete-old-state-or-complete-new-state across the WHOLE operation.

    Fourth-review reproductions: (1) single-root trials destroyed overlays
    and outline bookkeeping before the prospective session was proven;
    (2) rollback double faults were silently swallowed while the adapter
    kept the old document identity over a rootless renderer; (3) a
    SystemExit while pending picks were drained left old+new layers mixed
    and leaked the prospective snapshot; (4) old-handle removal failures
    were swallowed and the replacement still reported success.
    """

    def _dirty_scene(self, tmp_path, tag):
        d = tmp_path / tag
        d.mkdir()
        _write(d / f"{tag}.usda", _SCENE)
        stage = Usd.Stage.Open(str(d / f"{tag}.usda"))
        UsdGeom.Imageable(
            stage.GetPrimAtPath("/World/Sphere")
        ).GetVisibilityAttr().Set(UsdGeom.Tokens.invisible)
        _force_snapshot_relocation(d)
        return d, stage

    def _loaded_rich(self, tmp_path, renderer, tag="old"):
        """Load a dirty stage, then populate overlays (via the REAL overlay
        sync), selection bookkeeping, and a live pending pick callback."""
        adapter = _rich_adapter(renderer)
        d, stage = self._dirty_scene(tmp_path, tag)
        try:
            adapter.load_stage(stage)
        finally:
            _restore_snapshot_creation(d)
        assert adapter._sync_ovrtx_root_snapshot_overlay_from_stage() is True
        adapter._selected_paths = ["/World/Sphere"]
        adapter._selection_outline_previous_paths = {"/World/Sphere"}
        fired: list = []
        adapter._in_flight_pick_queries.append(
            [1, "rect", "probe", lambda hits: fired.append(hits), None, None]
        )
        return adapter, stage, fired

    def _snapshot(self, adapter, renderer):
        return {
            "stage": adapter._stage,
            "owned_tmp": adapter._owned_tmp_path,
            "owned_exists": os.path.exists(adapter._owned_tmp_path or ""),
            "picks": len(adapter._in_flight_pick_queries),
            "selected": list(adapter._selected_paths),
            "root": renderer.current_root,
            "layer_types": sorted(t for t, _ in renderer.layers.values()),
        }

    def _assert_complete_old(self, adapter, renderer, before, fired):
        after = self._snapshot(adapter, renderer)
        assert after["stage"] is before["stage"]
        assert after["owned_tmp"] == before["owned_tmp"]
        assert after["owned_exists"]
        assert after["picks"] == before["picks"], (
            "pending picks must survive a failed transition"
        )
        assert fired == [], "pick callbacks must not fire on failure"
        assert after["selected"] == before["selected"], (
            "authoritative selection must survive a failed transition"
        )
        assert after["root"] == before["root"]
        assert after["layer_types"] == before["layer_types"], (
            "the full old native composition (session AND overlays) must "
            "be restored"
        )
        assert getattr(adapter, "_native_scene_unresolved", False) is False

    def test_single_root_session_ki_restores_overlays_and_selection(
        self, tmp_path
    ):
        renderer = _DestructiveSingleRootOvrtx()
        adapter, stage, fired = self._loaded_rich(tmp_path, renderer)
        before = self._snapshot(adapter, renderer)
        d_new, new_stage = self._dirty_scene(tmp_path, "new")
        renderer.raise_on_session = KeyboardInterrupt()
        try:
            with pytest.raises(KeyboardInterrupt):
                adapter.load_stage(new_stage)
        finally:
            _restore_snapshot_creation(d_new)
        self._assert_complete_old(adapter, renderer, before, fired)

    def test_single_root_destructive_open_failure_restores_all(self, tmp_path):
        renderer = _DestructiveSingleRootOvrtx()
        adapter, stage, fired = self._loaded_rich(tmp_path, renderer)
        before = self._snapshot(adapter, renderer)
        d_new, new_stage = self._dirty_scene(tmp_path, "new")
        renderer.fail_open_unless = renderer.current_root
        try:
            with pytest.raises(RuntimeError, match="native root open failed"):
                adapter.load_stage(new_stage)
        finally:
            _restore_snapshot_creation(d_new)
            renderer.fail_open_unless = None
        self._assert_complete_old(adapter, renderer, before, fired)

    def test_rollback_double_fault_is_truthful_and_recoverable(self, tmp_path):
        renderer = _DestructiveSingleRootOvrtx()
        adapter, stage, fired = self._loaded_rich(tmp_path, renderer)
        d_new, new_stage = self._dirty_scene(tmp_path, "new")
        renderer.raise_on_session = KeyboardInterrupt()
        renderer.fail_opens_from = renderer.open_count + 2  # rollback open fails
        primary = None
        try:
            try:
                adapter.load_stage(new_stage)
            except BaseException as exc:
                primary = exc
        finally:
            _restore_snapshot_creation(d_new)
            renderer.fail_opens_from = None
        assert isinstance(primary, KeyboardInterrupt), (
            "the PRIMARY throwable's identity must be preserved"
        )
        notes = getattr(primary, "__notes__", [])
        assert any("restoration also failed" in note for note in notes), (
            "the rollback double fault must be attached to the primary"
        )
        assert adapter._native_scene_unresolved is True
        assert isinstance(
            adapter._native_scene_unresolved_error, RuntimeError
        )
        # Old document identity is retained truthfully for pxr consumers;
        # the flag records that the native renderer is scene-less.
        assert adapter._stage is stage
        assert adapter._usd_handle is None
        # The next NORMAL load must succeed and clear the condition.
        d_again, again = self._dirty_scene(tmp_path, "again")
        try:
            adapter.load_stage(again)
        finally:
            _restore_snapshot_creation(d_again)
        assert adapter._native_scene_unresolved is False
        assert adapter._stage is again
        assert "session" in [t for t, _ in renderer.layers.values()]

    def test_handle_api_systemexit_in_pick_drain_commits_coherently(
        self, tmp_path
    ):
        renderer = _HandleApiOvrtxFull()
        adapter, stage, fired = self._loaded_rich(tmp_path, renderer)
        adapter._in_flight_pick_queries.clear()
        adapter._in_flight_pick_queries.append(
            [
                2,
                "rect",
                "boom",
                lambda hits: (_ for _ in ()).throw(SystemExit(3)),
                None,
                None,
            ]
        )
        before = self._snapshot(adapter, renderer)
        old_handles = set(renderer.layers)
        d_new, new_stage = self._dirty_scene(tmp_path, "new")
        try:
            # The deferred pending-pick SystemExit is the primary throwable —
            # never lost or displaced — while the swap commits coherently.
            with pytest.raises(SystemExit):
                adapter.load_stage(new_stage)
        finally:
            _restore_snapshot_creation(d_new)
        after = self._snapshot(adapter, renderer)
        assert not (old_handles & set(renderer.layers)), (
            "no old native layer may remain after a committed replacement"
        )
        assert after["layer_types"] == ["root", "session"], (
            "exactly the new scene must be composed — never mixed"
        )
        assert after["stage"] is new_stage
        assert after["owned_tmp"] != before["owned_tmp"]
        assert after["owned_exists"]
        assert not os.path.exists(before["owned_tmp"]), (
            "the old snapshot must be reclaimed by the committed replacement"
        )
        assert after["picks"] == 0

    def test_old_handle_removal_failure_commits_new_and_carries_debt(
        self, tmp_path
    ):
        """Old-handle removal failure never rolls the new scene back or
        reports clean success: the new scene is the authoritative committed
        document, the un-removable old handle is tracked cleanup debt +
        unresolved state, its snapshot file is retained (not orphaned), and
        a later teardown/shutdown drains the debt (Codex finding 1)."""

        renderer = _HandleApiOvrtxFull()
        adapter, stage, fired = self._loaded_rich(tmp_path, renderer)
        old_root_handle = adapter._usd_handle
        old_snapshot = adapter._owned_tmp_path
        renderer.fail_remove_handles = {old_root_handle}
        d_new, new_stage = self._dirty_scene(tmp_path, "new")
        try:
            with pytest.raises(RuntimeError, match="native remove failed"):
                adapter.load_stage(new_stage)
        finally:
            _restore_snapshot_creation(d_new)
        # New scene is the authoritative committed document.
        assert adapter._stage is new_stage
        assert adapter._native_scene_unresolved is True
        assert old_root_handle in adapter._unremoved_native_handles
        # The old snapshot is retained (its root handle still references it),
        # never orphaned by deletion under a live handle.
        assert old_snapshot in adapter._retained_debt_snapshots
        assert os.path.exists(old_snapshot)
        # Recoverability: once removal is permitted, the next teardown drains
        # the debt, frees the retained snapshot, and clears unresolved state.
        renderer.fail_remove_handles = set()
        adapter._remove_ovrtx_layers()
        assert adapter._unremoved_native_handles == []
        assert not os.path.exists(old_snapshot)
        assert adapter._native_scene_unresolved is False

    def test_live_reload_failure_with_rich_state_is_truthful(self, tmp_path):
        renderer = _DestructiveSingleRootOvrtx()
        adapter, stage, fired = self._loaded_rich(tmp_path, renderer)
        before = self._snapshot(adapter, renderer)
        renderer.fail_open_unless = renderer.current_root
        assert adapter._reload_live_root_snapshot() is False
        renderer.fail_open_unless = None
        self._assert_complete_old(adapter, renderer, before, fired)

    def test_successful_replacement_reconciles_and_stays_usable(self, tmp_path):
        renderer = _HandleApiOvrtxFull()
        adapter, stage, fired = self._loaded_rich(tmp_path, renderer)
        old_handles = set(renderer.layers)
        old_snapshot = adapter._owned_tmp_path
        d_new, new_stage = self._dirty_scene(tmp_path, "new")
        try:
            adapter.load_stage(new_stage)
        finally:
            _restore_snapshot_creation(d_new)
        assert not (old_handles & set(renderer.layers))
        assert sorted(t for t, _ in renderer.layers.values()) == [
            "root",
            "session",
        ]
        assert adapter._stage is new_stage
        assert fired == [None] or fired == [[]], (
            "the old pending pick must have been drained as a miss "
            f"exactly once (got {fired!r})"
        )
        assert not os.path.exists(old_snapshot)
        assert os.path.exists(adapter._owned_tmp_path)
        assert adapter._native_scene_unresolved is False
        # Continued usability: another replacement, then shutdown teardown.
        d_third, third = self._dirty_scene(tmp_path, "third")
        try:
            adapter.load_stage(third)
        finally:
            _restore_snapshot_creation(d_third)
        assert adapter._stage is third
        adapter._remove_ovrtx_layers()
        assert renderer.layers == {}


class TestCleanupFaultRecovery:
    """Fifth-review family: the transaction stays truthful and recoverable
    even when CLEANUP itself fails — failed prospective-handle removal,
    scaffolding snapshot leaks, chained deferred/commit faults, and
    self-teardown snapshot residue."""

    def _dirty_scene(self, tmp_path, tag):
        d = tmp_path / tag
        d.mkdir()
        _write(d / f"{tag}.usda", _SCENE)
        stage = Usd.Stage.Open(str(d / f"{tag}.usda"))
        UsdGeom.Imageable(
            stage.GetPrimAtPath("/World/Sphere")
        ).GetVisibilityAttr().Set(UsdGeom.Tokens.invisible)
        _force_snapshot_relocation(d)
        return d, stage

    def _loaded(self, tmp_path, renderer, tag="old"):
        adapter = _make_native_adapter(renderer)
        d, stage = self._dirty_scene(tmp_path, tag)
        try:
            adapter.load_stage(stage)
        finally:
            _restore_snapshot_creation(d)
        return adapter, stage

    def test_prospective_root_removal_failure_carries_debt_no_orphan(
        self, tmp_path
    ):
        """Finding 1: handle-API session KI, then the prospective root cannot
        be removed. The KI stays primary; the leaked prospective root becomes
        tracked debt (not silently swallowed); its snapshot is retained (not
        deleted under the live handle); the next teardown drains it."""

        renderer = _HandleApiOvrtxFull()
        adapter, stage = self._loaded(tmp_path, renderer)
        old_handles = set(renderer.layers)
        d_new, new_stage = self._dirty_scene(tmp_path, "new")
        renderer.raise_on_session = KeyboardInterrupt()
        # New prospective root ("r*") cannot be removed during reclaim.
        original_remove = renderer.remove_usd

        def _remove(handle):
            if handle not in old_handles and str(handle).startswith("r"):
                raise RuntimeError("prospective root removal failed")
            return original_remove(handle)

        renderer.remove_usd = _remove
        try:
            with pytest.raises(KeyboardInterrupt):
                adapter.load_stage(new_stage)
        finally:
            _restore_snapshot_creation(d_new)
            renderer.remove_usd = original_remove
        leaked = [
            h
            for h, (t, _) in renderer.layers.items()
            if t == "root" and h not in old_handles
        ]
        assert leaked, "the reproduction requires a genuinely leaked root"
        assert adapter._native_scene_unresolved is True
        assert set(leaked).issubset(set(adapter._unremoved_native_handles))
        # The prospective snapshot the leaked root references must be retained.
        assert adapter._retained_debt_snapshots
        for snap in adapter._retained_debt_snapshots:
            assert os.path.exists(snap), "a referenced snapshot must not be deleted"
        # Recoverability: next teardown removes the leaked root + snapshot.
        retained = list(adapter._retained_debt_snapshots)
        adapter._remove_ovrtx_layers()
        assert adapter._unremoved_native_handles == []
        assert not [
            h
            for h, (t, _) in renderer.layers.items()
            if t == "root" and h not in old_handles
        ]
        for snap in retained:
            assert not os.path.exists(snap)
        assert adapter._native_scene_unresolved is False

    def test_scaffolding_failure_reclaims_prepared_snapshot(self, tmp_path):
        """Finding 2: a KeyboardInterrupt during session scaffolding — after
        the dirty read-only-root snapshot is prepared but before any native
        handle references it — must not leak the snapshot."""

        import glob as _glob
        import tempfile as _tempfile

        renderer = _DestructiveSingleRootOvrtx()
        adapter, stage = self._loaded(tmp_path, renderer)
        d_new, new_stage = self._dirty_scene(tmp_path, "new")

        import ovui_data_adapters.openusd._session_authoring as _sa

        def _snaps():
            return set(
                _glob.glob(
                    os.path.join(
                        _tempfile.gettempdir(), "*ovui_widgets_live_*"
                    )
                )
            ) | set(
                _glob.glob(
                    os.path.join(
                        _tempfile.gettempdir(), ".ovui_widgets_live_*"
                    )
                )
            ) | set(_glob.glob(str(d_new / "*ovui_widgets_live_*"))) | set(
                _glob.glob(str(d_new / ".ovui_widgets_live_*"))
            )

        before = _snaps()
        original = _sa.ensure_render_scope
        _sa.ensure_render_scope = lambda *a, **k: (_ for _ in ()).throw(
            KeyboardInterrupt()
        )
        try:
            with pytest.raises(KeyboardInterrupt):
                adapter.load_stage(new_stage)
        finally:
            _sa.ensure_render_scope = original
            _restore_snapshot_creation(d_new)
        assert _snaps() - before == set(), (
            "a scaffolding failure must reclaim the prepared snapshot"
        )

    def test_deferred_pick_fault_survives_later_commit_fault(self, tmp_path):
        """Finding 3: pending-pick SystemExit(31) plus a later commit-work
        RuntimeError — the first throwable stays primary and the later one is
        attached; neither is lost."""

        renderer = _HandleApiOvrtxFull()
        adapter, stage = self._loaded(tmp_path, renderer)
        adapter._in_flight_pick_queries.clear()
        adapter._in_flight_pick_queries.append(
            [9, "rect", "boom", lambda hits: (_ for _ in ()).throw(SystemExit(31)), None, None]
        )
        # Force later commit bookkeeping to raise.
        adapter._author_owned_session_render_product_resolution = (
            lambda res: (_ for _ in ()).throw(RuntimeError("later commit failed"))
        )
        d_new, new_stage = self._dirty_scene(tmp_path, "new")
        try:
            with pytest.raises(SystemExit) as excinfo:
                adapter.load_stage(new_stage)
        finally:
            _restore_snapshot_creation(d_new)
        assert excinfo.value.code == 31, "the FIRST throwable stays primary"
        assert any(
            "later commit failed" in note
            for note in getattr(excinfo.value, "__notes__", [])
        ), "the later fault must be attached, never lost"

    def test_repeated_loads_leave_zero_snapshot_residue(self, tmp_path):
        """Finding 7: an adapter that is torn down (shutdown) leaves zero of
        its own snapshot files behind, across repeated loads and failures."""

        import glob as _glob
        import tempfile as _tempfile

        def _snaps():
            return set(
                _glob.glob(
                    os.path.join(
                        _tempfile.gettempdir(), "*ovui_widgets_live_*"
                    )
                )
            )

        before = _snaps()
        for i in range(4):
            renderer = _HandleApiOvrtxFull()
            adapter, stage = self._loaded(tmp_path, renderer, tag=f"iter{i}")
            # A second load, then a genuine shutdown teardown.
            d2, stage2 = self._dirty_scene(tmp_path, f"iter{i}b")
            try:
                adapter.load_stage(stage2)
            finally:
                _restore_snapshot_creation(d2)
            adapter.shutdown()
        assert _snaps() - before == set(), (
            "torn-down adapters must leave zero snapshot residue"
        )


class _StrictSingleRootOvrtx(_SingleRootFakeOvrtx):
    """Single-root double whose ``remove_usd`` REJECTS an already-torn-down
    handle, exactly like real ovrtx.

    ``open_usd`` destroys the current root AND everything composed on it
    (session + overlays), so those layer handles become invalid. Re-issuing
    ``remove_usd`` on such a stale handle fails natively (the real
    "Operation 'remove_usd' failed" that crashed the reused-renderer
    transition). Only the renderer object is a double; every adapter
    transition method under test is production code."""

    def remove_usd(self, handle):
        if handle not in self.layers:
            raise RuntimeError(
                f"Operation 'remove_usd' failed: stale handle {handle}"
            )
        self.layers.pop(handle, None)


class TestSingleRootReuseReconcile:
    """Reusing ONE single-root renderer across documents (the in-place
    File > New / Recent Files reopen path) drives RECONCILE OLD against REAL
    prior native handles for the first time.

    Before the reuse fix the app built a fresh renderer per document, so
    RECONCILE OLD never had real old handles and never removed anything.
    Reusing the renderer means the previous load left a live session (and
    overlays); the incoming destructive ``open_usd`` tears those down, so a
    subsequent ``remove_usd`` on the now-stale handle fails natively — real
    ovrtx rejects it and the whole transition aborted/crashed. Reconcile must
    TOLERATE that stale-handle removal failure for the single-root API (the
    destructive open already released it) instead of turning it into a
    propagated fault / unresolved native debt."""

    def test_single_root_reuse_tolerates_torn_down_old_session(
        self, tmp_path
    ):
        renderer = _StrictSingleRootOvrtx()
        adapter = _make_native_adapter(renderer)
        scene_a = _write_scene(tmp_path, "reuse_a.usda")
        scene_b = _write_scene(tmp_path, "reuse_b.usda")

        adapter.load_stage(scene_a)
        first_session = adapter._session_handle
        assert first_session is not None
        assert first_session in renderer.layers, "first session must compose"

        # Second in-place load. ``open_usd(scene_b)`` tears the old root +
        # session down; the stale session handle's remove_usd raises, and
        # RECONCILE OLD must tolerate it for the single-root API. Pre-fix this
        # raised "Operation 'remove_usd' failed" and left the scene
        # unresolved / crashed the transition.
        adapter.load_stage(scene_b)

        assert renderer.current_root == str(scene_b), "new root must install"
        assert first_session not in renderer.layers, "old session is gone"
        assert getattr(adapter, "_native_scene_unresolved", False) is False, (
            "a single-root reuse must not report unresolved native debt"
        )
        assert adapter._native_scene_unresolved_error is None
        assert getattr(adapter, "_unremoved_native_handles", []) == [], (
            "no stale old handle may be retained as removal debt"
        )
        adapter.shutdown()

    def test_handle_based_reuse_still_removes_old_layers(self, tmp_path):
        """The single-root skip must NOT leak old layers for the handle-based
        API, where the old root/session compose ALONGSIDE the new ones and
        genuinely must be removed."""
        renderer = _HandleFakeOvrtx()
        adapter = _make_native_adapter(renderer)
        scene_a = _write_scene(tmp_path, "handle_a.usda")
        scene_b = _write_scene(tmp_path, "handle_b.usda")

        adapter.load_stage(scene_a)
        old_handles = set(renderer.layers)
        assert old_handles

        adapter.load_stage(scene_b)

        # None of the OLD handles may survive the handle-based transition.
        assert old_handles.isdisjoint(set(renderer.layers)), (
            "handle-based reuse must remove the old root/session layers"
        )
        assert getattr(adapter, "_native_scene_unresolved", False) is False
        adapter.shutdown()


class TestNativeCleanupRefusalAndIdentity:
    """Native cleanup is an owned, retryable transaction, including faults.

    These are durable versions of the external worker-phase-0 A/B/C probes.
    They use real dirty OpenUSD stages and the complete adapter lifecycle; only
    the two native API shapes are deterministic doubles.
    """

    def _dirty_scene(self, tmp_path, tag):
        directory = tmp_path / tag
        directory.mkdir()
        _write(directory / f"{tag}.usda", _SCENE)
        stage = Usd.Stage.Open(str(directory / f"{tag}.usda"))
        UsdGeom.Imageable(
            stage.GetPrimAtPath("/World/Sphere")
        ).GetVisibilityAttr().Set(UsdGeom.Tokens.invisible)
        _force_snapshot_relocation(directory)
        return directory, stage

    def _loaded(self, tmp_path, renderer):
        adapter = _make_native_adapter(renderer)
        directory, stage = self._dirty_scene(tmp_path, "old")
        try:
            adapter.load_stage(stage)
        finally:
            _restore_snapshot_creation(directory)
        return adapter, stage

    @pytest.mark.parametrize(
        "primary",
        [KeyboardInterrupt("primary-ki"), SystemExit(73)],
        ids=["keyboard-interrupt", "system-exit"],
    )
    def test_prospective_debt_refuses_load_and_shutdown_until_recovery(
        self, tmp_path, primary
    ):
        renderer = _HandleApiOvrtxFull()
        adapter, old_stage = self._loaded(tmp_path, renderer)
        renderer_identity = renderer
        old_handles = set(renderer.layers)
        old_root = adapter._usd_handle
        old_session = adapter._session_handle
        old_snapshot = adapter._owned_tmp_path
        cleanup = RuntimeError("exact prospective cleanup fault")
        blocked = True
        original_remove = renderer.remove_usd

        def remove(handle):
            if (
                blocked
                and handle not in old_handles
                and renderer.layers.get(handle, (None,))[0] == "root"
            ):
                raise cleanup
            return original_remove(handle)

        renderer.remove_usd = remove
        new_dir, new_stage = self._dirty_scene(tmp_path, "new")
        renderer.raise_on_session = primary
        try:
            with pytest.raises(BaseException) as caught:
                adapter.load_stage(new_stage)
        finally:
            _restore_snapshot_creation(new_dir)
        assert caught.value is primary

        leaked_roots = [
            handle
            for handle, (kind, _payload) in renderer.layers.items()
            if kind == "root" and handle not in old_handles
        ]
        assert len(leaked_roots) == 1
        leaked_root = leaked_roots[0]
        diagnostics = adapter.native_cleanup_diagnostics
        assert len(diagnostics) == 1
        diagnostic = diagnostics[0]
        assert diagnostic.owner == "prospective-root"
        assert diagnostic.handle is leaked_root
        assert diagnostic.primary is primary
        assert diagnostic.first_error is cleanup
        assert diagnostic.latest_error is cleanup
        assert adapter._native_scene_unresolved_error is cleanup
        assert leaked_root in adapter._unremoved_native_handles
        assert diagnostic.snapshot in adapter._retained_debt_snapshots
        assert os.path.exists(diagnostic.snapshot)
        assert any(
            relation.primary is primary
            and any(error is cleanup for error in relation.secondaries)
            for relation in adapter.throwable_diagnostics
        )
        assert not any(
            value is cleanup
            for value in (primary.__cause__, primary.__context__)
        )

        # Admission is gated before preparation/native setup: the complete
        # old stage and exact current handles remain current, and no second
        # prospective root appears.
        again_dir, again_stage = self._dirty_scene(tmp_path, "again")
        before_layers = dict(renderer.layers)
        try:
            with pytest.raises(RuntimeError) as refused_load:
                adapter.load_stage(again_stage)
        finally:
            _restore_snapshot_creation(again_dir)
        assert refused_load.value is cleanup
        assert adapter._stage is old_stage
        assert adapter._usd_handle is old_root
        assert adapter._session_handle is old_session
        assert dict(renderer.layers) == before_layers

        # Shutdown refusal retains renderer capability, current logical/native
        # ownership, both referenced snapshots, and exact diagnostics.
        with pytest.raises(RuntimeError) as refused_shutdown:
            adapter.shutdown()
        assert refused_shutdown.value is cleanup
        assert adapter._renderer is renderer_identity
        assert adapter._stage is old_stage
        assert adapter._usd_handle is old_root
        assert adapter._session_handle is old_session
        assert os.path.exists(old_snapshot)
        assert os.path.exists(diagnostic.snapshot)
        assert leaked_root in renderer.layers
        assert adapter._native_scene_unresolved is True

        # Once native removal recovers, the next load first drains exactly the
        # retained debt/snapshot and only then installs the requested stage.
        blocked = False
        adapter.load_stage(again_stage)
        assert adapter._stage is again_stage
        assert leaked_root not in renderer.layers
        assert not os.path.exists(diagnostic.snapshot)
        assert adapter.native_cleanup_diagnostics == ()
        assert adapter.throwable_diagnostics == ()
        assert adapter._native_scene_unresolved is False
        adapter.shutdown()
        assert adapter._renderer is None
        assert renderer.layers == {}

    def test_current_root_and_session_failures_refuse_without_abandoning(
        self, tmp_path
    ):
        renderer = _HandleApiOvrtxFull()
        adapter, stage = self._loaded(tmp_path, renderer)
        renderer_identity = renderer
        root = adapter._usd_handle
        session = adapter._session_handle
        snapshot = adapter._owned_tmp_path
        root_error = RuntimeError("exact current root removal fault")
        session_error = RuntimeError("exact current session removal fault")
        blocked = True
        original_remove = renderer.remove_usd

        def remove(handle):
            if blocked and handle == session:
                raise session_error
            if blocked and handle == root:
                raise root_error
            return original_remove(handle)

        renderer.remove_usd = remove
        with pytest.raises(RuntimeError) as refused:
            adapter.shutdown()
        assert refused.value is session_error
        assert adapter._renderer is renderer_identity
        assert adapter._stage is stage
        assert adapter._usd_handle is root
        assert adapter._session_handle is session
        assert renderer.layers[root][1] == snapshot
        assert root in renderer.layers and session in renderer.layers
        assert os.path.exists(snapshot)
        by_owner = {
            diagnostic.owner: diagnostic
            for diagnostic in adapter.native_cleanup_diagnostics
        }
        assert by_owner["current-session"].handle == session
        assert by_owner["current-session"].first_error is session_error
        assert by_owner["current-root"].handle == root
        assert by_owner["current-root"].first_error is root_error
        assert adapter._native_scene_unresolved_error is session_error

        # A second refusal is bounded and retains both exact throwable objects.
        with pytest.raises(RuntimeError) as refused_again:
            adapter.shutdown()
        assert refused_again.value is session_error
        assert by_owner["current-session"].failure_count == 2
        assert by_owner["current-root"].failure_count == 2
        assert all(error is session_error for error in by_owner["current-session"].errors)
        assert all(error is root_error for error in by_owner["current-root"].errors)

        blocked = False
        adapter.shutdown()
        assert renderer.layers == {}
        assert adapter._renderer is None
        assert adapter._stage is None
        assert adapter._usd_handle is None
        assert adapter._session_handle is None
        assert not os.path.exists(snapshot)
        assert adapter.native_cleanup_diagnostics == ()
        assert adapter.throwable_diagnostics == ()
        assert adapter._native_scene_unresolved is False

    def test_overlay_failure_retains_exact_handle_until_retry(self, tmp_path):
        renderer = _HandleApiOvrtxFull()
        adapter, stage = self._loaded(tmp_path, renderer)
        overlay = renderer.add_usd_layer("#usda 1.0", path_prefix=None)
        adapter._live_resync_handles = [overlay]
        error = KeyboardInterrupt("exact overlay removal fault")
        original_remove = renderer.remove_usd

        def remove(handle):
            if handle == overlay:
                raise error
            return original_remove(handle)

        renderer.remove_usd = remove
        with pytest.raises(KeyboardInterrupt) as refused:
            adapter.shutdown()
        assert refused.value is error
        assert adapter._renderer is renderer
        assert adapter._stage is stage
        assert adapter._live_resync_handles == [overlay]
        assert overlay in renderer.layers
        diagnostic = next(
            item
            for item in adapter.native_cleanup_diagnostics
            if item.owner == "current-overlay"
        )
        assert diagnostic.handle == overlay
        assert diagnostic.first_error is error

        renderer.remove_usd = original_remove
        adapter.shutdown()
        assert renderer.layers == {}
        assert adapter.native_cleanup_diagnostics == ()

    def test_single_root_reset_baseexception_retains_root_until_retry(
        self, tmp_path
    ):
        renderer = _DestructiveSingleRootOvrtx()
        adapter, stage = self._loaded(tmp_path, renderer)
        snapshot = adapter._owned_tmp_path
        root_token = adapter._usd_handle
        refusal = SystemExit(91)
        blocked = True

        def reset_stage():
            if blocked:
                raise refusal
            renderer.current_root = None
            renderer.layers.clear()

        renderer.reset_stage = reset_stage
        with pytest.raises(SystemExit) as caught:
            adapter.shutdown()
        assert caught.value is refusal
        assert adapter._renderer is renderer
        assert adapter._stage is stage
        assert adapter._usd_handle is root_token
        assert renderer.current_root == snapshot
        assert os.path.exists(snapshot)
        diagnostic = next(
            item
            for item in adapter.native_cleanup_diagnostics
            if item.owner == "current-root"
        )
        assert diagnostic.handle is root_token
        assert diagnostic.first_error is refusal

        blocked = False
        adapter.shutdown()
        assert renderer.current_root is None
        assert adapter._renderer is None
        assert not os.path.exists(snapshot)
        assert adapter.native_cleanup_diagnostics == ()

    def test_single_root_rollback_fault_identity_gates_later_load(
        self, tmp_path
    ):
        renderer = _DestructiveSingleRootOvrtx()
        adapter, old_stage = self._loaded(tmp_path, renderer)
        old_payload = adapter._root_open_payload[0]
        primary = KeyboardInterrupt("exact prospective session failure")
        rollback_error = RuntimeError("exact rollback root failure")
        original_open = renderer.open_usd
        block_rollback = True

        def open_usd(path):
            if block_rollback and str(path) == str(old_payload):
                raise rollback_error
            return original_open(path)

        renderer.open_usd = open_usd
        new_dir, new_stage = self._dirty_scene(tmp_path, "rollback-new")
        renderer.raise_on_session = primary
        try:
            with pytest.raises(KeyboardInterrupt) as caught:
                adapter.load_stage(new_stage)
        finally:
            _restore_snapshot_creation(new_dir)
        assert caught.value is primary
        assert adapter._stage is old_stage
        restore = adapter._native_restore_obligation
        assert restore is not None
        assert restore.primary is primary
        assert restore.diagnostic.first_error is rollback_error
        assert restore.diagnostic.primary is primary
        assert os.path.exists(restore.prospective_snapshot)
        assert any(
            relation.primary is primary
            and any(error is rollback_error for error in relation.secondaries)
            for relation in adapter.throwable_diagnostics
        )

        later_dir, later_stage = self._dirty_scene(tmp_path, "rollback-later")
        try:
            with pytest.raises(RuntimeError) as refused:
                adapter.load_stage(later_stage)
        finally:
            _restore_snapshot_creation(later_dir)
        assert refused.value is rollback_error
        assert adapter._stage is old_stage

        block_rollback = False
        adapter.load_stage(later_stage)
        assert adapter._stage is later_stage
        assert adapter._native_restore_obligation is None
        assert not os.path.exists(restore.prospective_snapshot)
        assert adapter.native_cleanup_diagnostics == ()
        assert adapter.throwable_diagnostics == ()
        adapter.shutdown()

    def test_snapshot_reclaim_failure_never_double_removes_native_root(
        self, tmp_path, monkeypatch
    ):
        renderer = _HandleApiOvrtxFull()
        adapter, old_stage = self._loaded(tmp_path, renderer)
        old_handles = set(renderer.layers)
        primary = KeyboardInterrupt("prospective operation")
        remove_error = RuntimeError("prospective root removal")
        unlink_error = OSError("retained snapshot unlink")
        native_blocked = True
        native_remove_count = 0
        original_remove = renderer.remove_usd

        def remove(handle):
            nonlocal native_remove_count
            prospective_root = (
                handle not in old_handles
                and renderer.layers.get(handle, (None,))[0] == "root"
            )
            if prospective_root and native_blocked:
                raise remove_error
            if prospective_root:
                native_remove_count += 1
            return original_remove(handle)

        renderer.remove_usd = remove
        new_dir, new_stage = self._dirty_scene(tmp_path, "unlink-new")
        renderer.raise_on_session = primary
        try:
            with pytest.raises(KeyboardInterrupt):
                adapter.load_stage(new_stage)
        finally:
            _restore_snapshot_creation(new_dir)
        diagnostic = adapter.native_cleanup_diagnostics[0]
        retained_snapshot = diagnostic.snapshot
        assert os.path.exists(retained_snapshot)

        native_blocked = False
        file_blocked = True
        original_unlink = os.unlink

        def unlink(path):
            if file_blocked and str(path) == str(retained_snapshot):
                raise unlink_error
            return original_unlink(path)

        monkeypatch.setattr(os, "unlink", unlink)
        later_dir, later_stage = self._dirty_scene(tmp_path, "unlink-later")
        try:
            with pytest.raises(OSError) as refused:
                adapter.load_stage(later_stage)
        finally:
            _restore_snapshot_creation(later_dir)
        assert refused.value is unlink_error
        assert native_remove_count == 1
        assert adapter._unremoved_native_handles == []
        assert adapter._retained_debt_snapshots == [retained_snapshot]
        assert os.path.exists(retained_snapshot)
        assert adapter._stage is old_stage
        assert diagnostic.first_error is remove_error
        assert diagnostic.latest_error is unlink_error

        # Another file failure retries only unlink, never the removed handle.
        with pytest.raises(OSError) as refused_again:
            adapter.load_stage(later_stage)
        assert refused_again.value is unlink_error
        assert native_remove_count == 1

        file_blocked = False
        adapter.load_stage(later_stage)
        assert native_remove_count == 1
        assert not os.path.exists(retained_snapshot)
        assert adapter.native_cleanup_diagnostics == ()
        adapter.shutdown()

    def test_session_reinject_removal_failure_retains_exact_owner(self, tmp_path):
        renderer = _HandleApiOvrtxFull()
        adapter, stage = self._loaded(tmp_path, renderer)
        session = adapter._session_handle
        error = SystemExit(101)
        original_remove = renderer.remove_usd
        blocked = True

        def remove(handle):
            if blocked and handle == session:
                raise error
            return original_remove(handle)

        renderer.remove_usd = remove
        with pytest.raises(SystemExit) as caught:
            adapter._reinject_session_layer()
        assert caught.value is error
        assert adapter._stage is stage
        assert adapter._session_handle == session
        assert session in renderer.layers
        diagnostic = next(
            item
            for item in adapter.native_cleanup_diagnostics
            if item.owner == "current-session"
        )
        assert diagnostic.handle == session
        assert diagnostic.first_error is error

        blocked = False
        adapter._reinject_session_layer()
        assert session not in renderer.layers
        assert adapter._session_handle in renderer.layers
        assert adapter.native_cleanup_diagnostics == ()
        adapter.shutdown()
