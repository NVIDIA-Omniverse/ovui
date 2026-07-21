# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for BatchTransformCommand."""

import subprocess
import sys

import pytest

from ovui_data_adapters.services.transforms import (
    BatchTransformCommand as ServiceBatchTransformCommand,
)
from ovui_widgets.common.testing.mock_transform import MockTransformAdapter
from ovui_widgets.common.undo import BatchTransformCommand, UndoManager

_IDENTITY = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]

_TRANSLATED = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [5.0, 3.0, 1.0, 1.0],
]


@pytest.fixture
def adapter():
    a = MockTransformAdapter()
    a.set_local_transform("/Sphere", [row[:] for row in _IDENTITY])
    return a


@pytest.fixture
def cmd(adapter):
    return BatchTransformCommand(adapter, "/Sphere", _IDENTITY, _TRANSLATED)


class TestBatchTransformCommandImport:
    def test_old_path_importable(self):
        from ovui_widgets.common.undo import BatchTransformCommand  # noqa: F401

    def test_old_path_reexports_service_object(self):
        assert BatchTransformCommand is ServiceBatchTransformCommand

    def test_is_command_subclass(self):
        from ovui_widgets.common.undo import BatchTransformCommand, Command
        assert issubclass(BatchTransformCommand, Command)

    def test_service_import_without_ui_runtime_modules(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "from ovui_data_adapters.services.transforms "
                    "import BatchTransformCommand; "
                    "forbidden = sorted(name for name in sys.modules "
                    "if name == 'ovui_widgets' or name.startswith('ovui_widgets.') "
                    "or name == 'omni' or name.startswith('omni.')); "
                    "print(BatchTransformCommand.__name__, forbidden); "
                    "raise SystemExit(1 if forbidden else 0)"
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert "BatchTransformCommand []" in proc.stdout


class TestBatchTransformCommandRedo:
    def test_redo_sets_final_transform(self, adapter, cmd):
        cmd.redo()
        result = adapter.get_local_transform("/Sphere")
        assert result[3][0] == pytest.approx(5.0)
        assert result[3][1] == pytest.approx(3.0)
        assert result[3][2] == pytest.approx(1.0)

    def test_do_sets_final_transform(self, adapter, cmd):
        cmd.do()
        result = adapter.get_local_transform("/Sphere")
        assert result[3][0] == pytest.approx(5.0)

    def test_redo_same_as_do(self, adapter):
        cmd = BatchTransformCommand(adapter, "/Sphere", _IDENTITY, _TRANSLATED)
        cmd.do()
        r1 = adapter.get_local_transform("/Sphere")
        cmd.undo()
        cmd.redo()
        r2 = adapter.get_local_transform("/Sphere")
        assert r1 == r2


class TestBatchTransformCommandUndo:
    def test_undo_restores_initial_transform(self, adapter, cmd):
        cmd.do()
        cmd.undo()
        result = adapter.get_local_transform("/Sphere")
        assert result[3][0] == pytest.approx(0.0)
        assert result[3][1] == pytest.approx(0.0)
        assert result[3][2] == pytest.approx(0.0)

    def test_undo_after_redo(self, adapter, cmd):
        cmd.do()
        cmd.undo()
        cmd.redo()
        cmd.undo()
        result = adapter.get_local_transform("/Sphere")
        assert result[3][0] == pytest.approx(0.0)


class TestBatchTransformCommandIsolation:
    def test_does_not_mutate_initial_arg(self):
        adapter = MockTransformAdapter()
        initial = [row[:] for row in _IDENTITY]
        final = [row[:] for row in _TRANSLATED]
        cmd = BatchTransformCommand(adapter, "/X", initial, final)
        cmd.do()
        # Mutating the original lists should not affect the stored copy
        initial[3][0] = 99.0
        cmd.undo()
        result = adapter.get_local_transform("/X")
        assert result[3][0] == pytest.approx(0.0)

    def test_does_not_mutate_final_arg(self):
        adapter = MockTransformAdapter()
        initial = [row[:] for row in _IDENTITY]
        final = [row[:] for row in _TRANSLATED]
        cmd = BatchTransformCommand(adapter, "/X", initial, final)
        final[3][0] = 99.0
        cmd.do()
        result = adapter.get_local_transform("/X")
        assert result[3][0] == pytest.approx(5.0)


class TestBatchTransformCommandWithUndoManager:
    def test_push_and_undo_via_manager(self, adapter):
        undo = UndoManager()
        initial = adapter.get_local_transform("/Sphere")
        cmd = BatchTransformCommand(adapter, "/Sphere", initial, _TRANSLATED)
        undo.push(cmd)
        assert adapter.get_local_transform("/Sphere")[3][0] == pytest.approx(5.0)
        undo.undo()
        assert adapter.get_local_transform("/Sphere")[3][0] == pytest.approx(0.0)

    def test_push_redo_via_manager(self, adapter):
        undo = UndoManager()
        initial = adapter.get_local_transform("/Sphere")
        cmd = BatchTransformCommand(adapter, "/Sphere", initial, _TRANSLATED)
        undo.push(cmd)
        undo.undo()
        undo.redo()
        assert adapter.get_local_transform("/Sphere")[3][0] == pytest.approx(5.0)

    def test_group_with_multiple_prims(self):
        adapter = MockTransformAdapter()
        undo = UndoManager()
        paths = ["/A", "/B", "/C"]
        finals = {
            "/A": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[1,0,0,1]],
            "/B": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[2,0,0,1]],
            "/C": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[3,0,0,1]],
        }
        undo.begin_group("Move")
        for p in paths:
            initial = adapter.get_local_transform(p)
            cmd = BatchTransformCommand(adapter, p, initial, finals[p])
            undo.push(cmd)
        undo.end_group()

        for p in paths:
            assert adapter.get_local_transform(p)[3][0] == pytest.approx(finals[p][3][0])

        undo.undo()
        for p in paths:
            assert adapter.get_local_transform(p)[3][0] == pytest.approx(0.0)
