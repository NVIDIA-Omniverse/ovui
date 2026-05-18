# SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

__all__ = ["AbstractShade"]

from . import _ui as ui
from collections import defaultdict
from typing import Any
from typing import Dict
from typing import Optional
import abc
import weakref

DEFAULT_SHADE = "default"


class AbstractShade(metaclass=abc.ABCMeta):
    """
    The implementation of shades for custom style parameter type.

    The user has to reimplement methods _store and _find to set/get the value
    in the specific store.
    """

    class _ShadeName(str):
        """An str-like object with a custom method to edit shade"""

        def _keep_as_weak(self, shade: "AbstractShade"):
            # Shade here is omni.ui.color or omni.ui.url. Weak pointer prevents
            # circular references.
            self.__weak_shade = weakref.ref(shade)

        def add_shade(self, **kwargs):
            """Explicitly add additional color to the shade"""
            shade = self.__weak_shade()
            if not shade:
                return

            # Edit the shade
            shade.shade(name=self, **kwargs)

    def __init__(self):
        # Avoid calling AbstractShade.__setattr__ that sets the color in the Store
        super().__setattr__("_current_shade", DEFAULT_SHADE)
        super().__setattr__("_shades", defaultdict(dict))
        # The list of dependencides. Example `cl.shade(0x0, light="background")`
        # makes dependency dict like this:
        # `{"background": ("shade:0x0;light=background")}`
        # We need it to update the shade once `background` is changed.
        # TODO: Clear the dict when the shade is updated. Example: after
        # `cl.bg = "red"; cl.bg = "green"` we will have two dependencies.
        super().__setattr__("_dependencies", defaultdict(set))

    def __getattr__(self, name: str):
        # We need it for the syntax `style={"color": cl.bg_color}`
        result = AbstractShade._ShadeName(name)
        result._keep_as_weak(self)
        return result

    def __setattr__(self, name: str, value):
        if name in self.__dict__:
            # We are here because this class has the method variable. Set it.
            super().__setattr__(name, value)
            return

        if isinstance(value, str) and value in self._shades:
            # It's a shade. Redirect it to the coresponding method.
            self.shade(name=name, **self._shades[value])
        else:
            # This class doesn't have this method variable. We need to set the
            # value in the Store.
            self.__set_value(name, {DEFAULT_SHADE: value})

    def shade(self, default: Any = None, **kwargs) -> str:
        """Save the given shade, pick the color and apply it to ui.ColorStore."""
        mangled_name = self.__mangle_name(default, kwargs, kwargs.pop("name", None))
        shade = self._shades[mangled_name]
        shade.update(kwargs)
        if default is not None:
            shade[DEFAULT_SHADE] = default

        self.__set_value(mangled_name, shade)

        return mangled_name

    def set_shade(self, name: Optional[str] = None):
        """Set the default shade."""
        if not name:
            name = DEFAULT_SHADE

        if name == self._current_shade:
            return

        self._current_shade = name

        for value_name, shade in self._shades.items():
            self.__set_value(value_name, shade)

    def __mangle_name(self, default: Any, values: Dict[str, Any], name: Optional[str] = None) -> str:
        """Convert set of values to the shade name"""
        if name:
            return name

        mangled_name = "shade:"

        if isinstance(default, float) or isinstance(default, int):
            mangled_name += str(default)
        else:
            mangled_name += default

        for name in sorted(values.keys()):
            value = values[name]

            if mangled_name:
                mangled_name += ";"

            if isinstance(value, int):
                value = str(value)

            mangled_name += f"{name}={value}"

        return mangled_name

    def __set_value(self, name: str, shade: Dict[str, float]):
        """Pick the color from the given shade and set it to ui.ColorStore"""
        # Save dependencies
        for dependentName, dependentFloat in shade.items():
            if isinstance(dependentFloat, str):
                self._dependencies[dependentFloat].add(name)

        value = shade.get(self._current_shade, shade.get(DEFAULT_SHADE))

        if isinstance(value, str):
            # It's named color. We need to resolve it from ColorStore.
            found = self._find(value)
            if found is not None:
                value = found

        self._store(name, value)

        # Recursively replace all the values that refer to the current name
        if name in self._dependencies:
            for dependent in self._dependencies[name]:
                shade = self._shades.get(dependent, None)
                if shade:
                    value = shade.get(self._current_shade, shade.get(DEFAULT_SHADE))
                    if value == name:
                        self.__set_value(dependent, shade)

    @abc.abstractmethod
    def _find(self, name):
        pass

    @abc.abstractmethod
    def _store(self, name, value):
        pass
