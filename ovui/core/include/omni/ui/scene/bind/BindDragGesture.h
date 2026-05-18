/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#pragma once

#include "BindShapeGesture.h"
#include "DocDragGesture.h"

#include <omni/ui/scene/DragGesture.h>

OMNIUI_PROTECT_PYBIND11_OBJECT(OMNIUI_SCENE_NS::DragGesture, DragGesture);

// clang-format off

#define OMNIUI_PYBIND_INIT_PyDragGesture                                                                               \
    OMNIUI_PYBIND_INIT_CAST(mouse_button, setMouseButton, uint32_t)                                                    \
    OMNIUI_PYBIND_INIT_CAST(mouse_buttons, setMouseButtons, std::vector<uint32_t>)                                     \
    OMNIUI_PYBIND_INIT_CAST(modifiers, setModifiers, uint32_t)                                                         \
    OMNIUI_PYBIND_INIT_CAST(check_mouse_moved, setCheckMouseMoved, bool)                                               \
    OMNIUI_PYBIND_INIT_CALLBACK(on_began_fn, setOnBeganFn, void(AbstractShape const*))                                 \
    OMNIUI_PYBIND_INIT_CALLBACK(on_changed_fn, setOnChangedFn, void(AbstractShape const*))                             \
    OMNIUI_PYBIND_INIT_CALLBACK(on_ended_fn, setOnEndedFn, void(AbstractShape const*))                                 \
    OMNIUI_PYBIND_INIT_ShapeGesture

#define OMNIUI_PYBIND_KWARGS_DOC_DragGesture                                                                           \
    "\n    `mouse_button : `\n        "                                                                                \
    OMNIUI_PYBIND_DOC_DragGesture_mouseButton                                                                          \
    "\n    `modifiers : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_DragGesture_modifiers                                                                            \
    "\n    `check_mouse_moved : `\n        "                                                                           \
    OMNIUI_PYBIND_DOC_DragGesture_checkMouseMoved                                                                      \
    "\n    `on_began_fn : `\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_DragGesture_onBegan                                                                              \
    "\n    `on_changed_fn : `\n        "                                                                               \
    OMNIUI_PYBIND_DOC_DragGesture_onChanged                                                                            \
    "\n    `on_ended_fn : `\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_DragGesture_onEnded                                                                              \
    OMNIUI_PYBIND_KWARGS_DOC_ShapeGesture

// clang-format on
