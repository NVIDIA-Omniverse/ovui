# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Session-level pytest fixtures.

Forces a clean process exit once pytest has reported its results.

The standalone backend's GLFW + Vulkan + CUDA-GL interop stack tears
down in an order that glibc reports as a heap double-free during
interpreter shutdown (after every test has already passed). The crash
originates inside ``libGLX.so.0`` and is not caused by any single test
— removing the most-recently-added cursor or streaming tests still
reproduces it.

There is no Python-level fix for the destructor ordering, so we cut
the process off at ``pytest_sessionfinish``: once pytest has tallied
its results and the exit status is success, we flush stdio and
``os._exit`` with that status. This skips Python interpreter shutdown
(and therefore the C++ ``__attribute__((destructor))`` chain) entirely.
"""

from __future__ import annotations

import ctypes
import os
import sys

import pytest


def _is_opengl_backend() -> bool:
    """True when the active backend exposes a real OpenGL context.

    Mirrors the env logic of ``tests/test_base._backend_tag()`` without
    depending on it (conftest is loaded before ``tests/`` is on
    ``sys.path``).

    - Pure headless Vulkan (``OMNIUI_HEADLESS=1`` without
      ``OMNIUI_HEADLESS_GL``) → no GL; ``requires_gl`` skipped.
    - Headless EGL surfaceless (``OMNIUI_HEADLESS=1`` +
      ``OMNIUI_HEADLESS_GL=1``) → real GL context via EGL;
      ``requires_gl`` runs.
    - ``OMNIUI_BACKEND=vulkan|vk`` (windowed Vulkan, currently unused) →
      no GL.
    - Otherwise developer-flow GLFW + OpenGL → GL available.
    """
    if os.environ.get("OMNIUI_HEADLESS", "").lower() in ("1", "true"):
        if os.environ.get("OMNIUI_HEADLESS_GL", "").lower() in ("1", "true"):
            return True
        return False
    if os.environ.get("OMNIUI_BACKEND", "").lower() in ("vulkan", "vk"):
        return False
    return True


def _have_libcudart() -> bool:
    """True when ``libcudart.so`` is loadable in-process."""
    try:
        ctypes.CDLL("libcudart.so")
        return True
    except OSError:
        return False


def _is_headless_mode() -> bool:
    """True when standalone init takes the headless path (no GLFW platform).

    The streaming pipeline is wired through ``s_glfwPlatform`` in
    ``StandaloneInit.cpp``; under ``OMNIUI_HEADLESS=1`` that pointer is
    null and ``_init_streaming`` hard-fails. EGL-surfaceless headless
    still has a real GL context (so ``requires_gl`` runs there), but
    streaming-specific tests must skip — hence the separate marker.
    """
    return os.environ.get("OMNIUI_HEADLESS", "").lower() in ("1", "true")


def pytest_collection_modifyitems(config, items) -> None:
    """Auto-skip tests whose marker preconditions are not met.

    - ``requires_gl``   skipped under headless Vulkan / headless EGL.
    - ``requires_glfw`` skipped under any ``OMNIUI_HEADLESS=1`` run.
    - ``requires_cuda`` skipped when libcudart.so cannot be loaded.

    Skipped items keep their marker so collectors / reports can still
    distinguish them from environment-independent skips.
    """
    skip_gl = pytest.mark.skip(
        reason="requires_gl: no OpenGL context (headless Vulkan without OMNIUI_HEADLESS_GL=1)"
    )
    skip_glfw = pytest.mark.skip(
        reason="requires_glfw: no GLFW platform under OMNIUI_HEADLESS=1 (streaming pipeline unavailable)"
    )
    skip_cuda = pytest.mark.skip(
        reason="requires_cuda: libcudart.so not loadable in this environment"
    )
    gl_ok = _is_opengl_backend()
    cuda_ok = _have_libcudart()
    headless = _is_headless_mode()
    for item in items:
        if "requires_gl" in item.keywords and not gl_ok:
            item.add_marker(skip_gl)
        if "requires_glfw" in item.keywords and headless:
            item.add_marker(skip_glfw)
        if "requires_cuda" in item.keywords and not cuda_ok:
            item.add_marker(skip_cuda)


@pytest.fixture(scope="session", autouse=True)
def _disable_core_dumps() -> None:
    """Cap core-dump size at 0 bytes for this pytest session.

    ovui CI runners ship with ~14 GiB of free disk; a single native
    crash from the GL/Vulkan stack can dump a multi-gigabyte core file
    and exhaust the disk before pytest reports. Capping ``RLIMIT_CORE``
    here suppresses that. ``ulimit -c 0`` in the workflow covers the
    parent shell; this fixture runs once per pytest session — and once
    per ``pytest --forked`` child, because pytest-forked re-runs the
    session-scoped fixture chain inside the forked subprocess after the
    fork.

    The ``resource`` module is POSIX-only, so the import is done inside
    the fixture and ``ImportError`` is swallowed alongside the usual
    ``ValueError``/``OSError`` to keep collection working on Windows.
    """
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, ValueError, OSError):
        # Hard limit may already be 0, the platform may not expose
        # ``resource`` (Windows), or the platform may not support
        # adjusting it from this process. Either way, we tried.
        pass


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config) -> None:
    if getattr(config.option, "collectonly", False):
        return
    session = getattr(config, "_pytest_session_exitstatus", None)
    if session is not None and session != 0:
        return
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus: int) -> None:
    session.config._pytest_session_exitstatus = exitstatus
