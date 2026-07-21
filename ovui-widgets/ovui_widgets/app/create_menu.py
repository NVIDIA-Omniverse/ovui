# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Create-menu UI dispatch for the standalone USD Viewer."""

from __future__ import annotations

import os
import sys
from typing import Any

import omni.ui as ui
from ovui_data_adapters.common import get_adapter_factories


_ADAPTER_PROVIDER_ENV = "OVUI_DATA_ADAPTER_PROVIDER"

MESH_MENU_ORDER = ("Cone", "Cube", "Cylinder", "Disk", "Plane", "Sphere", "Torus")
SHAPE_MENU_ORDER = ("Capsule", "Cone", "Cube", "Cylinder", "Sphere")
LIGHT_MENU_ORDER = (
    ("Cylinder Light", "CylinderLight"),
    ("Disk Light", "DiskLight"),
    ("Distant Light", "DistantLight"),
    ("Dome Light", "DomeLight"),
    ("Rect Light", "RectLight"),
    ("Sphere Light", "SphereLight"),
)


def _requested_provider_name() -> str | None:
    raw = os.environ.get(_ADAPTER_PROVIDER_ENV, "")
    provider_name = raw.strip()
    return provider_name or None


def _provider_session(app: Any) -> Any:
    getter = getattr(app, "get_adapter_session", None)
    if callable(getter):
        return getter()
    factories = get_adapter_factories(requested_name=_requested_provider_name())
    session_factory = factories.session
    if not callable(session_factory):
        raise RuntimeError("selected data adapter does not provide application helpers")
    return session_factory(app)


def _create_prims_enabled(app: Any) -> bool:
    try:
        session = _provider_session(app)
    except Exception:
        return False
    can_create = getattr(session, "can_create_prims", None)
    if callable(can_create):
        return bool(can_create())
    return True


def _call_create(app: Any, method_name: str, *args: Any) -> Any | None:
    session = _provider_session(app)
    can_create = getattr(session, "can_create_prims", None)
    if callable(can_create) and not can_create():
        return None
    return getattr(session, method_name)(*args)


def build_create_menu(app: Any) -> None:
    """Build the Create menu contents inside an ``omni.ui.Menu`` context."""
    registry = getattr(app, "menus", None)
    build_path = getattr(registry, "build_path", None)
    iter_contributions = getattr(registry, "iter_contributions", None)
    if callable(build_path) and callable(iter_contributions):
        try:
            if iter_contributions(("Create",)):
                build_path(("Create",), ui)
                return
        except Exception as exc:
            print(
                "[ovui_widgets.app.create_menu] contributed Create menu failed: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    enabled = _create_prims_enabled(app)
    with ui.Menu("Mesh"):
        for mesh_name in MESH_MENU_ORDER:
            ui.MenuItem(
                mesh_name,
                triggered_fn=lambda name=mesh_name: create_mesh_prim(app, name),
                enabled=enabled,
            )

    with ui.Menu("Shape"):
        for shape_name in SHAPE_MENU_ORDER:
            ui.MenuItem(
                shape_name,
                triggered_fn=lambda name=shape_name: create_shape_prim(app, name),
                enabled=enabled,
            )

    with ui.Menu("Light"):
        for label, type_name in LIGHT_MENU_ORDER:
            ui.MenuItem(
                label,
                triggered_fn=lambda t=type_name: create_light_prim(app, t),
                enabled=enabled,
            )

    ui.MenuItem("Camera", triggered_fn=lambda: create_camera(app), enabled=enabled)
    ui.Separator()
    ui.MenuItem("Scope", triggered_fn=lambda: create_scope(app), enabled=enabled)
    ui.Separator()
    ui.MenuItem("Xform", triggered_fn=lambda: create_xform(app), enabled=enabled)

    with ui.Menu("Material"):
        with ui.Menu("USD Materials"):
            ui.MenuItem(
                "USD Preview Surface",
                triggered_fn=lambda: create_usd_preview_surface_material(app),
                enabled=enabled,
            )


def create_mesh_prim(app: Any, mesh_name: str) -> Any | None:
    return _call_create(app, "create_mesh_prim", app, mesh_name)


def create_shape_prim(app: Any, shape_name: str) -> Any | None:
    return _call_create(app, "create_shape_prim", app, shape_name)


def create_light_prim(app: Any, light_type: str) -> Any | None:
    return _call_create(app, "create_light_prim", app, light_type)


def create_camera(app: Any) -> Any | None:
    return _call_create(app, "create_camera", app)


def create_scope(app: Any) -> Any | None:
    return _call_create(app, "create_scope", app)


def create_xform(app: Any) -> Any | None:
    return _call_create(app, "create_xform", app)


def create_usd_preview_surface_material(app: Any) -> Any | None:
    return _call_create(app, "create_usd_preview_surface_material", app)


def create_mesh_cone(app: Any) -> Any | None:
    return create_mesh_prim(app, "Cone")


def create_mesh_cube(app: Any) -> Any | None:
    return create_mesh_prim(app, "Cube")


def create_mesh_cylinder(app: Any) -> Any | None:
    return create_mesh_prim(app, "Cylinder")


def create_mesh_disk(app: Any) -> Any | None:
    return create_mesh_prim(app, "Disk")


def create_mesh_plane(app: Any) -> Any | None:
    return create_mesh_prim(app, "Plane")


def create_mesh_sphere(app: Any) -> Any | None:
    return create_mesh_prim(app, "Sphere")


def create_mesh_torus(app: Any) -> Any | None:
    return create_mesh_prim(app, "Torus")


def create_shape_capsule(app: Any) -> Any | None:
    return create_shape_prim(app, "Capsule")


def create_shape_cone(app: Any) -> Any | None:
    return create_shape_prim(app, "Cone")


def create_shape_cube(app: Any) -> Any | None:
    return create_shape_prim(app, "Cube")


def create_shape_cylinder(app: Any) -> Any | None:
    return create_shape_prim(app, "Cylinder")


def create_shape_sphere(app: Any) -> Any | None:
    return create_shape_prim(app, "Sphere")


def create_cylinder_light(app: Any) -> Any | None:
    return create_light_prim(app, "CylinderLight")


def create_disk_light(app: Any) -> Any | None:
    return create_light_prim(app, "DiskLight")


def create_distant_light(app: Any) -> Any | None:
    return create_light_prim(app, "DistantLight")


def create_dome_light(app: Any) -> Any | None:
    return create_light_prim(app, "DomeLight")


def create_rect_light(app: Any) -> Any | None:
    return create_light_prim(app, "RectLight")


def create_sphere_light(app: Any) -> Any | None:
    return create_light_prim(app, "SphereLight")


def get_geometry_standard_prim_attrs(stage: Any) -> dict[str, dict[Any, Any]]:
    return _provider_session(None).get_geometry_standard_prim_attrs(stage)


def get_light_prim_attrs(stage: Any) -> dict[str, dict[Any, Any]]:
    return _provider_session(None).get_light_prim_attrs(stage)


def get_next_free_prim_path(stage: Any, child_name: str) -> Any:
    return _provider_session(None).get_next_free_prim_path(stage, child_name)


def get_next_free_path(stage: Any, base_path: Any) -> Any:
    return _provider_session(None).get_next_free_path(stage, base_path)
