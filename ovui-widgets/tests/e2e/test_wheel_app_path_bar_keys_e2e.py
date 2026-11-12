# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Typing in the Content Browser path bar must not run viewport shortcuts.

Issue 509 (OMPE-118439): with an object selected and the camera moved, the
user double-clicked the Content Browser path bar and typed "f": the viewport
framed the selection. The user single-clicked the path bar and typed "h": the
camera went back to its home view. A single click gave the path field no
keyboard focus, and the one-key viewport shortcuts (F, H, W, E, R) ran while
the path field was editing.

The installed windowed USD Viewer (real ovrtx renderer, OpenUSD provider) is
driven only with injected mouse and keyboard input through the ovui inspector.
A real key gives a key event and a character. The test sends both for each
typed letter (``press`` and then ``type``), so each letter also reaches the
application shortcuts as a real key does. The camera state is the orbit state
of the viewport camera (target, distance, azimuth, elevation) in the app state.

1. Click the cube in the viewport, then zoom out with the mouse wheel.
2. Double-click the path bar and type "f" and "h". The camera must not change,
   and the path field must hold "fh". Press Escape.
3. Single-click the path bar outside the breadcrumbs: the path field must edit.
   Type the path of a test folder. The letters of its last part,
   ``frame_home_view``, are typed as keys. After each shortcut letter the
   camera and the viewport tool must not change. The folder suggestions must
   list ``frame_home_view/``. Press Enter: the Content Browser must go to the
   folder.
4. Single-click a folder name in the path bar, then another: each click must
   take the Content Browser to that folder and keep the folder names (the path
   field does not open).
5. Type the test folder path with a slash at the end, press Down until
   ``other_folder/`` is highlighted, press Enter: the Content Browser must go to
   ``other_folder``. Click the path bar, press Tab, type the test folder path
   and "fr", click the suggestion ``frame_home_view/``: the Content Browser
   must go to that folder (Tab does not end the edit, and it must not turn
   the click into an apply of the typed text).
6. Click the cube in the viewport and press F: the camera must change. Press H:
   the camera must go back to the view that the scene opened with.
7. Drag the Content tab out of the dock, so that the Content Browser floats.
   Single-click its path bar outside the breadcrumbs and type "f": the camera
   and the viewport tool must not change, and the path field must hold "f".
   Then type the test folder path: the field must hold all the typed text.

Paths are compared as the platform compares them: on Windows a path has no
case, and the Content Browser shows the typed ``C:/...`` as ``c:/...``.

