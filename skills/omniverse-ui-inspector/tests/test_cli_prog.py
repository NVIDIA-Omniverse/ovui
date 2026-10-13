# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _cli():
    path = Path(__file__).resolve().parents[1] / "scripts/ovui-inspect.py"
    spec = importlib.util.spec_from_file_location("ovui_inspect_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_front_end_names_the_cli_in_usage(capsys) -> None:
    with pytest.raises(SystemExit):
        _cli().main(["call", "--help"], prog="my-app", description="My application")
    assert capsys.readouterr().out.startswith("usage: my-app call ")
