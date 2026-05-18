# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Bug 1 fix — nav tree expands beyond level 1.

Before the fix, :meth:`NavigationModel.get_item_children` on a
:class:`FileItem` returned ``item.children`` verbatim without ever
populating, so every collection child (level 2 of the tree) sat with
``_populated=False`` and empty ``_children``. Clicking the chevron on
a level-2 row produced zero rows.

This QA script installs a deterministic nav model — one stub
collection whose children are a single ``mock://Home`` folder — then
expands three levels of the resulting tree (Home → Documents →
Projects). The screenshot at ``/tmp/ovgear_bugfix_1.png`` must show
each expanded level populated with only folders (Documents / Textures
/ Scripts / .hidden_folder under Home; Projects under Documents),
with no files rendered anywhere in the nav pane.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
      python3.12 tests/qa_bugfix_1_nav_multi_level.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting

from ovwidgets.app.application import Application
from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.app.testing.mock_backend import MockBackend
from ovwidgets.common.selection import SelectionBus
from ovwidgets.content.widget import CollectionItem, NavigationModel
from ovwidgets.content.widget.file_item import FileItem

OUT_PATH = "/tmp/ovgear_bugfix_1.png"


class _BugRepoCollection(CollectionItem):
    """Collection with a single folder child — the entry point into a
    mock:// tree for the fix-verification screenshot.
    """

    def __init__(self, root: FileItem) -> None:
        super().__init__(
            identifier="bugfix-1",
            title="Test Tree",
            icon_key="content_home",
        )
        self._root = root

    def get_children(self, backend) -> List[FileItem]:
        return [self._root]


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())

    await _drive(40)

    cw = app._content_window
    if cw is None or cw._widget is None:
        raise RuntimeError("Content window / widget not built yet")
    widget = cw._widget

    backend = MockBackend()
    widget.set_backend(backend)
    widget.navigate_to("mock://Home")
    await _drive(20)

    # Build a deterministic nav model: one collection → one Home folder.
    # With the Bug 1 fix, expanding Home populates Documents / Textures /
    # Scripts / .hidden_folder; expanding Documents populates Projects.
    home = FileItem(url="mock://Home", name="Home", is_folder=True)
    collection = _BugRepoCollection(home)
    nav_model = NavigationModel(backend, collections=[collection])
    nav_model.set_on_navigate(widget._navigate_to_url)

    widget._navigation_model = nav_model
    tree_view = widget._tree_tree_view
    if tree_view is None:
        raise RuntimeError("Navigation TreeView missing from widget")
    tree_view.model = nav_model
    await _drive(10)

    # Expand three levels deterministically so the screenshot captures
    # the same state every run. Each set_expanded call on a FileItem
    # routes through ``get_item_children`` — the exact path the fix
    # patches — so this is an end-to-end exercise of the bug fix.
    tree_view.set_expanded(collection, True, False)
    await _drive(6)
    tree_view.set_expanded(home, True, False)
    await _drive(6)

    # Grab Documents (level 3) after Home was populated.
    documents = next(
        (c for c in home.children if c.name == "Documents"), None,
    )
    if documents is None:
        raise RuntimeError(
            "Home not populated by get_item_children — bug not fixed?",
        )
    tree_view.set_expanded(documents, True, False)
    await _drive(6)

    # Drill one more level into Projects — exercises 4-level expansion.
    projects = next(
        (c for c in documents.children if c.name == "Projects"), None,
    )
    if projects is None:
        raise RuntimeError("Documents not populated — bug not fixed?")
    tree_view.set_expanded(projects, True, False)
    await _drive(10)

    # Diagnostic prints mirror the original repro output so the QA
    # run log stays comparable.
    level2 = nav_model.get_item_children(home)
    level3 = nav_model.get_item_children(documents)
    level4 = nav_model.get_item_children(projects)
    print(f"[BUGFIX 1] Home children (folders): {[c.name for c in level2]}")
    print(f"[BUGFIX 1] Documents children: {[c.name for c in level3]}")
    print(f"[BUGFIX 1] Projects children: {[c.name for c in level4]}")
    print(f"[BUGFIX 1] Home.populated={home.populated}, "
          f"Documents.populated={documents.populated}, "
          f"Projects.populated={projects.populated}")
    # Files must be absent at every level.
    assert all(c.is_folder for c in level2), "files leaked into level 2"
    assert all(c.is_folder for c in level3), "files leaked into level 3"
    assert level4 == [], "Projects (file-only folder) must show no rows"

    uitesting.capture_screenshot(OUT_PATH)
    print(f"Saved: {OUT_PATH}")

    await _drive(2)

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(layout_path):
        os.unlink(layout_path)
    write_split_ini()
    ui.init("OvGear Bugfix 1 QA", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())
