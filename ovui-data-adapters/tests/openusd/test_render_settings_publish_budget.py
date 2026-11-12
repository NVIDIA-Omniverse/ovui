# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A settings change is published over several frames, not in one frame.

Canonicalizing the whole catalog takes about 120 ms. With a frame loop, the
adapter runs the steps a few milliseconds per frame, and the newest change
replaces one that is still running. Without a frame loop it publishes at once.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ovui_data_adapters.openusd import renderer_adapter as mod
from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter


def _steps(catalog):
    parts = []
    for item in catalog.items:
        parts.append(item)
        yield
    return tuple(parts)


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setattr(mod, "_RENDER_SETTINGS_CATALOG_REVISION_STEPS_FN", _steps)
    monkeypatch.setattr(mod, "_RENDER_SETTINGS_CATALOG_REVISION_FN", lambda c: tuple(c.items))
    a = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    a._render_setting_batch_depth = 0
    a._catalog = SimpleNamespace(items=(1, 2, 3))
    a.list_render_settings = lambda path=None: a._catalog
    a.get_active_render_product_path = lambda: "/Render/Product"
    events = []
    a._render_settings_subscribers = [(object(), lambda: events.append("changed"))]
    a._render_settings_last_snapshot = ("/Render/Product", (1, 2, 3))
    a.events = events
    return a


def test_without_a_frame_loop_the_change_is_published_at_once(adapter):
    adapter._catalog = SimpleNamespace(items=(1, 2, 4))
    adapter._publish_render_settings_change()
    assert adapter.events == ["changed"]


def test_with_a_frame_loop_the_change_is_published_by_the_frames(adapter, monkeypatch):
    adapter._frame_service_active = True
    adapter._catalog = SimpleNamespace(items=(1, 2, 4))
    # Each step takes one time unit; a frame has two.
    clock = iter(range(10**6))
    monkeypatch.setattr(mod.time, "perf_counter", lambda: next(clock) / 2.0)
    monkeypatch.setattr(mod, "_RENDER_SETTINGS_PUBLISH_BUDGET_S", 1.0)

    adapter._publish_render_settings_change()
    assert adapter.events == []
    frames = 0
    while getattr(adapter, "_render_settings_publish_job", None) is not None:
        adapter._service_render_settings_publish()
        frames += 1
    assert frames > 1
    assert adapter.events == ["changed"]
    assert adapter._render_settings_last_snapshot == ("/Render/Product", (1, 2, 4))


def test_the_newest_change_replaces_one_in_flight_and_an_unchanged_state_is_silent(adapter):
    adapter._frame_service_active = True
    adapter._catalog = SimpleNamespace(items=(9, 9, 9))
    adapter._publish_render_settings_change()
    adapter._catalog = SimpleNamespace(items=(1, 2, 3))  # back to the published state
    adapter._publish_render_settings_change()
    while getattr(adapter, "_render_settings_publish_job", None) is not None:
        adapter._service_render_settings_publish()
    assert adapter.events == []


def test_a_failed_catalog_read_is_reported_and_the_change_is_published_at_once(adapter, capsys):
    adapter._frame_service_active = True

    def fail(path=None):
        raise RuntimeError("catalog unavailable")

    adapter.list_render_settings = fail
    adapter._publish_render_settings_change()
    assert adapter.events == ["changed"]
    error = capsys.readouterr().err
    assert "listing the render settings" in error
    assert "RuntimeError: catalog unavailable" in error
