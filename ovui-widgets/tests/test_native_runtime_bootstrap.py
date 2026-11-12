# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for OVRTX construction before Application/OVStage/UI imports."""

from __future__ import annotations

import ctypes
import pathlib
from types import SimpleNamespace

import pytest

from ovui_data_adapters.common import AdapterFactories
from ovui_widgets.app import native_runtime_bootstrap as bootstrap


@pytest.fixture(autouse=True)
def _clean_provider_environment(monkeypatch: pytest.MonkeyPatch):
    for name in bootstrap._PROVIDER_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


class _EntryPoint:
    def __init__(self, name: str, value=None) -> None:
        self.name = name
        self._value = value

    def load(self):
        return self._value


def _registers(factory, name: str = "ovstage"):
    """Return a register function that adds ``factory`` as ``name``'s renderer."""

    def register(registry) -> None:
        registry.register_adapter(name=name, factories=AdapterFactories(renderer=factory))

    return register


def _install_entry_points(
    monkeypatch: pytest.MonkeyPatch,
    *,
    adapters: tuple[_EntryPoint, ...] = (),
    factories: tuple[_EntryPoint, ...] = (),
    startup_hooks: tuple[_EntryPoint, ...] = (),
) -> None:
    def _entry_points(*, group: str):
        if group == bootstrap._ADAPTER_ENTRY_POINT_GROUP:
            return adapters
        if group == bootstrap._NATIVE_RENDERER_FACTORY_ENTRY_POINT_GROUP:
            return factories
        if group == bootstrap._RENDERER_STARTUP_ENTRY_POINT_GROUP:
            return startup_hooks
        return ()

    monkeypatch.setattr(bootstrap, "entry_points", _entry_points)


def test_provider_without_early_renderer_does_not_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Another provider's register function runs, but its renderer must not be
    # built, because the selected provider registered no early renderer.
    def _other_renderer():
        pytest.fail("a renderer of an unselected provider must not be built")

    _install_entry_points(
        monkeypatch,
        factories=(_EntryPoint("ovstage", _registers(_other_renderer, "ovstage")),),
    )
    monkeypatch.setenv("OVUI_DATA_ADAPTER_PROVIDER", "openusd")

    assert bootstrap.preconstruct_selected_native_renderer() == (False, None)


def test_any_provider_that_registers_an_early_renderer_bootstraps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Start-up holds no provider name: the entry point declares the need."""
    renderer = object()
    _install_entry_points(
        monkeypatch,
        adapters=(_EntryPoint("example"),),
        factories=(_EntryPoint("example", _registers(lambda: renderer, "example")),),
    )

    assert bootstrap.preconstruct_selected_native_renderer() == (True, renderer)


def test_every_installed_early_renderer_registration_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All register functions run, so one provider does not hide another."""
    called: list[str] = []

    def _tracks(name: str):
        def register(registry) -> None:
            called.append(name)
            registry.register_adapter(
                name=name, factories=AdapterFactories(renderer=lambda: object())
            )

        return register

    monkeypatch.setenv("OVUI_DATA_ADAPTER_PROVIDER", "first")
    _install_entry_points(
        monkeypatch,
        factories=(
            _EntryPoint("first", _tracks("first")),
            _EntryPoint("second", _tracks("second")),
        ),
    )

    attempted, _ = bootstrap.preconstruct_selected_native_renderer()

    assert attempted is True
    assert called == ["first", "second"]


def test_an_unselected_registration_failure_is_reported_but_not_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another provider's failed registration is reported, and start-up goes on."""
    warnings: list[tuple[str, str]] = []

    # Use the real log_warning(module, message) signature, so a wrong call fails.
    def _record(module: str, message: str) -> None:
        warnings.append((module, message))

    monkeypatch.setattr(bootstrap.ErrorReporter, "log_warning", staticmethod(_record))

    def _broken(registry) -> None:
        raise RuntimeError("second registration broke")

    renderer = object()
    monkeypatch.setenv("OVUI_DATA_ADAPTER_PROVIDER", "first")
    _install_entry_points(
        monkeypatch,
        factories=(
            _EntryPoint("first", _registers(lambda: renderer, "first")),
            _EntryPoint("second", _broken),
        ),
    )

    assert bootstrap.preconstruct_selected_native_renderer() == (True, renderer)
    assert any("second" in message and "broke" in message for _module, message in warnings)


