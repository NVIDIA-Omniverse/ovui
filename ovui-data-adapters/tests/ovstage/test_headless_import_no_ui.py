# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Step 19 import tests for ovstage without an ovui-widgets UI host."""

from __future__ import annotations

import builtins
import importlib
import sys


def test_ovstage_adapter_import_does_not_require_ovui_widgets(monkeypatch) -> None:
    for module_name in list(sys.modules):
        if module_name.startswith("ovui_data_adapters.ovstage"):
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    # Importing the fresh package also replaces its parent's attribute. Restore
    # that binding together with sys.modules so later imports see the same tree.
    import ovui_data_adapters
    monkeypatch.delattr(ovui_data_adapters, "ovstage", raising=False)

    real_import = builtins.__import__

    def _raise_for_ovui_widgets(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "ovui_widgets" or name.startswith("ovui_widgets."):
            raise ImportError("ovui-widgets unavailable in headless adapter process")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raise_for_ovui_widgets)

    module = importlib.import_module("ovui_data_adapters.ovstage")

    assert module.PROVIDER_NAME == "ovstage"


def test_physics_menu_register_noops_when_menu_subsystem_is_unavailable(
    monkeypatch,
) -> None:
    import ovui_widgets_physx_controls

    real_import = builtins.__import__

    def _raise_for_menu_bar(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "ovui_widgets.app.menu_bar":
            raise ImportError("menu subsystem unavailable")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _raise_for_menu_bar)

    ovui_widgets_physx_controls.register(object())
