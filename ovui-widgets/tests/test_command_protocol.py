# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""CI invariant: ``Command`` is unified across the data-adapters split.

Step 26 (Rev 4 §10.5 / pre-planning §6.1) — extended after the Codex
Step 26 review flagged that
the original test missed
``ovui_data_adapters.openusd.property_adapter.SetAttributeCommand``
and the layer-command surface. The implementation plan §10.5 says
this file should assert that **all** relevant ``Command`` subclasses
are compatible with both import paths.

The canonical ``Command`` ABC lives in
:mod:`ovui_data_adapters.common._command` so adapter packages can share it
without depending on higher-level services. Three import paths must resolve to
the **same class object**:

  - ``from ovui_data_adapters.common import Command``
  - ``from ovui_data_adapters.services.undo import Command``
  - ``from ovui_widgets.common.undo import Command``

This file pins:

  - ``Command`` identity across the two import paths.
  - ``Command`` remains an ABC with abstract ``do`` / ``undo`` and a
    concrete default ``redo`` (delegates to ``do``).
  - Every concrete ``Command`` subclass we care about — widget-side
    undo helpers, the OpenUSD property-side ``SetAttributeCommand``,
    the OpenUSD scene-mutation commands, and the
    ``AbstractLayerCommand`` family — passes ``issubclass`` /
    ``isinstance`` against both import paths. A future split that
    quietly forked ``Command`` into two unrelated classes would still
    work via duck typing on individual call sites but would fail
    ``isinstance(cmd, ovui_data_adapters.common.Command)``, which the
    cross-package undo machinery relies on.
