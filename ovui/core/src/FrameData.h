/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/Frame.h>
#include "ContainerData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

struct Frame::FrameData : public Container::ContainerData
{
    ~FrameData() override;

    // The only child of this frame
    std::shared_ptr<Widget> m_canvas;
    // The widget that will be the current at the next draw
    std::shared_ptr<Widget> m_canvasPending;

    std::unique_ptr<ImDrawList> m_drawList;
    ImVec2 m_drawListPosition;

    // Flag to rebuild the children with m_buildFn.
    bool m_needRebuildWithCallback = false;

    // Disables padding. We need it mostly for CollapsableFrame because it creates multiple nested frames and we need to
    // have only one padding applied.
    bool m_needPadding = true;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
