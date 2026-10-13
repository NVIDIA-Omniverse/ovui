# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Structural protocol for adapter change-subscription handles.

Part of ``ovui-data-adapters-common``; this module is stdlib-only at runtime.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class SubscriptionProtocol(Protocol):
    """Structural protocol for adapter change-subscription handles.

    Any object exposing a no-arg ``cancel()`` method that returns ``None``
    satisfies this protocol. The concrete ``Subscription`` class in
    ``ovui_widgets.common.settings`` satisfies it; the private ``_*Subscription``
    classes scattered through the codebase also satisfy it.
    """

    def cancel(self) -> None: ...