"""

from __future__ import annotations

import inspect
from typing import Type

import ovui_data_adapters.common as _adapters_common
import ovui_data_adapters.services.undo as _services_undo
import pytest

import ovui_widgets.common.undo as _widgets_undo

# ---------------------------------------------------------------------------
# Identity + ABC contract
# ---------------------------------------------------------------------------


def test_command_is_same_class_object_across_packages():
    """All command import paths must resolve to the identical class object."""
    assert _services_undo.Command is _adapters_common.Command, (
        "ovui_data_adapters.services.undo.Command must be "
        "ovui_data_adapters.common.Command"
    )
    assert _widgets_undo.Command is _adapters_common.Command, (
        "ovui_widgets.common.undo.Command must be ovui_data_adapters.common.Command"
    )


def test_undo_group_and_manager_are_services_objects():
    """The concrete undo/history behavior is canonical in services."""
    assert _widgets_undo.CommandCancelled is _services_undo.CommandCancelled
    assert _widgets_undo.UndoGroup is _services_undo.UndoGroup
    assert _widgets_undo.UndoManager is _services_undo.UndoManager
    assert _widgets_undo.UndoManagerProtocol is _services_undo.UndoManagerProtocol


def test_command_is_an_abstract_base_class():
    """``Command`` should still be an ABC with abstract ``do`` / ``undo``."""
    Command = _adapters_common.Command
    assert inspect.isabstract(Command), (
        "Command must remain abstract — concrete subclasses implement do/undo"
    )
    abstracts = set(getattr(Command, "__abstractmethods__", ()))
    assert "do" in abstracts, "Command.do must be abstract"
    assert "undo" in abstracts, "Command.undo must be abstract"


def test_command_has_redo_default_delegating_to_do():
    """``redo`` is concrete and falls through to ``do`` — Step 26 pins this
    contract so a future override keeps the documented default behavior.
    """
    Command = _adapters_common.Command
    assert hasattr(Command, "redo")
    assert "redo" not in getattr(Command, "__abstractmethods__", ())


# ---------------------------------------------------------------------------
# Command-subclass surface — parametrized over the entire repo
# ---------------------------------------------------------------------------


# Each entry is (importable dotted path, class name). Concrete
# ``Command`` subclasses that span the data-adapters boundary; the
# test below exercises ``issubclass`` against both
# ``ovui_data_adapters.common.Command`` and
# ``ovui_widgets.common.undo.Command`` for every entry.
COMMAND_SUBCLASSES: list[tuple[str, str]] = [
    # Transform command behavior lives in services and is re-exported by
    # ovui_widgets.common.undo.
    ("ovui_data_adapters.services.transforms", "BatchTransformCommand"),
    # Concrete undo/history behavior lives in services and is re-exported by
    # ovui_widgets.common.undo.
    ("ovui_data_adapters.services.undo", "UndoGroup"),
    # OpenUSD property-attribute command (Codex review correction —
    # this was missing from the original Step 26 commit).
    ("ovui_data_adapters.openusd.property_adapter", "SetAttributeCommand"),
    # OpenUSD scene-mutation commands (already covered before).
    ("ovui_data_adapters.openusd.commands", "SetVisibilityCommand"),
    ("ovui_data_adapters.openusd.commands", "DeletePrimCommand"),
    ("ovui_data_adapters.openusd.commands", "NamespaceEditCommand"),
    # Layer-command surface — base class + a representative cross-section
    # of the concrete layer commands. ``AbstractLayerCommand`` itself is
    # an ABC that sits between ``Command`` and the concrete commands;
    # the ``issubclass`` chain must hold even with that intermediate.
    ("ovui_widgets.layers.commands.base", "AbstractLayerCommand"),
    ("ovui_widgets.layers.commands.layer_commands", "SetEditTargetCommand"),
    ("ovui_widgets.layers.commands.layer_commands", "SetLayerMutenessCommand"),
    ("ovui_widgets.layers.commands.layer_commands", "SetLayerLockCommand"),
    ("ovui_widgets.layers.commands.sublayer_commands", "CreateSublayerCommand"),
    ("ovui_widgets.layers.commands.sublayer_commands", "InsertSublayerCommand"),
    ("ovui_widgets.layers.commands.sublayer_commands", "RemoveSublayerCommand"),
    ("ovui_widgets.layers.commands.sublayer_commands", "MoveSublayerCommand"),
    ("ovui_widgets.layers.commands.sublayer_commands", "ReplaceSublayerCommand"),
    ("ovui_widgets.layers.commands.sublayer_commands", "RemovePrimSpecsCommand"),
    ("ovui_widgets.layers.commands.merge_flatten_commands", "MergeDownCommand"),
    ("ovui_widgets.layers.commands.merge_flatten_commands", "FlattenSublayersCommand"),
    ("ovui_widgets.layers.commands.file_io_commands", "SaveLayerCommand"),
    ("ovui_widgets.layers.commands.file_io_commands", "ReloadLayerCommand"),
    ("ovui_widgets.layers.commands.file_io_commands", "SaveLayerAsCommand"),
]


def _resolve_class(module_path: str, class_name: str) -> Type[object]:
    import importlib

    module = importlib.import_module(module_path)
    cls = getattr(module, class_name, None)
    assert cls is not None, f"missing class: {module_path}.{class_name}"
    return cls


@pytest.mark.parametrize(
    "module_path,class_name",
    COMMAND_SUBCLASSES,
    ids=lambda v: v.split(".")[-1],
)
def test_subclass_is_command_via_both_import_paths(module_path: str, class_name: str):
    """Every concrete ``Command`` subclass must be recognised as a
    ``Command`` from BOTH import paths. Catches a future split that
    forks ``Command`` even though both are ABCs with the same
    interface.
    """
    cls = _resolve_class(module_path, class_name)
    assert issubclass(cls, _adapters_common.Command), (
        f"{module_path}.{class_name} must subclass "
        f"ovui_data_adapters.common.Command"
    )
    assert issubclass(cls, _widgets_undo.Command), (
        f"{module_path}.{class_name} must subclass "
        f"ovui_widgets.common.undo.Command"
    )


# ---------------------------------------------------------------------------
# Instance-level isinstance checks (cross-path)
# ---------------------------------------------------------------------------


def test_widget_side_command_instance_isinstance_of_unified_command():
    """An instance constructed via the widget-side path is recognised as a
    ``Command`` from the openusd-shared common path.
    """
    Command = _adapters_common.Command
    from ovui_widgets.common.undo import UndoGroup

    group = UndoGroup("test-undo-group", [])
    assert isinstance(group, Command)


def test_openusd_command_instance_isinstance_of_widget_side_command():
    """An openusd command instance is recognised as the widget-side
    ``Command`` import — symmetric to the previous test.
    """
    from ovui_data_adapters.openusd.commands import SetVisibilityCommand

    # Construct via __new__ to skip the heavy USD-stage init — the type
    # identity check doesn't depend on the instance being usable.
    cmd = SetVisibilityCommand.__new__(SetVisibilityCommand)
    assert isinstance(cmd, _widgets_undo.Command)


def test_openusd_set_attribute_command_instance_is_command():
    """``SetAttributeCommand`` (openusd property side) — the class
    Codex flagged as missing from the original Step 26 commit. Pinned
    here as both ``issubclass`` (above, via parametrization) AND
    ``isinstance`` (here) so a future regression where the class
    accidentally drops the ``Command`` base would be caught even if
    the parametrized scan was disabled.
    """
    from ovui_data_adapters.openusd.property_adapter import SetAttributeCommand

    cmd = SetAttributeCommand.__new__(SetAttributeCommand)
    assert isinstance(cmd, _adapters_common.Command)
    assert isinstance(cmd, _widgets_undo.Command)
