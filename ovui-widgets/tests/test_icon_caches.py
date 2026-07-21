# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Unit tests for :mod:`ovui_widgets.common.icon_caches`.

Issue #35, Step 2.
Issue #31, Step 5: tests for ``provider()`` added.

Each test runs in an isolated registry via ``monkeypatch.setattr`` so
test ordering does not affect outcomes. The autouse fixture below is
local to this file; the integration tests in
``tests/test_application_shutdown_integration.py`` deliberately do
NOT define such a fixture (they need the real, import-time
registrations to be live — Round 4 F1).
"""
from __future__ import annotations

import types

import pytest

from ovui_widgets.common import icon_caches


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    """Each test gets its own empty registry — no cross-test pollution."""
    monkeypatch.setattr(icon_caches, "_callbacks", [])


def test_register_dict_clears_dict() -> None:
    d = {"k": object()}
    icon_caches.register_dict(d)
    icon_caches.clear_all()
    assert d == {}


def test_register_dict_idempotent_by_dict_identity() -> None:
    """Round 2 F5: even though ``cache.clear`` is a fresh bound method
    each access, registering the same dict twice must dedupe by the
    dict's identity (not the bound method's)."""
    d = {"k": 1}
    icon_caches.register_dict(d)
    icon_caches.register_dict(d)  # MUST be a no-op
    icon_caches.register_dict(d)  # still a no-op
    assert len(icon_caches._callbacks) == 1


def test_register_callback_runs_callback() -> None:
    state = {"called": False}

    def cb() -> None:
        state["called"] = True

    icon_caches.register(cb)
    icon_caches.clear_all()
    assert state["called"] is True


def test_register_idempotent_by_identity() -> None:
    cb = lambda: None  # noqa: E731
    icon_caches.register(cb)
    icon_caches.register(cb)
    icon_caches.register(cb)
    assert len(icon_caches._callbacks) == 1


def test_register_singleton_idempotent() -> None:
    """register_singleton dedups by stable string key
    ``f"singleton:{owner.__name__}.{attr}"``."""
    m = types.ModuleType("fake")
    m._SINGLETON = object()
    icon_caches.register_singleton(m, "_SINGLETON")
    icon_caches.register_singleton(m, "_SINGLETON")
    assert len(icon_caches._callbacks) == 1
    icon_caches.clear_all()
    assert m._SINGLETON is None


def test_clear_all_continues_on_callback_error() -> None:
    state = {"second_ran": False}

    def _raise() -> None:
        raise RuntimeError("boom")

    icon_caches.register(_raise)
    icon_caches.register(lambda: state.__setitem__("second_ran", True))
    icon_caches.clear_all()  # MUST NOT raise
    assert state["second_ran"] is True


def test_singleton_pattern_supported() -> None:
    """Singletons clear via :func:`register_singleton` — sets the
    named attribute on the owner to ``None``."""
    fake_module = types.ModuleType("fake_module")
    fake_module._LOGO = object()
    icon_caches.register_singleton(fake_module, "_LOGO")
    icon_caches.clear_all()
    assert fake_module._LOGO is None


def test_register_classmethod_runs_once_with_dedup() -> None:
    """register_classmethod stores a closure that invokes
    ``cls.method_name()`` at clear time, dedups by the stable string
    key ``f"clsmethod:{cls.__module__}.{cls.__qualname__}.{method_name}"``,
    and survives the bound-method-identity instability that
    Round 2 F5 / Round 3 F3 was designed to fix.

    Asserts:
    1. Re-registering the same (cls, method_name) pair is a no-op
       (single entry in _callbacks).
    2. ``clear_all()`` calls the classmethod exactly once.
    3. The dedup key is the literal string the implementation uses,
       not ``id()`` of a bound method (defends against a future
       refactor that switches to id-based dedup and silently re-allows
       duplicates).
    """
    call_count = {"n": 0}

    class _FakeHelper:
        @classmethod
        def reset_singleton(cls) -> None:
            call_count["n"] += 1

    icon_caches.register_classmethod(_FakeHelper, "reset_singleton")
    icon_caches.register_classmethod(_FakeHelper, "reset_singleton")  # dedup
    icon_caches.register_classmethod(_FakeHelper, "reset_singleton")  # dedup

    # Single entry, regardless of how many times we re-registered.
    assert len(icon_caches._callbacks) == 1

    # The dedup key uses the documented stable-string form.
    expected_key = (
        f"clsmethod:{_FakeHelper.__module__}.{_FakeHelper.__qualname__}"
        f".reset_singleton"
    )
    assert icon_caches._callbacks[0][0] == expected_key

    icon_caches.clear_all()
    assert call_count["n"] == 1, (
        f"reset_singleton ran {call_count['n']} times, expected exactly 1"
    )


# ---------------------------------------------------------------------------
# Tests for provider() (Issue #31 Step 5)
# ---------------------------------------------------------------------------

class TestProvider:
    """Tests for :func:`ovui_widgets.common.icon_caches.provider`.

    The caching logic is tested by patching ``_PROVIDER_CACHE`` to an
    isolated dict and patching ``omni.ui.RasterImageProvider`` to a
    lightweight factory. Since ``provider()`` resolves ``omni.ui`` via
    a local ``import`` on each first-miss call, we target the already-loaded
    module object in ``sys.modules["omni.ui"]`` directly.
    """

    def test_provider_caches_on_second_call(self, monkeypatch):
        """Calling provider(path) a second time must return the same object
        and NOT create a new ``RasterImageProvider``."""
        import ovui_widgets.common.icon_caches as real_ic
        created = []

        def _factory(path):
            obj = object()
            created.append(obj)
            return obj

        isolated_cache: dict = {}
        monkeypatch.setattr(real_ic, "_PROVIDER_CACHE", isolated_cache)

        import omni.ui as _ui_mod
        monkeypatch.setattr(_ui_mod, "RasterImageProvider", _factory)

        first = real_ic.provider("/icons/cached.png")
        second = real_ic.provider("/icons/cached.png")
        assert first is second
        assert len(created) == 1

    def test_provider_different_paths_create_different_objects(self, monkeypatch):
        """Different paths must produce independent provider objects."""
        import ovui_widgets.common.icon_caches as real_ic
        created = []

        def _factory(path):
            obj = object()
            created.append(obj)
            return obj

        isolated_cache: dict = {}
        monkeypatch.setattr(real_ic, "_PROVIDER_CACHE", isolated_cache)

        import omni.ui as _ui_mod
        monkeypatch.setattr(_ui_mod, "RasterImageProvider", _factory)

        a = real_ic.provider("/icons/a.png")
        b = real_ic.provider("/icons/b.png")
        assert a is not b
        assert len(created) == 2

    def test_provider_cache_cleared_by_clear_all(self, monkeypatch):
        """``clear_all()`` must empty the provider cache so the next call
        creates a fresh ``RasterImageProvider``."""
        import ovui_widgets.common.icon_caches as real_ic

        fresh_cache: dict = {}
        monkeypatch.setattr(real_ic, "_PROVIDER_CACHE", fresh_cache)
        # Register fresh cache for cleanup (mimics module-import side effect).
        real_ic.register_dict(fresh_cache)

        import omni.ui as _ui_mod
        monkeypatch.setattr(_ui_mod, "RasterImageProvider", lambda path: object())

        real_ic.provider("/icons/clear_test.png")
        assert len(fresh_cache) == 1
        real_ic.clear_all()
        assert len(fresh_cache) == 0

    def test_provider_importable_from_ovui_widgets_app_icon_caches(self):
        """Issue #31 Step 5: ``provider`` must be importable directly from
        ``ovui_widgets.common.icon_caches`` (not only from the shim)."""
        from ovui_widgets.common.icon_caches import provider as shared_provider
        assert callable(shared_provider)

    def test_stage_icons_provider_delegates_to_shared(self):
        """Issue #31 Step 5: ``ovui_widgets.stage.widget.stage_icons.provider`` must
        be the same object as ``ovui_widgets.common.icon_caches.provider`` — it is
        imported, not re-defined locally."""
        from ovui_widgets.common.icon_caches import provider as shared_provider
        from ovui_widgets.stage.widget import stage_icons
        assert stage_icons.provider is shared_provider
