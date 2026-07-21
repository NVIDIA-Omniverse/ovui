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

1. ``ovui_widgets.app.headless.main`` sets ``OMNIUI_HEADLESS=1`` /
   ``OMNIUI_BACKEND=vulkan`` **before** importing ``ovui_widgets.app.application`` —
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
_NO_CHILD_OPENUSD_REASON = (
    "no usable OpenUSD runtime/provider for spawned child after usd-build scrub; "
    "install a usd-core wheel or otherwise make pxr importable without usd-build "
    "paths to run subprocess-launch tests"
)

_CHILD_OPENUSD_PROBE = textwrap.dedent('''
    from pxr import Usd
    stage = Usd.Stage.CreateInMemory()
    if stage is None:
        raise RuntimeError("Usd.Stage.CreateInMemory() returned None")

    from ovui_data_adapters.common._adapter_registry import (
        AdapterRegistry,
        discover_adapter_modules,
    )

    registry = discover_adapter_modules(AdapterRegistry())
    providers = {provider.name for provider in registry.available_adapters()}
    if "openusd" not in providers:
        failures = [
            f"{failure.name}:{failure.exception_type}:{failure.message}"
            for failure in registry.load_failures
        ]
        raise RuntimeError(
            "openusd provider unavailable in child; "
            f"providers={sorted(providers)!r}; failures={failures!r}"
        )
''')


