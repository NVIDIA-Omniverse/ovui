# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the Step-2.3 headless entrypoint and resolution plumbing.

Covers:

1. ``ovwidgets.app.headless.main`` sets ``OMNIUI_HEADLESS=1`` /
   ``OMNIUI_BACKEND=vulkan`` **before** importing ``ovwidgets.app.application`` —
   verified in a real subprocess so the import-order claim is enforced.
2. CLI flags ``--width`` / ``--height`` override env vars and propagate
   into the child process env.
3. ``Application.run()`` reads ``OVGEAR_HEADLESS_WIDTH`` /
   ``OVGEAR_HEADLESS_HEIGHT`` when calling ``ui.init`` — confirmed via a
   monkeypatched ``ui.init`` capture.
4. Regression: with no env vars the windowed default stays ``1280×720``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import types
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# CLI / env-var plumbing — runs in-process, doesn't touch omni.ui.
# ---------------------------------------------------------------------------

def _import_headless_without_running():
    """Import ``ovwidgets.app.headless`` without triggering ``main()`` side-effects."""
    import importlib

    import ovwidgets.app.headless as headless
    importlib.reload(headless)
    return headless


def test_cli_width_height_override_env(monkeypatch):
    """``--width 800 --height 600`` writes 800/600 into the env vars."""
    monkeypatch.delenv("OVGEAR_HEADLESS_WIDTH", raising=False)
    monkeypatch.delenv("OVGEAR_HEADLESS_HEIGHT", raising=False)

    headless = _import_headless_without_running()

    # Stub Application so main() doesn't try to boot ovui.
    fake_app = types.SimpleNamespace(run=lambda usd_path=None: None)
    fake_module = types.ModuleType("ovwidgets.app.application")
    fake_module.Application = lambda: fake_app

    with patch.dict(sys.modules, {
        "ovwidgets.app.application": fake_module,
    }):
        headless.main(["--width", "800", "--height", "600"])

    assert os.environ["OVGEAR_HEADLESS_WIDTH"] == "800"
    assert os.environ["OVGEAR_HEADLESS_HEIGHT"] == "600"
    assert os.environ["OMNIUI_HEADLESS"] == "1"
    assert os.environ["OMNIUI_BACKEND"] == "vulkan"


def test_cli_default_dims_when_no_flags_no_env(monkeypatch):
    """Without flags or env, headless main defaults to 1920×1080."""
    monkeypatch.delenv("OVGEAR_HEADLESS_WIDTH", raising=False)
    monkeypatch.delenv("OVGEAR_HEADLESS_HEIGHT", raising=False)

    headless = _import_headless_without_running()

    fake_app = types.SimpleNamespace(run=lambda usd_path=None: None)
    fake_module = types.ModuleType("ovwidgets.app.application")
    fake_module.Application = lambda: fake_app

    with patch.dict(sys.modules, {
        "ovwidgets.app.application": fake_module,
    }):
        headless.main([])

    assert os.environ["OVGEAR_HEADLESS_WIDTH"] == "1920"
    assert os.environ["OVGEAR_HEADLESS_HEIGHT"] == "1080"


def test_env_vars_set_before_application_import(tmp_path):
    """Real subprocess: prove env vars are set before any heavy import.

    Drives the real ``python -m ovwidgets.app.headless`` import path (no
    ``sys.modules`` pre-seeding). A ``sys.meta_path`` finder records the
    environment at the moment ``ovwidgets.app.application`` (and any ``omni.ui*``)
    is first looked up, then blocks the import so ovui doesn't actually
    boot. The first recorded event must be ``ovwidgets.app.application`` with
    ``OMNIUI_HEADLESS=1`` / ``OMNIUI_BACKEND=vulkan`` already set —
    otherwise the package's ``__init__.py`` is eagerly importing the
    application (and transitively ``omni.ui``) before ``headless.main``
    has a chance to set the env vars.
    """
    sitecustomize = tmp_path / "sitecustomize.py"
    sitecustomize.write_text(textwrap.dedent('''
        import os, sys, json
        from importlib.abc import MetaPathFinder

        _events_path = os.environ["_OVGEAR_TEST_EVENTS_PATH"]
        _events = []

        class _RecorderFinder(MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if (fullname in ("ovwidgets.app.application", "ovwidgets.app.application")
                        or fullname == "omni.ui"
                        or fullname.startswith("omni.ui.")):
                    _events.append({
                        "module": fullname,
                        "headless": os.environ.get("OMNIUI_HEADLESS"),
                        "backend": os.environ.get("OMNIUI_BACKEND"),
                        "w": os.environ.get("OVGEAR_HEADLESS_WIDTH"),
                        "h": os.environ.get("OVGEAR_HEADLESS_HEIGHT"),
                    })
                    with open(_events_path, "w") as f:
                        json.dump(_events, f)
                    raise ImportError(
                        "_RecorderFinder blocked " + fullname)
                return None

        sys.meta_path.insert(0, _RecorderFinder())
    '''))
    events_path = tmp_path / "events.json"

    env = {**os.environ}
    for k in ("OMNIUI_HEADLESS", "OMNIUI_BACKEND",
              "OVGEAR_HEADLESS_WIDTH", "OVGEAR_HEADLESS_HEIGHT"):
        env.pop(k, None)
    env["PYTHONPATH"] = (
        str(tmp_path) + os.pathsep + str(REPO_ROOT)
        + os.pathsep + env.get("PYTHONPATH", "")
    )
    env["_OVGEAR_TEST_EVENTS_PATH"] = str(events_path)

    # Real `python -m ovwidgets.app.headless` invocation. The recorder will block
    # the application import, so we expect a non-zero exit; what matters
    # is whether the recorded event happened with env vars already set.
    subprocess.run(
        [sys.executable, "-m", "ovwidgets.app.headless",
         "--width", "1280", "--height", "720"],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=30,
    )

    assert events_path.exists(), (
        "recorder produced no events — neither ovwidgets.app.application nor "
        "omni.ui was looked up by the headless entrypoint, which means "
        "the import path under test never ran"
    )
    import json
    events = json.loads(events_path.read_text())
    assert events, "events.json was empty"
    first = events[0]
    assert first["module"] in ("ovwidgets.app.application", "ovwidgets.app.application"), (
        f"first import attempt was {first['module']!r}; expected "
        "'ovwidgets.app.application'. omni.ui being loaded earlier proves "
        "eager imports in ovwidgets.app/__init__.py have leaked in."
    )
    assert first["headless"] == "1", (
        f"OMNIUI_HEADLESS was {first['headless']!r} when "
        "ovwidgets.app.application was first imported — env vars were set too "
        "late. Check that ovwidgets.app/__init__.py is not eagerly importing "
        "Application."
    )
    assert first["backend"] == "vulkan"
    assert first["w"] == "1280"
    assert first["h"] == "720"


