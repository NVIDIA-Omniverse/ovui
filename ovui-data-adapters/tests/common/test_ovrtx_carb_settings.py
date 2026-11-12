# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""OVUI_OVRTX_CARB_SETTINGS reaches ovrtx before a renderer is created.

``ovrtx.RendererConfig`` has no field for a generic Carb setting, and a plugin such
as the MaterialX plugin reads its settings when it starts. These tests use a fake
ovrtx module that records the order of the calls. They need no GPU and no pxr; the
test of the OpenUSD adapter, which needs pxr, is in
``tests/openusd/test_openusd_carb_settings_order.py``.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from ovui_data_adapters.common import ovrtx_carb_settings
from ovui_data_adapters.common.ovrtx_carb_settings import (
    OVRTX_CARB_SETTINGS_ENV,
    OvrtxCarbSettingsError,
    apply_carb_settings,
    apply_environment_carb_settings,
    parse_carb_settings,
)
from ovui_data_adapters.ovstage import renderer_adapter as ovstage_module

DEDUP_KEY = "/persistent/app/material/materialx/disableDeduplication"


class _RendererCreated(Exception):
    """Raised by the fake renderer: the constructor got as far as the renderer."""


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Record every setting that is published, with the renderer config that it got, in order."""

    recorded: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        ovrtx_carb_settings,
        "_publish_with_ovrtx_extension",
        lambda _ovrtx, token, config=None: recorded.append((f"publish {token}", config)),
    )
    return recorded


def _fake_ovrtx(events: list[tuple[str, Any]]) -> ModuleType:
    module = ModuleType("ovrtx")
    module.__version__ = "0.0.0"
    module.AttachMode = SimpleNamespace(BORROW=object())

    class RendererConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    class Renderer:
        # The methods are what the ovstage adapter checks before it creates a renderer.
        def __init__(self, config: Any = None) -> None:
            events.append(("create renderer", config))
            raise _RendererCreated

        def attach_ovstage(self, _stage: Any) -> None: ...

        def detach_ovstage(self) -> None: ...

        def step(self, **_kwargs: Any) -> dict[str, object]:
            return {}

    module.RendererConfig = RendererConfig
    module.Renderer = Renderer
    return module


@pytest.mark.parametrize(
    ("text", "tokens"),
    [
        ("", ()),
        (f"{DEDUP_KEY}=true", (f"--{DEDUP_KEY}=true",)),
        (f"--{DEDUP_KEY}=true", (f"--{DEDUP_KEY}=true",)),
        (
            f" {DEDUP_KEY} = true ;/a/b=1\n\n/c=text with spaces ",
            (f"--{DEDUP_KEY}=true", "--/a/b=1", "--/c=text with spaces"),
        ),
    ],
)
def test_parse_reads_entries_separated_by_semicolons_or_new_lines(text, tokens):
    assert parse_carb_settings(text) == tokens


@pytest.mark.parametrize("entry", ["disableDeduplication=true", "/a/b", "/a/b=", "=true", "/a b=1"])
def test_parse_names_the_bad_entry(entry):
    with pytest.raises(OvrtxCarbSettingsError, match=OVRTX_CARB_SETTINGS_ENV) as raised:
        parse_carb_settings(f"/ok/key=1;{entry}")
    assert repr(entry.strip()) in str(raised.value)


def test_apply_environment_does_nothing_when_the_variable_is_not_set(monkeypatch, events):
    monkeypatch.delenv(OVRTX_CARB_SETTINGS_ENV, raising=False)

    assert apply_environment_carb_settings(_fake_ovrtx(events)) == ()
    assert events == []


def test_apply_environment_publishes_each_entry_in_order(monkeypatch, events):
    monkeypatch.setenv(OVRTX_CARB_SETTINGS_ENV, f"{DEDUP_KEY}=true;/a/b=2")

    applied = apply_environment_carb_settings(_fake_ovrtx(events))

    assert applied == (f"--{DEDUP_KEY}=true", "--/a/b=2")
    assert [name for name, _config in events] == [f"publish --{DEDUP_KEY}=true", "publish --/a/b=2"]


def test_a_malformed_variable_is_an_error_and_publishes_nothing(monkeypatch, events):
    monkeypatch.setenv(OVRTX_CARB_SETTINGS_ENV, "/a/b=1;broken")

    with pytest.raises(OvrtxCarbSettingsError, match="broken"):
        apply_environment_carb_settings(_fake_ovrtx(events))
    assert events == []


#: Versions around the capability check of the settings module.
_FIX = ovrtx_carb_settings._MATERIALX_DEDUPLICATION_FIX_VERSION
_VERSIONS = {
    "older": f"{_FIX[0]}.{_FIX[1] - 1}.1",
    "first that applies the setting": ".".join(str(number) for number in _FIX),
    "newer": f"{_FIX[0]}.{_FIX[1]}.{_FIX[2] + 1}",
    "next major": f"{_FIX[0] + 1}.0.0",
}


@pytest.mark.parametrize(("which", "warns"), [
    ("older", True), ("first that applies the setting", False), ("newer", False), ("next major", False),
])
def test_ignored_deduplication_setting_is_reported_for_old_ovrtx(which, warns, events, caplog):
    version = _VERSIONS[which]
    ovrtx = _fake_ovrtx(events)
    ovrtx.__version__ = version

    with caplog.at_level("WARNING", logger=ovrtx_carb_settings.__name__):
        apply_carb_settings(ovrtx, (f"--{DEDUP_KEY}=true", "--/a/b=1"))

    messages = [record.getMessage() for record in caplog.records]
    assert bool(messages) is warns
    if warns:
        assert f"ovrtx {version} ignores {DEDUP_KEY}" in messages[0]


def test_a_rejected_setting_is_reported_and_stops_the_rest(monkeypatch):
    published: list[str] = []

    def publish(_ovrtx: Any, token: str, _config: Any = None) -> None:
        published.append(token)
        raise OvrtxCarbSettingsError(f"The ovrtx Carb setting {token!r} was rejected: test.")

    monkeypatch.setattr(ovrtx_carb_settings, "_publish_with_ovrtx_extension", publish)

    with pytest.raises(OvrtxCarbSettingsError, match="--/a/b=1"):
        apply_carb_settings(object(), ("--/a/b=1", "--/c/d=2"))
    assert published == ["--/a/b=1"]


def test_ovrtx_without_the_extension_reports_the_missing_extension():
    # The default publisher on an ovrtx copy that has no ctypes bindings.
    ovrtx = ModuleType("ovrtx_without_bindings")

    with pytest.raises(OvrtxCarbSettingsError, match="ovrtx_without_bindings._src.bindings"):
        apply_carb_settings(ovrtx, ("--/a/b=1",))


def _fake_ovrtx_package(monkeypatch: pytest.MonkeyPatch, name: str, with_converter: bool = True) -> SimpleNamespace:
    """An ovrtx package whose library is not loaded yet, and whose library has no settings extension."""

    seen = SimpleNamespace(converted=[], started_with=[])
    package = ModuleType(name)

    class RendererConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    class Renderer:
        pass

    if with_converter:
        def _to_c_config(config: Any) -> tuple[str, Any]:
            seen.converted.append(config)
            return ("c config of", config)

        Renderer._to_c_config = staticmethod(_to_c_config)
    package.RendererConfig = RendererConfig
    package.Renderer = Renderer

    class Function:
        # A ctypes function: the code under test sets argtypes and restype on it.
        def __init__(self, result: Any) -> None:
            self.result = result

        def __call__(self, *_args: Any) -> Any:
            return self.result

    class Library:
        def __init__(self) -> None:
            self.ovrtx_query_extension = Function(SimpleNamespace(status=1))
            self.ovrtx_get_last_error = Function("no such extension")

    class Loader:
        _lib = None

        def create_bindings(self, c_config: Any) -> None:
            seen.started_with.append(c_config)
            self._lib = Library()

    bindings = ModuleType(f"{name}._src.bindings")
    bindings._ovrtx_loader = Loader()
    bindings.OVRTX_API_SUCCESS = 0
    bindings.ovrtx_result_t = object
    bindings.ovx_string_t = str
    bindings.ovrtx_config_t = lambda entries: ("empty config", entries)
    monkeypatch.setitem(sys.modules, f"{name}._src", ModuleType(f"{name}._src"))
    monkeypatch.setitem(sys.modules, f"{name}._src.bindings", bindings)
    seen.package = package
    return seen


def test_the_library_starts_with_the_config_of_the_next_renderer(monkeypatch):
    seen = _fake_ovrtx_package(monkeypatch, "fake_ovrtx_with_converter")
    config = seen.package.RendererConfig(log_file_path="/tmp/renderer.log")

    with pytest.raises(OvrtxCarbSettingsError, match="apply_settings"):
        apply_carb_settings(seen.package, ("--/a/b=1",), config)

    # Not the empty config: ovrtx reads some options only from the first initialization.
    assert seen.converted == [config]
    assert seen.started_with == [("c config of", config)]


def test_the_library_starts_with_the_default_config_when_the_renderer_has_none(monkeypatch):
    seen = _fake_ovrtx_package(monkeypatch, "fake_ovrtx_default_config")

    with pytest.raises(OvrtxCarbSettingsError, match="apply_settings"):
        apply_carb_settings(seen.package, ("--/a/b=1",))

    assert len(seen.converted) == 1 and isinstance(seen.converted[0], seen.package.RendererConfig)


def test_an_ovrtx_that_cannot_convert_a_config_is_reported_by_the_missing_api(monkeypatch):
    seen = _fake_ovrtx_package(monkeypatch, "fake_ovrtx_without_converter", with_converter=False)

    with pytest.raises(OvrtxCarbSettingsError, match=r"fake_ovrtx_without_converter\.Renderer\._to_c_config"):
        apply_carb_settings(seen.package, ("--/a/b=1",))
    assert seen.started_with == []


def test_ovstage_adapter_applies_the_settings_before_it_creates_the_renderer(monkeypatch, events):
    ovrtx = _fake_ovrtx(events)
    monkeypatch.setattr(
        ovstage_module, "import_ovrtx", lambda: SimpleNamespace(module=ovrtx, error=None)
    )
    monkeypatch.setattr(ovstage_module, "_validate_configured_ovrtx_source", lambda _m: None)
    monkeypatch.setattr(ovstage_module, "_detect_gpu_device_name", lambda: "Test GPU")
    # The fake renderer writes no native log. A log reader started here stays
    # after the failed constructor and is seen by the next tests.
    monkeypatch.setattr(ovstage_module, "start_native_log", lambda _owner, _config: None)
    monkeypatch.setenv(OVRTX_CARB_SETTINGS_ENV, f"{DEDUP_KEY}=true")

    with pytest.raises(_RendererCreated):
        ovstage_module.OvstageRendererAdapter()

    assert [name for name, _config in events] == [f"publish --{DEDUP_KEY}=true", "create renderer"]
    # The settings get the config of the renderer that is created next.
    assert events[0][1] is events[1][1] is not None
