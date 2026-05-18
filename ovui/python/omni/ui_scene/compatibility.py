# SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

# Standalone variant: carb.log_warn replaced with warnings.warn.
#
__all__ = ["add_intersection_attributes"]

import warnings
from . import scene as sc


def _deprecate_warning(func, old, new):
    """Returns decorated function that prints a warning when it's executed"""

    def inner(*args, **kwargs):
        warnings.warn(
            f"[omni.ui.scene] Method {old} is deprecated. Please use {new} instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return func(*args, **kwargs)

    return inner


def _add_compatibility(obj, old, new, deprecate_warning=True):
    """Add the attribute old that equals to new"""
    new_obj = getattr(obj, new)
    if deprecate_warning:
        if isinstance(new_obj, property):
            setattr(
                obj,
                old,
                property(
                    fget=_deprecate_warning(new_obj.fget, obj.__name__ + "." + old, obj.__name__ + "." + new),
                    fset=_deprecate_warning(new_obj.fset, obj.__name__ + "." + old, obj.__name__ + "." + new),
                ),
            )
        else:
            setattr(obj, old, _deprecate_warning(new_obj, obj.__name__ + "." + old, obj.__name__ + "." + new))
    else:
        setattr(obj, old, new_obj)


def add_intersection_attributes():
    """Assigns deprecated methods that print warnings when executing"""
    for item in [
        sc.AbstractGesture,
        sc.AbstractShape,
        sc.Arc,
        sc.Line,
        sc.Points,
        sc.PolygonMesh,
        sc.Rectangle,
        sc.Screen,
    ]:
        _add_compatibility(item, "intersection", "gesture_payload")
        _add_compatibility(item, "get_intersection", "get_gesture_payload")

    _add_compatibility(sc.AbstractGesture, "Intersection", "GesturePayload", False)
