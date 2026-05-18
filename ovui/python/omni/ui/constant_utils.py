# SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from . import _ui as ui
from .singleton import Singleton
from .abstract_shade import AbstractShade


@Singleton
class FloatShade(AbstractShade):
    """
    The shade functionality for float style parameters.

    Usage:
        ui.Rectangle(style={"border_width": fl.shade(1, light=0)})

        # Make no border
        cl.set_shade("light")

        # Make border width 1
        cl.set_shade("default")
    """

    def _find(self, name: str) -> float:
        return ui.FloatStore.find(name)

    def _store(self, name: str, value: float):
        return ui.FloatStore.store(name, value)


constant = FloatShade()
