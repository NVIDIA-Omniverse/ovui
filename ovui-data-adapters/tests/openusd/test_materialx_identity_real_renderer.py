# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""OVUI_OVRTX_CARB_SETTINGS gives each MaterialX material its own module in the real renderer.

Scene of the issue: OpenPBR materials with the same graph and node names and
different albedo files (image to base_color, image to normal through normalmap,
image to roughness), each on its own cube.

The ovrtx MaterialX cache key is a sum over node types and connection names. Two
graphs with the same node types and connection names but other wiring get the
same key and share one module. With the ovrtx default, one of the materials then
fails and shows an error color. ``disableDeduplication=true``, applied before the
MaterialX plugin starts, gives each material its own module.

Each check runs ``materialx_identity_check.py`` (next to this file) in a new
process, because Carb settings are process-global and are read when the MaterialX
plugin starts. The check renders through the OpenUSD renderer adapter. These tests
need an NVIDIA GPU and an ovrtx that applies ``disableDeduplication``.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

from ovui_data_adapters.common.ovrtx_carb_settings import OVRTX_CARB_SETTINGS_ENV

pytestmark = pytest.mark.requires_ovrtx

CHECK = pathlib.Path(__file__).resolve().with_name("materialx_identity_check.py")
ADAPTERS = pathlib.Path(__file__).resolve().parents[2]
DISABLE_DEDUPLICATION = "/persistent/app/material/materialx/disableDeduplication=true"


def _check(tmp_path: pathlib.Path, *flags: str, carb_settings: str) -> dict:
    """Run the check in a new process; it must succeed. Returns its report."""

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ADAPTERS), env.get("PYTHONPATH", "")]))
    env["OVRTX_SKIP_USD_CHECK"] = "1"
    env[OVRTX_CARB_SETTINGS_ENV] = carb_settings
    report = tmp_path / "report.json"
    process = subprocess.run(
        [sys.executable, str(CHECK), "--report", str(report), *flags],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    output = f"{process.stdout[-3000:]}\n{process.stderr[-3000:]}"
    assert report.exists(), f"the check did not finish (exit code {process.returncode})\n{output}"
    result = json.loads(report.read_text())
    assert process.returncode == 0 and not result["failures"], (
        f"the check failed (exit code {process.returncode}): {result['failures']}\n{output}"
    )
    return result


def _assert_each_cube_shows_its_own_albedo(result: dict) -> None:
    shown = [(cube["material"], cube["albedo"], cube["rendered"]) for cube in result["cubes"]]
    assert len(result["cubes"]) == result["materials"], shown
    assert all(cube["own_texture"] for cube in result["cubes"]), f"a material does not show its own albedo: {shown}"


def test_materials_with_one_cache_key_and_other_wiring_render_their_own_textures(tmp_path):
    result = _check(
        tmp_path, "--rewired", "--materials", "2", "--expect-module-per-material", carb_settings=DISABLE_DEDUPLICATION
    )

    assert not result["material_errors"], f"ovrtx could not build a material: {result['material_errors']}"
    _assert_each_cube_shows_its_own_albedo(result)
    assert result["generated_modules"] == result["materials"]


def test_disable_deduplication_from_the_environment_gives_each_material_its_own_module(tmp_path):
    result = _check(tmp_path, "--expect-module-per-material", carb_settings=DISABLE_DEDUPLICATION)

    assert result["generated_modules"] == result["materials"], (
        f"ovrtx generated {result['generated_modules']} MaterialX module(s) for {result['materials']} materials "
        f"although {OVRTX_CARB_SETTINGS_ENV} set disableDeduplication=true before the first renderer"
    )
    _assert_each_cube_shows_its_own_albedo(result)
