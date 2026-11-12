# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Whole-GPU waits during a rebuild of many byte images.

A button that rebuilds an image grid releases every drawn texture and uploads
replacements inside one frame. On Vulkan each ``vkDeviceWaitIdle`` of the
image code also waits for the present thread, so a wait for every texture
copy froze the window for seconds. The released textures must be freed after
one wait at the end of the frame.

The Vulkan image code reports each such wait as a native timing scope, so the
test counts the scopes with a timing table built in Python with ``ctypes``.
Other backends have no such wait and report none.
"""

from __future__ import annotations

import ctypes
import unittest

import omni.ui as ui
from test_base import OmniUiTest

CAPSULE_NAME = b"omni.ui.native_timing_hooks"
HOOKS_VERSION = 1
WAIT_SCOPE = b"VulkanByteImageGpu.vkDeviceWaitIdle [ovui debug]"

_PyCapsule_New = ctypes.pythonapi.PyCapsule_New
_PyCapsule_New.restype = ctypes.py_object
_PyCapsule_New.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p]

_BeginScope = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32))
_EndScope = ctypes.CFUNCTYPE(None, ctypes.c_uint32)


class NativeTimingHooks(ctypes.Structure):
    """Same layout as omni::ui::standalone::NativeTimingHooks."""

    _fields_ = [
        ("structSize", ctypes.c_uint32),
        ("version", ctypes.c_uint32),
        ("beginScope", _BeginScope),
        ("endScope", _EndScope),
        ("beginRenderThreadScope", ctypes.c_void_p),
        ("endRenderThreadScope", ctypes.c_void_p),
        ("beginPhase", ctypes.c_void_p),
        ("endPhase", ctypes.c_void_p),
    ]


class TestByteImageProviderDeviceWaits(OmniUiTest):
    async def test_rebuild_inside_a_frame_does_not_wait_for_the_gpu_per_texture(self):
        count = 100
        frames = 3
        waits = []

        def begin_scope(name, cached_id):
            if name == WAIT_SCOPE:
                waits.append(name)
            return False

        hooks = NativeTimingHooks(
            ctypes.sizeof(NativeTimingHooks), HOOKS_VERSION, _BeginScope(begin_scope), _EndScope(lambda _: None)
        )

        def make_providers(seed):
            providers = []
            for index in range(count):
                provider = ui.ByteImageProvider()
                provider.set_bytes_data([seed, index * 2, 30, 255] * 16, [4, 4])
                providers.append(provider)
            return providers

        old = make_providers(200)
        new = []

        def rebuild():
            # Runs while the frame that has drawn ``old`` is built.
            for provider in old:
                provider.destroy()
            new.extend(make_providers(40))

        window = await self.create_test_window(256, 256)
        with window.frame:
            with ui.VStack():
                with ui.VGrid(column_width=8, row_height=8, height=0):
                    for provider in old:
                        ui.ImageWithProvider(provider, width=8, height=8)
                trigger = ui.Frame(build_fn=lambda: None)
        await self.wait_n_updates(2)

        ui._ui._set_native_timing_hooks(_PyCapsule_New(ctypes.byref(hooks), CAPSULE_NAME, None))
        try:
            trigger.set_build_fn(rebuild)
            trigger.rebuild()
            await self.wait_n_updates(frames)
        finally:
            ui._ui._set_native_timing_hooks(None)

        self.assertEqual(sum(provider.is_reference_valid for provider in new), count)
        # At most one wait for each frame; one for each texture copy froze the window.
        self.assertLessEqual(len(waits), frames)
        await self.finalize_test_no_image()


if __name__ == "__main__":
    unittest.main()
