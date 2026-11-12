# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Regression: File > Exit asks before it drops unsaved layer edits.

The tests use a real :class:`Application` with a file-backed OpenUSD stage,
the real Layers model and the real exit dialog. They drive File > Exit
through ``menu_bar._on_exit`` and press the dialog buttons through its test
helpers, then read the result from the file on disk and from the
application's run flag.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pxr import Sdf, Usd

import ovui_widgets.app.menu_bar as menu_bar
from ovui_widgets.app.application import Application
from ovui_widgets.common import dialogs
from ovui_widgets.common.error_reporter import ErrorReporter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.layers import LayerModel

_SCENE = """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
}
"""


class _LayerWindow:
    """The part of the Layers window that the save path reads."""

    def __init__(self, model: LayerModel) -> None:
        self._model = model

    def destroy(self) -> None:
        self._model.destroy()


def _install(app: Application, stage: Usd.Stage) -> None:
    app.open_stage(stage)
    app._layer_window = _LayerWindow(
        LayerModel(
            app._layer_adapter,
            services=app,
            before_save_all_fn=app._persist_layer_state_before_save,
        )
    )
    app._running = True


@pytest.fixture
def app():
    Application._instance = None
    SelectionBus._instance = None
    application = Application()
    yield application
    dialogs._clear_open_dialogs()
    application.shutdown()
    Application._instance = None
    SelectionBus._instance = None


@pytest.fixture
def scene(tmp_path: Path) -> Path:
    path = tmp_path / "root_only.usda"
    path.write_text(_SCENE)
    return path


@pytest.fixture
def warnings(monkeypatch) -> list[str]:
    shown: list[str] = []
    monkeypatch.setattr(
        ErrorReporter,
        "show_warning",
        classmethod(lambda cls, message, duration_ms=4000: shown.append(message)),
    )
    return shown


def _exit_dialog() -> dialogs._ConfirmUnsavedExitDialog:
    opened = [
        dialog
        for dialog in dialogs._OPEN_DIALOGS
        if isinstance(dialog, dialogs._ConfirmUnsavedExitDialog)
    ]
    assert len(opened) == 1, "File > Exit must open exactly one exit dialog"
    return opened[0]


def _prims_on_disk(path: Path) -> list[str]:
    layer = Sdf.Layer.OpenAsAnonymous(str(path))
    found: list[str] = []
    layer.Traverse(
        Sdf.Path.absoluteRootPath,
        lambda spec_path: found.append(str(spec_path))
        if spec_path.IsPrimPath()
        else None,
    )
    return sorted(found)


class TestFileExitWithUnsavedLayer:
    def test_exit_asks_and_does_not_exit(self, app, scene) -> None:
        stage = Usd.Stage.Open(str(scene))
        _install(app, stage)
        stage.DefinePrim("/World/Xform", "Xform")

        menu_bar._on_exit()

        assert app._running is True, "File > Exit dropped unsaved edits"
        dialog = _exit_dialog()
        assert dialog._layer_names == ["root_only.usda"]
        assert "'root_only.usda'" in dialog._message()

    def test_save_and_exit_writes_the_layer_then_exits(self, app, scene) -> None:
        stage = Usd.Stage.Open(str(scene))
        _install(app, stage)
        stage.DefinePrim("/World/Xform", "Xform")
        menu_bar._on_exit()

        _exit_dialog().save_and_exit()

        assert "/World/Xform" in _prims_on_disk(scene)
        assert stage.GetRootLayer().dirty is False
        assert app._running is False

    def test_exit_without_saving_exits_and_keeps_the_file(self, app, scene) -> None:
        stage = Usd.Stage.Open(str(scene))
        _install(app, stage)
        stage.DefinePrim("/World/Xform", "Xform")
        menu_bar._on_exit()

        _exit_dialog().exit_without_saving()

        assert scene.read_text() == _SCENE
        assert app._running is False

    def test_cancel_keeps_the_app_and_the_edits(self, app, scene) -> None:
        stage = Usd.Stage.Open(str(scene))
        _install(app, stage)
        stage.DefinePrim("/World/Xform", "Xform")
        menu_bar._on_exit()

        _exit_dialog().cancel()

        assert app._running is True
        assert stage.GetRootLayer().dirty is True
        assert stage.GetPrimAtPath("/World/Xform").IsValid()
        assert scene.read_text() == _SCENE

    def test_viewer_state_in_the_session_layer_alone_does_not_ask(
        self, app, scene,
    ) -> None:
        stage = Usd.Stage.Open(str(scene))
        _install(app, stage)
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            stage.DefinePrim("/OvGearSession/Cameras/Main", "Camera")
        assert stage.GetSessionLayer().dirty is True

        menu_bar._on_exit()

        assert app._running is False
        assert not any(
            isinstance(dialog, dialogs._ConfirmUnsavedExitDialog)
            for dialog in dialogs._OPEN_DIALOGS
        )

    def test_edits_that_save_all_cannot_write_keep_the_app_open(
        self, app, scene, warnings,
    ) -> None:
        stage = Usd.Stage.Open(str(scene))
        _install(app, stage)
        anonymous = Sdf.Layer.CreateAnonymous("unsaved_sublayer")
        stage.GetRootLayer().subLayerPaths.append(anonymous.identifier)
        with Usd.EditContext(stage, anonymous):
            stage.DefinePrim("/World/OnlyInMemory", "Xform")
        menu_bar._on_exit()

        _exit_dialog().save_and_exit()

        assert app._running is True
        assert anonymous.dirty is True
        assert len(warnings) == 1 and warnings[0].startswith("Exit cancelled")


