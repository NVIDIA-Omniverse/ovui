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
from .abstract_shade import AbstractShade
from .singleton import Singleton
from typing import Optional
from typing import Union
import struct


@Singleton
class ColorShade(AbstractShade):
    """
    Usage:
        import omni.ui.color as cl

        ui.Button(style={"color": cl.kit_bg})
        ui.CheckBox(style={"color": cl.kit_bg})
        ui.Slider(style={"color": "kit_bg"})

        # Make everything light:
        cl.kit_bg = (1,1,1)

        # Make everything dark:
        cl.kit_bg = (0,0,0)

    Usage:
        ui.Button(
            style={
                "color": cl.shade(
                    (0.1, 0.1, 0.1),
                    light=(1,1,1),
                    green=(0,0,1))})
        ui.CheckBox(
            style={
                "color": cl.shade(
                    (0.2, 0.2, 0.2),
                    light=(1,1,1),
                    name="my_bg")})
        ui.Slider(
            style={"color": cl.my_bg})

        # Make everything light:
        cl.set_shade("light")

        # Make everything dark:
        cl.set_shade("default")

    """

    def _find(self, name: str) -> int:
        return ui.ColorStore.find(name)

    def _store(self, name: str, value: int):
        return ui.ColorStore.store(name, value)

    def __call__(
        self,
        r: Union[str, int, float],
        g: Optional[Union[float, int]] = None,
        b: Optional[Union[float, int]] = None,
        a: Optional[Union[float, int]] = None,
    ) -> int:
        """
        Convert color representation to uint32_t color.

        ### Supported ways to set color:

           - `cl("#CCCCCC")`
           - `cl("#CCCCCCFF")`
           - `cl(128, 128, 128)`
           - `cl(0.5, 0.5, 0.5)`
           - `cl(128, 128, 128, 255)`
           - `cl(0.5, 0.5, 0.5, 1.0)`
           - `cl(128)`
           - `cl(0.5)`
        """

        # Check if rgb are numeric
        allnumeric = True
        hasfloat = False
        for i in [r, g, b]:
            if isinstance(i, int):
                pass
            elif isinstance(i, float):
                hasfloat = True
            else:
                allnumeric = False
                break

        if allnumeric:
            if hasfloat:
                # FLOAT RGBA
                if isinstance(a, float) or isinstance(a, int):
                    alpha = min(255, max(0, int(a * 255)))
                else:
                    alpha = 255
                rgba = (
                    min(255, max(0, int(r * 255))),
                    min(255, max(0, int(g * 255))),
                    min(255, max(0, int(b * 255))),
                    alpha,
                )
            else:
                # INT RGBA
                if isinstance(a, int):
                    alpha = min(255, max(0, a))
                else:
                    alpha = 255
                rgba = (min(255, max(0, r)), min(255, max(0, g)), min(255, max(0, b)), alpha)
        elif isinstance(r, str) and g is None and b is None and a is None:
            # HTML Color
            value = r.lstrip("#")
            # Add FF alpha if there is no alpha
            value += "F" * max(0, 8 - len(value))
            rgba = struct.unpack("BBBB", bytes.fromhex(value))
        elif isinstance(r, int) and g is None and b is None:
            # Single INT
            rr = min(255, max(0, r))
            rgba = (rr, rr, rr, 255)
        elif isinstance(r, float) and g is None and b is None:
            # Single FLOAT
            rr = min(255, max(0, int(r * 255)))
            rgba = (rr, rr, rr, 255)
        else:
            # TODO: More representations, like HSV
            raise ValueError

        return (rgba[3] << 24) + (rgba[2] << 16) + (rgba[1] << 8) + (rgba[0] << 0)


color = ColorShade()
