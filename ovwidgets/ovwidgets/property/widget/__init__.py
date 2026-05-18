# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Stackable property-widget base + built-in concrete widgets.

property widget stack behavior / the property inspector phase 6. The widgets that stack inside
:class:`ovwidgets.property.window.PropertyWindow` all subclass the abstract
:class:`PropertyWidget` exported here.

* Step 6.1 shipped the abstract base.
* Step 6.2 shipped :class:`AttributesWidget` — the catch-all that
  renders every attribute for the current selection.
* Step 6.3 shipped :class:`SimplePropertyWidget` — convenience base
  with ``CollapsableFrame`` + filter-subscription + ``request_rebuild``
  scaffolding; :class:`AttributesWidget` is now rebased on top of it.
* Step 6.4 shipped :class:`SchemaPropertyWidget` — schema-gated
  auto-discovery widget with ``_filter_props_to_build`` and
  ``_customize_props_layout`` customisation hooks.
* Step 6.5 shipped :class:`PropertySchemeRegistry` — singleton that
  :class:`PropertyWindow` queries at rebuild time to decide which
  widgets to show for the current payload's scheme.
* Step 6.6 shipped :class:`PropertySchemeDelegate` — the ABC that
  drives per-payload widget visibility;
  :meth:`PropertySchemeRegistry.get_widgets_for_payload` now unions
  every delegate's wanted / unwanted name lists and filters the
  candidate widget list accordingly (wanted wins over unwanted).
* Step 7.3 shipped :class:`ScrollPreserver` — save/restore
  ``ui.ScrollingFrame.scroll_y`` across :class:`PropertyWindow`
  rebuilds. Preserves when the new payload's scheme matches the
  prior payload's; resets to 0 otherwise.

The top-level :mod:`ovwidgets.property` package also exports a *deprecated*
``PropertyWidget`` alias that resolves to :class:`PropertyWindow` — it
preserves the old import shape for one release cycle and must not be
confused with the abstract base class re-exported from this subpackage.
"""

from ovwidgets.property.widget.attributes_widget import AttributesWidget
from ovwidgets.property.widget.property_widget import PropertyWidget
from ovwidgets.property.widget.schema_property_widget import SchemaPropertyWidget
from ovwidgets.property.widget.scheme_delegate import PropertySchemeDelegate
from ovwidgets.property.widget.scheme_registry import PropertySchemeRegistry
from ovwidgets.property.widget.scroll_preserver import ScrollPreserver
from ovwidgets.property.widget.simple_property_widget import SimplePropertyWidget

__all__ = [
    "PropertyWidget",
    "SimplePropertyWidget",
    "AttributesWidget",
    "SchemaPropertyWidget",
    "PropertySchemeRegistry",
    "PropertySchemeDelegate",
    "ScrollPreserver",
]
