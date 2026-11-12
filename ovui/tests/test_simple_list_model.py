# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the ``omni.ui.SimpleListModel`` Python binding.

These exercise the public binding contract without rendering: constructing a
list model from each supported value type, walking its items via the
inherited AbstractItemModel API, mutating the list, and verifying that the
model can be plugged into a ``ui.ComboBox`` (the documented primary use).

An item must not stay after its removal or after the end of its model: the
callback in an item's value model kept the item, and the item kept the value
model. A ComboBox built from a list of labels kept every item, value model and
callback for the life of the app.
"""

import ctypes
import sys
import unittest

import omni.ui as ui


class _MallInfo2(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_size_t)
        for name in ("arena", "ordblks", "smblks", "hblks", "hblkhd", "usmblks", "fsmblks", "uordblks",
                     "fordblks", "keepcost")
    ]


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32)] + [
        (name, ctypes.c_size_t)
        for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                     "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage",
                     "PeakPagefileUsage", "PrivateUsage")
    ]


def _heap_bytes() -> int:
    """Bytes that the process allocated: the allocator total on Linux, private bytes on Windows, else peak RSS."""
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL("libc.so.6")
        libc.mallinfo2.restype = _MallInfo2
        return int(libc.mallinfo2().uordblks)
    if sys.platform == "win32":
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
        if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
        return int(counters.PrivateUsage)
    import resource

    # ru_maxrss is in KiB on Linux and in bytes on macOS; only macOS reaches this line.
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


class TestSimpleListModel(unittest.TestCase):
    def test_default_constructor_is_empty(self):
        model = ui.SimpleListModel()
        self.assertEqual(model.get_item_children(None), [])
        # Root model exists and defaults to 0.
        root = model.get_item_value_model(None, 0)
        self.assertIsNotNone(root)
        self.assertEqual(root.get_value_as_int(), 0)

    def test_string_values(self):
        items = ["alpha", "beta", "gamma"]
        model = ui.SimpleListModel(items)

        children = model.get_item_children(None)
        self.assertEqual(len(children), len(items))

        actual = [
            model.get_item_value_model(child, 0).get_value_as_string()
            for child in children
        ]
        self.assertEqual(actual, items)

    def test_int_values_with_root(self):
        items = [10, 20, 30]
        model = ui.SimpleListModel(items, 2)

        # Root carries the selected index / default value.
        self.assertEqual(model.get_item_value_model(None, 0).get_value_as_int(), 2)

        children = model.get_item_children(None)
        self.assertEqual(len(children), 3)
        actual = [
            model.get_item_value_model(child, 0).get_value_as_int()
            for child in children
        ]
        self.assertEqual(actual, items)

    def test_float_values(self):
        items = [0.5, 1.5, 2.5]
        model = ui.SimpleListModel(items)

        children = model.get_item_children(None)
        self.assertEqual(len(children), 3)
        actual = [
            model.get_item_value_model(child, 0).get_value_as_float()
            for child in children
        ]
        self.assertEqual(actual, items)

    def test_bool_values(self):
        items = [True, False, True]
        model = ui.SimpleListModel(items)

        children = model.get_item_children(None)
        self.assertEqual(len(children), 3)
        actual = [
            model.get_item_value_model(child, 0).get_value_as_bool()
            for child in children
        ]
        self.assertEqual(actual, items)

    def test_default_value_kwarg(self):
        model = ui.SimpleListModel(["a", "b"], default_value=1)
        self.assertEqual(model.get_item_value_model(None, 0).get_value_as_int(), 1)

    def test_get_item_value_model_count(self):
        model = ui.SimpleListModel(["a", "b"])
        # SimpleListModel reports a single column per item.
        for child in model.get_item_children(None):
            self.assertEqual(model.get_item_value_model_count(child), 1)

    def test_append_and_remove(self):
        model = ui.SimpleListModel(["a"])
        self.assertEqual(len(model.get_item_children(None)), 1)

        extra = ui.SimpleStringModel("b")
        appended = model.append_child_item(None, extra)
        self.assertIsNotNone(appended)

        children = model.get_item_children(None)
        self.assertEqual(len(children), 2)
        last_value = model.get_item_value_model(children[-1], 0).get_value_as_string()
        self.assertEqual(last_value, "b")

        model.remove_item(children[-1])
        self.assertEqual(len(model.get_item_children(None)), 1)

    def test_item_changed_subscription_fires_on_append(self):
        model = ui.SimpleListModel()
        events = []

        def on_changed(sender, item):
            events.append(item)

        sub = model.subscribe_item_changed_fn(on_changed)
        try:
            model.append_child_item(None, ui.SimpleStringModel("x"))
            # appendChildItem calls _itemChanged(nullptr) — a single root-level
            # notification — so we expect at least one callback fired.
            self.assertGreaterEqual(len(events), 1)
        finally:
            sub.unsubscribe()

    def test_combobox_accepts_simple_list_model(self):
        # The documented primary use of SimpleListModel is to back a ComboBox.
        # Constructing the ComboBox with an explicit model proves the binding
        # is reachable through the AbstractItemModel base class.
        model = ui.SimpleListModel(["red", "green", "blue"], 1)
        combo = ui.ComboBox(model)
        self.assertIsNotNone(combo.model)
        root = combo.model.get_item_value_model(None, 0)
        self.assertEqual(root.get_value_as_int(), 1)

    def test_a_removed_item_no_longer_notifies_the_model(self):
        model = ui.SimpleListModel(["a"])
        extra = ui.SimpleStringModel("b")
        model.append_child_item(None, extra)
        model.remove_item(model.get_item_children(None)[-1])
        events = []
        sub = model.subscribe_item_changed_fn(lambda sender, item: events.append(item))
        try:
            extra.set_value("c")
            self.assertEqual(events, [], "the removed item stayed and still reports changes of its value model")
        finally:
            sub.unsubscribe()

    def test_a_deleted_model_frees_its_items(self):
        labels = [f"Render mode {index}" for index in range(10)]

        def build_and_delete(count):
            for _ in range(count):
                ui.ComboBox(0, *labels)

        build_and_delete(200)
        before = _heap_bytes()
        build_and_delete(2000)
        grown = _heap_bytes() - before
        # Kept items cost about 3 KB for each ComboBox of 10 labels (6 MB here).
        self.assertLess(grown, 1_000_000, f"2000 deleted ComboBoxes kept {grown} bytes")

    def test_unsupported_type_raises(self):
        with self.assertRaises(TypeError):
            ui.SimpleListModel([object()])


if __name__ == "__main__":
    unittest.main()
