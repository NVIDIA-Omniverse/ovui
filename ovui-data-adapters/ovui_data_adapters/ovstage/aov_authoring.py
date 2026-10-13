# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Atomic native render-graph authoring for the compact Create AOV workflow."""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from ovui_data_adapters.common import (
    AovAuthoringPreview,
    AovAuthoringRequest,
    CreateActionErrorCode,
    CreateResult,
)
from ovui_data_adapters.ovstage._authoring import (
    MISSING,
    NativeValueDescriptor,
    NativeValueEditCommand,
)
from ovui_data_adapters.ovstage._catalog import native_catalog_snapshot
from ovui_data_adapters.ovstage._structural import (
    NativeClonePrimsCommand,
    NativeCreatePrimsCommand,
)
from ovui_data_adapters.ovstage.runtime_import import import_ovstage_runtime_module


_LDR_PATH = "/Render/Vars/LdrColor"
_PRODUCT_PARENT = "/Render/Products"
_CAMERA_PARENT = "/Render/Cameras"
_VARS_PARENT = "/Render/Vars"
_RENDER_PRODUCT_TYPE_NAMES = {"renderproduct", "usdrenderproduct"}
_RENDER_VAR_TYPE_NAMES = {"rendervar", "usdrendervar"}
_CAMERA_TYPE_NAMES = {"camera", "usdgeomcamera"}
_RELATIONSHIP_DESCRIPTOR = NativeValueDescriptor(
    name="orderedVars",
    dtype=(1, 64, 1),
    semantic=4,
    native_is_array=True,
    logical_is_array=True,
)
_TOKEN_DESCRIPTOR = NativeValueDescriptor(
    name="omni:rtx:rendermode",
    dtype=(1, 64, 1),
    semantic=2,
    native_is_array=False,
    logical_is_array=False,
)
_SOURCE_NAME_DESCRIPTOR = NativeValueDescriptor(
    name="sourceName",
    dtype=(1, 8, 1),
    semantic=13,
    native_is_array=True,
    logical_is_array=False,
)


def preview_aov_authoring(adapter: Any, request: Any) -> AovAuthoringPreview:
    if not isinstance(request, AovAuthoringRequest):
        return _rejected_preview("Invalid AOV authoring request.")
    if request.render_var_name in {"", "LdrColor"}:
        return _rejected_preview("Choose a non-beauty AOV output.")
    output_path = f"{_VARS_PARENT}/{request.render_var_name}"
    scene = getattr(adapter, "_scene", None)
    stage = getattr(scene, "_stage", None)
    if scene is None or stage is None or not getattr(scene, "is_open", False):
        return _rejected_preview("Open an editable native stage first.")
    snapshot = native_catalog_snapshot(scene)

    collision = _render_var_collision(snapshot, _LDR_PATH, "LdrColor")
    if collision:
        return _rejected_preview(collision, output_path=output_path)
    collision = _render_var_collision(snapshot, output_path, request.source_name)
    if collision:
        return _rejected_preview(collision, output_path=output_path)

    product_path = str(request.render_product_path or "")
    existing_product = bool(product_path)
    camera_path = str(request.camera_path or "")
    create_camera = False
    mode = str(request.render_mode or "")
    metadata: dict[str, Any] = {}

    if existing_product:
        product = snapshot.prim(product_path)
        if product is None or product.type_name.lower() not in _RENDER_PRODUCT_TYPE_NAMES:
            return _rejected_preview(
                f"{product_path} is not a current RenderProduct.",
                output_path=output_path,
            )
        camera_targets = _path_values(product.value("camera"))
        if len(camera_targets) != 1:
            return _rejected_preview(
                f"{product_path} must have exactly one valid camera target.",
                product_path=product_path,
                output_path=output_path,
            )
        camera = snapshot.prim(camera_targets[0])
        if camera is None or camera.type_name.lower() not in _CAMERA_TYPE_NAMES:
            return _rejected_preview(
                f"{product_path} camera target is unavailable.",
                product_path=product_path,
                output_path=output_path,
            )
        camera_path = camera_targets[0]
        resolution = _positive_resolution(product.value("resolution"))
        if resolution is None:
            return _rejected_preview(
                f"{product_path} must have a positive resolution.",
                product_path=product_path,
                camera_path=camera_path,
                output_path=output_path,
            )
        ordered_vars = _path_values(product.value("orderedVars"))
        if _LDR_PATH not in ordered_vars:
            return _rejected_preview(
                f"{product_path} must target the canonical LdrColor RenderVar.",
                product_path=product_path,
                camera_path=camera_path,
                output_path=output_path,
            )
        authored_mode = str(product.value("omni:rtx:rendermode") or "")
        metadata.update(
            ordered_vars=ordered_vars,
            resolution=resolution,
            authored_render_mode=authored_mode,
        )
    else:
        product_path = adapter._next_unique_child_path(_PRODUCT_PARENT, "AOVProduct")
        if camera_path:
            camera = snapshot.prim(camera_path)
            if camera is None or camera.type_name.lower() not in _CAMERA_TYPE_NAMES:
                return _rejected_preview(
                    f"{camera_path} is not a current Camera.",
                    product_path=product_path,
                    output_path=output_path,
                )
        else:
            if request.camera_state is None:
                return _rejected_preview(
                    "Current View camera data is unavailable.",
                    product_path=product_path,
                    output_path=output_path,
                )
            camera_path = adapter._next_unique_child_path(_CAMERA_PARENT, "AOVCamera")
            create_camera = True

    return AovAuthoringPreview(
        accepted=True,
        message="Ready to create and display this AOV.",
        render_product_path=product_path,
        camera_path=camera_path,
        ldr_render_var_path=_LDR_PATH,
        output_render_var_path=output_path,
        render_mode=mode,
        existing_product=existing_product,
        create_camera=create_camera,
        create_ldr_render_var=snapshot.prim(_LDR_PATH) is None,
        create_output_render_var=snapshot.prim(output_path) is None,
        metadata=metadata,
    )


