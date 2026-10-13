/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

// Windows only: force-included into Module.cpp of `_ui`. Other binding
// modules import the three style helpers of BindStyleContainer.h, which
// Module.cpp defines, from `_ui.pyd`, so they are exported from it.
#pragma once

// Import the shared UI types before declaring the three helpers owned by Module.cpp.
#include <omni/ui/Api.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/StyleStore.h>
#include <omni/ui/Widget.h>
#include <omni/ui/bind/Pybind.h>

#pragma push_macro("OMNIUI_API")
#undef OMNIUI_API
#define OMNIUI_API OMNIUI_EXPORT
#include <omni/ui/bind/BindStyleContainer.h>
#pragma pop_macro("OMNIUI_API")
