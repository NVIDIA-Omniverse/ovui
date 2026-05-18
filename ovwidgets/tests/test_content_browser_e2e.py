# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""End-to-end integration test for the content browser — the content browser implementation step 60.

Exercises the full File > Open → edit → File > Save As user journey
across the menu-bar handlers, :class:`FileImporterHelper`,
:class:`FileExporterHelper`, :class:`Application.open_file` /
:meth:`Application.save_stage_to`, and the :class:`RecentFileList`.

The test uses :func:`tmp_path` for real filesystem I/O on the save
side — :meth:`pxr.Usd.Stage.Export` writes a real USD file we assert
against. The open side builds an in-memory :class:`Usd.Stage`,
exports it to disk first so the "user picking a file from disk" arm
of the round-trip has a real file to open. Picker callbacks are
injected by driving the menu-bar's ``on_import`` / ``on_export``
closures directly rather than spawning the modal dialog — the dialog
itself is covered by :file:`test_file_importer.py` /
:file:`test_file_exporter.py`; this test covers the cross-module
cycle.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from ovwidgets.app.application import Application
from ovwidgets.common.selection import SelectionBus

pytest.importorskip(
    "pxr", reason="USD Python bindings required for E2E stage round-trip",
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset every singleton the full app touches so each test starts clean."""
    Application._instance = None
    SelectionBus._instance = None
    yield
    if Application._instance is not None:
        try:
            Application._instance.shutdown()
        except Exception:
            Application._instance = None
    SelectionBus._instance = None


@pytest.fixture
def app():
    application = Application()
    yield application
    application.shutdown()


def _write_seed_usd(tmp_path) -> str:
    """Create a real on-disk USD file so File > Open has something to pick."""
    from pxr import Usd, UsdGeom
    path = str(tmp_path / "sample.usda")
    stage = Usd.Stage.CreateNew(path)
    UsdGeom.Sphere.Define(stage, "/Sphere")
    stage.GetRootLayer().Save()
    return path


class TestFullFlowOpenSave:
    """The Step-60 happy-path round-trip."""

    def test_open_then_save_as_cycle(self, app, tmp_path):
        seed_path = _write_seed_usd(tmp_path)
        save_path = str(tmp_path / "new.usda")

        # 1. File > Open — drive the same ``on_import`` closure the
        #    menu handler builds (selections list wins over filename).
        from ovwidgets.app.menu_bar import _on_open_clicked
        with patch(
            "ovwidgets.content.file_importer.FileImporterHelper.instance",
        ) as MockInstance:
            helper = MockInstance.return_value

            def _fake_show(**kwargs):
                import_handler = kwargs["import_handler"]
                import_handler("", "", [seed_path])

            helper.show = _fake_show
            _on_open_clicked(app)

        assert app._stage_adapter is not None, "stage not loaded"
        assert app._current_file_path == seed_path
        assert seed_path in app._recent_files.get_ordered()

        # 2. File > Save As — drive the same ``on_export`` closure.
        from ovwidgets.app.menu_bar import _on_save_as_clicked
        with patch(
            "ovwidgets.content.file_exporter.FileExporterHelper.instance",
        ) as MockInstance:
            helper = MockInstance.return_value

            def _fake_show(**kwargs):
                export_handler = kwargs["export_handler"]
                # Directory + bare filename + combo extension, as the
                # helper would deliver after the user hits Save.
                export_handler(
                    "new", str(tmp_path), ".usda", [],
                )

            helper.show = _fake_show
            _on_save_as_clicked(app)

        # 3. Verify the save landed on disk.
        assert os.path.exists(save_path), (
            f"Save As did not produce {save_path}"
        )
        assert app._current_file_path == save_path

        # 4. Both files end up in the recent list.
        recents = app._recent_files.get_ordered()
        assert seed_path in recents
        assert save_path in recents

    def test_save_direct_after_open_uses_same_path(self, app, tmp_path):
        # After File > Open, File > Save writes back to the opened path
        # with no dialog (Step 55 semantics).
        seed_path = _write_seed_usd(tmp_path)
        app.open_file(seed_path)

        assert app._current_file_path == seed_path

        from ovwidgets.app.menu_bar import _on_save_clicked
        _on_save_clicked(app)

        # Path unchanged; file still on disk.
        assert os.path.exists(seed_path)
        assert app._current_file_path == seed_path

    def test_typed_extension_not_double_appended(self, app, tmp_path):
        # A user who types "out.usd" with the ``.usd`` combo selected
        # must NOT end up with "out.usd.usd" — covered by the menu
        # bar's ``_on_save_as_clicked`` closure.
        seed_path = _write_seed_usd(tmp_path)
        app.open_file(seed_path)

        from ovwidgets.app.menu_bar import _on_save_as_clicked
        with patch(
            "ovwidgets.content.file_exporter.FileExporterHelper.instance",
        ) as MockInstance:
            helper = MockInstance.return_value

            def _fake_show(**kwargs):
                export_handler = kwargs["export_handler"]
                export_handler("out.usda", str(tmp_path), ".usda", [])

            helper.show = _fake_show
            _on_save_as_clicked(app)

        expected = str(tmp_path / "out.usda")
        doubled = str(tmp_path / "out.usda.usda")
        assert os.path.exists(expected)
        assert not os.path.exists(doubled)
        assert app._current_file_path == expected

    def test_open_failure_leaves_app_in_clean_state(self, app, tmp_path):
        # Opening a non-existent path must not crash the app nor
        # leave a stale ``_current_file_path``.
        bad_path = str(tmp_path / "does-not-exist.usda")
        assert app._current_file_path is None
        app.open_file(bad_path)
        # ``_current_file_path`` is only set on success.
        assert app._current_file_path is None

    def test_recent_files_reflects_save_cycle_order(self, app, tmp_path):
        # After Open → Save As, the most-recent-first RecentFileList
        # puts the Save As target ahead of the opened file.
        seed_path = _write_seed_usd(tmp_path)
        app.open_file(seed_path)

        save_path = str(tmp_path / "fresh.usda")
        ok = app.save_stage_to(save_path)
        assert ok is True
        ordered = app._recent_files.get_ordered()
        # Most-recent-first: save_path before seed_path.
        assert ordered.index(save_path) < ordered.index(seed_path)

    def test_file_open_dialog_file_url_selection_loads_stage(
        self, app, tmp_path,
    ):
        """The real picker returns file:// URLs; File > Open must load them."""
        seed_path = _write_seed_usd(tmp_path)
        file_url = f"file://{seed_path}"

        from ovwidgets.app.menu_bar import _on_open_clicked
        with patch(
            "ovwidgets.content.file_importer.FileImporterHelper.instance",
        ) as MockInstance:
            helper = MockInstance.return_value

            def _fake_show(**kwargs):
                import_handler = kwargs["import_handler"]
                import_handler("", "", [file_url])

            helper.show = _fake_show
            _on_open_clicked(app)

        assert app._stage_adapter is not None, "stage not loaded"
        assert app._current_file_path == seed_path
        assert seed_path in app._recent_files.get_ordered()