def test_a_reported_early_renderer_failure_is_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A register function that reports a failure stops start-up."""

    def register(registry) -> None:
        registry.report_module_load_failure(
            "ovstage", "ovstage:register", RuntimeError("renderer library missing")
        )

    monkeypatch.setenv("OVUI_DATA_ADAPTER_PROVIDER", "ovstage")
    _install_entry_points(monkeypatch, factories=(_EntryPoint("ovstage", register),))

    with pytest.raises(RuntimeError, match="renderer library missing"):
        bootstrap.preconstruct_selected_native_renderer()


def test_sole_installed_ovstage_provider_bootstraps_without_importing_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = object()

    class _Factory:
        def __new__(cls):
            return renderer

    _install_entry_points(
        monkeypatch,
        adapters=(_EntryPoint("ovstage"),),
        factories=(_EntryPoint("ovstage", _registers(_Factory)),),
    )

    assert bootstrap.preconstruct_selected_native_renderer() == (True, renderer)


def test_ovstage_early_failure_is_fatal_even_when_fallback_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Factory:
        def __init__(self) -> None:
            raise RuntimeError("early construction failed")

    _install_entry_points(
        monkeypatch,
        factories=(_EntryPoint("ovstage", _registers(_Factory)),),
    )
    monkeypatch.setenv("OVUI_DATA_ADAPTER_PROVIDER", "ovstage")
    monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "0")

    with pytest.raises(RuntimeError, match="early construction failed"):
        bootstrap.preconstruct_selected_native_renderer()


def test_required_early_failure_is_fatal(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Factory:
        def __init__(self) -> None:
            raise RuntimeError("early construction failed")

    _install_entry_points(
        monkeypatch,
        factories=(_EntryPoint("ovstage", _registers(_Factory)),),
    )
    monkeypatch.setenv("OVUI_DATA_ADAPTER_PROVIDER", "ovstage")
    monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "1")

    with pytest.raises(RuntimeError, match="before omni.ui"):
        bootstrap.preconstruct_selected_native_renderer()


def test_install_records_attempted_none_on_application() -> None:
    app = SimpleNamespace(_startup_prebuilt_renderer="unattempted")

    bootstrap.install_preconstructed_renderer(app, (True, None))

    assert app._startup_prebuilt_renderer is None


def test_install_binds_application_history_to_early_renderer() -> None:
    undo_manager = object()
    renderer = SimpleNamespace(set_undo_manager=lambda value: setattr(renderer, "undo", value))
    app = SimpleNamespace(
        _startup_prebuilt_renderer="unattempted",
        undo_manager=undo_manager,
    )

    bootstrap.install_preconstructed_renderer(app, (True, renderer))

    assert app._startup_prebuilt_renderer is renderer
    assert renderer.undo is undo_manager
    assert app._renderer_startup_hooks_complete is True


def test_ovstage_bootstrap_preserves_exact_missing_api_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Factory:
        def __init__(self) -> None:
            raise RuntimeError(
                "required runtime API is missing or not callable: "
                "ovrtx.Renderer.attach_ovstage"
            )

    _install_entry_points(
        monkeypatch,
        factories=(_EntryPoint("ovstage", _registers(_Factory)),),
    )
    monkeypatch.setenv("OVUI_DATA_ADAPTER_PROVIDER", "ovstage")
    monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "0")

    with pytest.raises(
        RuntimeError,
        match=r"ovrtx\.Renderer\.attach_ovstage",
    ):
        bootstrap.preconstruct_selected_native_renderer()


def test_required_ovstage_rejects_duplicate_factories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_entry_points(
        monkeypatch,
        factories=(
            _EntryPoint("ovstage", _registers(lambda: object())),
            _EntryPoint("OVSTAGE", _registers(lambda: object())),
        ),
    )
    monkeypatch.setenv("OVUI_DATA_ADAPTER_PROVIDER", "ovstage")
    monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "1")

    with pytest.raises(RuntimeError, match="already registered"):
        bootstrap.preconstruct_selected_native_renderer()


def test_bootstrap_has_no_concrete_ovstage_import() -> None:
    source = pathlib.Path(bootstrap.__file__).read_text(encoding="utf-8")

    assert "from ovui_data_adapters.ovstage" not in source
    assert "import ovui_data_adapters.ovstage" not in source


def test_early_renderer_runs_startup_hooks_and_survives_a_failed_hook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    renderer = object()
    calls = []

    def failing_hook(settings, hook_renderer):
        raise RuntimeError("hook failed")

    _install_entry_points(
        monkeypatch,
        factories=(_EntryPoint("ovstage", _registers(lambda: renderer)),),
        startup_hooks=(
            _EntryPoint("failing", failing_hook),
            _EntryPoint("working", lambda *args: calls.append(args)),
        ),
    )
    monkeypatch.setenv("OVUI_DATA_ADAPTER_PROVIDER", "ovstage")
    settings = {"example.setting": True}

    assert bootstrap.preconstruct_selected_native_renderer(settings) == (True, renderer)
    assert calls == [(settings, renderer)]


def test_native_timing_table_is_installed_before_ui_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native start-up phases run inside ui.init, so the table must be
    installed first. Application.run() calls this before ui.init."""

    import omni.ui as ui

    capsule = object()
    installed: list[object] = []
    monkeypatch.setattr(
        bootstrap,
        "entry_points",
        lambda *, group: (
            (_EntryPoint("tool", lambda: capsule),)
            if group == bootstrap._NATIVE_TIMING_ENTRY_POINT_GROUP
            else ()
        ),
    )
    monkeypatch.setattr(ui._ui, "_set_native_timing_hooks", installed.append)

    assert bootstrap.install_native_timing_hooks() is True
    assert installed == [capsule]


