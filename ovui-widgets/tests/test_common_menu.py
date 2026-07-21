# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary

from __future__ import annotations

from types import SimpleNamespace
import sys


class _FakeContext:
    def __init__(self, events: list[tuple[str, object, dict]]) -> None:
        self._events = events

    def __enter__(self) -> "_FakeContext":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeValueModel:
    def __init__(self, value: object = 0) -> None:
        self._value = value

    def set_value(self, value: object) -> None:
        self._value = value

    def get_value_as_int(self) -> int:
        return int(self._value)

    def get_value_as_string(self) -> str:
        return str(self._value)


class _FakeModel:
    def __init__(self, value: object = 0, items: list[object] | None = None) -> None:
        self._value_model = _FakeValueModel(value)
        self._items = list(items or [])

    def set_value(self, value: object) -> None:
        self._value_model.set_value(value)

    def add_item_changed_fn(self, _fn) -> None:
        return None

    def add_begin_edit_fn(self, _fn) -> None:
        return None

    def add_end_edit_fn(self, _fn) -> None:
        return None

    def add_value_changed_fn(self, _fn) -> None:
        return None

    def get_value_as_int(self) -> int:
        return self._value_model.get_value_as_int()

    def get_value_as_string(self) -> str:
        return self._value_model.get_value_as_string()

    def get_item_value_model(self, _item) -> _FakeValueModel:
        return self._value_model

    def get_item_children(self, _item) -> list[object]:
        return list(self._items)

    def append_child_item(self, _item, value) -> object:
        self._items.append(value)
        return value

    def remove_item(self, value) -> None:
        if value in self._items:
            self._items.remove(value)


class _FakeWidget:
    def __init__(self) -> None:
        self.enabled = True
        self.tooltip = ""
        self.model = _FakeModel()


class _FakeUi:
    class Menu:
        def __init__(self, text: str = "", **kwargs) -> None:
            self.text = text
            self.hotkey_text = kwargs.get("hotkey_text", "")
            self.enabled = kwargs.get("enabled", True)
            self.style_type_name_override = kwargs.get("style_type_name_override", "")

    class MenuItem:
        pass

    class Separator:
        pass

    Alignment = SimpleNamespace(
        RIGHT_CENTER="right",
        LEFT_CENTER="left_center",
        CENTER="center",
    )

    def __init__(self) -> None:
        self.events: list[tuple[str, object, dict]] = []

    def HStack(self, **kwargs) -> _FakeContext:
        self.events.append(("HStack", None, kwargs))
        return _FakeContext(self.events)

    def VStack(self, **kwargs) -> _FakeContext:
        self.events.append(("VStack", None, kwargs))
        return _FakeContext(self.events)

    def Label(self, text: str, **kwargs) -> _FakeWidget:
        self.events.append(("Label", text, kwargs))
        return _FakeWidget()

    def Spacer(self, **kwargs) -> _FakeWidget:
        self.events.append(("Spacer", None, kwargs))
        return _FakeWidget()

    def ImageWithProvider(self, provider=None, **kwargs) -> _FakeWidget:
        self.events.append(("ImageWithProvider", provider, kwargs))
        return _FakeWidget()

    def ComboBox(self, *args, **kwargs) -> _FakeWidget:
        self.events.append(("ComboBox", args, kwargs))
        widget = _FakeWidget()
        if args and isinstance(args[0], _FakeModel):
            widget.model = args[0]
        return widget

    def CheckBox(self, **kwargs) -> _FakeWidget:
        self.events.append(("CheckBox", None, kwargs))
        return _FakeWidget()

    def IntField(self, **kwargs) -> _FakeWidget:
        self.events.append(("IntField", None, kwargs))
        return _FakeWidget()

    def Button(self, text: str, **kwargs) -> _FakeWidget:
        self.events.append(("Button", text, kwargs))
        return _FakeWidget()

    def SimpleListModel(self, items, index: int) -> _FakeModel:
        self.events.append(("SimpleListModel", tuple(items), {"index": index}))
        return _FakeModel(index, list(items))

    def SimpleStringModel(self, value: str) -> _FakeValueModel:
        self.events.append(("SimpleStringModel", value, {}))
        return _FakeValueModel(value)


def test_plain_popup_submenus_use_base_delegate_auto_expand_mark(monkeypatch) -> None:
    from ovui_widgets.common import menu

    fake_ui = _FakeUi()
    calls: list[object] = []
    monkeypatch.setitem(sys.modules, "omni", SimpleNamespace(ui=fake_ui))
    monkeypatch.setitem(sys.modules, "omni.ui", fake_ui)
    monkeypatch.setattr(
        menu,
        "_get_base_menu_delegate",
        lambda: SimpleNamespace(build_item=lambda item: calls.append(item)),
    )

    submenu = fake_ui.Menu("Mesh")
    menu._build_menu_item(submenu)

    assert calls == [submenu]
    assert fake_ui.events == []


