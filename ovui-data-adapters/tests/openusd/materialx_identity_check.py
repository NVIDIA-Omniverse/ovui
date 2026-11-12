#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Render MaterialX materials of one graph through the OpenUSD renderer adapter and check each cube.

``test_materialx_identity_real_renderer.py`` runs this file in a new process for each check:
Carb settings (``OVUI_OVRTX_CARB_SETTINGS``) are process-global, and the MaterialX plugin reads
them when it starts. It needs a GPU and ovrtx. It prints one JSON report:

    python materialx_identity_check.py --report report.json [--rewired] [--materials N] \\
        [--expect-module-per-material]

Checks (exit code 1 when one fails; ``failures`` in the report lists each):

* every cube shows the color of its own albedo texture;
* ovrtx logs no error that names a material. A material that ovrtx cannot build shows an
  error color;
* ``--rewired``: graphs with the same node types and connection names but other wiring
  (see :func:`write_scene`). The MaterialX cache key of ovrtx gives them one shared module,
  and with the ovrtx default one of the materials then fails;
* ``--expect-module-per-material``: ovrtx generated one MDL module for each material, which
  is what ``disableDeduplication=true`` must give.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
import tempfile
import time
import uuid
import zlib
from pathlib import Path

CUBE_SPACING = 1.3
CAMERA_Z = 6.0
FOCAL_LENGTH = 24.0
HORIZONTAL_APERTURE = 20.955
WIDTH, HEIGHT = 900, 300
# One pure color per material. Solid textures keep the check about identity.
ALBEDO_COLORS = ((230, 20, 20), (20, 230, 20), (20, 20, 230), (230, 230, 20))
_SEARCH_PATH_RE = re.compile(
    r"Registered MDL search path for MaterialX generated modules: file:(?P<path>\S+)"
)
# An error that names a material, for example
# "Unable to find original SdfPath for key: '...' in material: '/...'".
_MATERIAL_ERROR_RE = re.compile(
    r"\[Error\] \[omni\.rtx\.materials\] (?P<message>.*\bmaterial: '.*)"
)


def _write_png(path: Path, pixels) -> None:
    """Write an 8-bit PNG from rows of ``(r, g, b)`` values."""

    height, width = len(pixels), len(pixels[0])
    raw = b"".join(b"\x00" + bytes(channel for pixel in row for channel in pixel) for row in pixels)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _solid_png(path: Path, color: tuple[int, int, int], size: int = 16) -> None:
    _write_png(path, [[color] * size for _ in range(size)])


_TINT = '''
            def Shader "Tint"
            {
                uniform token info:id = "ND_constant_color3"
                color3f inputs:value = (0.5, 0.5, 0.5)
                color3f outputs:out
            }'''


