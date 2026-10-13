/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/platform/PlatformRegistry.h>

namespace omni {
namespace ui {

PlatformRegistry& PlatformRegistry::instance()
{
    static PlatformRegistry s_instance;
    return s_instance;
}

} // namespace ui
} // namespace omni
