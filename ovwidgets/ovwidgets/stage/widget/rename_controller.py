# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""RenameController — inline rename with 500ms single-click delay.

RenameController handles inline rename timing and styling hooks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from ovui_data_adapters.common import StageAdapter

    from ovwidgets.stage.widget.hierarchy_model import HierarchyItem, HierarchyModel
    from ovwidgets.stage.widget.stage_delegate import StageDelegate


class RenameController:
    """Manages inline rename lifecycle: click timer, F2, commit, cancel."""

    RENAME_DELAY_MS = 500

    def __init__(
        self,
        adapter: "StageAdapter",
        model: "HierarchyModel",
        delegate: "StageDelegate",
        call_later: Optional[Callable] = None,
    ) -> None:
        self._adapter = adapter
        self._model = model
        self._delegate = delegate
        # Optional ``call_later`` injection (Rev 8 §5.5 + Plan Rev 2 §4
        # Step 5). Defaults to :func:`ovwidgets.common.scheduler.call_later`
        # so production callers go through the registered application
        # scheduler. Tests can pass a synchronous stub instead — the
        # request_rename_on_click site is RAISE-classified (no try/except)
        # because in production the scheduler is always registered before
        # a delegate click can fire.
        self._call_later: Callable = call_later if call_later is not None else _default_call_later
        self._pending_item: "HierarchyItem | None" = None
        self._timer: Optional[Any] = None
        self._active_item: "HierarchyItem | None" = None

    def request_rename_on_click(self, item: "HierarchyItem") -> None:
        """Start 500ms timer for an already-selected item click."""
        if not self._adapter.can_rename(item.adapter_item):
            return
        self._cancel_timer()
        self._pending_item = item
        self._timer = self._call_later(
            self.RENAME_DELAY_MS / 1000.0,
            lambda: self._begin_rename(item),
        )

    def request_rename_f2(self, item: "HierarchyItem") -> None:
        """Immediate rename via F2 key."""
        if not self._adapter.can_rename(item.adapter_item):
            return
        self._cancel_timer()
        self._begin_rename(item)

    def _begin_rename(self, item: "HierarchyItem") -> None:
        """Switch the name column row to a StringField for editing."""
        self._active_item = item
        self._delegate.set_rename_mode(item, True)
        self._model._item_changed(item)

    def commit_rename(self, new_name: str) -> None:
        """Commit the rename. Called when the user presses Enter."""
        if not self._active_item:
            return
        name = new_name.strip()
        current = self._adapter.get_display_name(self._active_item.adapter_item)
        if name and name != current:
            self._adapter.rename(self._active_item.adapter_item, name)
        self._end_rename()

    def cancel_rename(self) -> None:
        """Abort the rename without changes. Called on Escape or focus loss."""
        self._end_rename()

    def _end_rename(self) -> None:
        if self._active_item:
            self._delegate.set_rename_mode(self._active_item, False)
            self._model._item_changed(self._active_item)
            self._active_item = None

    def cancel_pending_timer(self) -> None:
        """Cancel any pending rename timer. Called when a drag starts."""
        self._cancel_timer()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._pending_item = None


def _default_call_later(delay_secs: float, callback: Callable) -> Any:
    """Default scheduler used when no ``call_later`` is injected.

    Lazy-imports :mod:`ovwidgets.common.scheduler` so the
    ``RenameController`` module body has no module-top runtime
    dependency on ``common.scheduler`` (matters for
    headless / static-analysis test imports).
    """
    from ovwidgets.common import scheduler as _scheduler
    return _scheduler.call_later(delay_secs, callback)
