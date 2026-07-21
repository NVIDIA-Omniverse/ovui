# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Selection adapter for the registered ovstage provider."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, List

from ovui_data_adapters.common import AdapterItem, SelectionAdapter

from ovui_data_adapters.ovstage._errors import raise_not_ready


class OvstageSelectionAdapter(SelectionAdapter):
    """Translate path-based application selection into ovstage adapter items."""

    def __init__(self, scene: Any | None = None, stage_adapter: Any | None = None) -> None:
        self._scene = scene
        self._stage_adapter = stage_adapter

    def to_adapter_items(self, selection: Any) -> List[AdapterItem]:
        paths = self._extract_paths(selection)
        if not paths:
            return []
        stage_adapter = self._require_stage_adapter()
        items: list[AdapterItem] = []
        for path in paths:
            try:
                item = stage_adapter.get_item_at_path(path)
            except (KeyError, NotImplementedError, ValueError):
                continue
            if item is not None:
                items.append(item)
        return items

    def to_selection_items(self, adapter_items: List[AdapterItem]) -> List[Any]:
        if not adapter_items:
            return []
        stage_adapter = self._require_stage_adapter()
        paths: list[str] = []
        for item in adapter_items:
            try:
                path = stage_adapter.get_item_path(item)
            except Exception:
                continue
            try:
                current_item = stage_adapter.get_item_at_path(path)
            except (KeyError, NotImplementedError, ValueError):
                continue
            if current_item is item:
                paths.append(path)
        return paths

    def _require_stage_adapter(self) -> Any:
        if self._stage_adapter is None:
            raise_not_ready("selection path lookup")
        return self._stage_adapter

    @classmethod
    def _extract_paths(cls, selection: Any) -> list[str]:
        if selection is None:
            return []
        if isinstance(selection, str):
            return [selection]
        paths_method = getattr(selection, "paths", None)
        if callable(paths_method):
            return [str(path) for path in paths_method()]
        items = getattr(selection, "items", None)
        if items is not None:
            return cls._extract_paths(items)
        path = cls._path_from_record(selection)
        if path is not None:
            return [path]
        if isinstance(selection, Iterable):
            paths: list[str] = []
            for entry in selection:
                entry_path = cls._path_from_record(entry)
                if entry_path is not None:
                    paths.append(entry_path)
            return paths
        return []

    @staticmethod
    def _path_from_record(record: Any) -> str | None:
        if isinstance(record, str):
            return record
        path = getattr(record, "path", None)
        if path is not None:
            return str(path)
        if isinstance(record, dict) and "path" in record:
            return str(record["path"])
        return None
