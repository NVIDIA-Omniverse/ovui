# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Provider-neutral contracts for the compact Create AOV workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class AovOutputDescriptor:
    """One reviewed output supported for authoring and viewport display."""

    output_id: str
    label: str
    source_name: str
    render_var_name: str
    compatible_render_modes: tuple[str, ...]
    note: str = ""

    def is_compatible_with(self, render_mode: str) -> bool:
        return str(render_mode) in self.compatible_render_modes


@dataclass(frozen=True)
class AovAuthoringCatalog:
    """Version-qualified, provider-owned AOV authoring catalog."""

    runtime_version: str = ""
    outputs: tuple[AovOutputDescriptor, ...] = ()
    render_modes: tuple[tuple[str, str], ...] = ()
    enabled: bool = False
    disabled_reason: str = ""
    template_render_product_path: str = ""
    template_camera_path: str = ""
    template_ldr_render_var_path: str = ""

    def output(self, output_id: str) -> AovOutputDescriptor | None:
        return next(
            (item for item in self.outputs if item.output_id == str(output_id)),
            None,
        )


@dataclass(frozen=True)
class AovCameraState:
    """Owned current-view matrices used when a new session camera is needed."""

    view_matrix: tuple[tuple[float, ...], ...]
    projection_matrix: tuple[tuple[float, ...], ...]
    width: int
    height: int


@dataclass(frozen=True)
class AovAuthoringRequest:
    """The complete user choice needed to author one displayable AOV graph."""

    output_id: str
    source_name: str
    render_var_name: str
    render_mode: str
    render_product_path: str = ""
    camera_path: str = ""
    camera_state: AovCameraState | None = None
    resolution: tuple[int, int] = (1280, 720)
    template_render_product_path: str = ""
    template_camera_path: str = ""
    template_ldr_render_var_path: str = ""


@dataclass(frozen=True)
class AovAuthoringPreview:
    """Deterministic preflight and exact path preview for the dialog."""

    accepted: bool = False
    message: str = ""
    render_product_path: str = ""
    camera_path: str = ""
    ldr_render_var_path: str = "/Render/Vars/LdrColor"
    output_render_var_path: str = ""
    render_mode: str = ""
    existing_product: bool = False
    create_camera: bool = False
    create_ldr_render_var: bool = False
    create_output_render_var: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = [
    "AovAuthoringCatalog",
    "AovAuthoringPreview",
    "AovAuthoringRequest",
    "AovCameraState",
    "AovOutputDescriptor",
]
