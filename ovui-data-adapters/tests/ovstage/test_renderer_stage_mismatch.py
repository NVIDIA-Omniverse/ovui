# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""An ovrtx that refuses an ovstage that does not match it is reported in plain words."""

from __future__ import annotations

from typing import Any

import pytest
from test_renderer_livestream import (
    _FakeRenderer,
    _FakeScene,
    _patch_adapter_construction,
)

from ovui_data_adapters.common import RendererStageMismatchError
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter


def test_attach_refusal_of_a_mismatched_stage_library_names_the_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refusal = RuntimeError(
        "Failed to attach ovstage: ovrtx_attach_ovstage: "
        "attached ovstage does not publish the internal accessor extension"
    )

    def attach_ovstage(_self: Any, _stage: Any) -> None:
        raise refusal

    _patch_adapter_construction(monkeypatch)
    monkeypatch.setattr(_FakeRenderer, "attach_ovstage", attach_ovstage)
    scene = _FakeScene()
    adapter = OvstageRendererAdapter()
    try:
        with pytest.raises(RendererStageMismatchError) as caught:
            adapter.load_stage(scene)
    finally:
        adapter.shutdown()

    message = str(caught.value)
    assert "installed renderer library (ovrtx)" in message
    assert "installed stage library (ovstage)" in message
    assert "do not match" in message
    assert caught.value.__cause__ is refusal
    assert scene.presentation_root_paths == set()
