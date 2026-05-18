# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""In-process clipboard state for cut / copy / paste (the content browser implementation step 35).

See the content browser behavior (``Clipboard``). The clipboard is
deliberately a **pure module-level state bag**, not a class:

* The state is process-global. Two open content-browser windows share
  one clipboard — a cut selection in window A must render the "cut"
  style on the same URLs in window B. A module is the simplest
  representation of that one-per-process contract.
* A class would need a singleton plus a back-edge from
  :class:`FileCard` (Step 38 applies the ``::Cut`` style variant from
  clipboard state) into the widget layer. Keeping this a leaf module
  with no widget imports means :mod:`file_card` can import
  :mod:`clipboard` in Step 38 without a circular dependency.

V1 is **process-local only**. No OS clipboard integration — Kit's
clipboard semantics are internal (architecture §11: "Why not OS
clipboard?"). Copy-to-text of a URL string is a separate helper
landing with Step 37's ``Copy URL`` menu entry.

This module is not wired to any caller yet:

* Step 36 wires Copy / Cut / Paste into :class:`FileContextMenu`.
* Step 38 wires the ``::Cut`` style variant into :class:`FileCard` via
  :func:`is_path_cut`.
"""

from __future__ import annotations

from typing import List

# ── Module state ────────────────────────────────────────────────────────────
#
# Kept module-private; the only sanctioned read/write path is via the
# public functions below. Tests reach in via the public surface too —
# no test imports ``_clipboard_urls`` directly.

_clipboard_urls: List[str] = []
_is_cut: bool = False


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
    global _is_cut
    _clipboard_urls[:] = list(urls)
    _is_cut = bool(is_cut)


def get_clipboard_urls() -> List[str]:
    """Return a fresh copy of the current clipboard URLs.

    A **copy** so callers can iterate / mutate without disturbing the
    module state. The returned list preserves the insertion order
    :func:`save_to_clipboard` recorded — Paste iterates in that order
    so multi-selection Paste is deterministic.

    Returns an empty list when the clipboard is empty.
    """
    return list(_clipboard_urls)


def is_clipboard_cut() -> bool:
    """Return ``True`` if the clipboard holds a Cut (vs. Copy) selection.

    Meaningless when the clipboard is empty; callers that care about
    "is there anything to paste?" should combine this with a non-empty
    :func:`get_clipboard_urls` check (see Step 36's Paste-enable gate).
    """
    return _is_cut


def is_path_cut(url: str) -> bool:
    """Return ``True`` if ``url`` is currently in the clipboard **and** cut.

    The card render path (Step 38) will call this per-item to decide
    whether to apply the faded ``::Cut`` style. A Copy selection
    therefore never triggers the style variant — by design: Copy
    leaves the source card looking normal because the source is not
    being removed.
    """
    if not _is_cut:
        return False
    return url in _clipboard_urls


def clear_clipboard() -> None:
    """Empty the clipboard and reset the cut flag.

    Called after a successful Cut + Paste so the source cards drop
    their ``::Cut`` style (there is no longer a pending move). Copy +
    Paste does **not** clear — repeat-paste of the same Copy is a
    standard affordance.

    Idempotent — clearing an already-empty clipboard is a no-op.
    """
    global _is_cut
    _clipboard_urls.clear()
    _is_cut = False
