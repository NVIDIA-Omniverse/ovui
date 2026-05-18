/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#define OMNIUI_PYBIND_DOC_Container                                                                                    \
    "The container is an abstract widget that can hold one or several child widgets.\n"                                \
    "The user is allowed to add or replace child widgets. If the widget has multiple children internally (like Button) and the user doesn't have access to them, it's not necessary to use this class.\n"


#define OMNIUI_PYBIND_DOC_Container_addChild                                                                           \
    "Adds widget to this container in a manner specific to the container. If it's allowed to have one sub-widget only, it will be overwriten.\n"


#define OMNIUI_PYBIND_DOC_Container_clear "Removes the container items from the container.\n"
