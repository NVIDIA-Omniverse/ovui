# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""``PropertySchemeDelegate`` — per-payload widget-visibility contract.

property window scheme behavior / the property inspector step 6.6 / the property inspector behavior
Abstract base for objects registered via
:meth:`PropertySchemeRegistry.register_scheme_delegate`. A delegate
answers two questions for a given :class:`PropertyPayload`:

* Which named property widgets *must* appear? (:meth:`get_widgets`)
* Which named property widgets must *not* appear? (:meth:`get_unwanted_widgets`)

Multiple delegates coexist per scheme. The registry unions every
delegate's outputs on each :meth:`~PropertySchemeRegistry.get_widgets_for_payload`
call and filters the registered-widget list accordingly — with the rule
that *wanted wins over unwanted* (a widget explicitly named by any
delegate's :meth:`get_widgets` survives even if another delegate's
:meth:`get_unwanted_widgets` names it). This precedence matters because
Kit's bundle extension registers one delegate per prim-type group and
a prim-type delegate may suppress generic widgets — the bundle layout
decides who wins by controlling which delegate names a widget first.

The "no delegates registered" case is a no-op: both union sets are
empty, so the registry's filter condition
``name in wanted or name not in unwanted`` reduces to ``True`` for
every widget and Step 6.5's catch-all behaviour survives intact.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from ovwidgets.property.payload import PropertyPayload


class PropertySchemeDelegate(ABC):
    """Decides which named property widgets show for a given payload.

    Register an instance via
    :meth:`PropertySchemeRegistry.register_scheme_delegate`. The
    registry calls :meth:`get_widgets` and :meth:`get_unwanted_widgets`
    on every :meth:`~PropertySchemeRegistry.get_widgets_for_payload`
    invocation — so the returned lists can vary with the payload
    (common use: a prim-type delegate returns different widget names
    for ``Mesh`` vs ``DomeLight`` payloads).

    Both methods are abstract: delegate authors must explicitly think
    about both the additive (wanted) and subtractive (unwanted) sides
    of visibility. A delegate that only contributes wanted names
    returns ``[]`` from :meth:`get_unwanted_widgets`; a delegate that
    only hides widgets returns ``[]`` from :meth:`get_widgets`.
    """

    @abstractmethod
    def get_widgets(self, payload: "PropertyPayload") -> List[str]:
        """Return names of widgets that must appear for ``payload``.

        A name in this list overrides any other delegate's
        :meth:`get_unwanted_widgets` entry for the same name — so
        listing a widget here is the strongest signal a delegate can
        emit. Names that do not match any registered widget are
        silently ignored by the registry (they reserve no slot).
        """

    @abstractmethod
    def get_unwanted_widgets(self, payload: "PropertyPayload") -> List[str]:
        """Return names of widgets that must not appear for ``payload``.

        A name in this list is suppressed unless another delegate's
        :meth:`get_widgets` names it — wanted-wins precedence applies
        across the whole delegate set for the scheme. Names that do
        not match any registered widget are silently ignored.
        """