def write_scene(directory: Path, count: int, run_id: str, rewired: bool = False) -> Path:
    """Write ``count`` OpenPBR materials with the same graph and node names, each on its own cube.

    Each material has its own albedo file. The normal map and roughness files are
    the same for all, as in the issue: image to base_color, image to normal
    through normalmap, image to roughness. ``run_id`` is part of the material names,
    so a persistent ovrtx cache from an earlier run cannot hold these modules.

    ``rewired``: each material also has a grey constant color and a coat
    (``coat_weight`` 1). The first material connects its albedo image to
    ``base_color`` and the constant to ``coat_color``; the others connect them the
    other way. The node types and connection names are the same, so the MaterialX
    cache key of ovrtx is the same; the wiring is not.
    """

    directory.mkdir(parents=True, exist_ok=True)
    _solid_png(directory / "normal.png", (128, 128, 255))
    _solid_png(directory / "rough.png", (100, 100, 100))
    uv = ",".join(["(0,0),(1,0),(1,1),(0,1)"] * 6)
    materials, cubes = [], []
    for index in range(count):
        _solid_png(directory / f"albedo{index}.png", ALBEDO_COLORS[index])
        base = f"/World/Looks/M{index}_{run_id}"
        coat = ""
        if rewired:
            to_base, to_coat = ("Albedo", "Tint") if index == 0 else ("Tint", "Albedo")
            coat = f'''
                float inputs:coat_weight = 1
                color3f inputs:coat_color.connect = <{base}/{to_coat}.outputs:out>'''
        else:
            to_base = "Albedo"
        materials.append(f'''
        def Material "M{index}_{run_id}"
        {{
            token outputs:mtlx:surface.connect = <{base}/PBR.outputs:out>
            def Shader "PBR"
            {{
                uniform token info:id = "ND_open_pbr_surface_surfaceshader"
                color3f inputs:base_color.connect = <{base}/{to_base}.outputs:out>{coat}
                float inputs:specular_roughness.connect = <{base}/Rough.outputs:out>
                vector3f inputs:geometry_normal.connect = <{base}/NMap.outputs:out>
                token outputs:out
            }}
            def Shader "Albedo"
            {{
                uniform token info:id = "ND_image_color3"
                asset inputs:file = @./albedo{index}.png@
                color3f outputs:out
            }}
            def Shader "Normal"
            {{
                uniform token info:id = "ND_image_vector3"
                asset inputs:file = @./normal.png@
                vector3f outputs:out
            }}
            def Shader "NMap"
            {{
                uniform token info:id = "ND_normalmap"
                vector3f inputs:in.connect = <{base}/Normal.outputs:out>
                vector3f outputs:out
            }}
            def Shader "Rough"
            {{
                uniform token info:id = "ND_image_float"
                asset inputs:file = @./rough.png@
                float outputs:out
            }}{_TINT if rewired else ""}
        }}''')
        x = (index - (count - 1) / 2) * CUBE_SPACING
        cubes.append(f'''
    def Cube "C{index}" (prepend apiSchemas = ["MaterialBindingAPI"])
    {{
        double size = 1
        rel material:binding = <{base}>
        double3 xformOp:translate = ({x}, 0, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
        texCoord2f[] primvars:st = [{uv}] (interpolation = "faceVarying")
    }}''')
    scene = directory / "scene.usda"
    scene.write_text(f'''#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 1
    upAxis = "Y"
)
def Xform "World"
{{
    def Scope "Looks"
    {{{"".join(materials)}
    }}{"".join(cubes)}
    def DomeLight "Dome"
    {{
        float inputs:intensity = 40
    }}
    def DistantLight "Sun"
    {{
        float inputs:intensity = 700
        float3 xformOp:rotateXYZ = (-40, 30, 0)
        uniform token[] xformOpOrder = ["xformOp:rotateXYZ"]
    }}
}}
''')
    return scene


def _camera_matrices():
    """GL view and projection matrices for a camera on +Z that looks at the origin."""

    import numpy as np

    near, far = 0.1, 100.0
    fy = FOCAL_LENGTH * 2 / (HORIZONTAL_APERTURE * HEIGHT / WIDTH)
    fx = fy * HEIGHT / WIDTH
    projection = np.array(
        [
            [fx, 0, 0, 0],
            [0, fy, 0, 0],
            [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)],
            [0, 0, -1, 0],
        ],
        dtype=np.float64,
    )
    view = np.eye(4, dtype=np.float64)
    view[2, 3] = -CAMERA_Z
    return view, projection


def _read_material_errors(log_path: Path) -> list[str]:
    """Return the errors that ovrtx logged for a named material, for example a failed one."""

    text = log_path.read_text(errors="replace") if log_path.exists() else ""
    return [match.group("message").strip() for match in _MATERIAL_ERROR_RE.finditer(text)]


def _read_generated_modules(log_path: Path, since: float) -> list[str]:
    """Return the MaterialX MDL modules that ovrtx generated in this run.

    ovrtx logs the directory for the MaterialX modules it generates. Files older
    than ``since`` come from a persistent cache of an earlier run. The files exist
    until the renderer is destroyed.
    """

    deadline = time.monotonic() + 10.0
    directory = None
    while directory is None and time.monotonic() < deadline:
        text = log_path.read_text(errors="replace") if log_path.exists() else ""
        match = _SEARCH_PATH_RE.search(text)
        if match:
            directory = Path(match.group("path"))
        else:
            time.sleep(0.5)
    if directory is None:
        raise RuntimeError(f"ovrtx did not log the directory of its MaterialX modules in {log_path}.")
    return [str(path) for path in sorted(directory.rglob("materialx.mdl")) if path.stat().st_mtime >= since]


