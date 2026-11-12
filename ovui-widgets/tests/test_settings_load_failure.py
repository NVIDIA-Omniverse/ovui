# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A settings file that does not load is reported and kept.

The app uses the default settings when ``settings.json`` does not load. The
save at exit writes over that file, so the app must first keep a copy of the
damaged file, and it must tell the user about the fallback.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import omni.ui as ui
import pytest

import ovui_widgets.app.application as application_module
from ovui_widgets.app.application import Application
from ovui_widgets.common import dialogs
from ovui_widgets.common.selection import SelectionBus

_VALID = json.dumps(
    {
        "ui.theme": "light",
        "snap.grid_size": 0.25,
        "ui.recent_files": ["/scenes/first.usda", "/scenes/second.usda"],
    },
    indent=2,
)
# Cut at half its length, as an interrupted save leaves it.
_CUT = _VALID[: len(_VALID) // 2]


@pytest.fixture
def settings_path(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "settings.json"
    monkeypatch.setenv("OVUI_WIDGETS_SETTINGS_PATH", str(path))
    return path


@pytest.fixture
def new_app():
    made: list[Application] = []

    def _make() -> Application:
        Application._instance = None
        SelectionBus._instance = None
        made.append(Application())
        return made[-1]

    yield _make
    dialogs._clear_open_dialogs()
    for app in made:
        app.shutdown()  # a second call does nothing
    Application._instance = None
    SelectionBus._instance = None


def _copies(settings_path: Path) -> list[Path]:
    return sorted(settings_path.parent.glob("settings.damaged-*.json"))


def _shown_texts(widget) -> list[str]:
    """Texts of the labels and buttons that the user sees in ``widget``."""
    texts = [widget.text] if isinstance(widget, (ui.Label, ui.Button)) else []
    for child in ui.Inspector.get_children(widget):
        texts.extend(_shown_texts(child))
    return texts


@pytest.mark.parametrize("damaged", [_CUT, ""], ids=["cut", "empty"])
def test_exit_keeps_a_copy_of_the_damaged_file(
    settings_path, new_app, capsys, damaged
) -> None:
    settings_path.write_text(damaged, encoding="utf-8")

    app = new_app()
    assert app.settings.get("ui.theme") == "dark"
    app.shutdown()

    copies = _copies(settings_path)
    assert len(copies) == 1, "the damaged settings file was not kept"
    assert copies[0].read_text(encoding="utf-8") == damaged
    # The save at exit still writes the settings of this session.
    assert json.loads(settings_path.read_text(encoding="utf-8"))["ui.theme"] == "dark"
    err = capsys.readouterr().err
    assert "The default settings are used." in err
    assert copies[0].name in err


def test_a_new_copy_never_replaces_an_earlier_copy(settings_path, new_app) -> None:
    settings_path.write_text(_CUT, encoding="utf-8")
    new_app().shutdown()
    settings_path.write_text("", encoding="utf-8")  # damaged again

    new_app().shutdown()

    copies = _copies(settings_path)
    assert len(copies) == 2
    assert sorted(copy.read_text(encoding="utf-8") for copy in copies) == ["", _CUT]


def test_no_copy_means_no_save_over_the_damaged_file(
    settings_path, new_app, monkeypatch, capsys
) -> None:
    settings_path.write_text(_CUT, encoding="utf-8")

    def _no_copy(path: str) -> str:
        raise PermissionError(f"cannot write next to {path!r}")

    monkeypatch.setattr(application_module, "_keep_damaged_settings_copy", _no_copy)

    app = new_app()
    app.shutdown()

    assert settings_path.read_text(encoding="utf-8") == _CUT
    assert _copies(settings_path) == []
    assert "settings are not saved" in capsys.readouterr().err


def test_the_dialog_names_the_fallback_the_file_and_the_copy(
    settings_path, new_app
) -> None:
    settings_path.write_text(_CUT, encoding="utf-8")
    app = new_app()

    app._report_settings_load_failure()

    window = ui.Workspace.get_window("Settings Not Loaded")
    assert window is not None and window.visible, "the fallback was not shown"
    message, button = _shown_texts(window.frame)
    assert "It uses the default settings." in message
    assert f"File: {settings_path}" in message
    assert _copies(settings_path)[0].name in message
    assert button == "OK"


def test_a_valid_file_shows_no_dialog_and_makes_no_copy(
    settings_path, new_app
) -> None:
    settings_path.write_text(_VALID, encoding="utf-8")
    app = new_app()

    app._report_settings_load_failure()

    assert app.settings.get("ui.theme") == "light"
    assert ui.Workspace.get_window("Settings Not Loaded") is None
    assert _copies(settings_path) == []


def test_the_same_damaged_file_again_uses_the_earlier_copy(
    settings_path, new_app, capsys
) -> None:
    settings_path.write_text(_CUT, encoding="utf-8")
    new_app().shutdown()
    # The same damaged file again, for example after a crash before the save.
    settings_path.write_text(_CUT, encoding="utf-8")
    capsys.readouterr()

    new_app().shutdown()

    copies = _copies(settings_path)
    assert len(copies) == 1, "a second copy with the same bytes was made"
    assert copies[0].read_text(encoding="utf-8") == _CUT
    assert copies[0].name in capsys.readouterr().err


def test_a_link_to_the_settings_file_is_not_taken_as_its_copy(
    settings_path, new_app
) -> None:
    settings_path.write_text(_CUT, encoding="utf-8")
    link = settings_path.parent / "settings.damaged-20000101-000000.json"
    os.link(settings_path, link)

    new_app().shutdown()

    kept = [copy.read_text(encoding="utf-8") for copy in _copies(settings_path)]
    assert _CUT in kept, "the save at exit wrote over the only copy"


def test_a_frame_rate_too_large_for_a_float_is_refused_and_the_rest_loads(
    settings_path, new_app
) -> None:
    rate_key = "app.runLoops.main.rateLimitFrequency"
    # The bad value comes first, so a load that stops at it reads nothing.
    text = '{"%s": %s, "ui.theme": "light"}' % (rate_key, "9" * 400)
    settings_path.write_text(text, encoding="utf-8")

    app = new_app()

    assert app.settings.get("ui.theme") == "light"
    assert app.settings.get(rate_key) is None
    assert _copies(settings_path) == []


def test_valid_json_that_is_not_an_object_has_a_plain_cause(
    settings_path, new_app, capsys
) -> None:
    settings_path.write_text('["ui.theme", "light"]', encoding="utf-8")

    new_app()

    err = capsys.readouterr().err
    assert "The file holds a JSON array, not a JSON object with settings" in err
    assert "has no attribute" not in err
