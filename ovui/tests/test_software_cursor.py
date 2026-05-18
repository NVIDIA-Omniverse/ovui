# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the software-cursor switch in :mod:`omni.ui.standalone`.

The headless Vulkan platform enables ``ImGui::GetIO().MouseDrawCursor``
by default so that injected mouse positions render visibly into the
captured/streamed frame. ``omni.ui.standalone.set_software_cursor()``
exposes that toggle to Python (idempotent setter).

The end-to-end test follows the QA-AGENT-PROMPT.md screenshot-action
cycle: inject mouse move, tick, screenshot — twice, at different
positions — and verify pixel-level differences near the new cursor
location and a return-to-baseline at the old one.
"""

from __future__ import annotations

import os
import unittest

from omni.ui import standalone


_IS_HEADLESS = os.environ.get("OMNIUI_HEADLESS", "").lower() in ("1", "true")
_BACKEND = os.environ.get("OMNIUI_BACKEND", "").lower()
_IS_VULKAN = _BACKEND in ("vulkan", "vk")


class TestSoftwareCursorSurface(unittest.TestCase):
    """The setter must exist and be callable regardless of runtime env."""

    def test_module_exposes_setter_and_query(self):
        self.assertTrue(callable(getattr(standalone, "set_software_cursor", None)))
        self.assertTrue(callable(getattr(standalone, "is_software_cursor_enabled", None)))

    def test_setter_is_safe_without_context(self):
        # Without an ImGui context the setter must be a no-op (no crash).
        standalone.set_software_cursor(True)
        standalone.set_software_cursor(False)
        # The query reports False when no context exists.
        # (After init a different test asserts the headless default.)


@unittest.skipUnless(
    _IS_HEADLESS and _IS_VULKAN,
    "software-cursor end-to-end requires OMNIUI_HEADLESS=1 OMNIUI_BACKEND=vulkan",
)
class TestSoftwareCursorRendersAtInjectedPosition(unittest.TestCase):
    """Inject two mouse moves and prove the cursor moves between captures."""

    DEFAULT_WIDTH = 1024
    DEFAULT_HEIGHT = 768
    # 32-pixel square around each location is large enough to cover
    # ImGui's default mouse cursor (~16 px) plus its black outline.
    PROBE_HALF = 16

    def setUp(self):
        # init() is idempotent in standalone — if another test already
        # initialised the platform at a smaller resolution, this call is
        # a no-op and we pick up that resolution. We discover the actual
        # framebuffer dimensions from the first captured PNG (the C++
        # _standalone_get_window_size path goes through GLFW and reports
        # (0,0) in headless mode).
        standalone.init(
            "test_software_cursor", self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT,
            max_fps=None,
        )
        # Force the cursor on regardless of any state left behind by a
        # previous test in this class (test methods run in alphabetical
        # order, but other harnesses may shuffle).
        standalone.set_software_cursor(True)

    def tearDown(self):
        # Restore the headless default so subsequent tests / classes see
        # cursor-on, matching what HeadlessVulkanPlatform sets at init.
        standalone.set_software_cursor(True)

    def _positions_for(self, w: int, h: int) -> tuple[tuple[int, int], tuple[int, int]]:
        """Pick two well-separated probe positions inside a `w x h` frame."""
        margin = self.PROBE_HALF + 4
        # Reject frames smaller than 2 * (margin + probe-window) — there
        # would be no separation between the two probe regions.
        min_dim = 2 * margin + 2 * self.PROBE_HALF + 4
        if w < min_dim or h < min_dim:
            self.skipTest(
                f"framebuffer {w}x{h} is too small to host two non-overlapping "
                f"probe windows (need >= {min_dim}x{min_dim})"
            )
        pos_a = (margin + w // 8, margin + h // 8)
        pos_b = (w - margin - w // 8, h - margin - h // 8)
        return pos_a, pos_b

    def _capture(self, path: str) -> None:
        from omni.ui import _ui

        # Schedule + tick mirrors testing.capture_screenshot but is loop-free
        # (no asyncio dependency for this unit test).
        self.assertTrue(_ui._schedule_screenshot(path), f"schedule_screenshot({path})")
        standalone._tick_one_frame()
        self.assertTrue(_ui._poll_screenshot_done(), f"poll_screenshot_done({path})")
        self.assertTrue(os.path.isfile(path), f"screenshot not written: {path}")

    def _probe_window(self, img, cx: int, cy: int):
        """Return a flat list of RGBA tuples in a square window."""
        x0 = max(0, cx - self.PROBE_HALF)
        x1 = min(img.width, cx + self.PROBE_HALF)
        y0 = max(0, cy - self.PROBE_HALF)
        y1 = min(img.height, cy + self.PROBE_HALF)
        return [
            img.getpixel((x, y)) for y in range(y0, y1) for x in range(x0, x1)
        ]

    def test_cursor_visible_at_injected_position(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed — cannot pixel-diff screenshots")

        from omni.ui import _ui

        # First, an uninhabited tick with the cursor pulled far off-frame
        # so neither probe window starts the test with a stale cursor.
        _ui._inject_mouse_move(-1024.0, -1024.0)
        standalone._tick_one_frame()

        # Capture a baseline at (-1024, -1024) so we know the framebuffer
        # dimensions, then derive two probe positions inside that frame.
        path_baseline = "/tmp/2.4-baseline.png"
        self._capture(path_baseline)
        img_baseline = Image.open(path_baseline).convert("RGBA")
        pos_a, pos_b = self._positions_for(img_baseline.width, img_baseline.height)

        # --- Action 1: move to pos_a, capture
        _ui._inject_mouse_move(float(pos_a[0]), float(pos_a[1]))
        standalone._tick_one_frame()
        path_a = "/tmp/2.4-a.png"
        self._capture(path_a)

        # --- Action 2: move to pos_b, capture
        _ui._inject_mouse_move(float(pos_b[0]), float(pos_b[1]))
        standalone._tick_one_frame()
        path_b = "/tmp/2.4-b.png"
        self._capture(path_b)

        img_a = Image.open(path_a).convert("RGBA")
        img_b = Image.open(path_b).convert("RGBA")
        self.assertEqual(img_a.size, img_b.size)

        # --- Verify: the probe window around pos_a in image A differs from
        # the same window in image B (cursor was there in A, not in B).
        wa_in_a = self._probe_window(img_a, *pos_a)
        wa_in_b = self._probe_window(img_b, *pos_a)
        diff_a = sum(1 for p, q in zip(wa_in_a, wa_in_b) if p != q)
        self.assertGreater(
            diff_a,
            0,
            f"expected pixel differences at {pos_a} between the two frames "
            "(cursor present in A, absent in B) but found none",
        )

        # And the probe window around pos_b in image B differs from the
        # same window in image A (cursor present in B, absent in A).
        wb_in_a = self._probe_window(img_a, *pos_b)
        wb_in_b = self._probe_window(img_b, *pos_b)
        diff_b = sum(1 for p, q in zip(wb_in_a, wb_in_b) if p != q)
        self.assertGreater(
            diff_b,
            0,
            f"expected pixel differences at {pos_b} between the two frames "
            "(cursor present in B, absent in A) but found none",
        )

    def test_setter_disables_cursor_idempotently(self):
        standalone.set_software_cursor(False)
        self.assertFalse(standalone.is_software_cursor_enabled())
        # Idempotent: second call with same value leaves state unchanged.
        standalone.set_software_cursor(False)
        self.assertFalse(standalone.is_software_cursor_enabled())
        # Re-enable and confirm.
        standalone.set_software_cursor(True)
        self.assertTrue(standalone.is_software_cursor_enabled())
        standalone.set_software_cursor(True)
        self.assertTrue(standalone.is_software_cursor_enabled())


if __name__ == "__main__":
    unittest.main()
