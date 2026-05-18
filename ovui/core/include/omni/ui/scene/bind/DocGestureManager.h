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

#define OMNIUI_PYBIND_DOC_GestureManager                                                                                                                                                            \
    "The object that controls batch processing and preventing of gestures. Typically each scene has a default manager and if the user wants to have own prevention logic, he can reimplement it.\n" \
    "\n"


#define OMNIUI_PYBIND_DOC_GestureManager_GestureManager "Constructor.\n"


#define OMNIUI_PYBIND_DOC_GestureManager_setView                                                                       \
    "Set the camera.\n"                                                                                                \
    "Todo\n"                                                                                                           \
    "resolution\n"


#define OMNIUI_PYBIND_DOC_GestureManager_preProcess "Process mouse inputs and do all the intersections.\n"


#define OMNIUI_PYBIND_DOC_GestureManager_prevent "Process all the prevention logic and reduce the number of gestures.\n"


#define OMNIUI_PYBIND_DOC_GestureManager_process "Process the gestures.\n"


#define OMNIUI_PYBIND_DOC_GestureManager_postProcess "Clean-up caches, save states.\n"


#define OMNIUI_PYBIND_DOC_GestureManager_canBePrevented                                                                \
    "Called per gesture. Determines if the gesture can be prevented.\n"


#define OMNIUI_PYBIND_DOC_GestureManager_shouldPrevent                                                                 \
    "Called per gesture. Determines if the gesture should be prevented with another gesture. Useful to resolve intersections.\n"


#define OMNIUI_PYBIND_DOC_GestureManager_amendInput                                                                    \
    "Called once a frame. Should be overriden to inject own input to the gestures.\n"
