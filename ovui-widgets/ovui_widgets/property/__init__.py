# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovui_widgets.property: property inspector window + stackable widget base.

Public exports:
    PropertyPayload — property metadata behavior payload value object.
    PropertyWindow  — property window scheme behavior dockable property inspector window
                      (formerly ``PropertyWidget``; renamed in
                      the property inspector step 6.1).
    PropertyWidget  — DEPRECATED alias for :class:`PropertyWindow`.
                      Preserved for one release cycle so existing
                      callers (notably
                      :class:`ovui_widgets.app.application.Application`) don't
                      break. New code should import the abstract
                      widget base from
                      :mod:`ovui_widgets.property.widget` instead.
"""

from ovui_widgets.property.payload import PropertyPayload
from ovui_widgets.property.provider_hooks import (
    PropertyProviderBinding,
    PropertyProviderContribution,
    PropertyProviderDescriptor,
    PropertyProviderHandle,
    PropertyProviderRegistry,
    PropertyProviderRow,
    ProviderPropertyWidget,
)
from ovui_widgets.property.window import PropertyWindow

# DEPRECATED: Step 6.1 renamed PropertyWidget (the window) to
# PropertyWindow. The name ``PropertyWidget`` is now reserved for the
# abstract stackable widget base in :mod:`ovui_widgets.property.widget`; this
# top-level compat alias keeps ``from ovui_widgets.property import PropertyWidget``
# resolving to the window class so Application.create_windows() keeps
# instantiating the docked panel. Remove after one release cycle.
PropertyWidget = PropertyWindow

__all__ = [
    "PropertyPayload",
    "PropertyProviderBinding",
    "PropertyProviderContribution",
    "PropertyProviderDescriptor",
    "PropertyProviderHandle",
    "PropertyProviderRegistry",
    "PropertyProviderRow",
    "PropertyWindow",
    "PropertyWidget",
    "ProviderPropertyWidget",
]
