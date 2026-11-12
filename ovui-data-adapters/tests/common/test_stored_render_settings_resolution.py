# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The stored render settings reach ovrtx from every supported install layout.

An ``OVRTX_ROOT`` install keeps its Python package under ``public/python`` and
its runtime files, including the settings schema, under ``bin``. A value the
schema refuses must be named, and the other settings must still apply.
"""

from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest

from ovui_data_adapters.common import stored_render_settings as module
from ovui_data_adapters.common.ovrtx_import import OvRtxImportResult


def test_the_schema_of_an_ovrtx_root_install_is_read(tmp_path, monkeypatch) -> None:
    root = tmp_path / "ovrtx_root"
    shutil.copytree(module._schema_dir(), root / "bin" / "usd_plugins" / "rtx_settings")
    package = root / "public" / "python" / "ovrtx"
    package.mkdir(parents=True)
    monkeypatch.setenv("OVRTX_ROOT", str(root))
    monkeypatch.setattr(
        module,
        "import_ovrtx",
        lambda: OvRtxImportResult(
            module=SimpleNamespace(__file__=str(package / "__init__.py")), error=None
        ),
    )
    module._ovrtx_setting_attributes.cache_clear()
    try:
        lines = module.stored_render_setting_lines({"rtx:post:tonemap:fNumber": 16})
    finally:
        module._ovrtx_setting_attributes.cache_clear()

    assert lines["Camera"] == ["float exposure:fStop = 16.0"]


@pytest.mark.parametrize(
    "key, value",
    [
        ("rtx:post:tonemap:fNumber", "not-a-number"),
        ("rtx:raytracing:indexdirect:svoBrickSize", [1, 2]),
        ("rtx:background:source:color", (1.0, 2.0)),
        ("rtx:pathtracing:totalSpp", float("inf")),
        ("rtx:post:tonemap:op", -1),
        # A number no uint holds, and an int3 component no int holds. USD
        # refuses the whole layer that states one.
        ("rtx:pathtracing:totalSpp", -1),
        ("rtx:pathtracing:totalSpp", 2**32),
        ("rtx:raytracing:indexdirect:svoBrickSize", [1, 2, 2**31]),
    ],
)
def test_a_refused_value_is_reported_and_the_others_apply(key, value, capsys) -> None:
    valid = {"rtx:post:tonemap:filmIso": 100.0}
    only_valid = module.stored_render_setting_lines(valid)
    capsys.readouterr()
    assert only_valid["Camera"] == ["float exposure:iso = 100.0"]

    lines = module.stored_render_setting_lines({**valid, key: value})

    assert lines == only_valid
    assert key in capsys.readouterr().err


def test_a_setting_stored_at_the_ovrtx_default_is_left_out() -> None:
    """Kit saves every setting; only those that differ from ovrtx reach the session.

    Factory.usd stores 28 RenderProduct settings, 26 of them at the ovrtx
    default. Each stated setting is one more attribute that ovrtx reads while
    it renders, and leaving a default out changes no pixel.
    """

    lines = module.stored_render_setting_lines(
        {
            "rtx:fog:fogColor": (0.75, 0.75, 0.75),
            "rtx:raytracing:inscattering:singleScatteringAlbedo": (0.9, 0.9, 0.9),
            "rtx:raytracing:indexdirect:svoBrickSize": (32, 32, 32),
            "rtx:post:chromaticAberration:strengthB": -0.055,
            "rtx:post:tonemap:op": 7,
        }
    )

    assert lines["RenderProduct"] == [
        "float omni:rtx:post:chromab:strengthB = -0.055",
        'token omni:rtx:post:tonemap:operator = "iray"',
    ]
    # Kit's tone mapper number 6 is the ovrtx default, acesApproximation.
    assert module.stored_render_setting_lines({"rtx:post:tonemap:op": 6})["RenderProduct"] == []


def test_a_camera_setting_at_the_ovrtx_default_is_still_stated() -> None:
    """``exposure:iso`` belongs to the USD Camera, whose own fallback may differ."""

    lines = module.stored_render_setting_lines({"rtx:post:tonemap:filmIso": 100.0})

    assert lines["Camera"] == ["float exposure:iso = 100.0"]
