# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

# Shared variant: works in both Kit (carb available) and standalone (no carb).
#
# When carb is present:
#   * Mouse/modifier constants come from carb.input (preserves existing Kit
#     behavior where tests compare against carb.input.MouseInput enum values).
#   * String bindings are resolved via carb.settings with a tree-change
#     subscription so a change rebuilds the manipulator's gestures.
#   * Diagnostics go through carb.log_error / carb.log_warn.
#
# When carb is not importable (standalone):
#   * Local integer constants stand in for carb.input values. Their numeric
#     values match the ImGui / GestureModifiers.h conventions carb also uses.
#   * String bindings degrade to an empty-dict no-op (no settings backend).
#   * Diagnostics go through the stdlib logging module.
#
__all__ = ["GestureBinding", "GestureBindings", "GestureBindingManipulator"]

import importlib
import logging
from functools import partial
from typing import List, Optional, Union
import weakref

from .scene import AbstractGesture, Manipulator

_log = logging.getLogger(__name__)

try:
    import carb
    import carb.input
    _HAVE_CARB = True
except ImportError:
    carb = None  # type: ignore[assignment]
    _HAVE_CARB = False


if _HAVE_CARB:
    _LEFT_BUTTON   = carb.input.MouseInput.LEFT_BUTTON
    _RIGHT_BUTTON  = carb.input.MouseInput.RIGHT_BUTTON
    _MIDDLE_BUTTON = carb.input.MouseInput.MIDDLE_BUTTON
    _MOD_SHIFT = carb.input.KEYBOARD_MODIFIER_FLAG_SHIFT
    _MOD_CTRL  = carb.input.KEYBOARD_MODIFIER_FLAG_CONTROL
    _MOD_ALT   = carb.input.KEYBOARD_MODIFIER_FLAG_ALT
    _MOD_SUPER = carb.input.KEYBOARD_MODIFIER_FLAG_SUPER

    def _log_error(msg: str) -> None:
        carb.log_error(msg)

    def _log_warn(msg: str) -> None:
        carb.log_warn(msg)
else:
    # Mouse button indices — match ImGui (and carb.input.MouseInput) conventions:
    #   LEFT_BUTTON  = 0
    #   RIGHT_BUTTON = 1
    #   MIDDLE_BUTTON= 2
    _LEFT_BUTTON   = 0
    _RIGHT_BUTTON  = 1
    _MIDDLE_BUTTON = 2
    # Keyboard modifier flag bits — match GestureModifiers.h and carb::input values:
    _MOD_SHIFT = 1 << 0
    _MOD_CTRL  = 1 << 1
    _MOD_ALT   = 1 << 2
    _MOD_SUPER = 1 << 3

    def _log_error(msg: str) -> None:
        _log.error(msg)

    def _log_warn(msg: str) -> None:
        _log.warning(msg)


class GestureBinding(tuple):
    """Class that encapsulates a gesture binding, holding the data needed for invocation"""

    @property
    def mouse_buttons(self):
        """Returns the mouse buttons associated with the gesture binding"""
        return self[0]

    @property
    def modifiers(self):
        """Returns the keyboard modifiers associated with the gesture binding"""
        return self[1]


class GestureBindings:
    def __init__(self, bindings: Union[dict, str], gesture_module: Union[str, dict] = None):
        """GestureBindings constructor

        Args:
            bindings (dict|str): A dictionary mapping gesture names to their key bindings or a string
                key. In Kit, string keys are looked up via carb.settings; in standalone, string keys
                cannot be resolved and fall back to empty bindings.
            gesture_module: (str|None): The name of the module where the gestures are defined.
        """
        if isinstance(bindings, str):
            if _HAVE_CARB:
                bindings = carb.settings.get_settings().get(bindings)
            else:
                _log_warn(
                    f"GestureBindings: settings key '{bindings}' cannot be resolved in standalone mode; "
                    "using empty bindings. Pass a dict instead."
                )
                bindings = {}
        self.__bindings = bindings or {}
        self.__module_obj = gesture_module

    def __contains__(self, key) -> bool:
        """Check if a key exists in the bindings."""
        return key in self.__bindings

    def __getitem__(self, key) -> str:
        """Get a single binding item for parsing by key."""
        return self.__bindings[key]

    def _get_instantiator(self, gesture):
        """Return a callable instantiator for the gesture."""
        if callable(gesture):
            return gesture
        if isinstance(gesture, str):
            parts = gesture.rsplit('.', 1)
            if len(parts) == 1:
                module_name, class_name = self.__module_obj, parts[0]
            else:
                module_name, class_name = parts

            if module_name:
                try:
                    if isinstance(module_name, str):
                        module = importlib.import_module(module_name)
                    else:
                        module = self.__module_obj
                    instantiator = module[class_name] if isinstance(module, dict) else getattr(module, class_name)
                    if instantiator and callable(instantiator):
                        return instantiator
                    _log_error(f"'{class_name}' in module '{module_name}' was not found or not callable.")
                except ImportError:
                    _log_error(f"Module '{module_name}' not found.")
                except AttributeError:
                    _log_error(f"Class '{class_name}' not found in module '{module_name}'.")
            else:
                instantiator = globals().get(gesture)
                if callable(instantiator):
                    return instantiator
                _log_error(f"'{class_name}' in globals was not found or not callable.")

        return None

    def parse_bindings(self, gesture_ignore_list: Optional[list] = None, *args, **kwargs) -> tuple:
        """Parse the bindings provided during initialization, optionally ignoring certain keys.

        Args:
            gesture_ignore_list (list|None): Optional list of keys to ignore during parsing.
        """

        for gesture, binding in self.__bindings.items():
            if gesture_ignore_list and gesture in gesture_ignore_list:
                continue

            instantiator = self._get_instantiator(gesture)
            if not instantiator:
                _log_warn(f'Gesture "{gesture}" was not found for key-binding: "{binding}"')
                continue

            try:
                binding = self.parse_binding(binding)
                yield instantiator(mouse_buttons=binding.mouse_buttons, modifiers=binding.modifiers,
                                   *args, **kwargs), binding
            except Exception as e:
                _log_error(f'Error building gesture {gesture} for binding {binding}: {e}')

    def parse_binding(self, binding_str: str) -> GestureBinding:
        """Parse a single binding string into a GestureBinding.

        Args:
            binding_str (str): The binding string to parse.

        Returns:
            GestureBinding: The parsed gesture binding.
        """
        keys = binding_str.split(' ')
        buttons, modifiers = [], 0
        for token in keys:
            button = {
                'LeftButton':   _LEFT_BUTTON,
                'RightButton':  _RIGHT_BUTTON,
                'MiddleButton': _MIDDLE_BUTTON,
            }.get(token, None)
            if button is not None:
                buttons.append(button)
                continue

            mod_bit = {
                'Shift': _MOD_SHIFT,
                'Ctrl':  _MOD_CTRL,
                'Alt':   _MOD_ALT,
                'Super': _MOD_SUPER,
                'Any':   0xffffffff,
            }.get(token, None)
            if mod_bit is not None:
                modifiers = modifiers | mod_bit
                continue

            raise RuntimeError(f'Unparsable binding: {binding_str}')

        return GestureBinding([buttons, modifiers])


