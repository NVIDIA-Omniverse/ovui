# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Truthful renderer attachment and native viewport projection reporting.

Current ovrtx 0.4 wheels expose neither a public ``AttachMode`` enum nor a
``RendererConfig.attach_mode`` field, so borrow-mode reporting must derive
from live native evidence (the renderer-retained borrowed-stage identity)
instead of claiming ``False`` on a genuinely borrowed attachment — or
claiming ``True`` without proof.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ovui_widgets.app.inspector_state import (
    _renderer_snapshot,
    _viewport_snapshot,
)


def _app_with_renderer(renderer: Any) -> SimpleNamespace:
    return SimpleNamespace(_viewport_window=SimpleNamespace(_renderer=renderer))


def _adapter(native: Any, stage: Any) -> SimpleNamespace:
    return SimpleNamespace(
        _renderer=native, _ovrtx=SimpleNamespace(), _attached_stage=stage
    )


def test_borrow_mode_is_claimed_only_with_native_attachment_proof() -> None:
    stage = object()
    attached = SimpleNamespace(config=SimpleNamespace(), _attached_ovstage=stage)
    snapshot = _renderer_snapshot(
        _app_with_renderer(_adapter(attached, stage)),
        SimpleNamespace(_stage=stage),
    )
    assert snapshot["is_borrow_mode"] is True
    assert snapshot["attach_mode"] == "borrow"
    assert snapshot["attach_mode_source"] == "native_attach_ovstage"
    assert snapshot["native_attached_exact_ovstage"] is True

    # A renderer retaining a DIFFERENT stage is not proof: no borrow claim.
    other = SimpleNamespace(config=SimpleNamespace(), _attached_ovstage=object())
    snapshot = _renderer_snapshot(
        _app_with_renderer(_adapter(other, stage)),
        SimpleNamespace(_stage=stage),
    )
    assert snapshot["is_borrow_mode"] is False
    assert snapshot["attach_mode"] == ""
    assert snapshot["native_attached_exact_ovstage"] is False


def test_native_projection_consumes_provider_user_facing_classification() -> None:
    """Projection targets follow the provider's ownership rule exactly.

    Adversarial pairs a path-prefix heuristic would get wrong: a
    non-user-facing ``/RendererPresentation`` root (false positive) and a
    user-AUTHORED ``/Render`` prim (false negative). Prims without a
    recorded classification (ownership rule unavailable) are excluded —
    fail closed, never guess.
    """
    identity = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    viewport = SimpleNamespace(
        _image=SimpleNamespace(
            computed_width=200,
            computed_height=100,
            screen_position_x=10.0,
            screen_position_y=20.0,
        ),
        _camera=SimpleNamespace(get_matrices=lambda w, h: (identity, identity)),
        _toolbar_buttons={},
        _camera_menu=None,
        _camera_menu_items=(),
        get_viewport_state_snapshot=lambda: None,
    )
    app = SimpleNamespace(
        _viewport_window=viewport,
        _stage_adapter=SimpleNamespace(
            compute_world_aabb=lambda paths: ((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))
        ),
    )

    native_snapshot = {
        "available": True,
        "prims": {
            "/World": {"user_facing": True},
            "/World/Cube": {"user_facing": True},
            "/Render": {"user_facing": True},  # authored-/Render exception
            "/RendererPresentation": {"user_facing": False},
            "/omni_rtx_loadingStatePrim": {"user_facing": False},
        },
    }
    snapshot = _viewport_snapshot(app, {"available": False}, native_snapshot)
    centers = snapshot["prim_screen_centers"]
    assert set(centers) == {"/World", "/World/Cube", "/Render"}
    assert centers["/World/Cube"] == [110, 70]  # image center

    unclassified = {
        "available": True,
        "paths": ["/World", "/RendererPresentation"],
        "prims": {"/World": {}, "/RendererPresentation": {}},
    }
    snapshot = _viewport_snapshot(app, {"available": False}, unclassified)
    assert snapshot["prim_screen_centers"] == {}
