# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ovui_widgets.property.models — shared attribute value models.

Introduced in Step 1.1 of the property inspector implementation. Provides ``AttributeModelBase``:
the begin_edit → set_value → end_edit sequence is centralised so individual row classes do not re-implement it.

No row classes consume ``AttributeModelBase`` yet; that swap lands in
Step 1.4.
"""

from ovui_widgets.property.models.attribute_model import AttributeModelBase

__all__ = ["AttributeModelBase"]
