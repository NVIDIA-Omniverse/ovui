# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compare two renders of one scene made on two devices (for example 1g.24gb and 2g.48gb).

The comparison fails with a clear message when a device is below the documented
minimum for the scene, or when the images differ more than render noise.

    python -m ovui_data_adapters.common.render_parity a.png b.png \\
        --scene-bytes 838860800 --gpu-gib-a 23.0 --gpu-gib-b 47.4
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

import numpy as np

from ovui_data_adapters.common.render_diagnostics import GIB, minimum_for_scene

#: Allowed mean absolute difference (0..255) and fraction of pixels that differ by more than 24.
DEFAULT_MEAN_ABS = 2.0
DEFAULT_BAD_FRACTION = 0.01


def compare_images(a: np.ndarray, b: np.ndarray, mean_abs: float = DEFAULT_MEAN_ABS,
                   bad_fraction: float = DEFAULT_BAD_FRACTION) -> tuple[bool, str]:
    """Return (same_within_noise, message)."""

    if a.shape != b.shape:
        return False, f"image sizes differ: {a.shape} and {b.shape}"
    diff = np.abs(a[..., :3].astype(np.int16) - b[..., :3].astype(np.int16))
    mean = float(diff.mean())
    bad = float((diff.max(axis=-1) > 24).mean())
    text = f"mean abs difference {mean:.2f} (limit {mean_abs}); pixels off by more than 24: {bad:.2%} (limit {bad_fraction:.2%})"
    return (mean <= mean_abs and bad <= bad_fraction), text


def check_parity(a: np.ndarray, b: np.ndarray, scene_bytes: int,
                 gpu_gib_a: Optional[float], gpu_gib_b: Optional[float]) -> tuple[int, str]:
    """Return (exit_code, message). 0 = same, 1 = different, 2 = a device is below the minimum."""

    minimum = minimum_for_scene(scene_bytes)
    for label, gib in (("A", gpu_gib_a), ("B", gpu_gib_b)):
        if gib is None:
            return 2, f"device {label}: GPU memory is unknown, so the render cannot be trusted. Run the gpu_memory command."
        if gib * GIB < minimum.min_gpu_gib * GIB:
            return 2, (
                f"device {label} has {gib:.1f} GiB, below the minimum of {minimum.min_gpu_gib:g} GiB for this scene "
                f"({scene_bytes / 2**20:.0f} MiB). Use a {minimum.advice}. Materials can render wrong without an error."
            )
    same, text = compare_images(a, b)
    return (0 if same else 1), ("renders match within noise: " if same else "renders DIFFER: ") + text


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image_a")
    parser.add_argument("image_b")
    parser.add_argument("--scene-bytes", type=int, required=True)
    parser.add_argument("--gpu-gib-a", type=float)
    parser.add_argument("--gpu-gib-b", type=float)
    args = parser.parse_args(argv)
    try:
        from PIL import Image
    except ImportError:
        print("reading the two images needs the optional image library Pillow, which is not installed", file=sys.stderr)
        return 2
    a = np.asarray(Image.open(args.image_a).convert("RGB"))
    b = np.asarray(Image.open(args.image_b).convert("RGB"))
    code, message = check_parity(a, b, args.scene_bytes, args.gpu_gib_a, args.gpu_gib_b)
    print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