def _set_authoring_layer(app: Application, identifier: str) -> None:
    """Do what Layers > right-click > Set as Authoring Layer does."""
    from ovui_widgets.layers.commands.layer_commands import SetEditTargetCommand

    app.undo_manager.push(
        SetEditTargetCommand(app._layer_adapter, app.selection_bus, identifier)
    )


class TestFileExitWithSessionLayerEdits:
    def test_prim_made_in_the_session_layer_asks(self, app, scene) -> None:
        stage = Usd.Stage.Open(str(scene))
        _install(app, stage)
        _set_authoring_layer(app, stage.GetSessionLayer().identifier)
        stage.DefinePrim("/World/Xform", "Xform")
        # The prim stays in the session layer after the user switches back.
        _set_authoring_layer(app, stage.GetRootLayer().identifier)

        menu_bar._on_exit()

        assert app._running is True, "File > Exit dropped a session-layer edit"
        assert _exit_dialog()._layer_names == ["session layer"]

    def test_session_layer_as_authoring_layer_asks(self, app, scene) -> None:
        stage = Usd.Stage.Open(str(scene))
        _install(app, stage)
        _set_authoring_layer(app, stage.GetSessionLayer().identifier)
        # A user edit inside the viewer's own scope looks like viewer state;
        # the authoring-layer choice is what makes it count.
        stage.DefinePrim("/OvGearSession/Lights/Key", "DistantLight")

        menu_bar._on_exit()

        assert app._running is True
        assert _exit_dialog()._layer_names == ["session layer"]

    def test_save_and_exit_keeps_session_layer_edits_and_the_app(
        self, app, scene, warnings,
    ) -> None:
        stage = Usd.Stage.Open(str(scene))
        _install(app, stage)
        _set_authoring_layer(app, stage.GetSessionLayer().identifier)
        stage.DefinePrim("/World/Xform", "Xform")
        menu_bar._on_exit()

        _exit_dialog().save_and_exit()

        # The session layer has no file: the app stays open with the edit.
        assert app._running is True
        assert stage.GetPrimAtPath("/World/Xform").IsValid()
        assert len(warnings) == 1 and "session layer" in warnings[0]

    def test_modified_session_sublayer_asks(self, app, scene) -> None:
        stage = Usd.Stage.Open(str(scene))
        _install(app, stage)
        sublayer = Sdf.Layer.CreateAnonymous("session_sublayer")
        stage.GetSessionLayer().subLayerPaths.append(sublayer.identifier)
        with Usd.EditContext(stage, sublayer):
            stage.DefinePrim("/World/FromSublayer", "Xform")

        menu_bar._on_exit()

        assert app._running is True
        assert _exit_dialog()._layer_names == ["session layer", "anonymous"]


class TestFileExitWithNewStage:
    def test_save_and_exit_asks_for_a_file_and_exits_after_the_save(
        self, app, tmp_path, monkeypatch,
    ) -> None:
        from ovui_widgets.content.file_exporter import FileExporterHelper

        pickers: list[dict] = []
        monkeypatch.setattr(
            FileExporterHelper,
            "show",
            lambda self, **kwargs: pickers.append(kwargs),
        )
        stage = app._create_empty_startup_stage()
        _install(app, stage)
        stage.DefinePrim("/World/Xform", "Xform")
        menu_bar._on_exit()

        _exit_dialog().save_and_exit()

        # The New Stage file is temporary: no exit before the user picks a file.
        assert app._running is True
        assert len(pickers) == 1
        pickers[0]["export_handler"](
            "kept", str(tmp_path), ".usda", [],
        )
        assert "/World/Xform" in _prims_on_disk(tmp_path / "kept.usda")
        assert app._running is False

    def test_save_and_exit_keeps_session_layer_edits_of_a_new_stage(
        self, app, tmp_path, monkeypatch, warnings,
    ) -> None:
        from ovui_widgets.content.file_exporter import FileExporterHelper

        pickers: list[dict] = []
        monkeypatch.setattr(
            FileExporterHelper,
            "show",
            lambda self, **kwargs: pickers.append(kwargs),
        )
        stage = app._create_empty_startup_stage()
        _install(app, stage)
        _set_authoring_layer(app, stage.GetSessionLayer().identifier)
        stage.DefinePrim("/World/Xform", "Xform")
        menu_bar._on_exit()

        _exit_dialog().save_and_exit()
        pickers[0]["export_handler"](
            "kept", str(tmp_path), ".usda", [],
        )

        # File > Save wrote the file, but not the session layer: the app
        # stays open with the edit.
        assert (tmp_path / "kept.usda").exists()
        assert "/World/Xform" not in _prims_on_disk(tmp_path / "kept.usda")
        assert app._running is True
        assert stage.GetPrimAtPath("/World/Xform").IsValid()
        assert len(warnings) == 1 and "session layer" in warnings[0]