def test_module_can_be_run_with_python_dash_m():
    """`python -m ovwidgets.app.headless --help` resolves the module file."""
    env = {**os.environ}
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "ovwidgets.app.headless", "--help"],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    # prog= is omitted in ovwidgets.app/headless.py (Step 3); Python uses argv[0].
    # Check for the essential flags rather than a specific prog string.
    assert "--width" in result.stdout
    assert "--height" in result.stdout


# ---------------------------------------------------------------------------
# Application.run() resolution plumbing — exercises the helper that
# Application.run uses to compute the ``ui.init`` width/height kwargs.
# ---------------------------------------------------------------------------

def test_resolve_window_size_default_when_env_unset(monkeypatch):
    """Windowed-mode regression: no env vars → default 1280×720."""
    monkeypatch.delenv("OVGEAR_HEADLESS_WIDTH", raising=False)
    monkeypatch.delenv("OVGEAR_HEADLESS_HEIGHT", raising=False)

    from ovwidgets.app.application import _resolve_window_size
    assert _resolve_window_size() == (1280, 720)


def test_resolve_window_size_honours_env_vars(monkeypatch):
    monkeypatch.setenv("OVGEAR_HEADLESS_WIDTH", "1920")
    monkeypatch.setenv("OVGEAR_HEADLESS_HEIGHT", "1080")

    from ovwidgets.app.application import _resolve_window_size
    assert _resolve_window_size() == (1920, 1080)


def test_resolve_window_size_partial_env_falls_back_to_defaults(monkeypatch):
    """If only one env var is set, the other keeps its 1280×720 default."""
    monkeypatch.setenv("OVGEAR_HEADLESS_WIDTH", "800")
    monkeypatch.delenv("OVGEAR_HEADLESS_HEIGHT", raising=False)

    from ovwidgets.app.application import _resolve_window_size
    assert _resolve_window_size() == (800, 720)


def test_application_run_calls_resolve_window_size(monkeypatch):
    """``Application.run`` reads dims via ``_resolve_window_size`` before
    handing them to ``ui.init`` — confirmed by patching ``ui.init`` and
    ``_resolve_window_size`` and stopping after the call."""
    monkeypatch.setenv("OVGEAR_HEADLESS_WIDTH", "640")
    monkeypatch.setenv("OVGEAR_HEADLESS_HEIGHT", "480")

    import omni.ui as ui  # ensure module is loaded

    captured: dict = {}

    def fake_init(name, *, width, height, max_fps=None):
        captured["name"] = name
        captured["width"] = width
        captured["height"] = height
        raise RuntimeError("test-stop after ui.init")

    monkeypatch.setattr(ui, "init", fake_init)

    # Stub side modules ``run()`` imports so the run path doesn't pull in
    # things we don't need to test here.
    # NOTE: ovwidgets.app/application.py imports from ``ovwidgets.app.layout`` and
    # ``ovwidgets.app.style`` directly, so we must patch the ``ovwidgets.app.*``
    # module entries so monkeypatch can restore them correctly after the test.
    fake_layout = types.ModuleType("ovwidgets.app.layout")
    fake_layout.write_split_ini = lambda: None
    fake_layout.DOCKSPACE_TOP_PADDING = 0
    fake_layout.MENU_BAR_HEIGHT = 0
    monkeypatch.setitem(sys.modules, "ovwidgets.app.layout", fake_layout)
    monkeypatch.setitem(sys.modules, "ovwidgets.app.layout", fake_layout)

    fake_style = types.ModuleType("ovwidgets.app.style")
    fake_style.apply_global_styles = lambda: None
    fake_style.set_theme = lambda *a, **kw: None
    monkeypatch.setitem(sys.modules, "ovwidgets.app.style", fake_style)
    monkeypatch.setitem(sys.modules, "ovwidgets.app.style", fake_style)
    from ovwidgets.app.application import Application
    from ovwidgets.common.selection import SelectionBus

    Application._instance = None
    SelectionBus._instance = None
    app = Application()
    try:
        with pytest.raises(RuntimeError, match="test-stop after ui.init"):
            app.run()
    finally:
        Application._instance = None
        SelectionBus._instance = None

    assert captured["width"] == 640
    assert captured["height"] == 480
