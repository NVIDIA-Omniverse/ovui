# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for optional app component entry points."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import tomllib

from ovui_widgets.app.component_loader import ComponentModuleLoadFailure
from ovui_widgets.app.components import ENTRY_POINT_GROUP, ComponentManager

REPO_ROOT = Path(__file__).resolve().parents[2]


class _EntryPoints(tuple):
    def select(self, *, group: str):
        assert group == ENTRY_POINT_GROUP
        return self


class _EntryPoint:
    def __init__(self, name, register, *, value: str | None = None):
        self.name = name
        self.value = value or f"{name}:register"
        self._register = register
        self.load_calls = 0

    def load(self):
        self.load_calls += 1
        return self._register


class _Handle:
    def __init__(self, events):
        self._events = events

    def unload(self):
        self._events.append("unloaded")


def test_component_entry_point_register_called_once_and_unloaded(monkeypatch):
    events = []
    app = SimpleNamespace(name="app")

    def register(received_app):
        events.append(("registered", received_app))
        return _Handle(events)

    entry_point = _EntryPoint("test_component", register)

    import ovui_widgets.app.components as components

    monkeypatch.setattr(
        components.metadata,
        "entry_points",
        lambda: _EntryPoints((entry_point,)),
    )

    manager = ComponentManager(app)
    manager.load_all()
    manager.load_all()

    assert entry_point.load_calls == 1
    assert events == [("registered", app)]
    assert manager.loaded_names == ("test_component",)

    assert manager.unload("test_component") is True
    assert events == [("registered", app), "unloaded"]
    assert manager.loaded_names == ()


def test_component_unload_all_cleans_multiple_handles(monkeypatch):
    events = []
    app = object()

    first = _EntryPoint("first", lambda received_app: _Handle(events))
    second = _EntryPoint(
        "second",
        lambda received_app: [
            lambda: events.append("second-child-a"),
            lambda: events.append("second-child-b"),
        ],
    )

    import ovui_widgets.app.components as components

    monkeypatch.setattr(
        components.metadata,
        "entry_points",
        lambda: _EntryPoints((second, first)),
    )

    manager = ComponentManager(app)
    loaded = manager.load_all()

    assert [record.name for record in loaded] == ["first", "second"]
    manager.unload_all()
    assert events == ["second-child-b", "second-child-a", "unloaded"]
    assert manager.loaded_names == ()


def test_component_manager_loads_declared_entry_point_from_metadata(
    tmp_path,
    monkeypatch,
):
    module_path = tmp_path / "dummy_component.py"
    module_path.write_text(
        "\n".join(
            [
                "calls = []",
                "unloads = []",
                "",
                "class Handle:",
                "    def unload(self):",
                "        unloads.append('unloaded')",
                "",
                "def register(app):",
                "    calls.append(app)",
                "    return Handle()",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    dist_info = tmp_path / "dummy_component-1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: dummy-component\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (dist_info / "entry_points.txt").write_text(
        "[ovui_widgets.components]\n"
        "dummy_component = dummy_component:register\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "path", [str(tmp_path)])
    importlib.invalidate_caches()
    sys.modules.pop("dummy_component", None)

    app = object()
    manager = ComponentManager(app)
    loaded = manager.load_all()
    module = importlib.import_module("dummy_component")

    assert [record.name for record in loaded] == ["dummy_component"]
    assert module.calls == [app]

    manager.unload_all()
    assert module.unloads == ["unloaded"]


def test_component_manager_reports_structured_load_failures(monkeypatch):
    app = SimpleNamespace(component_module_load_failures=[])

    def report_module_load_failure(name, value, exc):
        failure = ComponentModuleLoadFailure.from_exception(name, value, exc)
        app.component_module_load_failures.append(failure)
        return failure

    app.report_module_load_failure = report_module_load_failure

    def register(_received_app):
        raise RuntimeError("component failed to import runtime")

    entry_point = _EntryPoint(
        "broken_component",
        register,
        value="broken_component:register",
    )

    import ovui_widgets.app.components as components

    monkeypatch.setattr(
        components.metadata,
        "entry_points",
        lambda: _EntryPoints((entry_point,)),
    )

    manager = ComponentManager(app)

    assert manager.load_all() == ()
    assert manager.loaded_names == ()
    assert manager.failures["broken_component"].args == (
        "component failed to import runtime",
    )
    assert len(app.component_module_load_failures) == 1

    failure = app.component_module_load_failures[0]
    assert failure.name == "broken_component"
    assert failure.value == "broken_component:register"
    assert failure.exception_type == "RuntimeError"
    assert failure.message == "component failed to import runtime"


def test_component_manager_loads_multiple_component_metadata(
    tmp_path,
    monkeypatch,
):
    for module_name, marker in (
        ("fake_alpha_component", "alpha"),
        ("fake_ovstage_component", "ovstage"),
    ):
        (tmp_path / f"{module_name}.py").write_text(
            "\n".join(
                [
                    "calls = []",
                    "",
                    "def register(app):",
                    f"    calls.append(({marker!r}, app))",
                    "    return None",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

    dist_infos = {
        "fake_alpha_tools-1.0.dist-info": (
            "fake-alpha-tools",
            "fake_alpha_tools = fake_alpha_component:register",
        ),
        "ovui_data_adapters_ovstage-1.0.dist-info": (
            "ovui-data-adapters-ovstage",
            "ovstage_physics_controls = fake_ovstage_component:register",
        ),
    }
    for dirname, (dist_name, entry_point_line) in dist_infos.items():
        dist_info = tmp_path / dirname
        dist_info.mkdir()
        (dist_info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {dist_name}\nVersion: 1.0\n",
            encoding="utf-8",
        )
        (dist_info / "entry_points.txt").write_text(
            "[ovui_widgets.components]\n"
            f"{entry_point_line}\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(sys, "path", [str(tmp_path)])
    importlib.invalidate_caches()
    sys.modules.pop("fake_alpha_component", None)
    sys.modules.pop("fake_ovstage_component", None)

    app = object()
    manager = ComponentManager(app)
    loaded = manager.load_all()

    assert [record.name for record in loaded] == [
        "fake_alpha_tools",
        "ovstage_physics_controls",
    ]

    alpha_module = importlib.import_module("fake_alpha_component")
    ovstage_module = importlib.import_module("fake_ovstage_component")
    assert alpha_module.calls == [("alpha", app)]
    assert ovstage_module.calls == [("ovstage", app)]


def test_component_dist_metadata_declares_ovstage_physx():
    ovstage_pyproject = tomllib.loads(
        (
            REPO_ROOT
            / "ovui-data-adapters"
            / "dist"
            / "ovstage"
            / "pyproject.toml"
        ).read_text(encoding="utf-8")
    )

    assert (
        ovstage_pyproject["project"]["entry-points"][ENTRY_POINT_GROUP][
            "ovstage_physics_controls"
        ]
        == "ovui_widgets_physx_controls:register"
    )