def _cube_colors(frame, count: int) -> list[tuple[int, int, int]]:
    import numpy as np

    colors = []
    for index in range(count):
        x = (index - (count - 1) / 2) * CUBE_SPACING
        depth = CAMERA_Z - 0.5
        px = int(WIDTH / 2 + x / depth * FOCAL_LENGTH / HORIZONTAL_APERTURE * WIDTH)
        py = HEIGHT // 2
        patch = np.asarray(frame)[py - 10 : py + 10, px - 10 : px + 10, :3].reshape(-1, 3)
        colors.append(tuple(int(v) for v in patch.mean(0).round()))
    return colors


def _shows_own_albedo(got: tuple[int, int, int], expected: tuple[int, int, int]) -> bool:
    """The channels of the albedo lead the others clearly; a texture of another material does not."""

    own = [c for c in range(3) if expected[c] == max(expected)]
    others = [c for c in range(3) if c not in own]
    return min(got[c] for c in own) > max((got[c] for c in others), default=0) + 40


def run(count: int, workdir: Path, image: Path | None, rewired: bool = False) -> dict:
    import numpy as np
    import ovrtx
    from pxr import Usd

    from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter

    started = time.time()
    scene = write_scene(workdir / "scene", count, uuid.uuid4().hex[:8], rewired)
    log_path = workdir / "ovrtx.log"
    config = ovrtx.RendererConfig(log_level="info", log_file_path=str(log_path))
    adapter = OvRtxRendererAdapter(config=config)
    try:
        adapter.load_stage(Usd.Stage.Open(str(scene)))
        view, projection = _camera_matrices()
        frame = None
        for _ in range(40):
            frame = adapter.render_frame(WIDTH, HEIGHT, view, projection)
        frame = np.asarray(frame)
        if image is not None:
            image.parent.mkdir(parents=True, exist_ok=True)
            _write_png(image, frame[..., :3].tolist())
        modules = _read_generated_modules(log_path, started)
    finally:
        adapter.shutdown()
    cubes = []
    for index, got in enumerate(_cube_colors(frame, count)):
        expected = ALBEDO_COLORS[index]
        cubes.append({
            "material": f"M{index}",
            "albedo": list(expected),
            "rendered": list(got),
            "own_texture": _shows_own_albedo(got, expected),
        })
    return {
        "ovrtx_version": ovrtx.__version__,
        "materials": count,
        "cubes": cubes,
        "generated_modules": len(modules),
        "modules": modules,
        "material_errors": _read_material_errors(log_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--materials", type=int, default=3, choices=range(2, len(ALBEDO_COLORS) + 1))
    parser.add_argument("--workdir", type=Path, help="Directory for the scene and the log (default: a new temporary one).")
    parser.add_argument("--image", type=Path, help="Save the rendered frame here.")
    parser.add_argument("--report", type=Path, help="Write the JSON report to this file, as well as to the output.")
    parser.add_argument("--rewired", action="store_true", help="Use graphs with one cache key and other wiring.")
    parser.add_argument("--expect-module-per-material", action="store_true")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="ovui-materialx-identity-") as temporary:
        report = run(args.materials, args.workdir or Path(temporary), args.image, args.rewired)

    failures = []
    for cube in report["cubes"]:
        if not cube["own_texture"]:
            failures.append(f"{cube['material']} does not show its own albedo {cube['albedo']}: rendered {cube['rendered']}")
    for message in report["material_errors"]:
        failures.append(f"ovrtx logged a material error: {message}")
    if args.expect_module_per_material and report["generated_modules"] != report["materials"]:
        failures.append(
            f"ovrtx generated {report['generated_modules']} MaterialX module(s) for "
            f"{report['materials']} materials; disableDeduplication=true must give one for each"
        )
    report["failures"] = failures
    text = json.dumps(report, indent=2)
    if args.report:
        args.report.write_text(text)
    print(text)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