def author_aov_graph(adapter: Any, request: Any) -> CreateResult:
    preview = preview_aov_authoring(adapter, request)
    if not preview.accepted:
        return CreateResult.rejected_result(
            message=preview.message,
            error_code=CreateActionErrorCode.VALIDATION_FAILED,
        )
    assert isinstance(request, AovAuthoringRequest)
    manager = getattr(adapter, "_undo_manager", None)
    if manager is None:
        return CreateResult.rejected_result(
            message="AOV authoring requires the application undo service.",
            error_code=CreateActionErrorCode.UNSUPPORTED,
        )

    adapter.begin_undo_group("Create AOV")
    try:
        if preview.existing_product:
            _author_existing_product(adapter, request, preview)
        else:
            _author_new_product(adapter, request, preview)
        adapter.end_undo_group()
    except BaseException:
        adapter.abort_undo_group()
        raise

    created_paths = tuple(
        path
        for path, created in (
            (preview.camera_path, preview.create_camera),
            (preview.ldr_render_var_path, preview.create_ldr_render_var),
            (preview.output_render_var_path, preview.create_output_render_var),
            (preview.render_product_path, not preview.existing_product),
        )
        if created
    )
    return CreateResult.accepted_result(
        created_paths=created_paths,
        primary_path=preview.output_render_var_path,
        selection_paths=(preview.output_render_var_path,),
        focus_path=preview.output_render_var_path,
        message=f"Created and wired {request.source_name} for display.",
        metadata={
            "render_product_path": preview.render_product_path,
            "camera_path": preview.camera_path,
            "render_var_path": preview.output_render_var_path,
            "render_var_name": request.render_var_name,
            "source_name": request.source_name,
            "render_mode": request.render_mode,
        },
    )


