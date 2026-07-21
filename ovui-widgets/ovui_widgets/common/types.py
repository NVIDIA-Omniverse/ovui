# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Shared opaque type aliases used by adapter return-type annotations.

Aliases live here so :mod:`ovui_widgets.common.adapters` does not type-reference
any widget module. The concrete implementing types live in their respective
widget modules — for example, :class:`ovui_data_adapters.common.GpuFrame`
is the concrete dataclass that satisfies the :data:`GpuFrameHandle` alias
contract at runtime.
"""

from __future__ import annotations

from typing import Any

# GpuFrameHandle is the type-only alias for
# :meth:`ovui_widgets.common.adapters.RendererAdapter.render_frame`'s return
# type. The concrete implementation is :class:`ovui_data_adapters.common.GpuFrame`,
# which is referenced from this alias only under TYPE_CHECKING (so common does
# NOT import viewport at runtime). The alias is `Any` so mypy treats every
# concrete viewport `GpuFrame` instance as compatible — the contract is
# semantic (RGBA uint8 buffer or zero-copy GPU pointer), not static.
GpuFrameHandle = Any
"""Opaque adapter handle for a render-frame result. See
:class:`ovui_data_adapters.common.GpuFrame` for the concrete viewport
implementation; other RendererAdapter implementations may use other
GPU-side carriers."""