class GestureBindingManipulator(Manipulator):
    """Base class responsible for building up the gestures."""

    def __init__(self, bindings: dict = None, *args, **kwargs):
        """
        Constructor

        Args:
            bindings (dict|str): Bindings to use for the manipulator's gestures.  In Kit, a string
                settings key is subscribed via carb.settings and bindings rebuild when the key
                changes.  In standalone, string keys are not backed and fall back to empty.
            *args, **kwargs: Additional arguments to pass to the base class.
        """
        super().__init__(*args, **kwargs)
        self.__carb_sub = None
        self.__bindings_dirty = True
        self.bindings = bindings

    def _build_gestures(self, bindings: dict, *args, **kwargs):
        """Return the gestures that correspond to the given bindings."""
        module_name = kwargs.pop("gesture_module") if "gesture_module" in kwargs else None
        ignore_list = kwargs.pop("gesture_ignore_list") if "gesture_ignore_list" in kwargs else None
        gesture_bindings = GestureBindings(bindings, gesture_module=module_name)
        return [gesture for gesture, _ in gesture_bindings.parse_bindings(gesture_ignore_list=ignore_list, *args, **kwargs)]

    def get_gestures(self, *args, **kwargs):
        """Get the gestures for the Manipulator's bindings, possibly rebuilding them if dirty."""
        if self.__bindings_dirty:
            self.__bindings_dirty = False
            if self.__bindings is None:
                self.__bindings = self.get_default_bindings()
            bindings = self.__bindings
            if isinstance(bindings, str):
                if _HAVE_CARB:
                    bindings = carb.settings.get_settings().get(bindings)
                else:
                    _log_warn(
                        f"GestureBindingManipulator: settings key '{bindings}' "
                        "cannot be resolved in standalone mode."
                    )
                    bindings = {}
            self.__gestures = self._build_gestures(bindings, *args, **kwargs)
        return self.__gestures

    def get_default_bindings(self):
        return None

    @property
    def bindings(self) -> Union[dict, str]:
        """Return the bindings assigned to the manipulator."""
        return self.__bindings

    @bindings.setter
    def bindings(self, bindings: Union[dict, str]):
        """Set the bindings assigned to the manipulator."""
        self.__bindings = bindings
        self.__bindings_dirty = True
        if isinstance(self.__bindings, str):
            if _HAVE_CARB:
                settings = carb.settings.get_settings()
                if self.__carb_sub:
                    settings.unsubscribe_to_change_events(self.__carb_sub)
                    self.__carb_sub = None
                self.__carb_sub = settings.subscribe_to_tree_change_events(
                    self.__bindings, partial(self.__bindings_changed, weakref.ref(self))
                )
            else:
                _log_warn(
                    f"GestureBindingManipulator: settings key '{self.__bindings}' "
                    "cannot be subscribed in standalone mode. Pass a dict directly."
                )
        elif self.__carb_sub:
            if _HAVE_CARB:
                carb.settings.get_settings().unsubscribe_to_change_events(self.__carb_sub)
            self.__carb_sub = None
        self.invalidate()

    @staticmethod
    def __bindings_changed(weak_self, *args, **kwargs):
        target = weak_self()
        if target is not None:
            target.__bindings_dirty = True
            target.invalidate()

    def destroy(self):
        """Destroys the manipulator instance."""
        self.__bindings = None
        self.__gestures = None
        if self.__carb_sub:
            if _HAVE_CARB:
                carb.settings.get_settings().unsubscribe_to_change_events(self.__carb_sub)
            self.__carb_sub = None

        spr_destroy = getattr(super(), "destroy", None)
        if spr_destroy:
            spr_destroy()
