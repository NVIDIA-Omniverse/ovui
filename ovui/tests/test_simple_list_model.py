# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the ``omni.ui.SimpleListModel`` Python binding.

These exercise the public binding contract without rendering: constructing a
list model from each supported value type, walking its items via the
inherited AbstractItemModel API, mutating the list, and verifying that the
model can be plugged into a ``ui.ComboBox`` (the documented primary use).
"""

import unittest

import omni.ui as ui


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

    def test_unsupported_type_raises(self):
        with self.assertRaises(TypeError):
            ui.SimpleListModel([object()])


if __name__ == "__main__":
    unittest.main()
