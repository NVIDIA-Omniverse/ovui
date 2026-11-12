# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ovstage values in the form that the installed ovstage uses.

A newer ovstage gives tokens and prim paths as handle objects. A handle has
its number in ``raw_id``, refuses ``int()``, and is the only accepted
argument. A newer read group holds several columns that share its prims.
A previous ovstage uses plain integers and one attribute in each read group.
The adapter keeps numbers and the previous group form; these functions make
the conversion at the calls into ovstage.
"""

from __future__ import annotations

import sys
from typing import Any, Iterable, Iterator


def handle_number(value: Any) -> int:
    """Return the number of a handle object or of a plain integer."""

    raw_id = getattr(value, "raw_id", None)
    return int(value if raw_id is None else raw_id)


def _native(owner: Any, kind: str, value: Any) -> Any:
    # The handle types belong to the package of the object that takes the value.
    package = type(owner).__module__.partition(".")[0]
    handle_type = getattr(sys.modules.get(package), kind, None)
    number = handle_number(value)
    return number if handle_type is None else handle_type(number)


def native_token(owner: Any, value: Any) -> Any:
    """Return ``value`` as a token argument of ``owner``, an ovstage stage or dictionary."""

    return _native(owner, "Token", value)


def native_prim_path(owner: Any, value: Any) -> Any:
    """Return ``value`` as a prim path argument of ``owner``, an ovstage stage or dictionary."""

    return _native(owner, "PrimPath", value)


class _ColumnGroup:
    """One column of a newer read group, in the form of a previous read group.

    The column gives the attribute and its values; the group gives the prims.
    """

    __slots__ = ("_group", "_column", "_last")

    def __init__(self, group: Any, column: Any, last: bool) -> None:
        self._group = group
        self._column = column
        self._last = last

    @property
    def attribute(self) -> int:
        return handle_number(self._column.attribute)

    def __getattr__(self, name: str) -> Any:
        try:
            return getattr(self._column, name)
        except AttributeError:
            return getattr(self._group, name)


def read_groups(groups: Iterable[Any]) -> Iterator[Any]:
    """Yield the read groups of ``groups`` in the form of a previous ovstage.

    A newer group gives one item for each of its columns. Release each item
    with :func:`release_read_group`; the group is released after its last
    column. A group that has no columns, or whose columns are not all
    released when the iteration stops, is released here.
    """

    for group in groups:
        columns = getattr(group, "columns", None)
        if columns is None:
            yield group
            continue
        if not columns:
            group.release()
            continue
        try:
            for index, column in enumerate(columns):
                yield _ColumnGroup(group, column, index == len(columns) - 1)
        finally:
            if not group.released:
                group.release()


def release_read_group(stage: Any, group: Any) -> Any:
    """Release ``group`` of :func:`read_groups` on ``stage``."""

    if not isinstance(group, _ColumnGroup):
        return stage.release_group(group)
    if group._last and not group._group.released:
        return stage.release_group(group._group)
    return None
