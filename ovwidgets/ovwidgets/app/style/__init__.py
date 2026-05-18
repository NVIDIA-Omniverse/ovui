# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""OvGear style sub-package: palette, constants, URLs, and widget styles."""

from ovwidgets.common.style import palette as palette  # registers cl.* colour shades
from ovwidgets.common.style import urls as urls

from . import constants as constants  # registers fl.* float constants
from . import styles as styles


def apply_global_styles() -> None:
    """Assign merged global + module styles to ui.style.default.

    Module styles (Stage.*, Property.*, etc.) are merged here so that
    shade-aware cl.* color references resolve with the current shade when
    apply_global_styles() is re-called on theme change.  Applying them via
    window.frame.set_style() at window-creation time captures dark values
    and does not update on set_shade("light").
    """
    import omni.ui as ui

    from .styles import GLOBAL_STYLES

    merged: dict = dict(GLOBAL_STYLES)

    try:
        from ovwidgets.stage.style import STAGE_STYLES
        merged.update(STAGE_STYLES)
    except ImportError:
        pass

    try:
        from ovwidgets.property.style import PROPERTY_STYLES
        merged.update(PROPERTY_STYLES)
    except ImportError:
        pass

    try:
        from ovwidgets.content.style import CONTENT_STYLES
        merged.update(CONTENT_STYLES)
    except ImportError:
        pass

    try:
        from ovwidgets.layers.style import LAYERS_STYLES
        merged.update(LAYERS_STYLES)
    except ImportError:
        pass

    ui.style.default = merged

    from .imgui_runtime import apply_imgui_splitter_style
    apply_imgui_splitter_style()


def set_theme(theme_name: str) -> None:
    """Switch theme. theme_name is 'dark' (default) or 'light'."""
    import omni.ui as ui
    if theme_name == "light":
        ui.set_shade("light")
    else:
        ui.set_shade("default")
    # Re-apply global styles so resolved cl.* values propagate to ui.style.default.
    apply_global_styles()
