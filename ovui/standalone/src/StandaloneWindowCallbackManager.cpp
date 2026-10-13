/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "StandaloneWindowCallbackManager.h"
#include <omni/ui/platform/PlatformRegistry.h>

namespace omni {
namespace ui {
namespace standalone {

static StandaloneWindowCallbackManager* s_windowCallbackManager = nullptr;

StandaloneWindowCallbackManager* getStandaloneWindowCallbackManager()
{
    return s_windowCallbackManager;
}

void setStandaloneWindowCallbackManager(StandaloneWindowCallbackManager* mgr)
{
    s_windowCallbackManager = mgr;
    PlatformRegistry::instance().setWindowCallbackManager(mgr);
}

} // namespace standalone
} // namespace ui
} // namespace omni
