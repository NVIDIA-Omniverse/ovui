# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Regression: after File > Save As of a New Stage, a save writes the saved file.

The root layer of a New Stage is a file in a temporary folder that the app
deletes at exit. The tests use a real :class:`Application`, a real New Stage,
the real Layers window and model with the hooks that the app gives them, and
File > Save As through ``menu_bar._on_save_as_clicked``, with the file picker
answered through its export handler. They read the result from the files on
disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ovui_data_adapters.openusd.layer_stack_adapter import (
    AUTHORING_LAYER_KEY,
    OVGEAR_LAYER_KEY,
)
from pxr import Sdf, Usd

import ovui_widgets.app.menu_bar as menu_bar
from ovui_widgets.app.application import Application
from ovui_widgets.common.error_reporter import ErrorReporter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.content.file_exporter import FileExporterHelper
from ovui_widgets.layers import LayerWindow


@pytest.fixture
def app():
    Application._instance = None
    SelectionBus._instance = None
    application = Application()
    yield application
    application.shutdown()
    Application._instance = None
    SelectionBus._instance = None


@pytest.fixture
def new_stage(app) -> Usd.Stage:
    """A New Stage, with the Layers window built as ``Application.run`` builds it."""
    app._layer_window = LayerWindow(
        services=app,
        before_save_all_fn=app._persist_layer_state_before_save,
        before_root_save_fn=app._save_document_before_root_save,
    )
    stage = app._create_empty_startup_stage()
    app.open_stage(stage)
    return stage


@pytest.fixture
def errors(monkeypatch) -> list[str]:
    shown: list[str] = []
    monkeypatch.setattr(
        ErrorReporter,
        "show_error",
        classmethod(lambda cls, message, duration_ms=5000: shown.append(message)),
    )
    return shown


def _save_as(app: Application, monkeypatch, folder: Path, name: str) -> Path:
    """File > Save As: the user goes to ``folder``, types ``name`` and clicks Save."""
    pickers: list[dict] = []
    monkeypatch.setattr(
        FileExporterHelper,
        "show",
        lambda self, **kwargs: pickers.append(kwargs),
    )
    menu_bar._on_save_as_clicked(app)
    assert len(pickers) == 1, "File > Save As must open one file picker"
    pickers[0]["export_handler"](name, str(folder), ".usd", [])
    saved = folder / name
    assert saved.is_file(), "File > Save As did not write the file"
    return saved


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


class TestSaveAfterSaveAsOfANewStage:
    def test_ctrl_s_writes_later_edits_to_the_saved_file(
        self, app, new_stage, tmp_path, monkeypatch,
    ) -> None:
        new_stage.DefinePrim("/World/Cube", "Cube")
        saved = _save_as(app, monkeypatch, tmp_path, "b3_r2.usd")
        new_stage.DefinePrim("/World/Sphere", "Sphere")

        # Ctrl+S is Layer > Save All.
        app.save_stage()

        assert _prims_on_disk(saved) == ["/World", "/World/Cube", "/World/Sphere"]
        # The modified mark goes away only after the saved file has the edit.
        assert new_stage.GetRootLayer().dirty is False

    def test_save_of_the_root_row_writes_later_edits_to_the_saved_file(
        self, app, new_stage, tmp_path, monkeypatch,
    ) -> None:
        new_stage.DefinePrim("/World/Cube", "Cube")
        saved = _save_as(app, monkeypatch, tmp_path, "b3_r2.usd")
        new_stage.DefinePrim("/World/Sphere", "Sphere")
        model = app._layer_window._model

        # The save button of the root row, and Layer > Save Layer.
        model._request_save(model.root_item)

        assert _prims_on_disk(saved) == ["/World", "/World/Cube", "/World/Sphere"]
        assert new_stage.GetRootLayer().dirty is False

    def test_save_of_the_root_row_does_not_save_a_changed_sublayer(
        self, app, new_stage, tmp_path, monkeypatch,
    ) -> None:
        saved = _save_as(app, monkeypatch, tmp_path, "paths.usd")
        # A layer under the root, saved to child.usda, is the authoring layer.
        child_path = tmp_path / "child.usda"
        child = Sdf.Layer.CreateNew(str(child_path))
        new_stage.GetRootLayer().subLayerPaths.append(child.identifier)
        child_text = child_path.read_text()
        new_stage.SetEditTarget(Usd.EditTarget(child))
        new_stage.DefinePrim("/World/Sphere", "Sphere")
        model = app._layer_window._model

        # Only the save button of the root row.
        model._request_save(model.root_item)

        # The other layer keeps its unsaved edit and its modified mark.
        assert child_path.read_text() == child_text
        assert child.dirty is True
        # The saved file has the root layer, with its sublayer list and, as
        # File > Save writes it, the authoring layer.
        saved_root = Sdf.Layer.OpenAsAnonymous(str(saved))
        assert list(saved_root.subLayerPaths) == [child.identifier]
        layer_state = saved_root.customLayerData[OVGEAR_LAYER_KEY]
        assert layer_state[AUTHORING_LAYER_KEY] == child.identifier
        assert new_stage.GetRootLayer().dirty is False

    def test_a_stage_opened_from_a_file_saves_only_to_its_own_file(
        self, app, tmp_path, monkeypatch,
    ) -> None:
        # The app starts with a New Stage, as it does with no scene file.
        app._layer_window = LayerWindow(
            services=app,
            before_save_all_fn=app._persist_layer_state_before_save,
            before_root_save_fn=app._save_document_before_root_save,
        )
        app.open_stage(app._create_empty_startup_stage())
        opened = tmp_path / "opened.usda"
        stage = Usd.Stage.CreateNew(str(opened))
        stage.DefinePrim("/World/Cube", "Cube")
        stage.GetRootLayer().Save()
        del stage
        app._startup_prebuilt_renderer = None
        # File > Open: this stage is not a New Stage.
        app.open_file(str(opened))
        copy = _save_as(app, monkeypatch, tmp_path, "copy.usd")
        copy_bytes = copy.read_bytes()
        app._stage_adapter.stage.DefinePrim("/World/Sphere", "Sphere")

        app.save_stage()

        # Ctrl+S saves the root layer to its own file only, as before.
        assert _prims_on_disk(opened) == ["/World", "/World/Cube", "/World/Sphere"]
        assert copy.read_bytes() == copy_bytes

    def test_a_failed_write_of_the_saved_file_keeps_the_modified_mark(
        self, app, new_stage, tmp_path, monkeypatch, errors,
    ) -> None:
        new_stage.DefinePrim("/World/Cube", "Cube")
        saved = _save_as(app, monkeypatch, tmp_path, "b3_r2.usd")
        # A folder now has the name of the saved file: the file cannot be written.
        saved.unlink()
        saved.mkdir()
        temporary_root = Path(new_stage.GetRootLayer().realPath)
        temporary_text = temporary_root.read_text()
        new_stage.DefinePrim("/World/Sphere", "Sphere")

        app.save_stage()

        assert len(errors) == 1 and errors[0].startswith("Cannot save file:")
        assert new_stage.GetRootLayer().dirty is True
        assert temporary_root.read_text() == temporary_text
