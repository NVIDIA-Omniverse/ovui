# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from ovui_widgets.app.application import _normalize_printable_key


def test_inspector_named_keys_normalize_to_application_glfw_shortcuts() -> None:
    assert _normalize_printable_key(522) == 261  # ImGui Delete -> GLFW Delete
    assert _normalize_printable_key(523) == 259  # ImGui Backspace -> GLFW Backspace
    assert _normalize_printable_key(573) == 291  # ImGui F2 -> GLFW F2
    assert _normalize_printable_key(513) == 263  # ImGui Left -> GLFW Left
    assert _normalize_printable_key(514) == 262  # ImGui Right -> GLFW Right
    assert _normalize_printable_key(526) == 256  # ImGui Escape -> GLFW Escape


def test_inspector_printable_keys_normalize_to_ascii() -> None:
    assert _normalize_printable_key(536) == ord("0")
    assert _normalize_printable_key(545) == ord("9")
    assert _normalize_printable_key(546) == ord("A")
    assert _normalize_printable_key(571) == ord("Z")


def test_native_glfw_and_ascii_keys_are_unchanged() -> None:
    assert _normalize_printable_key(261) == 261
    assert _normalize_printable_key(ord("Z")) == ord("Z")


def test_reference_viewer_contributes_the_shared_selection_command(monkeypatch, request):
    import sys
    from pathlib import Path
    from types import SimpleNamespace

    # ovuiinspect ships in the inspector skill, not on the default import
    # path. Load it from the checkout without starting its HTTP server, and
    # unload it afterwards so later tests see a normal launch again.
    monkeypatch.setenv("OVUIINSPECT_ENABLED", "0")
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "skills" / "omniverse-ui-inspector")
    )

    def _unload():
        for name in [name for name in sys.modules if name.split(".")[0] == "ovuiinspect"]:
            del sys.modules[name]

    request.addfinalizer(_unload)
    import ovuiinspect  # noqa: F401
    from ovui_widgets.app.application import Application

    app = Application.__new__(Application)
    app._viewport_window = None
    app._selection_bus = SimpleNamespace(
        get_snapshot=lambda: SimpleNamespace(paths=lambda: ("/World/Cube",))
    )
    commands = {command.name: command for command in app.get_inspector_commands()}
    assert commands["selection_get"].handler() == {"selection": ["/World/Cube"]}
    assert commands["viewport_list"].handler() == {"views": []}
    assert {"viewport_pick", "camera_list", "camera_set"} <= commands.keys()
