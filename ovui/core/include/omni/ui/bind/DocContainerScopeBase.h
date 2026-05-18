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

#define OMNIUI_PYBIND_DOC_ContainerScopeBase                                                                                               \
    "Puts the given container to the top of the stack when this object is constructed. And removes this container when it's destructed.\n" \
    "\n"


#define OMNIUI_PYBIND_DOC_ContainerScopeBase_get "Returns the container it was created with.\n"


#define OMNIUI_PYBIND_DOC_ContainerScopeBase_isValid                                                                   \
    "Checks if this object is valid. It's always valid untill it's invalidated. Once it's invalidated, there is no way to make it valid again.\n"


#define OMNIUI_PYBIND_DOC_ContainerScopeBase_invalidate "Makes this object invalid.\n"