def test_no_native_timing_package_installs_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import omni.ui as ui

    monkeypatch.setattr(bootstrap, "entry_points", lambda *, group: ())
    monkeypatch.setattr(
        ui._ui,
        "_set_native_timing_hooks",
        lambda capsule: pytest.fail("no package published a timing table"),
    )

    assert bootstrap.install_native_timing_hooks() is False


def test_a_failing_native_timing_hook_does_not_stop_start_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import omni.ui as ui

    def _raise():
        raise RuntimeError("no native module")

    installed: list[object] = []
    capsule = object()
    monkeypatch.setattr(
        bootstrap,
        "entry_points",
        lambda *, group: (
            (_EntryPoint("broken", _raise), _EntryPoint("good", lambda: capsule))
            if group == bootstrap._NATIVE_TIMING_ENTRY_POINT_GROUP
            else ()
        ),
    )
    monkeypatch.setattr(ui._ui, "_set_native_timing_hooks", installed.append)

    assert bootstrap.install_native_timing_hooks() is True
    assert installed == [capsule]



# The renderer slot of native frame pacing, driven through the real ovui core:
# the tables are built with ctypes, so these tests exercise the same refusal
# the core applies to a table from an installed package.
_PyCapsule_New = ctypes.pythonapi.PyCapsule_New
_PyCapsule_New.restype = ctypes.py_object
_PyCapsule_New.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p]


class _PacingHooks(ctypes.Structure):
    """Same layout as omni::ui::standalone::NativeFramePacingHooks."""

    _fields_ = [("structSize", ctypes.c_uint32), ("version", ctypes.c_uint32)] + [
        (name, ctypes.c_void_p)
        for name in (
            "openRenderer",
            "pauseRenderWorker",
            "resumeRenderWorker",
            "closeRenderer",
            "shutdownWorker",
            "readRendererInfo",
            "lastError",
            "queryCapabilities",
            "cancel",
        )
    ]


def _pacing_capsule(version: int):
    table = _PacingHooks()
    table.structSize = ctypes.sizeof(_PacingHooks)
    table.version = version
    placeholder = ctypes.cast(_PyCapsule_New, ctypes.c_void_p).value
    for name, _ in _PacingHooks._fields_[2:]:
        setattr(table, name, placeholder)
    capsule = _PyCapsule_New(ctypes.byref(table), b"omni.ui.native_frame_pacing_hooks", None)
    return table, capsule


