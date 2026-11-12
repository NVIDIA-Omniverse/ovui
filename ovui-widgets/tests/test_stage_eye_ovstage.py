# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Regression: the Stage eye under a hidden parent with the real ovstage provider.

Each click goes through the StageDelegate click handler of the eye, the
VisibilityValueModel and the ovstage stage adapter of an opened ovstage
stage. The values are read back from the native stage.
"""

from __future__ import annotations

import pathlib
from typing import Any, Iterator

import pytest
from ovui_data_adapters.ovstage._native import read_token_attribute
from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    create_provider_session,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes
from ovui_data_adapters.ovstage.stage_adapter import OvstageStageAdapter
from ovui_data_adapters.services.undo import UndoManager

from ovui_widgets.stage.widget import stage_delegate as delegate_mod
from ovui_widgets.stage.widget.hierarchy_model import HierarchyModel
from ovui_widgets.stage.widget.stage_delegate import StageDelegate

pytestmark = [pytest.mark.requires_ovstage]

_STATIC_SCENE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "ovui-data-adapters"
    / "tests"
    / "data"
    / "ovstage_static_scene.usda"
)
_PARENT = "/World/VisibilityCases/VisibleParent"
_CHILD = f"{_PARENT}/InheritedVisibleChild"
_HIDDEN_CHILD = f"{_PARENT}/ExplicitHiddenChild"


class _Context:
    def __enter__(self) -> "_Context":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False


class _EyeFrame:
    """The eye frame of one row: its click handler and the eye it drew last."""

    def __init__(self, drawn: list) -> None:
        self._drawn = drawn
        self._build = None
        self._press = None
        self.look: tuple[str, str] | None = None

    def set_mouse_pressed_fn(self, fn: Any) -> None:
        self._press = fn

    def set_build_fn(self, fn: Any) -> None:
        self._build = fn
        self.rebuild()

    def rebuild(self) -> None:
        self._build()
        glyph, name = self._drawn[-1]
        closed = glyph == delegate_mod.stage_icons.eye_off_icon()
        self.look = ("closed" if closed else "open", name)

    def click(self) -> None:
        self._press(0, 0, 0, 0)


class _Eyes:
    """Builds the eye of a row with one StageDelegate, which keeps the repaint subscriptions."""

    def __init__(self) -> None:
        self.delegate = StageDelegate()
        self.frames: list[_EyeFrame] = []

    def of(self, model: HierarchyModel, path: str) -> _EyeFrame:
        item = model.resolve_path(path)
        assert item is not None, f"missing fixture prim: {path}"
        # Column 2 is the eye column of the Stage Browser.
        self.delegate.build_widget(model, item, 2, 0, False)
        return self.frames[-1]


@pytest.fixture()
def eyes(monkeypatch: pytest.MonkeyPatch) -> _Eyes:
    drawn: list[tuple[str, str]] = []
    result = _Eyes()
    frames = result.frames

    def frame(**_kwargs: Any) -> _EyeFrame:
        frames.append(_EyeFrame(drawn))
        return frames[-1]

    def image(glyph: str, **kwargs: Any) -> None:
        drawn.append((glyph, kwargs["name"]))

    monkeypatch.setattr(delegate_mod.ui, "HStack", lambda **_kwargs: _Context())
    monkeypatch.setattr(delegate_mod.ui, "VStack", lambda **_kwargs: _Context())
    monkeypatch.setattr(delegate_mod.ui, "Spacer", lambda **_kwargs: None)
    monkeypatch.setattr(delegate_mod.ui, "Frame", frame)
    monkeypatch.setattr(delegate_mod.ui, "ImageWithProvider", image)
    monkeypatch.setattr(delegate_mod.stage_icons, "provider", lambda path: path)
    return result


@pytest.fixture()
def opened() -> Iterator[tuple[Any, HierarchyModel, UndoManager]]:
    runtime = load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )
    session = create_provider_session(runtime=runtime)
    scene = session.open_stage(str(_STATIC_SCENE_PATH))
    undo = UndoManager()
    model = HierarchyModel(OvstageStageAdapter(scene, undo_manager=undo))
    try:
        yield scene, model, undo
    finally:
        model.detach_document()
        session.shutdown_scene()


def _native(scene: Any, path: str) -> str:
    return read_token_attribute(scene.native_stage, path, "visibility") or "inherited"


def test_second_click_under_hidden_parent_gives_back_the_own_value(opened, eyes) -> None:
    scene, model, _undo = opened
    parent_eye = eyes.of(model, _PARENT)
    parent_eye.click()
    assert _native(scene, _PARENT) == "invisible"

    child_eye = eyes.of(model, _CHILD)
    assert child_eye.look == ("open", "inherited")

    child_eye.click()
    assert _native(scene, _CHILD) == "invisible"
    assert child_eye.look == ("closed", "hidden")

    child_eye.click()
    assert _native(scene, _CHILD) == "inherited"
    assert child_eye.look == ("open", "inherited")
    assert _native(scene, _PARENT) == "invisible"
    assert _native(scene, _HIDDEN_CHILD) == "invisible"

    parent_eye.click()
    assert _native(scene, _PARENT) == "inherited"
    assert _native(scene, _CHILD) == "inherited"


def test_click_on_hidden_child_under_hidden_parent_shows_it(opened, eyes) -> None:
    scene, model, undo = opened
    eyes.of(model, _PARENT).click()
    hidden_eye = eyes.of(model, _HIDDEN_CHILD)
    assert hidden_eye.look == ("closed", "hidden")

    hidden_eye.click()
    assert _native(scene, _HIDDEN_CHILD) == "inherited"
    assert hidden_eye.look == ("open", "inherited")
    assert _native(scene, _PARENT) == "invisible"
    assert _native(scene, _CHILD) == "inherited"

    undo.undo()
    assert _native(scene, _HIDDEN_CHILD) == "invisible"
    undo.redo()
    assert _native(scene, _HIDDEN_CHILD) == "inherited"
    assert _native(scene, _PARENT) == "invisible"
