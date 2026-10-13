# SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from . import _ui as ui
from .singleton import Singleton
from .abstract_shade import AbstractShade


@Singleton
class StringShade(AbstractShade):
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
        return ui.StringStore.find(name)

    def _store(self, name: str, value: str):
        return ui.StringStore.store(name, value)


url = StringShade()
