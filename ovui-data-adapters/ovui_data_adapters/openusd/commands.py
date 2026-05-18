# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""USD-specific undo Commands for UsdStageAdapter mutations.

SetVisibilityCommand and NamespaceEditCommand implement the Command ABC so
UsdStageAdapter can push all mutations through UndoManager.
"""

from __future__ import annotations

from typing import Any

try:
    from pxr import Sdf, UsdGeom
    _HAS_USD = True
except ImportError:
    _HAS_USD = False

from ovui_data_adapters.common import Command


_CAMERA_POSE_PROPERTY_NAMES = frozenset(
    {
        "focusDistance",
        "omni:kit:centerOfInterest",
        "xformOpOrder",
    }
)


def _camera_pose_property_names(layer: Any, prim_path: Any) -> set[str]:
    names = set(_CAMERA_POSE_PROPERTY_NAMES)
    prim_spec = layer.GetPrimAtPath(prim_path)
    if prim_spec is None:
        return names
    names.update(
        str(name)
        for name in prim_spec.properties.keys()
        if str(name).startswith("xformOp:")
    )
    return names


class _CameraPoseSnapshot:
    """Snapshot the authored camera pose fields in one edit-target layer."""

    def __init__(self, layer: Any, prim_path: Any) -> None:
        self._prim_path = prim_path
        self._holder = Sdf.Layer.CreateAnonymous()
        Sdf.CreatePrimInLayer(self._holder, self._prim_path)
        self._property_names = tuple(sorted(_camera_pose_property_names(layer, prim_path)))
        for name in self._property_names:
            prop_path = self._prim_path.AppendProperty(name)
            if layer.GetPropertyAtPath(prop_path) is not None:
                Sdf.CopySpec(layer, prop_path, self._holder, prop_path)

    def restore(self, layer: Any) -> None:
        Sdf.CreatePrimInLayer(layer, self._prim_path)
        prim_spec = layer.GetPrimAtPath(self._prim_path)
        if prim_spec is None:
            return

        names_to_remove = _camera_pose_property_names(layer, self._prim_path)
        names_to_remove.update(self._property_names)
        for name in sorted(names_to_remove):
            prop = layer.GetPropertyAtPath(self._prim_path.AppendProperty(name))
            if prop is not None:
                prim_spec.RemoveProperty(prop)

        for name in self._property_names:
            prop_path = self._prim_path.AppendProperty(name)
            if self._holder.GetPropertyAtPath(prop_path) is not None:
                Sdf.CopySpec(self._holder, prop_path, layer, prop_path)


class SetVisibilityCommand(Command):
    """Toggle prim visibility, storing the old authored value for undo."""

    def __init__(self, prim: Any, visible: bool) -> None:
        self._prim = prim
        self._visible = visible
        imageable = UsdGeom.Imageable(prim)
        vis_attr = imageable.GetVisibilityAttr()
        # Capture current authored value (None = not yet authored)
        if vis_attr.HasAuthoredValue():
            self._old_value = vis_attr.Get()
        else:
            self._old_value = None

    def do(self) -> None:
        imageable = UsdGeom.Imageable(self._prim)
        if self._visible:
            imageable.MakeVisible()
        else:
            imageable.MakeInvisible()

    def undo(self) -> None:
        imageable = UsdGeom.Imageable(self._prim)
        vis_attr = imageable.GetVisibilityAttr()
        if self._old_value is None:
            vis_attr.Clear()
        else:
            vis_attr.Set(self._old_value)


class DeletePrimCommand(Command):
    """Delete a prim at path via BatchNamespaceEdit. Undo restores it.

    Captures the prim's full spec before deletion so it can be recreated on
    undo via ``Sdf.CopySpec`` into a temporary anonymous layer, then copied
    back on undo.
    """

    def __init__(self, stage: Any, prim_path: "Sdf.Path") -> None:
        self._stage = stage
        self._path = prim_path
        self._captured_layer = None

    def do(self) -> None:
        # Capture current spec into an in-memory layer for undo.
        #
        # ``Sdf.CopySpec(src_layer, src_path, dst_layer, dst_path)`` requires
        # the destination layer to already have a parent prim spec along
        # ``dst_path``. For a freshly-anonymous ``tmp`` layer the parent
        # specs do not exist yet, so we have to call
        # ``Sdf.CreatePrimInLayer`` on the parent path first — without this,
        # USD's ``SdfData`` raises ``No spec at <…> when trying to set field
        # 'primChildren'`` and the deletion silently aborts. Reproduced
        # against ``tests/data/simple_scene.usda``: deleting
        # ``/World/Cube`` failed because ``/World`` was missing on ``tmp``.
        # The previous mock-only test in
        # ``tests/test_delete_prim_command.py`` did not exercise this
        # precondition because it patched ``Sdf`` entirely.
        layer = self._stage.GetEditTarget().GetLayer()
        tmp = Sdf.Layer.CreateAnonymous()
        parent_path = self._path.GetParentPath()
        if parent_path != Sdf.Path.absoluteRootPath:
            Sdf.CreatePrimInLayer(tmp, parent_path)
        Sdf.CopySpec(layer, self._path, tmp, self._path)
        self._captured_layer = tmp
        batch = Sdf.BatchNamespaceEdit()
        batch.Add(self._path, Sdf.Path.emptyPath)
        layer.Apply(batch)

    def undo(self) -> None:
        if self._captured_layer is None:
            return
        layer = self._stage.GetEditTarget().GetLayer()
        # Restoring the prim back into ``layer`` does not need ancestor
        # pre-creation because ``layer`` already authored the original
        # parent specs (we deleted only ``self._path``, not its parents).
        # If a future caller deletes the parent too, the parent's
        # ``DeletePrimCommand`` undoes first under ``UndoGroup`` ordering.
        Sdf.CopySpec(self._captured_layer, self._path, layer, self._path)


class NamespaceEditCommand(Command):
    """Move a prim path (rename or reparent) via Sdf.BatchNamespaceEdit.

    Undo swaps src and dst, restoring the original path.
    """

    def __init__(self, layer: Any, old_path: "Sdf.Path", new_path: "Sdf.Path") -> None:
        self._layer = layer
        self._old_path = old_path
        self._new_path = new_path

    def do(self) -> None:
        batch = Sdf.BatchNamespaceEdit()
        batch.Add(self._old_path, self._new_path)
        self._layer.Apply(batch)

    def undo(self) -> None:
        batch = Sdf.BatchNamespaceEdit()
        batch.Add(self._new_path, self._old_path)
        self._layer.Apply(batch)


class CameraPoseCommand(Command):
    """Undo/redo command for a selected USD camera pose write."""

    def __init__(
        self,
        stage: Any,
        camera_path: str,
        view_matrix: Any,
        target_world: Any,
    ) -> None:
        self._stage = stage
        self._camera_path = str(camera_path)
        self._view_matrix = tuple(
            tuple(float(value) for value in row)
            for row in view_matrix
        )
        self._target_world = (
            float(target_world[0]),
            float(target_world[1]),
            float(target_world[2]),
        )
        self._layer = stage.GetEditTarget().GetLayer()
        self._prim_path = Sdf.Path(self._camera_path)
        self._before = _CameraPoseSnapshot(self._layer, self._prim_path)
        self._after: _CameraPoseSnapshot | None = None

    def do(self) -> None:
        from ovui_data_adapters.openusd._camera_writer import (
            write_scene_camera_pose_from_matrices,
        )

        write_scene_camera_pose_from_matrices(
            self._stage,
            self._camera_path,
            self._view_matrix,
            self._target_world,
        )
        self._after = _CameraPoseSnapshot(self._layer, self._prim_path)

    def undo(self) -> None:
        self._before.restore(self._layer)

    def redo(self) -> None:
        if self._after is None:
            self.do()
            return
        self._after.restore(self._layer)