The test takes no screenshot and has no reference image. It checks the camera,
the viewport tool and the path bar in the app state after each action.
"""

from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path

import pytest


def _load_by_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HERE = Path(__file__).resolve().parent
driver = _load_by_path("ovui_e2e_driver_path_bar_keys", _HERE / "driver.py")
field_delete = _load_by_path(
    "ovui_e2e_field_delete_helpers_path_bar_keys",
    _HERE / "test_wheel_app_field_delete_e2e.py",
)
pytestmark = pytest.mark.requires_ovrtx

CUBE = driver.SELECTED_PRIM
FOLDER = "frame_home_view"
# One-key viewport shortcuts: frame selected, home, and the W/E/R tools.
SHORTCUT_LETTERS = "fhwer"
# A shortcut can move the camera over some frames; wait this long before a
# check that the camera did not change.
SETTLE = 0.5


def _folder_text(path: str) -> str:
    """``path`` in the form that this platform compares folders in.

    On Windows ``os.path.normcase`` folds the case and the slashes (``C:/x``
    and ``c:/x`` are the same folder); on Linux it changes nothing.
    """
    return os.path.normcase(os.path.normpath(path)).rstrip("\\/")


def _in_folder(shown: str, folder: str) -> bool:
    """True when the Content Browser path ``shown`` is the folder ``folder``."""
    return _folder_text(shown).endswith(_folder_text(folder))


def _same_camera(a: dict | None, b: dict | None, tolerance: float = 1.0e-4) -> bool:
    if not a or not b:
        return False
    return all(
        abs(float(x) - float(y)) <= tolerance for x, y in zip(a["target"], b["target"])
    ) and all(
        abs(float(a[key]) - float(b[key])) <= tolerance
        for key in ("distance", "azimuth", "elevation")
    )


class _Flow:
    def __init__(self, session):
        self.session = session

    def state(self) -> dict:
        return self.session.state()

    def camera(self) -> dict:
        camera = self.state()["viewport"].get("camera")
        assert camera, (
            "the app state has no viewport camera\n"
            f"--- app log ---\n{self.session.log_tail()}"
        )
        return camera

    def still_camera(self, timeout: float = 20.0) -> dict:
        """Wait until the camera stops moving (a zoom eases out); return it."""
        deadline = time.monotonic() + timeout
        last = self.camera()
        while True:
            time.sleep(SETTLE)
            camera = self.camera()
            if _same_camera(camera, last):
                return camera
            assert time.monotonic() < deadline, (
                f"the camera did not stop moving: {last} -> {camera}"
            )
            last = camera

    def wait(self, check, what: str, timeout: float = 20.0) -> dict:
        """Wait until ``check(state)`` is true; return that state."""
        deadline = time.monotonic() + timeout
        while True:
            state = self.state()
            if check(state):
                return state
            if time.monotonic() > deadline:
                raise AssertionError(
                    f"{what}; content_ui: {state.get('content_ui')}; "
                    f"camera: {state['viewport'].get('camera')}\n"
                    f"--- app log ---\n{self.session.log_tail()}"
                )
            time.sleep(0.5)

    def assert_unchanged(self, camera: dict, tool: str, where: str) -> None:
        time.sleep(SETTLE)
        state = self.state()
        actual = state["viewport"].get("camera")
        assert _same_camera(actual, camera), (
            f"the camera changed {where}: {camera} -> {actual}\n"
            f"--- app log ---\n{self.session.log_tail()}"
        )
        assert state["viewport"]["active_tool"] == tool, (
            f"the viewport tool changed {where}: {tool!r} -> "
            f"{state['viewport']['active_tool']!r}"
        )

    def key(self, letter: str) -> None:
        """One typed letter: its key event, then its character."""
        self.session.press(letter)
        self.session.type_text(letter)

    def path_bar_point(self) -> tuple[int, int]:
        """A point on the visible path bar that is not on a breadcrumb.

        In the 1000x720 test window the path bar is narrow, and a long path
        fills it. Then the separators between the breadcrumbs are the free
        parts of the bar. Take the centre of the right-most free part.
        """
        content = self.state()["content_ui"]
        assert content.get("available"), f"no Content Browser path bar: {content}"
        rect = content["path_bar_rect"]
        taken = [
            (r["x"], r["x"] + r["width"])
            for r in (crumb["rect"] for crumb in content["breadcrumbs"])
            if r
        ]
        free = [
            x for x in range(int(rect["x"]) + 2, int(rect["x"] + rect["width"]) - 2)
            if not any(a <= x < b for a, b in taken)
        ]
        assert free, f"no point of the path bar is free of breadcrumbs: {content}"
        end = start = free[-1]
        while start - 1 in free:
            start -= 1
        return (start + end) // 2, int(rect["y"] + rect["height"] / 2)


    def visible_breadcrumbs(self) -> list:
        """Folder breadcrumbs that are fully inside the visible path bar.

        In the 1000x720 test window the path bar is narrow and a long path
        is cut at its right edge. The URL scheme token (``file://``) is not
        a folder.
        """
        content = self.state()["content_ui"]
        bar = content["path_bar_rect"]
        return [
            crumb for crumb in content["breadcrumbs"]
            if crumb["rect"]
            and not crumb["text"].endswith("://")
            and crumb["rect"]["x"] >= bar["x"]
            and crumb["rect"]["x"] + crumb["rect"]["width"] <= bar["x"] + bar["width"]
        ]

    def click_folder_name(self, crumb: dict, camera: dict, tool: str, where: str) -> None:
        """Click a breadcrumb: the browser goes there and keeps the names."""
        before = self.state()["content_ui"]["path"]
        self.session.click(*crumb["point"])
        name = crumb["text"].rstrip("/")
        self.wait(
            lambda s: not s["content_ui"]["editing"]
            and _in_folder(s["content_ui"]["path"], name)
            and s["content_ui"]["breadcrumbs"]
            and s["content_ui"]["breadcrumbs"][-1]["text"].rstrip("/") == name
            and s["content_ui"]["breadcrumbs"][-1]["rect"],
            f"a single click on the {where} {name!r} did not open that folder "
            f"with the folder names shown (path before: {before!r})",
        )
        self.assert_unchanged(camera, tool, f"after a click on the {where}")
        state = self.state()["content_ui"]
        assert not state["editing"], (
            f"the path field opened after a click on the {where} {name!r}: {state}"
        )

    def float_content_window(self) -> None:
        """Drag the Content tab out of the dock, as a user does."""
        state = self.state()
        window = state["content_ui"].get("window")
        assert window and window["docked"], f"the Content window is not docked: {window}"
        rect = window["rect"]
        # The tab of a docked window is at the top left of the window.
        tab = (int(rect["x"]) + 28, int(rect["y"]) + 12)
        # Drop it near the top left of the viewport, away from the docking
        # targets in the middle of the viewport and of its edges.
        image = state["viewport"]["image_rect"]
        drop = (int(image["x"]) + 40, int(image["y"]) + 40)
        res = self.session._cli_retry(
            "drag", str(tab[0]), str(tab[1]), str(drop[0]), str(drop[1]), timeout=60,
        )
        assert res is not None and res.returncode == 0, (
            f"the drag of the Content tab failed: {getattr(res, 'stdout', '')}"
            f"{getattr(res, 'stderr', '')}"
        )
        self.wait(
            lambda s: s["content_ui"].get("window")
            and not s["content_ui"]["window"]["docked"],
            f"a drag of the Content tab from {tab} to {drop} did not make the "
            "Content window float",
        )


# The CI window jobs select tests with ``-k <provider>``; the fault is in the
# app's key dispatch and the path bar, not in a data provider, so one provider
# is enough.
@pytest.mark.parametrize("provider", ["openusd"])
def test_path_bar_keys_keep_the_camera_and_shortcuts_resume(provider, tmp_path):
    field_delete._require_renderer_and_display()
    driver.assert_installed_provenance(driver.PRODUCT_MODULES)

    root = tmp_path / "content_keys"
    (root / FOLDER).mkdir(parents=True)
    (root / "other_folder").mkdir()
    root_text = root.as_posix()

    session = driver.FullAppSession(
        workdir=tmp_path, log_path=tmp_path / "app.log", provider=provider,
        headless=False, capture_frames=False,
    )
    session.start()
    try:
        flow = _Flow(session)
        session.wait_ready(timeout=180)
        assert session.state().get("provider") == provider

        # 1. Select the cube and move the camera away from its home view.
        driver._click_cube(session)
        home = flow.still_camera()
        driver.zoom_camera(session, flow.state()["viewport"]["image_rect"])
        flow.wait(
            lambda s: not _same_camera(s["viewport"].get("camera"), home),
            "the mouse wheel did not move the camera",
        )
        moved = flow.still_camera()
        tool = flow.state()["viewport"]["active_tool"]

        # 2. Double-click editing: "f" and "h" go to the path field.
        session.click(*flow.path_bar_point(), double=True)
        flow.wait(lambda s: s["content_ui"]["editing"],
                  "a double-click did not start path bar editing")
        for letter in "fh":
            flow.key(letter)
            flow.assert_unchanged(moved, tool, f"after '{letter}' in the path field (double-click)")
        flow.wait(lambda s: s["content_ui"]["edit_text"] == "fh",
                  "the path field does not hold the typed 'fh'")
        session.press("Escape")
        flow.wait(lambda s: not s["content_ui"]["editing"], "Escape did not end path bar editing")

        # 3. Single-click focus: a typed path goes to the path field.
        session.click(*flow.path_bar_point())
        flow.wait(lambda s: s["content_ui"]["editing"],
                  "a single click on the path bar did not give the path field the keyboard focus")
        session.type_text(f"{root_text}/")
        for index, letter in enumerate(FOLDER):
            if letter.isalnum():
                flow.key(letter)
            else:
                session.type_text(letter)
            if letter in SHORTCUT_LETTERS:
                flow.assert_unchanged(moved, tool, f"after '{letter}' in the path field (single click)")
            if index == 0:
                flow.wait(lambda s: f"{FOLDER}/" in s["content_ui"]["suggestions"],
                          f"the folder suggestions do not list '{FOLDER}/'")
        typed = f"{root_text}/{FOLDER}"
        flow.wait(lambda s: s["content_ui"]["edit_text"] == typed,
                  f"the path field does not hold the typed path {typed!r}")
        session.press("Enter")
        flow.wait(
            lambda s: not s["content_ui"]["editing"]
            and _in_folder(s["content_ui"]["path"], typed),
            f"Enter did not take the Content Browser to {typed!r}",
        )
        flow.assert_unchanged(moved, tool, "after Enter in the path field")

        # 4. A click on a folder name goes to that folder and keeps the
        #    folder names, also for a second click. When the narrow bar shows
        #    two folder names, the first click goes to the second one, so the
        #    second click goes to another folder.
        crumbs = flow.visible_breadcrumbs()
        assert crumbs, f"no folder name is visible in the path bar: {flow.state()['content_ui']}"
        flow.click_folder_name(crumbs[min(1, len(crumbs) - 1)], moved, tool, "folder name")
        crumbs = flow.visible_breadcrumbs()
        assert crumbs, f"no folder name is visible in the path bar: {flow.state()['content_ui']}"
        flow.click_folder_name(crumbs[0], moved, tool, "second folder name")

        # 5. Pick a folder suggestion with Down and Enter, then with a click.
        session.click(*flow.path_bar_point())
        flow.wait(lambda s: s["content_ui"]["editing"], "a click on the path bar did not edit it")
        session.type_text(f"{root_text}/")
        state = flow.wait(
            lambda s: {f"{FOLDER}/", "other_folder/"} <= set(s["content_ui"]["suggestions"]),
            f"the folder suggestions of {root_text}/ do not list both test folders",
        )
        target = state["content_ui"]["suggestions"].index("other_folder/")
        for down in range(target + 1):
            session.press("Down")
            flow.wait(lambda s, d=down: s["content_ui"]["suggestion_selected"] == d,
                      f"Down #{down + 1} did not highlight suggestion {down}")
        session.press("Enter")
        other = f"{root_text}/other_folder"
        flow.wait(
            lambda s: not s["content_ui"]["editing"]
            and _in_folder(s["content_ui"]["path"], other),
            f"Enter on the highlighted suggestion did not take the Content Browser to {other!r}",
        )
        flow.assert_unchanged(moved, tool, "after a suggestion picked with Down and Enter")

        session.click(*flow.path_bar_point())
        flow.wait(lambda s: s["content_ui"]["editing"], "a click on the path bar did not edit it")
        session.press("Tab")
        flow.wait(lambda s: s["content_ui"]["editing"], "Tab ended the path bar edit")
        session.type_text(f"{root_text}/fr")
        state = flow.wait(
            lambda s: s["content_ui"]["suggestions"] == [f"{FOLDER}/"]
            and s["content_ui"]["suggestion_rows"]
            and s["content_ui"]["suggestion_rows"][0]["point"],
            f"the folder suggestions of {root_text}/fr do not show '{FOLDER}/'",
        )
        # The browser is in other_folder, so only a working pick can reach
        # the target folder.
        assert not _in_folder(state["content_ui"]["path"], typed), state["content_ui"]
        session.click(*state["content_ui"]["suggestion_rows"][0]["point"])
        flow.wait(
            lambda s: not s["content_ui"]["editing"]
            and _in_folder(s["content_ui"]["path"], typed),
            f"a click on the suggestion did not take the Content Browser to {typed!r}; "
            f"status: {flow.state()['status']['text']!r}",
        )
        flow.assert_unchanged(moved, tool, "after a click on a suggestion")

        # 6. With the viewport focused, the camera shortcuts work again.
        session.click(*flow.state()["viewport"]["prim_screen_centers"][CUBE])
        session.press("f")
        flow.wait(lambda s: not _same_camera(s["viewport"].get("camera"), moved),
                  "F with the viewport focused did not frame the selection")
        session.press("h")
        flow.wait(lambda s: _same_camera(s["viewport"].get("camera"), home),
                  "H with the viewport focused did not send the camera home")

        # 7. Floating Content Browser: the first click on its path bar gives
        #    the path field the keyboard. In a floating window a press on an
        #    empty part also starts a window move, which once dropped the
        #    focus: F framed the cube and the typed text was lost.
        flow.float_content_window()
        camera = flow.still_camera()
        session.click(*flow.path_bar_point())
        flow.wait(lambda s: s["content_ui"]["editing"],
                  "a single click on the floating path bar did not start editing")
        flow.key("f")
        flow.assert_unchanged(camera, tool, "after 'f' in the floating path bar")
        flow.wait(lambda s: s["content_ui"]["edit_text"] == "f",
                  "the floating path field does not hold the typed 'f'")
        session.type_text(root_text)
        flow.wait(lambda s: s["content_ui"]["edit_text"] == f"f{root_text}",
                  f"the floating path field does not hold the typed text 'f{root_text}'")
        flow.assert_unchanged(camera, tool, "after a path typed in the floating path bar")
    finally:
        session.stop()
