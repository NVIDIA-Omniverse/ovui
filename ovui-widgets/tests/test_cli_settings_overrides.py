# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for command-line settings overrides (``--/path/to/key=value``)."""

import json

import pytest

from ovui_widgets.app.__main__ import _parse_args
from ovui_widgets.app.application import Application
from ovui_widgets.app.cli_settings import (
    coerce_value,
    extract_setting_overrides,
    parse_override_token,
)
from ovui_widgets.common.selection import SelectionBus

EXAMPLE_OVERRIDES = [
    "--/ui/theme=light",
    "--/snap/enabled=True",
    "--/snap/grid_size=0.25",
]

EXAMPLE_EXPECTED = {
    "ui.theme": "light",
    "snap.enabled": True,
    "snap.grid_size": 0.25,
}


@pytest.fixture(autouse=True)
def reset_application():
    """Reset Application and SelectionBus singletons before and after each test."""
    Application._instance = None
    SelectionBus._instance = None
    yield
    Application._instance = None
    SelectionBus._instance = None


# ---------------------------------------------------------------------------
# Value coercion
# ---------------------------------------------------------------------------


class TestCoerceValue:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("True", True),
            ("true", True),
            ("FALSE", False),
            ("false", False),
            ("0.25", 0.25),
            ("42", 42),
            ("-7", -7),
            ("light", "light"),
            ("", ""),
            ("1.5e3", 1500.0),
        ],
    )
    def test_scalars(self, text, expected):
        value = coerce_value(text)
        assert value == expected
        assert type(value) is type(expected)


# ---------------------------------------------------------------------------
# Token parsing
# ---------------------------------------------------------------------------


class TestParseOverrideToken:
    def test_slash_path_maps_to_dotted_key(self):
        assert parse_override_token("--/ui/theme=light") == ("ui.theme", "light")

    def test_single_segment(self):
        assert parse_override_token("--/verbose=true") == ("verbose", True)

    @pytest.mark.parametrize(
        "token",
        [
            "--/ui/theme",  # missing =value
            "--/=light",  # empty path
            "--//theme=light",  # empty segment
            "--/ui/theme/=light",  # trailing empty segment
            "--/ui theme=light",  # whitespace in segment
        ],
    )
    def test_malformed_tokens_raise(self, token):
        with pytest.raises(ValueError):
            parse_override_token(token)


# ---------------------------------------------------------------------------
# argv extraction
# ---------------------------------------------------------------------------


class TestExtractSettingOverrides:
    def test_example_with_usd_file(self):
        overrides, remaining = extract_setting_overrides(
            ["scene.usda", *EXAMPLE_OVERRIDES]
        )
        assert overrides == EXAMPLE_EXPECTED
        assert remaining == ["scene.usda"]

    def test_example_without_usd_file(self):
        overrides, remaining = extract_setting_overrides(EXAMPLE_OVERRIDES)
        assert overrides == EXAMPLE_EXPECTED
        assert remaining == []

    def test_overrides_may_precede_positional(self):
        overrides, remaining = extract_setting_overrides(
            ["--/ui/theme=light", "scene.usda"]
        )
        assert overrides == {"ui.theme": "light"}
        assert remaining == ["scene.usda"]

    def test_last_duplicate_wins(self):
        overrides, _ = extract_setting_overrides(
            ["--/ui/theme=dark", "--/ui/theme=light"]
        )
        assert overrides == {"ui.theme": "light"}

    def test_double_dash_ends_extraction(self):
        overrides, remaining = extract_setting_overrides(
            ["--/ui/theme=light", "--", "--/literal=path"]
        )
        assert overrides == {"ui.theme": "light"}
        assert remaining == ["--", "--/literal=path"]


# ---------------------------------------------------------------------------
# _parse_args integration
# ---------------------------------------------------------------------------


class TestParseArgs:
    def test_exact_example_with_usd_file(self):
        args = _parse_args(["scene.usda", *EXAMPLE_OVERRIDES])
        assert args.usd_file == "scene.usda"
        assert args.settings_overrides == EXAMPLE_EXPECTED

    def test_exact_example_without_usd_file(self):
        args = _parse_args(EXAMPLE_OVERRIDES)
        assert args.usd_file is None
        assert args.settings_overrides == EXAMPLE_EXPECTED

    def test_plain_launch_still_works(self):
        args = _parse_args([])
        assert args.usd_file is None
        assert args.settings_overrides == {}

    def test_positional_only_still_works(self):
        args = _parse_args(["scene.usda"])
        assert args.usd_file == "scene.usda"
        assert args.settings_overrides == {}

    @pytest.mark.parametrize(
        "token",
        ["--/ui/theme", "--/=light", "--//theme=light"],
    )
    def test_malformed_override_exits_with_usage_error(self, token, capsys):
        with pytest.raises(SystemExit) as excinfo:
            _parse_args([token])
        assert excinfo.value.code == 2
        assert "invalid settings override" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# main() wiring
