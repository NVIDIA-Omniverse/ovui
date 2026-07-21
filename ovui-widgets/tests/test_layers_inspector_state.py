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

from types import SimpleNamespace

from ovui_widgets.app.inspector_state import _layers_ui_snapshot


def _rect(x: float, y: float, width: float, height: float, **kwargs):
    return SimpleNamespace(
        screen_position_x=x,
        screen_position_y=y,
        computed_width=width,
        computed_height=height,
        **kwargs,
    )


def test_layers_ui_snapshot_exposes_rows_columns_controls_and_menu_geometry() -> None:
    root = SimpleNamespace(
        identifier="/root.usda",
        parent=None,
        display_name="root.usda",
        is_focused=False,
        is_edit_target=True,
        is_dirty=False,
        is_muted=False,
        is_locked=False,
        is_anonymous=False,
        is_missing=False,
        is_read_only=False,
    )
    child = SimpleNamespace(
        identifier="/child.usda",
        parent=root,
        display_name="child.usda",
        is_focused=True,
        is_edit_target=False,
        is_dirty=True,
        is_muted=False,
        is_locked=False,
        is_anonymous=False,
        is_missing=False,
        is_read_only=False,
    )
    spec = SimpleNamespace(
        layer_item=child,
        path="/World",
        parent=None,
        type_name="Xform",
        specifier=SimpleNamespace(value="def"),
        descriptor=SimpleNamespace(
            has_reference=True,
            has_payload=False,
            is_instanceable=False,
        ),
    )

    def children(item):
        if item is None:
            return [root]
        if item is root:
            return [child]
        if item is child:
            return [spec]
        return []

    model = SimpleNamespace(
        selected_items=[child],
        get_item_children=children,
        can_item_have_children=lambda item: item in (root, child),
    )
    tree = SimpleNamespace(is_expanded=lambda item: item in (root, child))
    menu_item = _rect(25, 220, 180, 22)
    menu = _rect(20, 215, 190, 28, shown=True, visible=True)
    context_builder = SimpleNamespace(
        _menu=menu,
        _inspector_menu_anchor=(60.0, 130.0),
        _inspector_menu_items=[("Set as Authoring Layer", True, menu_item)],
    )
    layer_window = SimpleNamespace(
        _model=model,
        _tree_view=tree,
        _tree_scrolling_frame=_rect(10, 100, 240, 180, scroll_y=0.0),
        _window=SimpleNamespace(
            visible=True,
            focused=True,
            position_x=0,
            position_y=20,
            width=240,
            height=340,
            frame=_rect(0, 20, 240, 340),
        ),
        _filter_field=SimpleNamespace(
            model=SimpleNamespace(get_value_as_string=lambda: "child")
        ),
        _filter_border_rect=_rect(6, 40, 228, 22),
        _filter_clear_button=_rect(214, 45, 12, 12, visible=True),
        _options_button=SimpleNamespace(_hit_rectangle=_rect(4, 70, 24, 24)),
        _save_all_button=_rect(144, 70, 92, 22, enabled=True),
        _insert_button=_rect(12, 300, 64, 22, enabled=True),
        _create_button=_rect(84, 300, 64, 22, enabled=True),
        _delete_button=_rect(156, 300, 64, 22, enabled=True),
        _context_menu_builder=context_builder,
    )

    snapshot = _layers_ui_snapshot(SimpleNamespace(_layer_window=layer_window))

    assert snapshot["available"] is True
    assert snapshot["filter_text"] == "child"
    assert [row["type"] for row in snapshot["rows"]] == [
        "layer",
        "layer",
        "prim_spec",
    ]
    child_row = snapshot["rows"][1]
    assert child_row["key"] == "layer:/child.usda#0"
    assert child_row["selected"] is True
    assert child_row["action_points"]["save"] == [140, 125]
    assert child_row["action_points"]["mute"] == [164, 125]
    assert child_row["action_points"]["lock"] == [237, 125]
    assert snapshot["controls"]["delete"]["point"] == [188, 311]
    menu_entry = snapshot["context_menu"]["entries"][0]
    assert menu_entry["id"] == "set_as_authoring_layer"
    assert menu_entry["point"] == [115, 231]


def test_layers_ui_snapshot_exposes_open_file_dialog_geometry(monkeypatch) -> None:
    field = _rect(20, 400, 300, 24)
    apply_button = _rect(330, 400, 80, 24, enabled=True)
    cancel_button = _rect(420, 400, 80, 24)
    file_bar = SimpleNamespace(
        _field=field,
        _apply_button=apply_button,
        _cancel_button=cancel_button,
    )
    dialog = SimpleNamespace(
        _window=SimpleNamespace(
            visible=True,
            title="Open USD",
            position_x=10,
            position_y=30,
            width=500,
            height=420,
        ),
        _file_bar=file_bar,
        get_filename=lambda: "scene.usda",
        get_directory=lambda: "/assets",
    )
    importer = SimpleNamespace(_dialog=dialog)
    monkeypatch.setattr(
        "ovui_widgets.content.file_importer.FileImporterHelper._singleton",
        importer,
    )
    layer_window = SimpleNamespace(
        _model=SimpleNamespace(
            selected_items=[],
            get_item_children=lambda _item: [],
        ),
        _tree_view=SimpleNamespace(is_expanded=lambda _item: False),
        _tree_scrolling_frame=_rect(0, 100, 240, 180, scroll_y=0.0),
        _window=SimpleNamespace(
            visible=True,
            focused=False,
            position_x=0,
            position_y=20,
            width=240,
            height=340,
            frame=_rect(0, 20, 240, 340),
        ),
    )

    snapshot = _layers_ui_snapshot(SimpleNamespace(_layer_window=layer_window))

    open_dialog = snapshot["open_file_dialog"]
    assert open_dialog["shown"] is True
    assert open_dialog["filename"] == "scene.usda"
    assert open_dialog["directory"] == "/assets"
    assert open_dialog["field_point"] == [170, 412]
    assert open_dialog["apply_point"] == [370, 412]
    assert open_dialog["apply_enabled"] is True
    assert open_dialog["cancel_point"] == [460, 412]
