# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Pure-Python coverage for ``_backend_tag()`` in ``tests/test_base.py``.

The helper is a tiny env-var classifier that decides which golden-image
subdirectory a screenshot test will compare against. It is consumed by
the test base in a follow-up commit; this module exercises it in
isolation against synthesised env dicts so that the classifier itself
can be regression-tested without spinning up the omni.ui backend.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

from test_base import _backend_tag


# ---------------------------------------------------------------------------
# Env-vars touched by _backend_tag(); restored after every case.
# ---------------------------------------------------------------------------
_ENV_KEYS = ("OMNIUI_HEADLESS", "OMNIUI_HEADLESS_GL", "OMNIUI_BACKEND")


@contextmanager
def _env(values: dict[str, str | None]):
    """Temporarily set/clear the env vars _backend_tag() reads."""
    saved = {k: os.environ.get(k) for k in _ENV_KEYS}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

def test_backend_tag_vulkan_headless():
    with _env({"OMNIUI_HEADLESS": "1", "OMNIUI_HEADLESS_GL": None, "OMNIUI_BACKEND": None}):
        assert _backend_tag() == "vulkan"


def test_backend_tag_vulkan_via_backend_env():
    """OMNIUI_BACKEND=vulkan alone (no OMNIUI_HEADLESS) still classifies as vulkan."""
    with _env({"OMNIUI_HEADLESS": None, "OMNIUI_HEADLESS_GL": None, "OMNIUI_BACKEND": "vulkan"}):
        assert _backend_tag() == "vulkan"


def test_backend_tag_vulkan_via_backend_env_vk_alias():
    """OMNIUI_BACKEND=vk is accepted by the runtime (StandaloneInit.cpp:1285)
    and must classify as vulkan in the test helper too."""
    with _env({"OMNIUI_HEADLESS": None, "OMNIUI_HEADLESS_GL": None, "OMNIUI_BACKEND": "vk"}):
        assert _backend_tag() == "vulkan"


def test_backend_tag_vulkan_headless_truthy_string():
    with _env({"OMNIUI_HEADLESS": "true", "OMNIUI_HEADLESS_GL": None, "OMNIUI_BACKEND": None}):
        assert _backend_tag() == "vulkan"


def test_backend_tag_egl():
    with _env({"OMNIUI_HEADLESS": "1", "OMNIUI_HEADLESS_GL": "1", "OMNIUI_BACKEND": None}):
        assert _backend_tag() == "egl"


def test_backend_tag_egl_takes_priority_over_vulkan_backend_env():
    """Even with OMNIUI_BACKEND=vulkan, headless+headless_gl picks egl."""
    with _env({"OMNIUI_HEADLESS": "1", "OMNIUI_HEADLESS_GL": "1", "OMNIUI_BACKEND": "vulkan"}):
        assert _backend_tag() == "egl"


def test_backend_tag_opengl_default():
    with _env({"OMNIUI_HEADLESS": None, "OMNIUI_HEADLESS_GL": None, "OMNIUI_BACKEND": None}):
        assert _backend_tag() == "opengl"


def test_backend_tag_opengl_explicit_backend():
    with _env({"OMNIUI_HEADLESS": None, "OMNIUI_HEADLESS_GL": None, "OMNIUI_BACKEND": "opengl"}):
        assert _backend_tag() == "opengl"


def test_backend_tag_headless_gl_without_headless_falls_through():
    """OMNIUI_HEADLESS_GL=1 without OMNIUI_HEADLESS=1 is not 'egl' — it
    falls through the headless gate and ends up classified by
    OMNIUI_BACKEND (here: opengl, since BACKEND is unset)."""
    with _env({"OMNIUI_HEADLESS": None, "OMNIUI_HEADLESS_GL": "1", "OMNIUI_BACKEND": None}):
        assert _backend_tag() == "opengl"


def test_backend_tag_current_test_env_is_vulkan():
    """The pytest baseline runs with OMNIUI_HEADLESS=1 and
    OMNIUI_BACKEND=vulkan; confirm the tag matches in that real env."""
    if os.environ.get("OMNIUI_HEADLESS") in ("1", "true") and not os.environ.get(
        "OMNIUI_HEADLESS_GL"
    ):
        assert _backend_tag() == "vulkan"
    else:
        # Sanity: helper returned something from the documented set.
        assert _backend_tag() in ("vulkan", "egl", "opengl")
