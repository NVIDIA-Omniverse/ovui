# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""PropertyPayload — selection value object for the property window.

property metadata behavior / §4.3.7: a thin wrapper around the selected paths plus a scheme
label. Carries the minimum state PropertyWindow / PropertyWidget need to
decide which sub-widgets to build and provides a helper that delegates
shared-attribute computation to a PropertyAdapter.

Introduced by Step 0.2 of the property inspector implementation. No callsite wiring yet — later
steps (notably 7.4 large-selection gate, 6.5 PropertySchemeRegistry) will
switch PropertyWindow over from its raw ``List[str]`` selection.
"""

from typing import Iterator, List, Sequence


class PropertyPayload:
    """Immutable-ish carrier of selected paths + scheme for the property window."""

    def __init__(self, paths: Sequence[str], scheme: str = "default") -> None:
        self._paths: List[str] = list(paths)
        self._scheme: str = scheme

    @property
    def paths(self) -> List[str]:
        return list(self._paths)

    def get_scheme(self) -> str:
        return self._scheme

    def is_large_selection(self, threshold: int = 100) -> bool:
        return len(self._paths) >= threshold

    def compute_shared_attrs(self, adapter: object) -> List[str]:
        """Return attribute names shared across the payload's selection.

        Delegates to the adapter's existing ``get_attribute_names()`` (which
        already performs multi-selection intersection per property metadata behavior). The
        adapter is expected to be constructed against the same paths this
        payload holds; PropertyPayload does not enforce that here.
        """
        return list(adapter.get_attribute_names())  # type: ignore[attr-defined]

    def __bool__(self) -> bool:
        return bool(self._paths)

    def __len__(self) -> int:
        return len(self._paths)

    def __iter__(self) -> Iterator[str]:
        return iter(self._paths)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PropertyPayload):
            return NotImplemented
        return self._paths == other._paths and self._scheme == other._scheme

    def __hash__(self) -> int:
        return hash((tuple(self._paths), self._scheme))

    def __repr__(self) -> str:
        return f"PropertyPayload(paths={self._paths!r}, scheme={self._scheme!r})"