# ---------------------------------------------------------------------------


class TestMainWiring:
    def test_main_passes_overrides_and_usd_path(self, monkeypatch):
        import ovui_widgets.app.__main__ as app_main
        import ovui_widgets.app.application as application_module
        import ovui_widgets.app.native_runtime_bootstrap as bootstrap_module

        captured = {}

        class FakeApplication:
            def __init__(self, settings_overrides=None):
                captured["settings_overrides"] = settings_overrides

            def run(self, usd_path=None):
                captured["usd_path"] = usd_path

        monkeypatch.setattr(
            bootstrap_module, "preconstruct_selected_native_renderer", lambda: None
        )
        monkeypatch.setattr(
            bootstrap_module,
            "install_preconstructed_renderer",
            lambda app, bootstrap: None,
        )
        monkeypatch.setattr(application_module, "Application", FakeApplication)

        app_main.main(["scene.usda", *EXAMPLE_OVERRIDES])

        assert captured["settings_overrides"] == EXAMPLE_EXPECTED
        assert captured["usd_path"] == "scene.usda"


# ---------------------------------------------------------------------------
# Application behaviour
# ---------------------------------------------------------------------------


class TestApplicationOverrides:
    def test_overrides_reach_settings_and_startup_consumers(self):
        app = Application(settings_overrides=EXAMPLE_EXPECTED)
        try:
            assert app.settings.get("ui.theme") == "light"
            assert app.settings.get("snap.enabled") is True
            assert app.settings.get("snap.grid_size") == 0.25
            # Startup consumers constructed in __init__ must observe the
            # overridden values, not the defaults.
            assert app.snap_system._enabled is True
            assert app._grid_snap_provider.grid_size == 0.25
        finally:
            app.shutdown()

    def test_no_overrides_keeps_defaults(self):
        app = Application()
        try:
            assert app.settings.get("ui.theme") == "dark"
            assert app.settings.get("snap.enabled") is False
            assert app.settings.get("snap.grid_size") == 1.0
        finally:
            app.shutdown()

    def test_overrides_win_over_persisted_settings(self, tmp_path, monkeypatch):
        persisted = tmp_path / "settings.json"
        persisted.write_text(
            json.dumps({"ui.theme": "dark", "snap.grid_size": 2.0})
        )
        monkeypatch.setenv("OVUI_WIDGETS_SETTINGS_PATH", str(persisted))
        app = Application(settings_overrides={"ui.theme": "light"})
        try:
            # CLI override wins over the persisted value...
            assert app.settings.get("ui.theme") == "light"
            # ...while untouched persisted values still load normally.
            assert app.settings.get("snap.grid_size") == 2.0
        finally:
            app.shutdown()


# ---------------------------------------------------------------------------
# Persistence boundary: overrides are launch-local
# ---------------------------------------------------------------------------


def _relaunch():
    """Reset process singletons so a second Application can be constructed."""
    Application._instance = None
    SelectionBus._instance = None


