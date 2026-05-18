# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Read the "current" USD camera from stage metadata.

Many USD files (DCC-exported kitchens, Kit scenes, etc.) record which
camera the user was last framed on inside the root layer's
``customLayerData``:

    customLayerData = {
        dictionary cameraSettings = {
            ...
            string boundCamera = "/World/Camera"
        }
    }

This module fetches that prim, computes the world-space eye + target +
FOV, and returns them in a form the :class:`CameraController` can apply
via :meth:`CameraController.set_pose`.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from ovui_data_adapters.common import BoundCameraPose


def _extract_coi_distance(cam_prim: Any) -> Optional[float]:
    """Return the distance from the camera to its orbit target, or ``None``.

    Priority:
      1. ``omni:kit:centerOfInterest`` — a camera-local vector pointing
         toward the target (Kit convention, ``(0, 0, -dist)``).
      2. ``focusDistance`` — USD standard for the DOF focus plane, a
         reasonable fallback.
    """
    coi_attr = cam_prim.GetAttribute("omni:kit:centerOfInterest")
    if coi_attr and coi_attr.HasAuthoredValue():
        coi = coi_attr.Get()
        if coi is not None:
            return float(math.sqrt(coi[0] ** 2 + coi[1] ** 2 + coi[2] ** 2))
    focus_attr = cam_prim.GetAttribute("focusDistance")
    if focus_attr and focus_attr.HasAuthoredValue():
        fd = focus_attr.Get()
        if fd and fd > 0.0:
            return float(fd)
    return None


def _pose_from_perspective_preset(
    cam_settings: dict, up_axis: str, prim_path: str
) -> Optional[BoundCameraPose]:
    """Fallback: read ``cameraSettings.Perspective`` viewpoint.

    Kit stores its last-session persistent perspective camera state here as
    ``{"position": Gf.Vec3d, "target": Gf.Vec3d}`` (sometimes ``radius`` +
    ``target`` on the ortho presets). When ``boundCamera`` points at a prim
    that doesn't exist in the saved layer (common for ``/OmniverseKit_Persp``
    — Kit injects it at runtime but DCCs don't always export it), this dict
    still carries a usable viewpoint.
    """
    persp = cam_settings.get("Perspective") or {}
    pos = persp.get("position")
    tgt = persp.get("target")
    if pos is None or tgt is None:
        return None
    return BoundCameraPose(
        eye=(float(pos[0]), float(pos[1]), float(pos[2])),
        target=(float(tgt[0]), float(tgt[1]), float(tgt[2])),
        up_axis=up_axis,
        fov_degrees=45.0,  # Kit presets don't carry focal/aperture; stay at default.
        prim_path=prim_path + " (Perspective preset fallback)",
    )


def read_camera_pose(stage: Any, camera_path: str) -> Optional[BoundCameraPose]:
    """Return a :class:`BoundCameraPose` for the camera prim at ``camera_path``.

    This is the explicit-camera counterpart to :func:`read_bound_camera`.
    It shares the same USD matrix/FOV interpretation but does not inspect
    ``customLayerData`` or fall back to the Perspective preset.
    """
    try:
        from pxr import UsdGeom
    except ImportError:
        return None

    if stage is None or not camera_path:
        return None
    cam_prim = stage.GetPrimAtPath(camera_path)
    if not cam_prim or not cam_prim.IsValid() or not UsdGeom.Camera(cam_prim):
        return None
    up_axis = str(UsdGeom.GetStageUpAxis(stage) or "Y").upper()
    return _pose_from_camera_prim(cam_prim, up_axis=up_axis, prim_path=str(camera_path))


def _pose_from_camera_prim(
    cam_prim: Any,
    up_axis: str,
    prim_path: str,
) -> Optional[BoundCameraPose]:
    """Compute a viewport pose from a concrete ``UsdGeom.Camera`` prim."""
    try:
        from pxr import Gf, UsdGeom
    except ImportError:
        return None

    if not cam_prim or not cam_prim.IsValid() or not UsdGeom.Camera(cam_prim):
        return None

    cam = UsdGeom.Camera(cam_prim)
    xcache = UsdGeom.XformCache()
    world = xcache.GetLocalToWorldTransform(cam_prim)
    eye = world.ExtractTranslation()

    # Target = camera-local centerOfInterest, or camera-local -Z at focus
    # distance. USD camera convention: camera looks down its local -Z.
    coi_attr = cam_prim.GetAttribute("omni:kit:centerOfInterest")
    target_world: Optional[Gf.Vec3d] = None
    if coi_attr and coi_attr.HasAuthoredValue():
        coi = coi_attr.Get()
        if coi is not None:
            target_world = world.Transform(Gf.Vec3d(coi[0], coi[1], coi[2]))
    if target_world is None:
        dist = _extract_coi_distance(cam_prim) or 1000.0
        target_world = world.Transform(Gf.Vec3d(0.0, 0.0, -float(dist)))

    focal = cam.GetFocalLengthAttr().Get()
    v_aper = cam.GetVerticalApertureAttr().Get()
    h_aper = cam.GetHorizontalApertureAttr().Get()
    aperture = v_aper if (v_aper and v_aper > 0.0) else h_aper
    fov_deg = 45.0
    if focal and focal > 0.0 and aperture and aperture > 0.0:
        fov_deg = 2.0 * math.degrees(math.atan(aperture / (2.0 * focal)))

    return BoundCameraPose(
        eye=(float(eye[0]), float(eye[1]), float(eye[2])),
        target=(float(target_world[0]), float(target_world[1]), float(target_world[2])),
        up_axis=up_axis,
        fov_degrees=float(fov_deg),
        prim_path=prim_path,
    )


def read_bound_camera(stage: Any) -> Optional[BoundCameraPose]:
    """Parse ``customLayerData.cameraSettings`` off ``stage``.

    Priority order:
      1. ``boundCamera`` → resolves to a ``UsdGeom.Camera`` prim →
         world-space eye + target derived from its xform + centerOfInterest,
         FOV from focal length + aperture.
      2. ``Perspective`` preset (``{position, target}``) — used when the
         named bound camera prim is missing (Kit's built-in
         ``/OmniverseKit_Persp`` is often referenced but not authored).

    Returns ``None`` if neither path yields a pose — callers then fall back
    to bbox framing.
    """
    try:
        from pxr import UsdGeom
    except ImportError:
        return None

    root = stage.GetRootLayer()
    if root is None:
        return None
    layer_data = root.customLayerData or {}
    cam_settings = layer_data.get("cameraSettings") or {}
    cam_path = cam_settings.get("boundCamera")
    up_axis = str(UsdGeom.GetStageUpAxis(stage) or "Y").upper()

    # Path 1: resolve boundCamera to an actual Camera prim.
    if cam_path:
        cam_prim = stage.GetPrimAtPath(cam_path)
        pose = _pose_from_camera_prim(
            cam_prim,
            up_axis=up_axis,
            prim_path=str(cam_path),
        )
        if pose is not None:
            return pose

    # Path 2: fall back to the Perspective preset (no prim needed).
    return _pose_from_perspective_preset(
        cam_settings,
        up_axis=up_axis,
        prim_path=str(cam_path) if cam_path else "<no boundCamera>",
    )
