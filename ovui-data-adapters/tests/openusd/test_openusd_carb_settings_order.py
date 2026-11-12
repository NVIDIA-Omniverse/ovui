# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The OpenUSD adapter applies OVUI_OVRTX_CARB_SETTINGS before it creates the renderer.

The OpenUSD adapter needs pxr, so this test is here and not with the other tests of
the variable in ``tests/common/test_ovrtx_carb_settings.py``. It uses a fake ovrtx
module that records the order of the calls. It needs no GPU.
"""

from __future__ import annotations

from types import ModuleType
from typing import Any

import pytest

from ovui_data_adapters.common import ovrtx_carb_settings
from ovui_data_adapters.common.ovrtx_carb_settings import OVRTX_CARB_SETTINGS_ENV
from ovui_data_adapters.openusd import renderer_adapter as openusd_module

DEDUP_KEY = "/persistent/app/material/materialx/disableDeduplication"


class _RendererCreated(Exception):
    """Raised by the fake renderer: the constructor got as far as the renderer."""


def _fake_ovrtx(events: list[tuple[str, Any]]) -> ModuleType:
    module = ModuleType("ovrtx")
    module.__version__ = "0.0.0"

    class RendererConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    class Renderer:
        def __init__(self, config: Any = None) -> None:
            events.append(("create renderer", config))
            raise _RendererCreated

    module.RendererConfig = RendererConfig
    module.Renderer = Renderer
    return module


def test_openusd_adapter_applies_the_settings_before_it_creates_the_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        ovrtx_carb_settings,
        "_publish_with_ovrtx_extension",
        lambda _ovrtx, token, config=None: events.append((f"publish {token}", config)),
    )
    monkeypatch.setattr(openusd_module, "_probe_ovrtx", lambda: True)
    monkeypatch.setattr(openusd_module, "_ovrtx", _fake_ovrtx(events))
    # The fake renderer writes no native log. A log reader started here stays
    # after the failed constructor and is seen by the next tests.
    monkeypatch.setattr(openusd_module, "start_native_log", lambda _owner, _config: None)
    monkeypatch.setenv(OVRTX_CARB_SETTINGS_ENV, f"{DEDUP_KEY}=true")

    with pytest.raises(_RendererCreated):
        openusd_module.OvRtxRendererAdapter()

    assert [name for name, _config in events] == [f"publish --{DEDUP_KEY}=true", "create renderer"]
    # The settings get the config of the renderer that is created next.
    assert events[0][1] is events[1][1] is not None
