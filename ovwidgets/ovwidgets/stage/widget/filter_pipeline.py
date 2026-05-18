# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""FilterPipeline for Stage Browser hierarchy filtering."""

from typing import Any, Callable


class FilterPipeline:
    """Pipeline of filter predicates for stage hierarchy filtering."""

    def __init__(self) -> None:
        self._predicates: list = []

    def add_predicate(self, predicate: Callable[..., bool]) -> None:
        """Add a filter predicate: fn(adapter, item) -> bool."""
        self._predicates.append(predicate)

    def passes(self, adapter: Any, item: Any) -> bool:
        """Returns True if item passes all predicates."""
        return all(p(adapter, item) for p in self._predicates)

    def clear(self) -> None:
        """Remove all predicates."""
        self._predicates.clear()

    @property
    def is_active(self) -> bool:
        return len(self._predicates) > 0


def make_name_filter(text: str) -> Callable[..., bool]:
    """Case-insensitive substring match on display name."""
    lower = text.lower()

    def predicate(adapter: Any, item: Any) -> bool:
        return lower in adapter.get_display_name(item).lower()

    return predicate
