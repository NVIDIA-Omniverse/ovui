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

#define OMNIUI_PYBIND_DOC_RadioCollection                                                                              \
    "Radio Collection is a class that groups RadioButtons and coordinates their state.\n"                              \
    "It makes sure that the choice is mutually exclusive, it means when the user selects a radio button, any previously selected radio button in the same collection becomes deselected.\n"


#define OMNIUI_PYBIND_DOC_RadioCollection_onModelUpdated                                                               \
    "Called by the model when the model value is changed. The class should react to the changes.\n"                    \
    "Reimplemented from ValueModelHelper\n"


#define OMNIUI_PYBIND_DOC_RadioCollection_RadioCollection "Constructs RadioCollection.\n"
