# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Thread rule of image providers from Python (issue 227).

A Python render thread gives frames with ``publish_on_ui_thread``. The ovui
frame runs them on the UI thread before the draw, so the drawn image is the
newest frame. A change that raises is reported through ``sys.unraisablehook``
and the next change still runs. The changes run once per frame, before
anything is drawn: a scene image drawn before an ``ImageWithProvider`` sees the
same change. A setter called on the render thread is
counted by ``ImageProvider.off_ui_thread_call_count()`` and still made; the
back end decides whether it can upload on that thread (Vulkan can; OpenGL
uploads only on the thread of its GL context), and the upload result says what
it did.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import threading

import numpy as np
import omni.ui as ui
from omni.ui import _ui
from test_base import OmniUiTest

_SIZE = 64


def _frame(rgba):
    frame = np.zeros((8, 8, 4), dtype=np.uint8)
    frame[...] = rgba
    return frame


class TestImageProviderThreads(OmniUiTest):
    async def _show(self, provider):
        window = await self.create_test_window(_SIZE, _SIZE)
        with window.frame:
            ui.ImageWithProvider(provider, width=_SIZE, height=_SIZE)
        # The first frames make this thread the UI thread.
        await self.wait_n_updates(2)
        return window

    async def _center_pixel(self):
        return (await self._pixels([(_SIZE // 2, _SIZE // 2)]))[0]

    async def _pixels(self, points):
        """The pixels at ``points`` of the next frame."""
        with tempfile.TemporaryDirectory() as tmp:
            capture = pathlib.Path(tmp) / "capture.png"
            self.assertTrue(_ui._schedule_screenshot(str(capture)), "screenshot request was refused")
            for _ in range(10):
                await self.wait_n_updates(1)
                if _ui._poll_screenshot_done() and capture.exists():
                    break
            self.assertTrue(capture.exists(), "screenshot was not written")

            from PIL import Image

            with Image.open(capture) as img:
                rgb = img.convert("RGB")
                return [rgb.getpixel(point) for point in points]

    async def test_render_thread_frames_run_on_the_ui_thread(self):
        provider = ui.ByteImageProvider()
        provider.set_data_array(_frame((0, 0, 255, 255)), [8, 8])
        _window = await self._show(provider)
        ui_thread = threading.get_ident()
        reported_before = ui.ImageProvider.off_ui_thread_call_count()
        ran = []

        def give(rgba):
            def change(p):
                ran.append((rgba, threading.get_ident()))
                p.set_data_array(_frame(rgba), [8, 8])

            return provider.publish_on_ui_thread(change, replace_pending=True)

        ids = []
        render = threading.Thread(target=lambda: ids.extend(give(c) for c in ((0, 255, 0, 255), (255, 0, 0, 255))))
        render.start()
        render.join()
        self.assertEqual(ids, [1, 2])
        self.assertEqual(ran, [], "nothing runs on the render thread")

        await self.wait_n_updates(2)
        self.assertEqual(ran, [((255, 0, 0, 255), ui_thread)], "only the newest frame runs, once, on the UI thread")
        self.assertEqual(provider.applied_publication_id, 2)
        self.assertEqual(ui.ImageProvider.off_ui_thread_call_count(), reported_before, "nothing is reported")
        self.assertEqual(await self._center_pixel(), (255, 0, 0), "the newest frame is drawn")

    async def test_changes_run_once_per_frame_before_drawing(self):
        from omni.ui_scene import scene as sc

        provider = ui.ByteImageProvider()
        provider.set_data_array(_frame((0, 0, 255, 255)), [8, 8])
        window = await self.create_test_window(2 * _SIZE, _SIZE)
        with window.frame:
            with ui.HStack():
                # The scene image is drawn before the ImageWithProvider of the same provider.
                scene_view = sc.SceneView(aspect_ratio_policy=sc.AspectRatioPolicy.STRETCH, width=_SIZE, height=_SIZE)
                with scene_view.scene:
                    sc.Image(provider, width=2, height=2)
                ui.ImageWithProvider(provider, width=_SIZE, height=_SIZE)
        await self.wait_n_updates(2)
        points = [(_SIZE // 2, _SIZE // 2), (_SIZE + _SIZE // 2, _SIZE // 2)]
        self.assertEqual(await self._pixels(points), [(0, 0, 255), (0, 0, 255)])

        def red_then_green(p):
            p.set_data_array(_frame((255, 0, 0, 255)), [8, 8])
            # Given while the pass runs: it waits for the next frame.
            p.publish_on_ui_thread(lambda q: q.set_data_array(_frame((0, 255, 0, 255)), [8, 8]))

        provider.publish_on_ui_thread(red_then_green)
        self.assertEqual(await self._pixels(points), [(255, 0, 0), (255, 0, 0)],
                         "in the next frame both images show the first change, and only it")
        await self.wait_n_updates(2)
        self.assertEqual(await self._pixels(points), [(0, 255, 0), (0, 255, 0)], "then both show the second change")

    async def test_failing_change_is_reported_and_the_next_runs(self):
        provider = ui.ByteImageProvider()
        provider.set_data_array(_frame((0, 0, 255, 255)), [8, 8])
        _window = await self._show(provider)
        unraisable = []
        old_hook = sys.unraisablehook
        sys.unraisablehook = unraisable.append
        try:

            def fail(_p):
                raise RuntimeError("change failed on purpose")

            render = threading.Thread(
                target=lambda: (
                    provider.publish_on_ui_thread(fail),
                    provider.publish_on_ui_thread(lambda p: p.set_data_array(_frame((0, 255, 0, 255)), [8, 8])),
                )
            )
            render.start()
            render.join()
            await self.wait_n_updates(2)
        finally:
            sys.unraisablehook = old_hook
        self.assertEqual(len(unraisable), 1)
        self.assertIsInstance(unraisable[0].exc_value, RuntimeError)
        self.assertEqual(provider.applied_publication_id, 2, "the change after the failing one ran")
        self.assertEqual(await self._center_pixel(), (0, 255, 0))

    async def test_setter_on_another_thread_is_counted_and_made(self):
        provider = ui.ByteImageProvider()
        provider.set_data_array(_frame((0, 0, 255, 255)), [8, 8])
        _window = await self._show(provider)
        before = ui.ImageProvider.off_ui_thread_call_count()
        failures_before = provider.upload_failure_count
        render = threading.Thread(target=lambda: provider.set_data_array(_frame((255, 0, 0, 255)), [8, 8]))
        render.start()
        render.join()
        self.assertEqual(ui.ImageProvider.off_ui_thread_call_count(), before + 1, "the call is counted")
        # A release build makes the call; the back end decides whether it can upload on that thread.
        result = provider.last_upload_result
        await self.wait_n_updates(2)
        if result.accepted:
            self.assertEqual(provider.upload_failure_count, failures_before)
            self.assertEqual(await self._center_pixel(), (255, 0, 0), "an accepted upload is drawn")
        else:
            self.assertIsNotNone(result.cause, "a refused upload names its cause")
            self.assertEqual(provider.upload_failure_count, failures_before + 1)
            self.assertEqual(await self._center_pixel(), (0, 0, 255), "a refused upload keeps the previous image")
        provider.set_data_array(_frame((0, 255, 0, 255)), [8, 8])
        self.assertEqual(ui.ImageProvider.off_ui_thread_call_count(), before + 1, "a call on the UI thread is not counted")
        await self.wait_n_updates(2)
        self.assertEqual(await self._center_pixel(), (0, 255, 0), "the provider still takes changes on the UI thread")
