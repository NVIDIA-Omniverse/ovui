# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import logging
from types import SimpleNamespace

import pytest

from ovui_data_adapters.common import ovrtx_compile_limits as limits

TOKENS_FOR_3 = ["--/gpu/shadercompiler/warmcountMax=3", "--/gpu/shadercompiler/warmcount=3"]


@pytest.fixture
def applied(monkeypatch):
    calls: list[list[str]] = []
    result = {"error": ""}

    def apply(tokens, config=None):
        calls.append(list(tokens))
        result["config"] = config
        return result["error"]

    monkeypatch.setattr(limits, "apply_setting_tokens", apply)
    return calls, result


def test_without_the_setting_nothing_is_applied_and_ovrtx_is_not_touched(monkeypatch, applied):
    calls, _result = applied
    for value in (None, "", "native", " Native "):
        if value is None:
            monkeypatch.delenv(limits.SESSIONS_ENV, raising=False)
        else:
            monkeypatch.setenv(limits.SESSIONS_ENV, value)
        assert limits.limit_shader_compile_sessions() is None
    assert calls == []


def test_the_setting_publishes_both_compiler_tokens(monkeypatch, applied, caplog):
    calls, result = applied
    monkeypatch.setenv(limits.SESSIONS_ENV, "3")
    config = SimpleNamespace(log_file_path="/logs/ovui.log")
    with caplog.at_level(logging.INFO, logger="ovui.render_diagnostics"):
        assert limits.limit_shader_compile_sessions(config) == 3
    assert calls == [TOKENS_FOR_3] and result["config"] is config  # the config of the renderer that comes next
    assert "shader compiler sessions limited to 3" in caplog.text


class _Loader:
    """The library loader of a fake ovrtx: it records the config of the first initialization."""

    def __init__(self):
        self._lib = None
        self.initialized = []

    def create_bindings(self, c_config):
        self.initialized.append(c_config)
        self._lib = SimpleNamespace(ovrtx_query_extension=_NoExtension())


class _NoExtension:
    def __call__(self, name, pointer):
        return SimpleNamespace(status=1)


def _fake_ovrtx(monkeypatch):
    class RendererConfig(SimpleNamespace):
        pass

    class Renderer:
        @staticmethod
        def _to_c_config(config):
            return ("c config", config)

    loader = _Loader()
    bindings = SimpleNamespace(_ovrtx_loader=loader, ovrtx_result_t=object, OVRTX_API_SUCCESS=0)
    module = SimpleNamespace(_src=SimpleNamespace(bindings=bindings), Renderer=Renderer, RendererConfig=RendererConfig)
    from ovui_data_adapters.common import ovrtx_import

    monkeypatch.setattr(ovrtx_import, "import_ovrtx", lambda: SimpleNamespace(module=module, error=None))
    return loader, RendererConfig


def test_a_library_that_is_not_loaded_is_initialized_with_the_config_of_the_next_renderer(monkeypatch):
    # The library takes its process-wide settings (the log file) from its first initialization.
    loader, config_type = _fake_ovrtx(monkeypatch)
    config = config_type(log_file_path="/logs/ovui.log")
    assert "no 'ovrtx.settings.apply_settings' extension" in limits.apply_setting_tokens(TOKENS_FOR_3, config)
    assert loader.initialized == [("c config", config)]
    # Once loaded, the library is not initialized again; without a config it gets the default one.
    limits.apply_setting_tokens(TOKENS_FOR_3, config_type(log_file_path="/other.log"))
    assert len(loader.initialized) == 1
    loader, config_type = _fake_ovrtx(monkeypatch)
    limits.apply_setting_tokens(TOKENS_FOR_3)
    assert loader.initialized == [("c config", config_type())]


def test_a_failed_apply_is_reported_with_the_reason(monkeypatch, applied, caplog):
    calls, result = applied
    result["error"] = "this ovrtx has no 'ovrtx.settings.apply_settings' extension"
    monkeypatch.setenv(limits.SESSIONS_ENV, "3")
    with caplog.at_level(logging.WARNING, logger="ovui.render_diagnostics"):
        assert limits.limit_shader_compile_sessions() is None
    assert calls == [TOKENS_FOR_3]
    assert "could not limit shader compiler sessions to 3: this ovrtx has no" in caplog.text


@pytest.mark.parametrize("value", ["0", "-2", "many"])
def test_a_bad_value_is_reported_and_nothing_is_applied(monkeypatch, applied, caplog, value):
    calls, _result = applied
    monkeypatch.setenv(limits.SESSIONS_ENV, value)
    with caplog.at_level(logging.WARNING, logger="ovui.render_diagnostics"):
        assert limits.limit_shader_compile_sessions() is None
    assert calls == []
    assert f"{limits.SESSIONS_ENV}={value!r} is not 'native' or a number" in caplog.text


@pytest.mark.requires_ovrtx
@pytest.mark.own_process
def test_the_settings_extension_of_the_installed_ovrtx_accepts_the_tokens():
    assert limits.apply_setting_tokens(TOKENS_FOR_3) == ""
