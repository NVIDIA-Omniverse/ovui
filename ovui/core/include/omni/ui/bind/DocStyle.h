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

#define OMNIUI_PYBIND_DOC_Style                                                                                        \
    "A singleton that controls the global style of the session.\n"                                                     \
    "\n"


#define OMNIUI_PYBIND_DOC_Style_getInstance "Get the instance of this singleton object.\n"


#define OMNIUI_PYBIND_DOC_Style_getDefaultStyle                                                                        \
    "Returns the default root style. It's the style that is preselected when no alternative is specified.\n"


#define OMNIUI_PYBIND_DOC_Style_setDefaultStyle                                                                        \
    "Set the default root style. It's the style that is preselected when no alternative is specified.\n"


#define OMNIUI_PYBIND_DOC_Style_setDefaultStyle01                                                                      \
    "Set the default root style. It's the style that is preselected when no alternative is specified.\n"


#define OMNIUI_PYBIND_DOC_Style_connectToGlobalStyle "Connect the widget to the default root style.\n"