@pytest.fixture
def real_slot():
    import omni.ui as ui

    setter = ui._ui._set_native_frame_pacing_hooks
    setter(None)
    yield ui
    setter(None)


def _providers(monkeypatch: pytest.MonkeyPatch, *points) -> list[str]:
    loaded: list[str] = []

    class _Point:
        def __init__(self, name, value):
            self.name = name
            self._value = value

        def load(self):
            loaded.append(self.name)
            return self._value

    monkeypatch.setattr(
        bootstrap,
        "_entry_points_for",
        lambda group: tuple(_Point(n, v) for n, v in points)
        if group == bootstrap._NATIVE_PACING_ENTRY_POINT_GROUP
        else (),
    )
    return loaded


def test_a_refused_pacing_table_does_not_hide_a_later_compatible_one(
    monkeypatch: pytest.MonkeyPatch, real_slot
) -> None:
    # The core keeps a pointer to an accepted table; the fixture empties the
    # slot before these locals go away.
    _, incompatible = _pacing_capsule(version=99)
    keep, compatible = _pacing_capsule(version=3)
    loaded = _providers(
        monkeypatch,
        ("incompatible", lambda registry: registry.add_frame_source(incompatible)),
        ("compatible", lambda registry: registry.add_frame_source(compatible)),
    )

    installed = bootstrap.install_native_frame_pacing_hooks()

    assert loaded == ["incompatible", "compatible"]
    assert installed is True
    assert keep.version == 3
    status = real_slot.get_frame_pacing_status()
    if status["status_reason"] != "backend_unavailable":
        assert status["supported"] is True


def test_every_pacing_entry_point_is_called(
    monkeypatch: pytest.MonkeyPatch, real_slot
) -> None:
    keep, compatible = _pacing_capsule(version=3)
    called: list[str] = []

    def first(registry):
        called.append("first")
        registry.add_frame_source(compatible)

    _providers(monkeypatch, ("first", first), ("second", lambda registry: called.append("second")))

    assert bootstrap.install_native_frame_pacing_hooks() is True
    assert called == ["first", "second"]
    assert keep.version == 3


def test_only_refused_pacing_tables_report_failure(
    monkeypatch: pytest.MonkeyPatch, real_slot
) -> None:
    _, incompatible = _pacing_capsule(version=99)
    _providers(
        monkeypatch,
        ("incompatible", lambda registry: registry.add_frame_source(incompatible)),
    )

    assert bootstrap.install_native_frame_pacing_hooks() is False
    assert real_slot.get_frame_pacing_status()["supported"] is False


def test_without_a_pacing_provider_the_slot_stays_empty(
    monkeypatch: pytest.MonkeyPatch, real_slot
) -> None:
    # A public install: ovui presents the viewport on the ordinary UI tick.
    _providers(monkeypatch)

    assert bootstrap.install_native_frame_pacing_hooks() is False
    status = real_slot.get_frame_pacing_status()
    assert status["supported"] is False
    assert status["status_reason"] in {"hooks_unavailable", "backend_unavailable"}


def test_a_broken_pacing_provider_does_not_stop_a_later_one(
    monkeypatch: pytest.MonkeyPatch, real_slot
) -> None:
    def broken(registry):
        raise ImportError("the native module is missing")

    keep, compatible = _pacing_capsule(version=3)
    loaded = _providers(
        monkeypatch,
        ("broken", broken),
        ("empty", lambda registry: None),
        ("compatible", lambda registry: registry.add_frame_source(compatible)),
    )

    assert bootstrap.install_native_frame_pacing_hooks() is True
    assert loaded == ["broken", "empty", "compatible"]
    assert keep.version == 3


