# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Test-only probe: does this computer have a Vulkan device?

Tests that draw frames with ``omni.ui.standalone`` in headless Vulkan mode
need one. The probe asks the Vulkan loader directly and never starts ovui, so
a broken ovui start still fails the test.
A software device such as lavapipe counts: these tests do not need a GPU.

The filename intentionally does **not** start with ``test_`` so pytest
does not try to collect it as a test module.
"""

from __future__ import annotations

import ctypes
import functools
import os
import sys

import pytest

_VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO = 1
_VK_SUCCESS = 0
_VK_ERROR_INCOMPATIBLE_DRIVER = -9


class _InstanceCreateInfo(ctypes.Structure):
    _fields_ = [
        ("sType", ctypes.c_uint32),
        ("pNext", ctypes.c_void_p),
        ("flags", ctypes.c_uint32),
        ("pApplicationInfo", ctypes.c_void_p),
        ("enabledLayerCount", ctypes.c_uint32),
        ("ppEnabledLayerNames", ctypes.c_void_p),
        ("enabledExtensionCount", ctypes.c_uint32),
        ("ppEnabledExtensionNames", ctypes.c_void_p),
    ]


def _load_loader() -> ctypes.CDLL:
    if sys.platform == "win32":
        vulkan_dir = os.environ.get("Vulkan_DLL_DIR")
        if vulkan_dir:
            return ctypes.CDLL(os.path.join(vulkan_dir, "vulkan-1.dll"))
        return ctypes.CDLL("vulkan-1.dll")
    if sys.platform == "darwin":
        return ctypes.CDLL("libvulkan.1.dylib")
    return ctypes.CDLL("libvulkan.so.1")


@functools.lru_cache(maxsize=1)
def missing_vulkan_device() -> str:
    """Return why this computer has no Vulkan device, or ``""`` if it has one.

    Only a missing loader, a missing driver or a successful enumeration of
    zero devices is an answer about the hardware. Any other Vulkan error fails
    the calling test (rule 7.6).
    """
    try:
        loader = _load_loader()
    except OSError as exc:
        return f"no Vulkan loader: {exc}"
    create = loader.vkCreateInstance
    create.restype = ctypes.c_int32
    create.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    enumerate_devices = loader.vkEnumeratePhysicalDevices
    enumerate_devices.restype = ctypes.c_int32
    enumerate_devices.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    destroy = loader.vkDestroyInstance
    destroy.restype = None
    destroy.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    info = _InstanceCreateInfo(sType=_VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO)
    instance = ctypes.c_void_p()
    result = create(ctypes.byref(info), None, ctypes.byref(instance))
    if result == _VK_ERROR_INCOMPATIBLE_DRIVER:
        return "no Vulkan driver (vkCreateInstance: VK_ERROR_INCOMPATIBLE_DRIVER)"
    if result != _VK_SUCCESS:
        # A loader with a driver that fails is not a missing device.
        pytest.fail(f"vkCreateInstance failed: VkResult {result}")
    try:
        count = ctypes.c_uint32(0)
        result = enumerate_devices(instance, ctypes.byref(count), None)
    finally:
        destroy(instance, None)
    if result != _VK_SUCCESS:
        pytest.fail(f"vkEnumeratePhysicalDevices failed: VkResult {result}")
    if count.value == 0:
        return "no Vulkan physical device"
    return ""


def use_headless_vulkan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the next ``standalone.init`` use headless Vulkan, or skip the test.

    Earlier tests in the same process can already set ``OMNIUI_HEADLESS``, so
    the mode is set here explicitly. Headless Vulkan has no OpenGL fallback:
    without a Vulkan device there is nothing to draw with, and the test skips.
    """
    reason = missing_vulkan_device()
    if reason:
        pytest.skip(reason)
    monkeypatch.setenv("OMNIUI_HEADLESS", "1")
    monkeypatch.delenv("OMNIUI_HEADLESS_GL", raising=False)