def _author_new_product(
    adapter: Any,
    request: AovAuthoringRequest,
    preview: AovAuthoringPreview,
) -> None:
    parent_rows: list[tuple[str, str]] = []
    for parent in (_PRODUCT_PARENT, _CAMERA_PARENT, _VARS_PARENT):
        parent_rows.extend(adapter._missing_default_parent_rows(parent))
    parent_rows = list(dict.fromkeys(parent_rows))
    rows = list(parent_rows)
    if preview.create_camera:
        rows.append((preview.camera_path, "Camera"))
    if preview.create_ldr_render_var:
        rows.append((preview.ldr_render_var_path, "RenderVar"))
    if preview.create_output_render_var:
        rows.append((preview.output_render_var_path, "RenderVar"))
    rows.append((preview.render_product_path, "RenderProduct"))
    rows = list(dict.fromkeys(rows))

    token_attributes: dict[str, dict[str, str]] = {
        preview.render_product_path: {
            "omni:rtx:rendermode": request.render_mode,
        }
    }
    fixed_attributes: dict[str, dict[str, tuple[Any, int, Any]]] = {
        preview.render_product_path: {
            "resolution": (
                np.asarray(request.resolution, dtype=np.int32),
                2,
                0,
            )
        }
    }
    if preview.create_camera:
        assert request.camera_state is not None
        camera_attributes, projection = _camera_attributes(request.camera_state)
        token_attributes[preview.camera_path] = {"projection": projection}
        fixed_attributes[preview.camera_path] = camera_attributes

    relationship_attributes = {
        preview.render_product_path: {
            "camera": (preview.camera_path,),
            "orderedVars": (
                preview.ldr_render_var_path,
                preview.output_render_var_path,
            ),
        }
    }
    templates = (
        str(request.template_render_product_path or ""),
        str(request.template_camera_path or ""),
        str(request.template_ldr_render_var_path or ""),
    )
    if all(templates):
        if parent_rows:
            adapter._push_structural_command(
                NativeCreatePrimsCommand(
                    adapter._scene,
                    parent_rows,
                    promoted_paths=("/Render",),
                )
            )
        template_product, template_camera, template_ldr = templates
        clones: list[tuple[str, str, str]] = []
        if preview.create_camera:
            clones.append((template_camera, preview.camera_path, "Camera"))
        if preview.create_ldr_render_var:
            clones.append((template_ldr, preview.ldr_render_var_path, "RenderVar"))
        if preview.create_output_render_var:
            clones.append((template_ldr, preview.output_render_var_path, "RenderVar"))
        clones.append((template_product, preview.render_product_path, "RenderProduct"))
        adapter._push_structural_command(
            NativeClonePrimsCommand(
                adapter._scene,
                clones,
                token_attributes=token_attributes,
                fixed_attributes=fixed_attributes,
                relationship_attributes=relationship_attributes,
            )
        )
        if preview.create_output_render_var:
            _push_value_edit(
                adapter,
                preview.output_render_var_path,
                _SOURCE_NAME_DESCRIPTOR,
                "LdrColor",
                request.source_name,
            )
        return
    adapter._push_structural_command(
        NativeCreatePrimsCommand(
            adapter._scene,
            rows,
            token_attributes=token_attributes,
            fixed_attributes=fixed_attributes,
            relationship_attributes=relationship_attributes,
            promoted_paths=("/Render",),
        )
    )
    if preview.create_ldr_render_var:
        _push_value_edit(
            adapter,
            preview.ldr_render_var_path,
            _SOURCE_NAME_DESCRIPTOR,
            MISSING,
            "LdrColor",
        )
    if preview.create_output_render_var:
        _push_value_edit(
            adapter,
            preview.output_render_var_path,
            _SOURCE_NAME_DESCRIPTOR,
            MISSING,
            request.source_name,
        )


def _author_existing_product(
    adapter: Any,
    request: AovAuthoringRequest,
    preview: AovAuthoringPreview,
) -> None:
    if preview.create_output_render_var:
        rows = (*adapter._missing_default_parent_rows(_VARS_PARENT), (
            preview.output_render_var_path,
            "RenderVar",
        ))
        parent_rows = tuple(
            row
            for row in dict.fromkeys(rows)
            if row[0] != preview.output_render_var_path
        )
        if parent_rows:
            adapter._push_structural_command(
                NativeCreatePrimsCommand(
                    adapter._scene,
                    parent_rows,
                    promoted_paths=("/Render",),
                )
            )
        template_ldr = str(request.template_ldr_render_var_path or "")
        command_type = NativeClonePrimsCommand if template_ldr else NativeCreatePrimsCommand
        command_args = (
            ((template_ldr, preview.output_render_var_path, "RenderVar"),)
            if template_ldr
            else ((preview.output_render_var_path, "RenderVar"),)
        )
        adapter._push_structural_command(
            command_type(
                adapter._scene,
                command_args,
            )
        )
        _push_value_edit(
            adapter,
            preview.output_render_var_path,
            _SOURCE_NAME_DESCRIPTOR,
            "LdrColor" if template_ldr else MISSING,
            request.source_name,
        )
    ordered_vars = tuple(preview.metadata.get("ordered_vars", ()))
    if preview.output_render_var_path not in ordered_vars:
        _push_value_edit(
            adapter,
            preview.render_product_path,
            _RELATIONSHIP_DESCRIPTOR,
            ordered_vars,
            (*ordered_vars, preview.output_render_var_path),
        )
    previous_mode = str(preview.metadata.get("authored_render_mode") or "")
    if request.render_mode and request.render_mode != previous_mode:
        _push_value_edit(
            adapter,
            preview.render_product_path,
            _TOKEN_DESCRIPTOR,
            previous_mode if previous_mode else MISSING,
            request.render_mode,
        )


