# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Value models for the Stage Browser.

Thin wrappers over :class:`omni.ui.AbstractValueModel` that translate
adapter state into the shape each column delegate expects. Kept in a
dedicated subpackage so the delegate-per-column split in the stage implementation step 11
can import from here without pulling the whole widget layer.
"""

from ovwidgets.stage.models.visibility_value_model import VisibilityValueModel

__all__ = ["VisibilityValueModel"]
