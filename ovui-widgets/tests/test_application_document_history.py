# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from ovui_data_adapters.services.undo import Command


class _HistoryCommand(Command):
    def do(self) -> None:
        pass

    def undo(self) -> None:
        pass


def test_successful_file_open_discards_prior_document_history(
    headless_app, monkeypatch
) -> None:
    app = headless_app
    stage = object()
    session = MagicMock()
    session.open_stage.return_value = stage
    app._startup_prebuilt_renderer = None
    app._undo_manager.push(_HistoryCommand())
    monkeypatch.setattr(app, "get_adapter_session", lambda: session)
    app._load_stage = MagicMock()

    app.open_file("next.usda")

    app._load_stage.assert_called_once_with(
        stage,
        title="next.usda",
        prebuilt_renderer=None,
    )
    assert app._undo_manager.can_undo() is False
    assert app._undo_manager.can_redo() is False


def test_failed_file_open_preserves_current_document_history(
    headless_app, monkeypatch
) -> None:
    app = headless_app
    session = MagicMock()
    session.open_stage.side_effect = RuntimeError("open failed")
    app._startup_prebuilt_renderer = None
    app._current_file_path = "current.usda"
    app._undo_manager.push(_HistoryCommand())
    monkeypatch.setattr(app, "get_adapter_session", lambda: session)
    app._load_stage = MagicMock()

    app.open_file("broken.usda")

    app._load_stage.assert_not_called()
    assert app._undo_manager.can_undo() is True
    assert app._current_file_path == "current.usda"


def test_history_is_cleared_when_provider_replaces_scene_before_wiring_fails(
    headless_app, monkeypatch
) -> None:
    app = headless_app
    session = MagicMock()
    session.open_stage.return_value = object()
    app._startup_prebuilt_renderer = None
    app._current_file_path = "old-document.usda"
    app._undo_manager.push(_HistoryCommand())
    monkeypatch.setattr(app, "get_adapter_session", lambda: session)

    def fail_wiring(*_args, **_kwargs) -> None:
        assert app._current_file_path == "replacement.usda"
        raise RuntimeError("renderer wiring failed")

    app._load_stage = MagicMock(side_effect=fail_wiring)

    with pytest.raises(RuntimeError, match="renderer wiring failed"):
        app.open_file("replacement.usda")

    assert app._undo_manager.can_undo() is False
    assert app._undo_manager.can_redo() is False
    # The provider already switched but replacement construction failed:
    # the application converges on the EXPLICIT no-document state rather
    # than a split document (old commands cleared, no stale save path).
    assert app._current_file_path is None
    assert app._stage_adapter is None


def test_new_stage_clears_old_save_path_before_replacement_wiring_fails(
    headless_app, monkeypatch
) -> None:
    app = headless_app
    replacement_stage = object()
    app._startup_prebuilt_renderer = None
    app._current_file_path = "old-document.usda"
    app._undo_manager.push(_HistoryCommand())
    monkeypatch.setattr(app, "_can_create_empty_startup_stage", lambda: True)
    monkeypatch.setattr(app, "_create_empty_startup_stage", lambda: replacement_stage)

    def fail_wiring(*_args, **_kwargs) -> None:
        assert app._current_file_path is None
        raise RuntimeError("renderer wiring failed")

    app._load_stage = MagicMock(side_effect=fail_wiring)

    assert app.new_stage() is False
    assert app._current_file_path is None
    assert app._undo_manager.can_undo() is False
    assert app._undo_manager.can_redo() is False
