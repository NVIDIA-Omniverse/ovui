# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A small stage adapter for the light pick tests."""

from types import SimpleNamespace

from ovui_data_adapters.common import VisibilityState


class FakeStage:
    """A small stage adapter. A prim is hidden by itself or by an ancestor."""

    def __init__(self, light_types=()):
        self.items = {"/": SimpleNamespace(path="/", type="Xform", parent=None, kids=[])}
        self.hidden = set()
        for index, light_type in enumerate(light_types):
            self.add(f"/World/L{index}", light_type)

    def add(self, path, prim_type, parent="/"):
        item = SimpleNamespace(path=path, type=prim_type, parent=self.items[parent], kids=[])
        self.items[path] = item
        self.items[parent].kids.append(item)
        return item

    def remove(self, path):
        item = self.items.pop(path)
        item.parent.kids.remove(item)

    def get_root(self):
        return self.items["/"]

    def get_children(self, item):
        return list(item.kids)

    def get_item_path(self, item):
        return item.path

    def get_item_at_path(self, path):
        return self.items.get(path)

    def get_type_category(self, item):
        return "Light" if item.type.endswith("Light") else "Other"

    def get_icon_name(self, item):
        return item.type

    def get_light_shape_attributes(self, item):
        return {}

    def read_stage_meters_per_unit(self):
        return 1.0

    def compute_visibility(self, item):
        ancestor = item.parent
        while ancestor is not None:
            if ancestor.path in self.hidden:
                return VisibilityState.INHERITED_INVISIBLE
            ancestor = ancestor.parent
        if item.path in self.hidden:
            return VisibilityState.INVISIBLE
        return VisibilityState.VISIBLE
