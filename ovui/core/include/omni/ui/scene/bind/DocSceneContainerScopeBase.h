/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_SceneContainerScopeBase                                                                                          \
    "Puts the given container to the top of the stack when this object is constructed. And removes this container when it's destructed.\n" \
    "\n"


#define OMNIUI_PYBIND_DOC_SceneContainerScopeBase_get "Returns the container it was created with.\n"


#define OMNIUI_PYBIND_DOC_SceneContainerScopeBase_isValid                                                              \
    "Checks if this object is valid. It's always valid untill it's invalidated. Once it's invalidated, there is no way to make it valid again.\n"


#define OMNIUI_PYBIND_DOC_SceneContainerScopeBase_invalidate "Makes this object invalid.\n"