def _push_value_edit(
    adapter: Any,
    path: str,
    descriptor: NativeValueDescriptor,
    old_value: Any,
    new_value: Any,
) -> None:
    adapter._push_structural_command(
        NativeValueEditCommand(
            adapter._scene,
            (path,),
            descriptor,
            (old_value,),
            (new_value,),
            source="aov:author",
        )
    )


def _camera_attributes(camera_state: Any) -> tuple[dict[str, tuple[Any, int, Any]], str]:
    view = np.asarray(camera_state.view_matrix, dtype=np.float64)
    projection = np.asarray(camera_state.projection_matrix, dtype=np.float64)
    if view.shape != (4, 4) or projection.shape != (4, 4):
        raise ValueError("Current View requires 4x4 view and projection matrices.")
    world = np.ascontiguousarray(np.linalg.inv(view).T, dtype=np.float64).reshape(-1)
    fx = abs(float(projection[0, 0]))
    fy = abs(float(projection[1, 1]))
    if fx <= 1.0e-9 or fy <= 1.0e-9:
        raise ValueError("Current View projection is invalid.")
    orthographic = bool(
        np.isclose(projection[3, 3], 1.0)
        and np.isclose(projection[3, 2], 0.0)
    )
    if orthographic:
        focal = 50.0
        horizontal_aperture = 20.0 / fx
        vertical_aperture = 20.0 / fy
        projection_token = "orthographic"
    else:
        vertical_aperture = 15.2908
        horizontal_aperture = vertical_aperture * fy / fx
        focal = 0.5 * vertical_aperture * fy
        projection_token = "perspective"
    matrix_semantic = import_ovstage_runtime_module("ovstage").AttributeSemantic.MATRIX
    return (
        {
            "omni:xform": (world, 16, matrix_semantic),
            "focalLength": (np.asarray([focal], dtype=np.float32), 1, 0),
            "horizontalAperture": (
                np.asarray([horizontal_aperture], dtype=np.float32),
                1,
                0,
            ),
            "verticalAperture": (
                np.asarray([vertical_aperture], dtype=np.float32),
                1,
                0,
            ),
        },
        projection_token,
    )


def _render_var_collision(snapshot: Any, path: str, source_name: str) -> str:
    prim = snapshot.prim(path)
    if prim is None:
        return ""
    if prim.type_name.lower() not in _RENDER_VAR_TYPE_NAMES:
        return f"{path} is occupied by an incompatible prim."
    actual_source = str(prim.value("sourceName") or "")
    if actual_source != source_name:
        return (
            f"{path} has Source Name {actual_source or '<unset>'}; "
            f"expected {source_name}."
        )
    return ""


def _path_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values: Iterable[Any] = (value,)
    elif isinstance(value, (tuple, list)):
        values = value
    else:
        return ()
    return tuple(str(item) for item in values if str(item).startswith("/"))


def _positive_resolution(value: Any) -> tuple[int, int] | None:
    try:
        width, height = (int(item) for item in value)
    except (TypeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def _rejected_preview(
    message: str,
    *,
    product_path: str = "",
    camera_path: str = "",
    output_path: str = "",
) -> AovAuthoringPreview:
    return AovAuthoringPreview(
        accepted=False,
        message=message,
        render_product_path=product_path,
        camera_path=camera_path,
        output_render_var_path=output_path,
    )


__all__ = ["author_aov_graph", "preview_aov_authoring"]
