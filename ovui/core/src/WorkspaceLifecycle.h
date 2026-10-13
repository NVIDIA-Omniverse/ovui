/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/Api.h>

OMNIUI_NAMESPACE_OPEN_SCOPE
namespace detail
{

// The host brackets callback ownership while Python and the UI platform are alive.
OMNIUI_API void beginWorkspaceCallbackLifetime();
OMNIUI_API void endWorkspaceCallbackLifetime();

} // namespace detail
OMNIUI_NAMESPACE_CLOSE_SCOPE