def _skip_if_child_openusd_unavailable(env: dict) -> None:
    """Skip when the exact spawned-child env cannot run the OpenUSD provider."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", _CHILD_OPENUSD_PROBE],
            env=env,
            capture_output=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired as exc:
        stderr_tail = (exc.stderr or b"").decode("utf-8", errors="replace")[-500:]
        pytest.skip(
            f"{_NO_CHILD_OPENUSD_REASON}; child OpenUSD probe timed out; "
            f"stderr tail: {stderr_tail}"
        )

    if result.returncode == 0:
        return

    stderr_tail = result.stderr.decode("utf-8", errors="replace")[-500:]
    stdout_tail = result.stdout.decode("utf-8", errors="replace")[-500:]
    pytest.skip(
        f"{_NO_CHILD_OPENUSD_REASON}; probe rc={result.returncode}; "
        f"stderr tail: {stderr_tail}; stdout tail: {stdout_tail}"
    )


# ---------------------------------------------------------------------------
# CLI / env-var plumbing — runs in-process, doesn't touch omni.ui.
# ---------------------------------------------------------------------------

def _import_headless_without_running():
    """Import ``ovui_widgets.app.headless`` without triggering ``main()`` side-effects."""
    import importlib

    import ovui_widgets.app.headless as headless
    importlib.reload(headless)
    return headless


def test_cli_width_height_override_env(monkeypatch):
    """``--width 800 --height 600`` writes 800/600 into the env vars."""
    monkeypatch.delenv("OVGEAR_HEADLESS_WIDTH", raising=False)
    monkeypatch.delenv("OVGEAR_HEADLESS_HEIGHT", raising=False)

    headless = _import_headless_without_running()

    # Stub Application so main() doesn't try to boot ovui.
    fake_app = types.SimpleNamespace(run=lambda usd_path=None: None)
    fake_module = types.ModuleType("ovui_widgets.app.application")
    fake_module.Application = lambda settings_overrides=None: fake_app

    with patch.dict(sys.modules, {
        "ovui_widgets.app.application": fake_module,
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
    fake_module = types.ModuleType("ovui_widgets.app.application")
    fake_module.Application = lambda settings_overrides=None: fake_app

    with patch.dict(sys.modules, {
        "ovui_widgets.app.application": fake_module,
    }):
        headless.main([])

    assert os.environ["OVGEAR_HEADLESS_WIDTH"] == "1920"
    assert os.environ["OVGEAR_HEADLESS_HEIGHT"] == "1080"


def test_cli_settings_overrides_with_width_and_usd():
    """Generic --/path=value overrides coexist with headless flags + USD."""
    headless = _import_headless_without_running()
    ns = headless._parse_args([
        "--width", "800",
        "scene.usda",
        "--/app/runLoops/main/rateLimitFrequency=30",
        "--/ui/theme=light",
    ])
    assert ns.width == 800
    assert ns.usd_file == "scene.usda"
    assert ns.settings_overrides == {
        "app.runLoops.main.rateLimitFrequency": 30,
        "ui.theme": "light",
    }


def test_cli_settings_overrides_without_usd():
    headless = _import_headless_without_running()
    ns = headless._parse_args(["--/app/runLoops/main/rateLimitFrequency=30"])
    assert ns.usd_file is None
    assert ns.width is None
    assert ns.settings_overrides == {"app.runLoops.main.rateLimitFrequency": 30}


def test_cli_malformed_override_exits_with_usage_error(capsys):
    headless = _import_headless_without_running()
    with pytest.raises(SystemExit) as excinfo:
        headless._parse_args(["--/app/runLoops/main/rateLimitFrequency"])
    assert excinfo.value.code == 2
    assert "invalid settings override" in capsys.readouterr().err


def test_main_passes_overrides_to_application(monkeypatch):
    """headless.main() hands the parsed overrides to Application, so the
    cap reaches ui.init (via Application.run) before the pump starts."""
    monkeypatch.delenv("OVGEAR_HEADLESS_WIDTH", raising=False)
    monkeypatch.delenv("OVGEAR_HEADLESS_HEIGHT", raising=False)

    headless = _import_headless_without_running()

    captured = {}

    def fake_application(settings_overrides=None):
        captured["settings_overrides"] = settings_overrides
        return types.SimpleNamespace(
            run=lambda usd_path=None: captured.__setitem__("usd", usd_path)
        )

    fake_module = types.ModuleType("ovui_widgets.app.application")
    fake_module.Application = fake_application

    with patch.dict(sys.modules, {
        "ovui_widgets.app.application": fake_module,
    }):
        headless.main([
            "scene.usda", "--/app/runLoops/main/rateLimitFrequency=30"
        ])

    assert captured["settings_overrides"] == {
        "app.runLoops.main.rateLimitFrequency": 30
    }
    assert captured["usd"] == "scene.usda"


def test_env_vars_set_before_application_import(tmp_path):
    """Real subprocess: prove env vars are set before any heavy import.

    Drives the real ``python -m ovui_widgets.app.headless`` import path (no
    ``sys.modules`` pre-seeding). A ``sys.meta_path`` finder records the
    environment at the moment ``ovui_widgets.app.application`` (and any ``omni.ui*``)
    is first looked up, then blocks the import so ovui doesn't actually
    boot. The first recorded event must be ``ovui_widgets.app.application`` with
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
                if (fullname in ("ovui_widgets.app.application", "ovui_widgets.app.application")
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

    # Real `python -m ovui_widgets.app.headless` invocation. The recorder will block
    # the application import, so we expect a non-zero exit; what matters
    # is whether the recorded event happened with env vars already set.
    subprocess.run(
        [sys.executable, "-m", "ovui_widgets.app.headless",
         "--width", "1280", "--height", "720"],
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=30,
    )

    assert events_path.exists(), (
        "recorder produced no events — neither ovui_widgets.app.application nor "
        "omni.ui was looked up by the headless entrypoint, which means "
        "the import path under test never ran"
    )
    import json
    events = json.loads(events_path.read_text())
    assert events, "events.json was empty"
    first = events[0]
    assert first["module"] in ("ovui_widgets.app.application", "ovui_widgets.app.application"), (
        f"first import attempt was {first['module']!r}; expected "
        "'ovui_widgets.app.application'. omni.ui being loaded earlier proves "
        "eager imports in ovui_widgets.app/__init__.py have leaked in."
    )
    assert first["headless"] == "1", (
        f"OMNIUI_HEADLESS was {first['headless']!r} when "
        "ovui_widgets.app.application was first imported — env vars were set too "
        "late. Check that ovui_widgets.app/__init__.py is not eagerly importing "
        "Application."
    )
    assert first["backend"] == "vulkan"
    assert first["w"] == "1280"
    assert first["h"] == "720"


def test_module_can_be_run_with_python_dash_m():
    """`python -m ovui_widgets.app.headless --help` resolves the module file."""
    env = {**os.environ}
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUTF8"] = "1"
    _skip_if_child_openusd_unavailable(env)
    result = subprocess.run(
        [sys.executable, "-m", "ovui_widgets.app.headless", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    # prog= is omitted in ovui_widgets.app/headless.py (Step 3); Python uses argv[0].
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

    from ovui_widgets.app.application import _resolve_window_size
    assert _resolve_window_size() == (1280, 720)


def test_resolve_window_size_honours_env_vars(monkeypatch):
    monkeypatch.setenv("OVGEAR_HEADLESS_WIDTH", "1920")
    monkeypatch.setenv("OVGEAR_HEADLESS_HEIGHT", "1080")

    from ovui_widgets.app.application import _resolve_window_size
    assert _resolve_window_size() == (1920, 1080)


def test_resolve_window_size_partial_env_falls_back_to_defaults(monkeypatch):
    """If only one env var is set, the other keeps its 1280×720 default."""
    monkeypatch.setenv("OVGEAR_HEADLESS_WIDTH", "800")
    monkeypatch.delenv("OVGEAR_HEADLESS_HEIGHT", raising=False)

    from ovui_widgets.app.application import _resolve_window_size
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
        captured["max_fps"] = max_fps
        raise RuntimeError("test-stop after ui.init")

    monkeypatch.setattr(ui, "init", fake_init)

    # Stub side modules ``run()`` imports so the run path doesn't pull in
    # things we don't need to test here.
    # NOTE: ovui_widgets.app/application.py imports from ``ovui_widgets.app.layout`` and
    # ``ovui_widgets.app.style`` directly, so we must patch the ``ovui_widgets.app.*``
    # module entries so monkeypatch can restore them correctly after the test.
    fake_layout = types.ModuleType("ovui_widgets.app.layout")
    fake_layout.write_split_ini = lambda: None
    fake_layout.DOCKSPACE_TOP_PADDING = 0
    fake_layout.MENU_BAR_HEIGHT = 0
    monkeypatch.setitem(sys.modules, "ovui_widgets.app.layout", fake_layout)
    monkeypatch.setitem(sys.modules, "ovui_widgets.app.layout", fake_layout)

    fake_style = types.ModuleType("ovui_widgets.app.style")
    fake_style.apply_global_styles = lambda: None
    fake_style.set_theme = lambda *a, **kw: None
    monkeypatch.setitem(sys.modules, "ovui_widgets.app.style", fake_style)
    monkeypatch.setitem(sys.modules, "ovui_widgets.app.style", fake_style)
    from ovui_widgets.app.application import Application
    from ovui_widgets.common.selection import SelectionBus

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
    # The ovui pump is the Kit-style main-loop enforcer of
    # app.runLoops.main.rateLimitFrequency — ui.init receives the
    # settings-derived cap (default 120), not None/uncapped.
    assert captured["max_fps"] == 120.0
