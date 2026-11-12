# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Scrolling a TreeView with many expanded rows does not lay out the tree twice per step.

The tree is in a ScrollingFrame with a horizontal scroll bar. It has one
expanded group of rows that all have the same height. Each scroll step brings
new rows into view, and the tree lays out its height once for them. The frame
after a row is built, the row is laid out again. Its height does not change, so
the rows below it do not move, and it must not ask for a second height layout,
which visits every expanded row.

The test counts the "TreeView.layout.height" native timing scopes. The hook
table is built in Python with ``ctypes``.
"""

import ctypes

import omni.ui as ui
from test_base import OmniUiTest

CAPSULE_NAME = b"omni.ui.native_timing_hooks"
HOOKS_VERSION = 1
HEIGHT_SCOPE = b"TreeView.layout.height [ovui debug]"

_PyCapsule_New = ctypes.pythonapi.PyCapsule_New
_PyCapsule_New.restype = ctypes.py_object
_PyCapsule_New.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p]

_BeginScope = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32))
_EndScope = ctypes.CFUNCTYPE(None, ctypes.c_uint32)


class NativeTimingHooks(ctypes.Structure):
    """Same layout as omni::ui::standalone::NativeTimingHooks."""

    _fields_ = [
        ("structSize", ctypes.c_uint32),
        ("version", ctypes.c_uint32),
        ("beginScope", _BeginScope),
        ("endScope", _EndScope),
        ("beginRenderThreadScope", ctypes.c_void_p),
        ("endRenderThreadScope", ctypes.c_void_p),
        ("beginPhase", ctypes.c_void_p),
        ("endPhase", ctypes.c_void_p),
    ]


class _Item(ui.AbstractItem):
    def __init__(self, text, children=()):
        super().__init__()
        self.model = ui.SimpleStringModel(text)
        self.children = list(children)


class _Model(ui.AbstractItemModel):
    def __init__(self):
        super().__init__()
        self.group = _Item("Group", [_Item("Row") for _ in range(2000)])

    def get_item_children(self, item=None):
        return [self.group] if item is None else item.children

    def get_item_value_model_count(self, item=None):
        return 2

    def get_item_value_model(self, item=None, column_id=0):
        return item.model if item else None


class TestTreeViewScrollLayout(OmniUiTest):
    async def test_scroll_step_lays_out_the_tree_once(self):
        window = await self.create_test_window(300, 300)
        model = _Model()
        with window.frame:
            with ui.ScrollingFrame(horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED) as frame:
                tree = ui.TreeView(model, root_visible=False, header_visible=False)
        await self.wait_n_updates(3)
        tree.set_expanded(model.group, True, False)
        await self.wait_n_updates(5)

        layouts = [0]

        def begin_scope(name, cached_id):
            if name == HEIGHT_SCOPE:
                layouts[0] += 1
            # No scope is opened, so ovui does not call endScope.
            return False

        hooks = NativeTimingHooks()
        hooks.structSize = ctypes.sizeof(NativeTimingHooks)
        hooks.version = HOOKS_VERSION
        hooks.beginScope = _BeginScope(begin_scope)
        hooks.endScope = _EndScope(lambda cached_id: None)
        ui._ui._set_native_timing_hooks(_PyCapsule_New(ctypes.byref(hooks), CAPSULE_NAME, None))
        layouts_per_step = []
        try:
            for _ in range(20):
                before = layouts[0]
                frame.scroll_y += 200
                await self.wait_n_updates(4)
                layouts_per_step.append(layouts[0] - before)
        finally:
            ui._ui._set_native_timing_hooks(None)

        self.assertEqual(frame.scroll_y, 4000)
        self.assertLessEqual(max(layouts_per_step), 1, layouts_per_step)

        await self.finalize_test_no_image()
