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

from typing import Any

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.layers import LayerModel


class _Services:
    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


def _model() -> tuple[LayerModel, Any, _Services]:
    adapter = MockLayerStackAdapter()
    adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child.usda")
    services = _Services()
    model = LayerModel(adapter, services=services)
    return model, model._items_by_id["./child.usda"], services


def test_save_as_existing_path_waits_for_explicit_replace(
    tmp_path, monkeypatch,
) -> None:
    model, item, services = _model()
    target = tmp_path / "existing.usda"
    target.write_text("existing", encoding="utf-8")
    selected: dict[str, Any] = {}

    def fake_file_dialog(**kwargs: Any) -> None:
        kwargs["on_selected"](str(target))

    def fake_confirm_dialog(**kwargs: Any) -> None:
        selected.update(kwargs)

    monkeypatch.setattr(
        "ovui_widgets.common.file_dialogs.save_file_dialog",
        fake_file_dialog,
    )
    monkeypatch.setattr(
        "ovui_widgets.common.dialogs.confirm_dialog",
        fake_confirm_dialog,
    )
    try:
        model._request_save_as(item)
        assert services.undo_manager.can_undo() is False
        assert selected["title"] == "Replace Existing Layer"
        assert selected["confirm_label"] == "Replace"

        selected["on_confirm"]()
        assert services.undo_manager.can_undo() is True
    finally:
        model.destroy()


def test_save_as_existing_path_cancel_does_not_push(tmp_path, monkeypatch) -> None:
    model, item, services = _model()
    target = tmp_path / "existing.usda"
    target.write_text("existing", encoding="utf-8")

    monkeypatch.setattr(
        "ovui_widgets.common.file_dialogs.save_file_dialog",
        lambda **kwargs: kwargs["on_selected"](str(target)),
    )
    monkeypatch.setattr(
        "ovui_widgets.common.dialogs.confirm_dialog",
        lambda **kwargs: kwargs.get("on_cancel", lambda: None)(),
    )
    try:
        model._request_save_as(item)
        assert services.undo_manager.can_undo() is False
        assert target.read_text(encoding="utf-8") == "existing"
    finally:
        model.destroy()
