# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Frontend-neutral content file-operation policies.

The service owns duplicate-name generation and batch duplicate behavior over
neutral file records plus backend contracts. Context menus, dialogs,
progress/status UI, OS-native file browser integration, and OS clipboard
integration stay with the frontend.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Protocol, Sequence, Tuple

from ovui_data_adapters.services.content.backends import (
    BackendAdapter,
    BackendResult,
)


@dataclass(frozen=True)
class ContentFileRecord:
    """Toolkit-neutral file-operation identity record."""

    url: str
    name: str
    is_folder: bool = False


class ContentFileRecordProtocol(Protocol):
    """Structural input accepted by file-operation services."""

    url: str
    name: str
    is_folder: bool


_COPY_SUFFIX_RE = re.compile(r" Copy(?: (\d+))?$")
_COPY_TEMPLATE_BASE = "{stem} Copy{ext}"
_COPY_TEMPLATE_N = "{stem} Copy {n}{ext}"


def _split_name(name: str, is_folder: bool) -> Tuple[str, str]:
    """Return ``(stem, ext)`` honoring folder vs file semantics."""
    if is_folder:
        return name, ""
    return os.path.splitext(name)


def _next_copy_name(
    name: str, is_folder: bool, existing_names: set[str],
) -> str:
    """Return a fresh ``" Copy"``-suffixed name that does not collide."""
    stem, ext = _split_name(name, is_folder)
    match = _COPY_SUFFIX_RE.search(stem)
    if match is not None:
        stripped_stem = stem[: match.start()]
        initial_n = int(match.group(1)) if match.group(1) else 1
        candidate_n = initial_n + 1
    else:
        stripped_stem = stem
        candidate_n = 1

    while True:
        if candidate_n == 1:
            candidate = _COPY_TEMPLATE_BASE.format(
                stem=stripped_stem, ext=ext,
            )
        else:
            candidate = _COPY_TEMPLATE_N.format(
                stem=stripped_stem, ext=ext, n=candidate_n,
            )
        if candidate not in existing_names:
            return candidate
        candidate_n += 1


def next_copy_name(
    name: str, is_folder: bool, existing_names: set[str],
) -> str:
    """Public alias for duplicate-name generation policy."""
    return _next_copy_name(name, is_folder, existing_names)


def duplicate_items(
    backend: BackendAdapter,
    items: Sequence[ContentFileRecordProtocol],
    refresh_parent_fn: Optional[Callable[[str], None]] = None,
) -> Tuple[int, List[Tuple[str, str]]]:
    """Duplicate file records into their parent folder.

    The batch keeps going after per-item failures and returns
    ``(success_count, errors)`` where each error is
    ``(source_url, result_name)``. ``refresh_parent_fn`` is called once per
    parent with at least one successful duplicate.
    """
    if not items:
        return 0, []

    success_count = 0
    errors: List[Tuple[str, str]] = []
    refreshed_parents: List[str] = []
    siblings_by_parent: dict[str, set[str]] = {}

    for item in items:
        src_url = item.url
        parent_url = backend.parent_url(src_url)
        if parent_url is None:
            errors.append((src_url, BackendResult.ERROR_NOT_SUPPORTED.name))
            continue

        if parent_url not in siblings_by_parent:
            result, entries = backend.list_dir(parent_url)
            if result == BackendResult.OK:
                siblings_by_parent[parent_url] = {entry.name for entry in entries}
            else:
                errors.append((src_url, result.name))
                continue

        existing = siblings_by_parent[parent_url]
        new_name = _next_copy_name(item.name, item.is_folder, existing)
        dst_url = backend.join_url(parent_url, new_name)
        copy_result = backend.copy(src_url, dst_url, overwrite=False)
        if copy_result != BackendResult.OK:
            errors.append((src_url, copy_result.name))
            continue

        success_count += 1
        existing.add(new_name)
        if parent_url not in refreshed_parents:
            refreshed_parents.append(parent_url)

    if refresh_parent_fn is not None:
        for parent_url in refreshed_parents:
            refresh_parent_fn(parent_url)

    return success_count, errors


__all__ = [
    "ContentFileRecord",
    "ContentFileRecordProtocol",
    "duplicate_items",
    "next_copy_name",
]