def test_menu_bar_roots_keep_base_delegate(monkeypatch) -> None:
    from ovui_widgets.common import menu

    fake_ui = _FakeUi()
    calls: list[object] = []
    monkeypatch.setitem(sys.modules, "omni", SimpleNamespace(ui=fake_ui))
    monkeypatch.setitem(sys.modules, "omni.ui", fake_ui)
    monkeypatch.setattr(
        menu,
        "_get_base_menu_delegate",
        lambda: SimpleNamespace(build_item=lambda item: calls.append(item)),
    )

    root_menu = fake_ui.Menu("Create", style_type_name_override="MenuBar.Menu")
    menu._build_menu_item(root_menu)

    assert calls == [root_menu]
    assert not any(event[0] == "ImageWithProvider" for event in fake_ui.events)


def test_submenu_rows_with_current_label_use_default_expand_mark(monkeypatch) -> None:
    from ovui_widgets.common import menu

    fake_ui = _FakeUi()
    monkeypatch.setitem(sys.modules, "omni", SimpleNamespace(ui=fake_ui))
    monkeypatch.setitem(sys.modules, "omni.ui", fake_ui)

    menu._build_menu_item(fake_ui.Menu("Render Resolution", hotkey_text="Viewport"))

    image_events = [
        event for event in fake_ui.events if event[0] == "ImageWithProvider"
    ]
    assert len(image_events) == 1
    _kind, provider, kwargs = image_events[0]
    assert provider is None
    assert kwargs["width"] == 20.0
    assert kwargs["style_type_name_override"] == "Menu.Item.ExpandMark"
    assert not any(event[0] == "VStack" for event in fake_ui.events)
    assert any(
        kind == "Label" and text == "Viewport"
        for kind, text, _kwargs in fake_ui.events
    )
    assert not any(
        kind == "Label" and text == ">"
        for kind, text, _kwargs in fake_ui.events
    )


def test_default_expand_mark_style_uses_visible_common_chevron() -> None:
    from pathlib import Path

    from omni.ui import color as cl

    from ovui_widgets.app.style.styles import GLOBAL_STYLES

    expand_style = GLOBAL_STYLES["Menu.Item.ExpandMark"]
    disabled_style = GLOBAL_STYLES["Menu.Item.ExpandMark:disabled"]

    assert Path(expand_style["image_url"]).name == "chevron_right.png"
    assert Path(expand_style["image_url"]).exists()
    assert expand_style["color"] == cl.text_secondary
    assert expand_style["margin_width"] == 5
    assert disabled_style["image_url"] == expand_style["image_url"]
    assert disabled_style["color"] == cl.text_disabled


def test_resolution_menu_inline_controls_use_reference_sizing() -> None:
    from ovui_widgets.common import menu

    assert menu._CUSTOM_RESOLUTION_CONTROL_HEIGHT == 24.0
    assert menu._RENDER_SCALE_ROW_HEIGHT == 32.0
    assert menu._RENDER_SCALE_COMBO_HEIGHT == 22.0
    assert menu._RENDER_SCALE_COMBO_TOP_INSET == 4.0
    assert menu._RENDER_SCALE_COMBO_BOTTOM_INSET == 6.0
    assert menu._FILL_VIEWPORT_ROW_HEIGHT == 32.0
    assert menu._FILL_VIEWPORT_CHECKBOX_SIZE == 18.0
    assert menu._FILL_VIEWPORT_CHECKBOX_SLOT_WIDTH == 24.0
    assert menu._FILL_VIEWPORT_CHECKBOX_TOP_INSET == 7.0


def test_render_scale_combo_uses_explicit_centering_and_menu_style(monkeypatch) -> None:
    from ovui_widgets.common import menu

    fake_ui = _FakeUi()
    monkeypatch.setitem(sys.modules, "omni", SimpleNamespace(ui=fake_ui))
    monkeypatch.setitem(sys.modules, "omni.ui", fake_ui)

    menu._build_render_scale_combo_item(
        SimpleNamespace(text="Render Scale", hotkey_text="")
    )

    combo_events = [event for event in fake_ui.events if event[0] == "ComboBox"]
    assert len(combo_events) == 1
    _kind, _args, kwargs = combo_events[0]
    assert kwargs["height"] == menu._RENDER_SCALE_COMBO_HEIGHT
    assert kwargs["style_type_name_override"] == "Menu.ControlComboBox"
    assert [
        kwargs
        for kind, _text, kwargs in fake_ui.events
        if kind == "HStack" and kwargs.get("height") == menu._RENDER_SCALE_ROW_HEIGHT
    ]
    assert [
        kwargs
        for kind, _text, kwargs in fake_ui.events
        if kind == "Spacer" and kwargs.get("height") == menu._RENDER_SCALE_COMBO_TOP_INSET
    ]
    assert [
        kwargs
        for kind, _text, kwargs in fake_ui.events
        if kind == "Spacer"
        and kwargs.get("height") == menu._RENDER_SCALE_COMBO_BOTTOM_INSET
    ]


