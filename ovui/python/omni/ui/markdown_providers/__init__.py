# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Optional provider plugins for MarkdownWidget.

The native widget has a C++ provider interface for performance-sensitive
integrations.  This package provides Python workflow plugins that can be used
today with ``set_image_url_provider_fn`` and source pre-processing, plus a
stable Python-side abstract class (:class:`PythonAssetProvider`) that will
shortly be backed by a pybind11 trampoline for ``IMarkdownAssetProvider``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .core import (
    DEFAULT_CACHE_DIR,
    AsyncProviderPlugin,
    MarkdownProviderChain,
    MarkdownProviderRequest,
    MarkdownProviderResult,
    stable_digest,
)
from .document import MarkdownProviderDocumentRenderer
from .http import HttpImageProviderPlugin, SSRFError
from .math import MathJaxProviderPlugin
from .mermaid import MermaidCliProviderPlugin
from .resolver import MarkdownAssetResolver
from .svg import SvgRasterProviderPlugin


@dataclass(frozen=True)
class PythonAssetRequest:
    """Shape that mirrors C++ ``MarkdownAssetRequest``.

    TODO: will be replaced by the pybind11-bound
    ``omni.ui._ui.MarkdownAssetRequest`` once the binding lands.  Kept here as
    a vanilla dataclass so downstream plugin authors can target a stable
    Python shape today.
    """

    kind: str = "raster_image"
    source: str = ""
    language: str = ""
    alt_text: str = ""
    title: str = ""
    max_display_width: float = 0.0
    font_size: float = 14.0
    device_scale: float = 1.0
    inline_asset: bool = False
    dark_theme: bool = False
    style_hash: int = 0
    document_generation: int = 0


@dataclass(frozen=True)
class PythonAssetResult:
    """Shape that mirrors C++ ``MarkdownAssetResult``.

    Python providers should use the pixel bytes path.  GPU texture lifetime
    must be owned by the widget / renderer -- Python cannot safely hold
    ImGui texture IDs across frames.

    TODO: will be replaced by the pybind11-bound
    ``omni.ui._ui.MarkdownAssetResult`` once the binding lands.
    """

    state: str = "unsupported"  # one of {unsupported, pending, ready, failed}
    # Pixel bytes path.  ``pixels`` is bytes-like; when non-empty the widget
    # uploads via its normal image path.
    pixels: bytes = b""
    pixel_width: int = 0
    pixel_height: int = 0
    pixel_format: str = "rgba8_unorm"
    width: float = 0.0
    height: float = 0.0
    baseline: float = 0.0
    error: str = ""
    extras: Mapping[str, Any] = field(default_factory=dict)


class PythonAssetProvider(ABC):
    """Abstract Python side of the eventual pybind11 trampoline.

    TODO: will be replaced by a pybind11 binding that wraps
    ``IMarkdownAssetProvider``.  The Python API surface is pinned now so
    downstream subclasses work before and after the binding lands -- the
    binding will forward ``request`` / ``tick`` / ``cancel_generation`` into
    this same contract.

    Thread safety
    -------------
    * ``request`` may be called from any thread (the C++ widget currently
      calls it from the render thread; pybind11 will acquire the GIL before
      entering Python).  Implementations must be thread-safe against
      themselves.
    * ``tick`` is always called from the UI / render thread.
    * ``cancel_generation`` is called from the render thread when the widget
      reparses new source text.
    """

    @abstractmethod
    def request(self, request: PythonAssetRequest) -> PythonAssetResult:
        """Return current status for ``request``.

        Must not block on network, subprocess, or GPU work.  Return
        ``state='pending'`` while background work is in flight; return
        ``state='ready'`` with populated ``pixels`` once available.
        """

    def tick(self) -> None:
        """Per-frame pump.  Default is a no-op."""

    def cancel_generation(self, generation: int) -> None:
        """Drop any pending work tied to an obsolete document generation."""
        _ = generation


__all__ = [
    "DEFAULT_CACHE_DIR",
    "AsyncProviderPlugin",
    "HttpImageProviderPlugin",
    "MarkdownAssetResolver",
    "MarkdownProviderChain",
    "MarkdownProviderDocumentRenderer",
    "MarkdownProviderRequest",
    "MarkdownProviderResult",
    "MathJaxProviderPlugin",
    "MermaidCliProviderPlugin",
    "PythonAssetProvider",
    "PythonAssetRequest",
    "PythonAssetResult",
    "SSRFError",
    "SvgRasterProviderPlugin",
    "stable_digest",
]
