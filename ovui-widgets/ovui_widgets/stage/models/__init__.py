# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Value models for the Stage Browser.

Thin wrappers over :class:`omni.ui.AbstractValueModel` that translate
adapter state into the shape each column delegate expects. Kept in a
dedicated subpackage so the delegate-per-column split in the stage implementation step 11
can import from here without pulling the whole widget layer.
"""

from ovui_widgets.stage.models.visibility_value_model import VisibilityValueModel

__all__ = ["VisibilityValueModel"]