# The child process starts with OpenUSD not loaded, as the application does.
# Arguments: cgroup root, /proc/self/cgroup file, then options:
#   affinity=N        the process may use N CPUs
#   hide-openusd      OpenUSD is not installed (find_spec finds no "pxr")
#   start-openusd     after the bootstrap, OpenUSD runs parallel work
_WORK_LIMIT_SCRIPT = """
import importlib.util, os, sys
from ovui_data_adapters.common import cpu_budget
cpu_budget._CGROUP_ROOT = sys.argv[1]
cpu_budget._PROC_CGROUP = sys.argv[2]
options = sys.argv[3:]
for option in options:
    if option.startswith("affinity="):
        count = int(option.split("=", 1)[1])
        os.sched_getaffinity = lambda pid, count=count: set(range(count))
if "hide-openusd" in options:
    find_spec = importlib.util.find_spec
    importlib.util.find_spec = lambda name, *args: None if name == "pxr" else find_spec(name, *args)
from ovui_widgets.app.native_runtime_bootstrap import limit_openusd_work_threads
limit_openusd_work_threads()
print("pxr loaded before:", "pxr" in sys.modules)
print("env:", os.environ.get("PXR_WORK_THREAD_LIMIT"))
if "start-openusd" in options:
    from pxr import Usd, UsdGeom, Work
    UsdGeom.Xform.Define(Usd.Stage.CreateInMemory(), "/World")
    print("work limit:", Work.GetConcurrencyLimit())
"""


def _run_work_limit_script(
    tmp_path: pathlib.Path, cpu_max: str, *options: str, **env: str
) -> str:
    import os
    import subprocess
    import sys

    root = tmp_path / "cgroup"
    root.mkdir()
    (root / "cpu.max").write_text(cpu_max)
    proc = tmp_path / "proc_self_cgroup"
    proc.write_text("0::/\n")
    environment = {key: value for key, value in os.environ.items() if key != "PXR_WORK_THREAD_LIMIT"}
    environment.update(env)
    done = subprocess.run(
        [sys.executable, "-c", _WORK_LIMIT_SCRIPT, str(root), str(proc), *options],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    output = done.stdout + done.stderr
    assert done.returncode == 0, f"the child process failed:\n{output}"
    return output


def _openusd_work():
    """Return OpenUSD's ``Work`` module; these checks start OpenUSD in the child process.

    Without OpenUSD this import fails with the missing ``pxr`` module, which is the
    failure that the package checks without OpenUSD accept.
    """

    from pxr import Work

    return Work


def test_openusd_work_threads_follow_the_cpu_quota_before_openusd_loads(tmp_path):
    """Regression: the pool is sized before an optional component makes OpenUSD start its threads."""

    if _openusd_work().GetPhysicalConcurrencyLimit() < 2:
        pytest.skip("this computer has one CPU, so no quota can lower the limit")
    output = _run_work_limit_script(tmp_path, "100000 100000\n", "start-openusd")

    assert "pxr loaded before: False" in output
    assert "env: 1" in output
    assert "work limit: 1" in output
    assert "OpenUSD work threads: 1, the CPUs that this process may use" in output


def test_openusd_work_threads_keep_a_user_limit(tmp_path):
    _openusd_work()
    output = _run_work_limit_script(
        tmp_path, "100000 100000\n", "start-openusd", PXR_WORK_THREAD_LIMIT="3"
    )

    assert "env: 3" in output
    assert "work limit: 3" in output
    assert "OpenUSD work threads:" not in output


def test_openusd_work_threads_unchanged_without_a_quota_or_affinity_limit(tmp_path):
    import os

    host = _openusd_work().GetPhysicalConcurrencyLimit()
    output = _run_work_limit_script(
        tmp_path, "max 100000\n", f"affinity={os.cpu_count()}", "start-openusd"
    )

    assert "env: None" in output
    assert f"work limit: {host}" in output
    assert "OpenUSD work threads:" not in output


def test_openusd_work_threads_unchanged_without_openusd(tmp_path):
    """With no OpenUSD installed (for example the ovstage provider alone) there is no pool to size."""

    output = _run_work_limit_script(tmp_path, "100000 100000\n", "affinity=4", "hide-openusd")

    assert "pxr loaded before: False" in output
    assert "env: None" in output
    assert "OpenUSD work threads:" not in output