class TestOverridePersistenceBoundary:
    def test_reviewer_scenario_overrides_do_not_persist(self, tmp_path, monkeypatch):
        """CLI overrides (incl. an unknown key) must not survive into the
        persisted preferences file or the next launch."""
        persisted = tmp_path / "settings.json"
        persisted.write_text(json.dumps({"snap.grid_size": 2.0}))
        monkeypatch.setenv("OVUI_WIDGETS_SETTINGS_PATH", str(persisted))

        overrides = {"ui.theme": "light", "snap.enabled": True, "qa.launch_probe": 7}
        app = Application(settings_overrides=overrides)
        # Effective for this launch.
        assert app.settings.get("ui.theme") == "light"
        assert app.settings.get("snap.enabled") is True
        assert app.settings.get("snap.grid_size") == 2.0
        assert app.settings.get("qa.launch_probe") == 7
        app.shutdown()

        saved = json.loads(persisted.read_text())
        assert saved["ui.theme"] == "dark"  # default, not the override
        assert saved["snap.enabled"] is False
        assert saved["snap.grid_size"] == 2.0  # persisted value retained
        assert "qa.launch_probe" not in saved

        _relaunch()
        app2 = Application()
        try:
            assert app2.settings.get("ui.theme") == "dark"
            assert app2.settings.get("snap.enabled") is False
            assert app2.settings.get("snap.grid_size") == 2.0
            assert app2.settings.get("qa.launch_probe") is None
        finally:
            app2.shutdown()

    def test_runtime_change_to_overridden_key_persists(self, tmp_path, monkeypatch):
        persisted = tmp_path / "settings.json"
        monkeypatch.setenv("OVUI_WIDGETS_SETTINGS_PATH", str(persisted))

        app = Application(settings_overrides={"ui.theme": "light"})
        app.settings.set("ui.theme", "sepia")  # explicit user change
        assert app.settings.get("ui.theme") == "sepia"
        app.shutdown()

        saved = json.loads(persisted.read_text())
        assert saved["ui.theme"] == "sepia"

        _relaunch()
        app2 = Application()
        try:
            assert app2.settings.get("ui.theme") == "sepia"
        finally:
            app2.shutdown()

    def test_runtime_change_to_other_keys_persists_normally(
        self, tmp_path, monkeypatch
    ):
        persisted = tmp_path / "settings.json"
        monkeypatch.setenv("OVUI_WIDGETS_SETTINGS_PATH", str(persisted))

        app = Application(settings_overrides={"ui.theme": "light"})
        app.settings.set("snap.grid_size", 0.5)
        app.shutdown()

        saved = json.loads(persisted.read_text())
        assert saved["snap.grid_size"] == 0.5
        assert saved["ui.theme"] == "dark"  # untouched override stays launch-local

    def test_setting_override_value_explicitly_commits_it(
        self, tmp_path, monkeypatch
    ):
        """Re-affirming the override value via a runtime set() is an explicit
        choice and must persist, even though nothing visibly changes."""
        persisted = tmp_path / "settings.json"
        monkeypatch.setenv("OVUI_WIDGETS_SETTINGS_PATH", str(persisted))

        app = Application(settings_overrides={"ui.theme": "light"})
        app.settings.set("ui.theme", "light")
        app.shutdown()

        saved = json.loads(persisted.read_text())
        assert saved["ui.theme"] == "light"


class TestLaunchOverrideSettingsSemantics:
    """Unit-level checks on Settings.apply_launch_overrides overlay behavior."""

    def test_apply_notifies_subscribers_on_visible_change(self):
        from ovui_widgets.common.settings import Settings

        settings = Settings()
        events = []
        sub = settings.subscribe("ui.theme", lambda k, v: events.append((k, v)))
        settings.apply_launch_overrides({"ui.theme": "light"})
        assert events == [("ui.theme", "light")]
        sub.cancel()

    def test_apply_does_not_notify_when_value_unchanged(self):
        from ovui_widgets.common.settings import Settings

        settings = Settings()
        events = []
        sub = settings.subscribe("ui.theme", lambda k, v: events.append((k, v)))
        settings.apply_launch_overrides({"ui.theme": "dark"})  # equals default
        assert events == []
        assert settings.get("ui.theme") == "dark"
        sub.cancel()

    def test_set_on_overridden_key_notifies_against_visible_value(self):
        from ovui_widgets.common.settings import Settings

        settings = Settings()
        settings.apply_launch_overrides({"ui.theme": "light"})
        events = []
        sub = settings.subscribe("ui.theme", lambda k, v: events.append((k, v)))
        # Store still holds "dark"; visible value is "light". Setting "dark"
        # is a visible change and must notify despite matching the store.
        settings.set("ui.theme", "dark")
        assert events == [("ui.theme", "dark")]
        assert settings.get("ui.theme") == "dark"
        sub.cancel()

    def test_set_equal_to_override_commits_without_notification(self):
        from ovui_widgets.common.settings import Settings

        settings = Settings()
        settings.apply_launch_overrides({"ui.theme": "light"})
        events = []
        sub = settings.subscribe("ui.theme", lambda k, v: events.append((k, v)))
        settings.set("ui.theme", "light")
        assert events == []
        # Committed to the underlying store (would now persist).
        assert settings._data["ui.theme"] == "light"
        sub.cancel()
