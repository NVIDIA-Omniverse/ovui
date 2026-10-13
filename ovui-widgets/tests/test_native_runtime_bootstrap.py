# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for OVRTX construction before Application/OVStage/UI imports."""

from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest
import tomllib

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


def test_explicit_non_ovstage_provider_does_not_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OVUI_DATA_ADAPTER_PROVIDER", "openusd")
    monkeypatch.setattr(
        bootstrap,
        "entry_points",
        lambda **kwargs: pytest.fail("explicit selection must not inspect metadata"),
    )

    assert bootstrap.preconstruct_selected_native_renderer() == (False, None)


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
        factories=(_EntryPoint("ovstage", _Factory),),
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
        factories=(_EntryPoint("ovstage", _Factory),),
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
        factories=(_EntryPoint("ovstage", _Factory),),
    )
    monkeypatch.setenv("OVUI_DATA_ADAPTER_PROVIDER", "ovstage")
    monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "1")

    with pytest.raises(RuntimeError, match="before omni.ui/OVStage"):
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


def test_explicit_ovstage_missing_factory_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_entry_points(monkeypatch)
    monkeypatch.setenv("OVUI_DATA_ADAPTER_PROVIDER", "ovstage")
    monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "0")

    with pytest.raises(RuntimeError, match="does not publish"):
        bootstrap.preconstruct_selected_native_renderer()


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
        factories=(_EntryPoint("ovstage", _Factory),),
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
            _EntryPoint("ovstage", lambda: object()),
            _EntryPoint("OVSTAGE", lambda: object()),
        ),
    )
    monkeypatch.setenv("OVUI_DATA_ADAPTER_PROVIDER", "ovstage")
    monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "1")

    with pytest.raises(RuntimeError, match="exactly one"):
        bootstrap.preconstruct_selected_native_renderer()


def test_ovstage_distribution_publishes_native_renderer_factory() -> None:
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    metadata_path = repo_root / "ovui-data-adapters" / "dist" / "ovstage" / "pyproject.toml"
    metadata = tomllib.loads(metadata_path.read_text(encoding="utf-8"))

    entry_points_metadata = metadata["project"]["entry-points"]
    assert entry_points_metadata[
        bootstrap._NATIVE_RENDERER_FACTORY_ENTRY_POINT_GROUP
    ] == {
        "ovstage": (
            "ovui_data_adapters.ovstage.renderer_adapter:"
            "OvstageRendererAdapter"
        )
    }


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
        factories=(_EntryPoint("ovstage", lambda: renderer),),
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
