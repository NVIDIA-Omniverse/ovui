# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""
Kit-compatible image comparison utilities for ovui tests.

Ported from Kit's ``omni.ui`` compare_utils.py, using Pillow (PIL) for
image I/O and pixel math.  The comparison metrics and semantics match
Kit so that thresholds are directly transferable.
"""
__all__ = ["CompareError", "CompareMetric", "compare"]

from pathlib import Path
from PIL import Image, ImageChops, ImageStat


class CompareError(Exception):
    """Raised when image comparison cannot proceed."""
    pass


class CompareMetric:
    """Comparison metric selectors -- values match Kit's string constants."""
    MEAN_ERROR = "mean_error"
    MEAN_ERROR_SQUARED = "mean_error_squared"
    PIXEL_COUNT = "pixel_count"


def compare(
    image1: Path,
    image2: Path,
    image_diffmap: Path,
    threshold: float | None = None,
    cmp_metric: str = CompareMetric.MEAN_ERROR,
) -> float:
    """Compare two images and return a difference metric value.

    This is a faithful port of Kit's ``compare()`` function:

    * **MEAN_ERROR** -- average per-channel absolute difference, range [0, 255].
    * **MEAN_ERROR_SQUARED** -- mean squared error normalised to [0, 1].
    * **PIXEL_COUNT** -- number of pixels that differ.

    A diff-map image is saved to *image_diffmap* when the difference
    exceeds ``threshold / 100`` (same heuristic as Kit).

    Args:
        image1: Reference (golden) image path.
        image2: Captured (test) image path.
        image_diffmap: Where to write the amplified diff image.
        threshold: Value used to decide whether to save the diff-map.
        cmp_metric: One of the ``CompareMetric`` constants.

    Returns:
        The computed difference value.

    Raises:
        CompareError: If files are missing or images have incompatible
            sizes / modes.
    """
    image1 = Path(image1)
    image2 = Path(image2)

    if not image1.exists():
        raise CompareError(f"File image1 {image1} does not exist")
    if not image2.exists():
        raise CompareError(f"File image2 {image2} does not exist")

    original = Image.open(str(image1))
    contrast = Image.open(str(image2))

    if original.size != contrast.size:
        raise CompareError(
            f"[omni.ui.test] Can't compare different resolutions\n\n"
            f"{image1} {original.size[0]}x{original.size[1]}\n"
            f"{image2} {contrast.size[0]}x{contrast.size[1]}\n"
        )

    if original.mode != contrast.mode:
        raise CompareError(
            f"[omni.ui.test] Can't compare images with different mode (channels).\n\n"
            f"{image1} {original.mode}\n"
            f"{image2} {contrast.mode}\n"
        )

    img_diff = ImageChops.difference(original, contrast)
    stat = ImageStat.Stat(img_diff)

    if cmp_metric == CompareMetric.MEAN_ERROR:
        # Average difference per channel -- range [0, 255]
        diff = sum(stat.mean) / len(stat.mean)

    elif cmp_metric == CompareMetric.MEAN_ERROR_SQUARED:
        # Mean squared error normalised to [0, 1]
        errors = [x / stat.count[i] for i, x in enumerate(stat.sum2)]
        diff = sum(errors) / len(stat.sum2) / 255 ** 2

    elif cmp_metric == CompareMetric.PIXEL_COUNT:
        # Count of pixels that differ
        if isinstance(img_diff.getpixel((0, 0)), int):
            diff = sum(
                img_diff.getpixel((j, i)) > 0
                for i in range(img_diff.height)
                for j in range(img_diff.width)
            )
        else:
            diff = sum(
                sum(img_diff.getpixel((j, i))) > 0
                for i in range(img_diff.height)
                for j in range(img_diff.width)
            )
    else:
        raise CompareError(f"Unknown comparison metric: {cmp_metric}")

    # Save amplified diff-map when difference is significant
    if diff > 0 and threshold and diff > threshold / 100:
        image_diffmap = Path(image_diffmap)
        image_diffmap.parent.mkdir(parents=True, exist_ok=True)
        amp = img_diff.convert("RGB").point(lambda i: min(i * 255, 255))
        amp.save(str(image_diffmap))

    return diff
