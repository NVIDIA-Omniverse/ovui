# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovwidgets.property.models — shared attribute value models.

Introduced in Step 1.1 of the property inspector implementation. Provides ``AttributeModelBase``:
the begin_edit → set_value → end_edit sequence is centralised so individual row classes do not re-implement it.

No row classes consume ``AttributeModelBase`` yet; that swap lands in
Step 1.4.
"""

from ovwidgets.property.models.attribute_model import AttributeModelBase

__all__ = ["AttributeModelBase"]
