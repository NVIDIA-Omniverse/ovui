# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""View/projection-matrix → USD camera attribute writer.

Given the OpenGL-convention ``(view_matrix, proj_matrix)`` produced by
:class:`ovui_widgets.viewport.camera_controller.CameraController`, this module
authors equivalent ``UsdGeomCamera`` attributes onto USD camera prims so
ovrtx (which reads camera intrinsics and world transform from the USD
scene, not from an API call) can render the corresponding view.

The owned runtime-camera writer scopes writes to the stage's **session
layer** via ``Usd.EditContext`` so the user's root layer stays untouched on
free-camera moves. The selected scene-camera writer intentionally authors
through the current edit target so user navigation in a selected USD camera
edits that camera prim.

Convention notes
----------------
* ``view_matrix`` and ``proj_matrix`` are 4×4 numpy arrays in OpenGL
  layout: row-major storage, column-vector math (``p' = M * p``). That
  matches ``camera_controller._look_at`` / ``_perspective``.
* ``Gf.Matrix4d`` stores row-major but is row-vector (``p' = p * M``).
  A numpy column-vector matrix therefore transposes into a Gf row-vector
  matrix representing the same transform.
* The camera's world transform is ``inverse(view_matrix)``.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np
from pxr import Gf, Sdf, Usd, UsdGeom

# Film-back constant. The ovrtx reference scene
# (``planet-system/simple_scene.usda``) fixes ``horizontalAperture`` at
# 20.955 mm — the classic 35 mm full-frame width. We keep the same value
# and derive focal length + vertical aperture from the projection matrix
# so scenes authored against that reference frame identically.
_FIXED_HORIZONTAL_APERTURE = 20.955


def _decompose_perspective(proj: np.ndarray) -> Tuple[float, float, float, float]:
    """Extract ``(fovy_rad, aspect, near, far)`` from a GL perspective matrix.

    Inverse of :func:`ovui_widgets.viewport.camera_controller._perspective`.

    Assumes the input is the exact GL form::

        [[1/(aspect*t),  0,              0,                   0              ],
         [0,             1/t,            0,                   0              ],
         [0,             0,             -(f+n)/(f-n),        -2fn/(f-n)      ],
         [0,             0,             -1,                   0              ]]

    where ``t = tan(fovy/2)``. Orthographic or otherwise-shaped matrices
    are rejected with :class:`ValueError`.
    """
    proj = np.asarray(proj, dtype=np.float64)
    if proj.shape != (4, 4):
        raise ValueError(f"proj must be 4x4, got {proj.shape}")

    m11 = proj[1, 1]
    m00 = proj[0, 0]
    if m11 <= 0.0 or m00 <= 0.0:
        raise ValueError(
            "projection matrix is not a standard GL perspective "
            "(proj[0,0] and proj[1,1] must be positive)"
        )

    # fovy from proj[1,1] = 1 / tan(fovy/2)
    fovy_rad = 2.0 * math.atan(1.0 / m11)
    # aspect from proj[0,0] = proj[1,1] / aspect
    aspect = m11 / m00

    # near/far from the (2,2) and (2,3) entries.
    # A = -proj[2,2] = (f+n)/(f-n), B = -proj[2,3] = 2fn/(f-n)
    a = -proj[2, 2]
    b = -proj[2, 3]
    if a <= 1.0:
        raise ValueError(
            "projection matrix has degenerate near/far "
            f"(-proj[2,2]={a}, must be > 1)"
        )
    near = b / (a + 1.0)
    far = b / (a - 1.0)

    return float(fovy_rad), float(aspect), float(near), float(far)


def _numpy_to_gf_matrix4d(world_np: np.ndarray) -> Gf.Matrix4d:
    """Convert a 4×4 numpy column-vector matrix to a ``Gf.Matrix4d`` row-vector matrix."""
    # numpy column-vector → Gf row-vector means transpose. Gf.Matrix4d
    # accepts 16 scalars in row-major order.
    flat = world_np.T.astype(np.float64).flatten().tolist()
    return Gf.Matrix4d(*flat)


def _world_matrix_from_view(view_matrix: np.ndarray) -> Gf.Matrix4d:
    view_np = np.asarray(view_matrix, dtype=np.float64)
    if view_np.shape != (4, 4):
        raise ValueError(f"view_matrix must be 4x4, got {view_np.shape}")
    return _numpy_to_gf_matrix4d(np.linalg.inv(view_np))


def _local_matrix_for_world(cam_prim: Usd.Prim, world: Gf.Matrix4d) -> Gf.Matrix4d:
    parent = cam_prim.GetParent()
    if not parent or not parent.IsValid() or parent.GetPath() == Sdf.Path.absoluteRootPath:
        return world
    parent_world = UsdGeom.XformCache().GetLocalToWorldTransform(parent)
    return world * parent_world.GetInverse()


def compute_camera_intrinsics(
    proj_matrix: np.ndarray,
) -> Tuple[float, float, float, float, float]:
    """Decompose a GL perspective into ``(focal, h_ap, v_ap, near, far)``.

    Reused by :func:`write_camera_from_matrices` (which authors the values
    on the pxr stage's session layer for Property Inspector consistency)
    and by :class:`ovui_data_adapters.openusd.renderer_adapter.OvRtxRendererAdapter`
    (which pushes the same values into ovrtx Fabric every frame so the
    rendered image and the ``omni.ui.scene`` overlay use the same camera).
    """
    fovy_rad, aspect, near, far = _decompose_perspective(proj_matrix)
    fovx = 2.0 * math.atan(math.tan(fovy_rad * 0.5) * aspect)
    h_aperture = _FIXED_HORIZONTAL_APERTURE
    focal_length = 0.5 * h_aperture / math.tan(fovx * 0.5)
    v_aperture = h_aperture / aspect
    return float(focal_length), float(h_aperture), float(v_aperture), float(near), float(far)


def write_camera_from_matrices(
    stage: Usd.Stage,
    camera_path: str,
    view_matrix: np.ndarray,
    proj_matrix: np.ndarray,
    width: int,
    height: int,
) -> None:
    """Write camera world transform + intrinsics derived from GL matrices.

    Parameters
    ----------
    stage :
        Target USD stage. Must already have a ``Camera`` prim at
        ``camera_path`` (typically created by
        :func:`ovui_data_adapters.openusd._session_authoring.ensure_camera`).
    camera_path :
        Absolute prim path to the session-layer camera.
    view_matrix, proj_matrix :
        4×4 numpy arrays, OpenGL convention, row-major storage,
        column-vector math. Produced by
        :meth:`ovui_widgets.viewport.camera_controller.CameraController.get_matrices`.
    width, height :
        Viewport pixel dimensions. Accepted for signature stability with
        the adapter's per-frame call; aspect is already encoded in
        ``proj_matrix`` so these are not used for the attribute math.

    All writes go to the session layer. Existing non-transform xform ops
    are cleared so the camera is driven by a single ``xformOp:transform``.
    """
    view_np = np.asarray(view_matrix, dtype=np.float64)
    if view_np.shape != (4, 4):
        raise ValueError(f"view_matrix must be 4x4, got {view_np.shape}")

    cam_prim = stage.GetPrimAtPath(camera_path)
    if not cam_prim.IsValid():
        raise ValueError(f"no prim at camera_path={camera_path!r}")
    if not cam_prim.IsA(UsdGeom.Camera):
        raise ValueError(
            f"prim at {camera_path!r} is not a UsdGeomCamera "
            f"(type={cam_prim.GetTypeName()!r})"
        )
    cam = UsdGeom.Camera(cam_prim)

    # Camera world transform is the inverse of the view matrix.
    world_np = np.linalg.inv(view_np)
    gf_world = _numpy_to_gf_matrix4d(world_np)

    focal_length, h_aperture, v_aperture, near, far = compute_camera_intrinsics(
        proj_matrix
    )

    with Usd.EditContext(stage, stage.GetSessionLayer()):
        xformable = UsdGeom.Xformable(cam_prim)
        ops = xformable.GetOrderedXformOps()
        if len(ops) == 1 and ops[0].GetOpType() == UsdGeom.XformOp.TypeTransform:
            transform_op = ops[0]
        else:
            xformable.ClearXformOpOrder()
            transform_op = xformable.AddTransformOp()
        transform_op.Set(gf_world)

        cam.GetFocalLengthAttr().Set(float(focal_length))
        cam.GetHorizontalApertureAttr().Set(float(h_aperture))
        cam.GetVerticalApertureAttr().Set(float(v_aperture))
        cam.GetClippingRangeAttr().Set(Gf.Vec2f(float(near), float(far)))


def write_scene_camera_pose_from_matrices(
    stage: Usd.Stage,
    camera_path: str,
    view_matrix: np.ndarray,
    target_world: Tuple[float, float, float],
) -> None:
    """Author a selected scene camera's pose in the current edit target.

    Unlike :func:`write_camera_from_matrices`, this is for user-selected USD
    cameras, not the owned runtime/session camera. It writes through the
    stage's current edit target so the camera prim visible in Properties is
    the camera being moved. The authored transform is parent-relative when
    the camera lives under Xform ancestors, but composes back to the world
    matrix represented by ``view_matrix``.
    """
    cam_prim = stage.GetPrimAtPath(camera_path)
    if not cam_prim.IsValid():
        raise ValueError(f"no prim at camera_path={camera_path!r}")
    if not cam_prim.IsA(UsdGeom.Camera):
        raise ValueError(
            f"prim at {camera_path!r} is not a UsdGeomCamera "
            f"(type={cam_prim.GetTypeName()!r})"
        )

    world = _world_matrix_from_view(view_matrix)
    local = _local_matrix_for_world(cam_prim, world)
    xformable = UsdGeom.Xformable(cam_prim)
    xformable.MakeMatrixXform().Set(local)

    target = Gf.Vec3d(
        float(target_world[0]),
        float(target_world[1]),
        float(target_world[2]),
    )
    local_target = world.GetInverse().Transform(target)
    coi_attr = cam_prim.GetAttribute("omni:kit:centerOfInterest")
    if not coi_attr:
        coi_attr = cam_prim.CreateAttribute(
            "omni:kit:centerOfInterest",
            Sdf.ValueTypeNames.Double3,
            custom=True,
        )
    coi_attr.Set(Gf.Vec3d(local_target[0], local_target[1], local_target[2]))
    distance = (
        local_target[0] * local_target[0]
        + local_target[1] * local_target[1]
        + local_target[2] * local_target[2]
    ) ** 0.5
    UsdGeom.Camera(cam_prim).GetFocusDistanceAttr().Set(float(distance))
