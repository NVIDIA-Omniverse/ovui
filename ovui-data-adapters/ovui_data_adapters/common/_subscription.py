# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Structural protocol for adapter change-subscription handles.

Part of ``ovui-data-adapters-common`` — zero-dependency, stdlib-only.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class SubscriptionProtocol(Protocol):
    """Structural protocol for adapter change-subscription handles.

    Any object exposing a no-arg ``cancel()`` method that returns ``None``
    satisfies this protocol. The concrete ``Subscription`` class in
    ``ovwidgets.common.settings`` satisfies it; the private ``_*Subscription``
    classes scattered through the codebase also satisfy it.
    """

    def cancel(self) -> None: ...