def test_fill_viewport_uses_real_reference_sized_checkbox(monkeypatch) -> None:
    from ovui_widgets.common import menu

    fake_ui = _FakeUi()
    monkeypatch.setitem(sys.modules, "omni", SimpleNamespace(ui=fake_ui))
    monkeypatch.setitem(sys.modules, "omni.ui", fake_ui)

    menu._build_fill_viewport_checkbox_item(
        SimpleNamespace(text="Fill Viewport", hotkey_text="")
    )

    checkbox_events = [event for event in fake_ui.events if event[0] == "CheckBox"]
    assert len(checkbox_events) == 1
    _kind, _text, kwargs = checkbox_events[0]
    assert kwargs["width"] == menu._FILL_VIEWPORT_CHECKBOX_SIZE
    assert kwargs["height"] == menu._FILL_VIEWPORT_CHECKBOX_SIZE
    assert [
        kwargs
        for kind, _text, kwargs in fake_ui.events
        if kind == "HStack" and kwargs.get("height") == menu._FILL_VIEWPORT_ROW_HEIGHT
    ]
    assert [
        kwargs
        for kind, _text, kwargs in fake_ui.events
        if kind == "Spacer" and kwargs.get("height") == menu._FILL_VIEWPORT_CHECKBOX_TOP_INSET
    ]
    assert not any(event[0] == "Rectangle" for event in fake_ui.events)
    assert not any(event[0] == "ImageWithProvider" for event in fake_ui.events)


def test_custom_resolution_enabled_compact_controls_do_not_add_redundant_tooltips(
    monkeypatch,
) -> None:
    from ovui_widgets.common import menu

    fake_ui = _FakeUi()
    monkeypatch.setitem(sys.modules, "omni", SimpleNamespace(ui=fake_ui))
    monkeypatch.setitem(sys.modules, "omni.ui", fake_ui)

    menu._build_custom_resolution_editor_item(
        SimpleNamespace(text="Custom Resolution", enabled=True)
    )

    int_fields = [event for event in fake_ui.events if event[0] == "IntField"]
    assert len(int_fields) == 2
    assert all("tooltip" not in kwargs for _kind, _text, kwargs in int_fields)
    buttons = [event for event in fake_ui.events if event[0] == "Button"]
    assert [text for _kind, text, _kwargs in buttons] == ["L", "S"]
    assert all("tooltip" not in kwargs for _kind, _text, kwargs in buttons)


def test_custom_resolution_disabled_compact_controls_keep_reason_tooltips(
    monkeypatch,
) -> None:
    from ovui_widgets.common import menu

    fake_ui = _FakeUi()
    monkeypatch.setitem(sys.modules, "omni", SimpleNamespace(ui=fake_ui))
    monkeypatch.setitem(sys.modules, "omni.ui", fake_ui)

    reason = "Resolution unavailable"
    menu._build_custom_resolution_editor_item(
        SimpleNamespace(
            text="Custom Resolution",
            enabled=False,
            custom_resolution_disabled_reason=reason,
        )
    )

    int_fields = [event for event in fake_ui.events if event[0] == "IntField"]
    assert len(int_fields) == 2
    assert all(kwargs.get("tooltip") == reason for _kind, _text, kwargs in int_fields)
    buttons = [event for event in fake_ui.events if event[0] == "Button"]
    assert [text for _kind, text, _kwargs in buttons] == ["L", "S"]
    assert all(kwargs.get("tooltip") == reason for _kind, _text, kwargs in buttons)


def test_menu_control_styles_remove_button_margin_and_center_combo() -> None:
    import omni.ui as ui
    from omni.ui import color as cl

    from ovui_widgets.app.style.styles import GLOBAL_STYLES

    button_style = GLOBAL_STYLES["Menu.ControlButton"]
    combo_style = GLOBAL_STYLES["Menu.ControlComboBox"]
    assert button_style["margin"] == 0
    assert button_style["padding"] == 0
    assert GLOBAL_STYLES["Menu.ControlButton.Label"]["alignment"] == ui.Alignment.CENTER
    assert combo_style["alignment"] == ui.Alignment.LEFT_CENTER
    assert combo_style["background_color"] == cl.background_field


def test_submenu_chevrons_do_not_use_stage_or_custom_style_names() -> None:
    from pathlib import Path

    from ovui_widgets.common import menu

    source = Path(menu.__file__).read_text()

    stage_style_prefix = "Sta" + "ge."
    stage_import_path = "ovui_widgets." + "stage"
    assert stage_style_prefix not in source
    assert stage_import_path not in source
    removed_custom_style = "Menu.Item." + "Submenu" + "Chevron"
    removed_width_constant = "_SUBMENU_" + "CHEVRON_WIDTH"
    assert removed_custom_style not in source
    assert removed_width_constant not in source
