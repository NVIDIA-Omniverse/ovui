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
Standalone equivalent of the Kit OmniUiTest base class.

Replaces Kit-specific imports (carb, omni.kit.test, omni.appwindow) with
the ovui backend.  Tests inherit from
``unittest.IsolatedAsyncioTestCase`` so that ``async def test_*`` methods
work out of the box with pytest (via pytest-asyncio) or plain unittest.
"""
__all__ = ["OmniUiTest"]

import asyncio
import os
import pathlib
import shutil
import struct
import unittest

import omni.ui as ui
from omni.ui import standalone


# ---------------------------------------------------------------------------
# Standard directory layout for golden image testing
# ---------------------------------------------------------------------------

_TESTS_DIR = pathlib.Path(__file__).resolve().parent
GOLDEN_DIR = _TESTS_DIR / "golden"
CAPTURED_DIR = _TESTS_DIR / "captured"


# ---------------------------------------------------------------------------
# Screenshot helpers
# ---------------------------------------------------------------------------

def _backend_tag() -> str:
    """Return the active backend as a short string tag.

    The tag selects which sibling golden directory under ``tests/golden/``
    a test compares against:

    - ``"vulkan"`` — headless Vulkan compositor (OMNIUI_HEADLESS=1)
    - ``"egl"``    — headless EGL surfaceless GL (OMNIUI_HEADLESS=1 +
                     OMNIUI_HEADLESS_GL=1)
    - ``"opengl"`` — desktop GLFW + OpenGL (default developer flow)

    The two Vulkan-related env vars must agree about which capture API
    works, so the matrix is intentionally small. ``OMNIUI_BACKEND=vulkan``
    (or its ``vk`` alias) without ``OMNIUI_HEADLESS=1`` (a configuration
    nobody currently exercises) is still classified as ``"vulkan"``
    because the capture path it would take is the Vulkan one — it never
    falls back to GL.
    """
    headless = os.environ.get("OMNIUI_HEADLESS") in ("1", "true")
    headless_gl = os.environ.get("OMNIUI_HEADLESS_GL") in ("1", "true")
    backend = os.environ.get("OMNIUI_BACKEND", "").lower()

    if headless and headless_gl:
        return "egl"
    if headless:
        return "vulkan"
    if backend in ("vulkan", "vk"):
        return "vulkan"
    return "opengl"


def _is_vulkan_backend() -> bool:
    """Backwards-compat shim — prefer ``_backend_tag()`` in new code."""
    return _backend_tag() == "vulkan"


def _try_read_pixels(width: int, height: int) -> bytes | None:
    """Try to capture the framebuffer via OpenGL glReadPixels.

    Returns RGBA bytes or None if PyOpenGL is not available.
    """
    try:
        from OpenGL.GL import glReadPixels, GL_RGBA, GL_UNSIGNED_BYTE
        data = glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE)
        return bytes(data)
    except Exception:
        return None


def _save_screenshot(path: pathlib.Path, width: int, height: int, rgba_bytes: bytes) -> None:
    """Save raw RGBA bytes as a PNG file.  Requires Pillow."""
    try:
        from PIL import Image
        img = Image.frombytes("RGBA", (width, height), rgba_bytes)
        img = img.transpose(Image.FLIP_TOP_BOTTOM)  # OpenGL origin is bottom-left
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(path))
    except ImportError:
        # Pillow not available -- silently skip
        pass


# ---------------------------------------------------------------------------
# Base test class
# ---------------------------------------------------------------------------

class OmniUiTest(unittest.IsolatedAsyncioTestCase):
    """Standalone equivalent of Kit's OmniUiTest.

    Provides the same core methods:
      * ``create_test_window()``
      * ``wait_n_updates()``
      * ``finalize_test()``
      * ``finalize_test_no_image()``

    The standalone backend is initialised once per test-run and each test
    gets a fresh ``ui.Window`` positioned at (0, 0).
    """

    MEAN_ERROR_THRESHOLD = 0.01
    MEAN_ERROR_SQUARED_THRESHOLD = 1e-5
    THRESHOLD = MEAN_ERROR_THRESHOLD

    # Set by subclasses or via env var OMNI_UI_GOLDEN_DIR
    GOLDEN_IMG_DIR: pathlib.Path | None = None

    # Class-level flag so we only init once across all tests
    _backend_initialized: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def _ensure_backend(cls) -> None:
        if not cls._backend_initialized:
            # Initialise big enough to contain the largest test area any
            # currently ported test requests; individual tests shrink the
            # window via ``standalone.set_window_size`` in ``create_test_area``.
            standalone.init("OmniUiTest", 1024, 1024)
            cls._backend_initialized = True

    async def asyncSetUp(self) -> None:
        self._ensure_backend()
        self._test_window: ui.Window | None = None
        self._need_finalize = False

    async def asyncTearDown(self) -> None:
        if self._need_finalize:
            await self.finalize_test_no_image()

    # ------------------------------------------------------------------
    # Core helpers
    # ------------------------------------------------------------------

    @property
    def _test_name(self) -> str:
        return f"{self.__class__.__name__}.{self._testMethodName}"

    async def wait_n_updates(self, n: int = 3) -> None:
        """Pump *n* frames through the standalone backend.

        Each tick sleeps 15 ms real time so that ClickGesture's
        ``singleClickWait`` threshold (default 10 ms) is reliably exceeded
        between the release frame and the frame that fires the callback.
        """
        for _ in range(n):
            standalone._tick_one_frame()
            await asyncio.sleep(0.015)

    async def next_frame(self) -> None:
        """Single-frame step (convenience wrapper)."""
        standalone._tick_one_frame()
        await asyncio.sleep(0.015)

    async def create_test_area(self, width: int = 256, height: int = 256) -> None:
        """Resize the OS window so its framebuffer matches the requested area.

        Stores the requested size for screenshot capture.  The backend must
        render at exactly the requested size — this is what Kit's
        ``omni.kit.test.OmniUiTest`` guarantees, and golden images are
        generated against that size.
        """
        self._area_width = width
        self._area_height = height
        standalone.set_window_size(width, height)
        # One tick lets GLFW's framebuffer callbacks fire so subsequent
        # draws use the new viewport/DisplaySize.
        await self.wait_n_updates(1)
        self._need_finalize = True

    async def create_test_window(
        self,
        width: int = 256,
        height: int = 256,
        block_devices: bool = True,
        window_flags=None,
    ) -> ui.Window:
        """Create a test window filling the standalone area.

        Returns:
            ``ui.Window`` with black background, ready for testing.
        """
        await self.create_test_area(width, height)

        if window_flags is None:
            window_flags = (
                ui.WINDOW_FLAGS_NO_SCROLLBAR
                | ui.WINDOW_FLAGS_NO_TITLE_BAR
                | ui.WINDOW_FLAGS_NO_RESIZE
            )

        self._test_window = ui.Window(
            f"{self._test_name} Test",
            dockPreference=ui.DockPreference.DISABLED,
            flags=window_flags,
            width=width,
            height=height,
            position_x=0,
            position_y=0,
        )
        self._test_window.frame.set_style(
            {"Window": {"background_color": 0xFF000000, "border_color": 0x0, "border_radius": 0}}
        )
        self._need_finalize = True

        # Pump a couple of frames so the window is laid out.
        await self.wait_n_updates(2)

        return self._test_window

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    async def finalize_test_no_image(self) -> None:
        """Restore state after a test -- no screenshot comparison."""
        if self._test_window is not None:
            self._test_window.destroy()
            self._test_window = None
        self._need_finalize = False

    async def finalize_test(
        self,
        threshold: float | None = None,
        golden_img_dir: pathlib.Path | None = None,
        golden_img_name: str | None = None,
        cmp_metric=None,
        **kwargs,
    ) -> None:
        """Pump frames, capture screenshot, compare with golden image.

        Directory layout::

            tests/golden/<backend_tag>/<ImageName>.png  -- reference images
                                                           (vulkan/, egl/, opengl/)
            tests/captured/<ImageName>.png              -- latest capture
            tests/captured/diff_<ImageName>.png         -- amplified diff (on failure)

        Reads tolerate a legacy untagged golden at ``tests/golden/<ImageName>.png``
        as a transitional fallback when no tagged baseline exists yet. Writes
        (first-run promotion or ``OMNI_UI_GENERATE_GOLDEN=1`` regeneration)
        always target the backend-tagged path, never the legacy root.
        """
        from compare_utils import CompareMetric

        # Pump a few frames to ensure all layout is settled.
        await self.wait_n_updates(4)

        # OMNI_UI_SKIP_GOLDEN_TESTS=1 disables image-comparison entirely:
        # B2 sets it because ASan instrumentation perturbs the rasterizer's
        # float math enough to drift comparisons; B3 sets it (transitionally)
        # while tests/golden/egl/ is empty. Render still runs — only the
        # capture-and-compare half is skipped — so the compositor stays in
        # ASan's scope.
        if os.environ.get("OMNI_UI_SKIP_GOLDEN_TESTS", "").strip() == "1":
            import pytest
            await self.finalize_test_no_image()
            pytest.skip("golden comparison disabled by OMNI_UI_SKIP_GOLDEN_TESTS=1")

        if threshold is None:
            threshold = self.MEAN_ERROR_THRESHOLD
        if cmp_metric is None:
            cmp_metric = CompareMetric.MEAN_ERROR

        # Determine golden root directory
        golden_root = golden_img_dir or self.GOLDEN_IMG_DIR
        env_dir = os.environ.get("OMNI_UI_GOLDEN_DIR")
        if golden_root is None and env_dir:
            golden_root = pathlib.Path(env_dir)
        if golden_root is None:
            golden_root = GOLDEN_DIR
        golden_root = pathlib.Path(golden_root)

        # Backend-specific subdirectory (vulkan/, egl/, opengl/). Different
        # rasterizers, sampler defaults, and AA paths produce subtly
        # different pixels so each backend gets its own baselines.
        golden_dir = golden_root / _backend_tag()
        golden_dir.mkdir(parents=True, exist_ok=True)

        captured_dir = CAPTURED_DIR
        captured_dir.mkdir(parents=True, exist_ok=True)

        name = golden_img_name or f"{self._test_name}.png"
        # Reads prefer the backend-tagged location and fall back to the
        # legacy untagged path during migration. Writes (first-run promotion
        # and OMNI_UI_GENERATE_GOLDEN=1) always target the tagged path so
        # regeneration cannot resurrect the legacy layout.
        tagged_path = golden_dir / name
        legacy_path = golden_root / name
        golden_write_path = tagged_path
        if tagged_path.exists() or not legacy_path.exists():
            golden_read_path = tagged_path
        else:
            golden_read_path = legacy_path
        captured_path = captured_dir / name
        diff_path = captured_dir / f"diff_{name}"

        # Capture at the actual framebuffer size -- we asked the backend to
        # resize earlier, so the GL default framebuffer should match.
        fb_w, fb_h = standalone.get_window_size()
        width = fb_w if fb_w > 0 else getattr(self, "_area_width", 256)
        height = fb_h if fb_h > 0 else getattr(self, "_area_height", 256)

        # Headless platforms enable ImGui's software-rendered cursor so that
        # streamed/captured frames show the mouse — useful interactively but
        # noise in golden images. Disable it for the duration of capture and
        # restore after, so tests that explicitly exercise cursor visibility
        # (e.g. tests/test_software_cursor.py) keep working.
        prev_cursor = standalone.is_software_cursor_enabled()
        try:
            if prev_cursor:
                standalone.set_software_cursor(False)
                # Pump a frame so ImGui re-renders without drawing the cursor
                # before we grab the framebuffer.
                await self.wait_n_updates(1)
            await self._capture_and_compare_golden(
                captured_path=captured_path,
                golden_read_path=golden_read_path,
                golden_write_path=golden_write_path,
                diff_path=diff_path,
                width=width,
                height=height,
                threshold=threshold,
                cmp_metric=cmp_metric,
            )
        finally:
            if prev_cursor:
                standalone.set_software_cursor(True)

        await self.finalize_test_no_image()

    async def _capture_and_compare_golden(
        self,
        *,
        captured_path: pathlib.Path,
        golden_read_path: pathlib.Path,
        golden_write_path: pathlib.Path,
        diff_path: pathlib.Path,
        width: int,
        height: int,
        threshold: float,
        cmp_metric,
    ) -> None:
        """Capture the framebuffer and (regenerate or compare) the golden.

        Split out of ``finalize_test`` so the surrounding cursor-toggle
        try/finally stays tight and the compare logic is unaffected by it.
        """
        from compare_utils import compare

        captured_ok = False
        if _is_vulkan_backend():
            # No GL context → schedule a pre-swap capture that the platform
            # writes to disk itself (it handles Vulkan readback).
            from omni.ui import _ui
            captured_path.parent.mkdir(parents=True, exist_ok=True)
            if _ui._schedule_screenshot(str(captured_path)):
                await self.wait_n_updates(1)
                # Poll a couple more frames in case the compositor lags.
                for _ in range(5):
                    if _ui._poll_screenshot_done():
                        captured_ok = True
                        break
                    await self.wait_n_updates(1)
                # Fall back to "assume written" if the flag was cleared by a
                # previous test — the file itself is the authoritative signal.
                if not captured_ok:
                    captured_ok = captured_path.exists()
            # Headless Vulkan's offscreen image is always the init-time size
            # (1024x1024); set_window_size doesn't resize the FBO. Crop the
            # PNG down to the test's requested area so it can be compared
            # against goldens generated at that size.
            if captured_ok and captured_path.exists():
                try:
                    from PIL import Image
                    img = Image.open(str(captured_path))
                    req_w = getattr(self, "_area_width", width)
                    req_h = getattr(self, "_area_height", height)
                    if img.size != (req_w, req_h):
                        cropped = img.crop((0, 0, req_w, req_h))
                        cropped.save(str(captured_path))
                except Exception:
                    pass
        else:
            rgba = _try_read_pixels(width, height)
            if rgba is not None:
                _save_screenshot(captured_path, width, height, rgba)
                captured_ok = True

        if captured_ok:

            generate = os.environ.get("OMNI_UI_GENERATE_GOLDEN", "").strip() == "1"
            strict = os.environ.get("OMNI_UI_GOLDEN_STRICT", "").strip() == "1"

            if not golden_read_path.exists():
                # CI sets OMNI_UI_GOLDEN_STRICT=1 to forbid silent baseline
                # generation; OMNI_UI_GENERATE_GOLDEN=1 is the explicit opt-in
                # to (re)create the golden even under strict mode.
                if strict and not generate:
                    raise AssertionError(
                        f"Golden reference missing in strict mode: {golden_write_path}"
                    )
                golden_write_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(captured_path), str(golden_write_path))
                print(f"[golden] Generated: {golden_write_path}")
            elif generate:
                golden_write_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(captured_path), str(golden_write_path))
                print(f"[golden] Regenerated: {golden_write_path}")
            else:
                # Compare captured against golden
                diff_val = compare(
                    golden_read_path, captured_path, diff_path,
                    threshold=threshold, cmp_metric=cmp_metric,
                )
                if diff_val >= threshold:
                    self.fail(
                        f"Golden image mismatch for {self._test_name}: "
                        f"error={diff_val:.6f} >= threshold={threshold} "
                        f"(metric={cmp_metric})"
                    )
