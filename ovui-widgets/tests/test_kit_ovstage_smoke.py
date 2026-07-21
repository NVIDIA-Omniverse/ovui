# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Runtime-free tests for the Kit ovstage smoke script's pure helpers.

The script's heavy imports (omni.ui, numpy, ovui-widgets app) are deferred into
``run_smoke``, so the module loads and its argument parsing / env resolution /
ovrtx-scrub helpers are testable without any Kit runtime.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import struct
import sys
import types
import zlib

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "kit_ovstage_smoke.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("_kit_ovstage_smoke_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def smoke():
    return _load_module()


def test_parser_defaults(smoke) -> None:
    args = smoke._build_parser().parse_args(["--out-dir", "/tmp/x"])
    assert args.out_dir == "/tmp/x"
    assert args.label == "kit_ovstage_smoke"
    assert args.first_frame_timeout == pytest.approx(300.0)
    assert args.first_frame_timeout >= 120.0  # safe warmup default
    assert args.performance_seconds == pytest.approx(3.0)
    assert args.min_fps == pytest.approx(0.0)
    assert args.prim_path == "/World/Hierarchy/GroupA/BoxA"
    assert args.no_drag is False
    assert args.scene.endswith("ovstage_static_scene.usda")


def test_resolve_roots_from_kit_root(smoke, monkeypatch) -> None:
    monkeypatch.delenv("OVSTAGE_ROOT", raising=False)
    monkeypatch.delenv("OVRTX_ROOT", raising=False)
    args = smoke._build_parser().parse_args(["--out-dir", "/tmp/x", "--kit-root", "/k"])
    roots = smoke._resolve_roots(args)
    assert roots["OVSTAGE_ROOT"].replace("\\", "/") == "/k/rendering/ovstage"
    assert roots["OVRTX_ROOT"].replace("\\", "/") == "/k/rendering/ovrtx"


def test_resolve_roots_explicit_overrides_win(smoke, monkeypatch) -> None:
    monkeypatch.setenv("OVSTAGE_ROOT", "/env/ovstage")
    monkeypatch.setenv("OVRTX_ROOT", "/env/ovrtx")
    args = smoke._build_parser().parse_args(
        ["--out-dir", "/tmp/x", "--kit-root", "/k", "--ovstage-root", "/flag/ovstage"]
    )
    roots = smoke._resolve_roots(args)
    # Explicit flag beats env; env beats KIT_ROOT derivation.
    assert roots["OVSTAGE_ROOT"] == "/flag/ovstage"
    assert roots["OVRTX_ROOT"] == "/env/ovrtx"


def test_scrub_standalone_ovrtx_removes_modules_and_path(smoke, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "ovrtx", types.ModuleType("ovrtx"))
    monkeypatch.setitem(sys.modules, "ovrtx.sub", types.ModuleType("ovrtx.sub"))
    monkeypatch.syspath_prepend("/some/dev/ovrtx/public/python")

    removed = smoke._scrub_standalone_ovrtx()

    assert "ovrtx" in removed and "ovrtx.sub" in removed
    assert "ovrtx" not in sys.modules
    assert not any("/dev/ovrtx" in p for p in sys.path)


def test_png_size_reads_dimensions(smoke, tmp_path) -> None:
    png = tmp_path / "tiny.png"
    width, height = 7, 3

    def _chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    png.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _chunk(b"IEND", b"")
    )
    assert smoke._png_size(png) == (width, height)


def test_png_size_handles_missing_or_bad(smoke, tmp_path) -> None:
    assert smoke._png_size(tmp_path / "nope.png") == (None, None)
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a png")
    assert smoke._png_size(bad) == (None, None)
