# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Compatibility path for content-browser internal clipboard state.

The reusable clipboard state object now lives in
``ovui_data_adapters.services.content.clipboard``. This module keeps the
historical process-global ovui_widgets clipboard instance used by content
browser widgets and cut-row styling.
"""

from __future__ import annotations

from typing import List

from ovui_data_adapters.services.content.clipboard import ContentClipboard

_clipboard = ContentClipboard()


# ── Public API ──────────────────────────────────────────────────────────────


def save_to_clipboard(urls: List[str], is_cut: bool = False) -> None:
    """Replace the clipboard contents with ``urls``.

    Stores a **copy** of ``urls`` so caller-side mutation of the input
    list does not leak into clipboard state. Overwrites any previous
    clipboard — Copy and Cut are mutually exclusive; there is no append mode.

    ``is_cut=True`` marks the URLs as a Cut selection. Cards pointing
    at these URLs should render the ``::Cut`` style variant (Step 38).
    ``is_cut=False`` marks them as a Copy selection — no visual change
    on the source cards.

    An empty ``urls`` list is accepted and is equivalent to a clear.
    """
    _clipboard.save_to_clipboard(urls, is_cut=is_cut)


def get_clipboard_urls() -> List[str]:
    """Return a fresh copy of the current clipboard URLs.

    A **copy** so callers can iterate / mutate without disturbing the
    module state. The returned list preserves the insertion order
    :func:`save_to_clipboard` recorded — Paste iterates in that order
    so multi-selection Paste is deterministic.

    Returns an empty list when the clipboard is empty.
    """
    return _clipboard.get_clipboard_urls()


def is_clipboard_cut() -> bool:
    """Return ``True`` if the clipboard holds a Cut (vs. Copy) selection.

    Meaningless when the clipboard is empty; callers that care about
    "is there anything to paste?" should combine this with a non-empty
    :func:`get_clipboard_urls` check (see Step 36's Paste-enable gate).
    """
    return _clipboard.is_clipboard_cut()


def is_path_cut(url: str) -> bool:
    """Return ``True`` if ``url`` is currently in the clipboard **and** cut.

    The card render path (Step 38) will call this per-item to decide
    whether to apply the faded ``::Cut`` style. A Copy selection
    therefore never triggers the style variant — by design: Copy
    leaves the source card looking normal because the source is not
    being removed.
    """
    return _clipboard.is_path_cut(url)


def clear_clipboard() -> None:
    """Empty the clipboard and reset the cut flag.

    Called after a successful Cut + Paste so the source cards drop
    their ``::Cut`` style (there is no longer a pending move). Copy +
    Paste does **not** clear — repeat-paste of the same Copy is a
    standard affordance.

    Idempotent — clearing an already-empty clipboard is a no-op.
    """
    _clipboard.clear_clipboard()


__all__ = [
    "clear_clipboard",
    "get_clipboard_urls",
    "is_clipboard_cut",
    "is_path_cut",
    "save_to_clipboard",
]
