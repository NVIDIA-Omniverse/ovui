/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include "Alignment.h"
#include "Callback.h"
#include "Shape.h"
#include "Widget.h"

#include <memory>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 */
class OMNIUI_CLASS_API ShapeAnchorHelper : protected CallbackHelper<ShapeAnchorHelper>
{
public:

    OMNIUI_API
    virtual ~ShapeAnchorHelper();

    /**
     */
    OMNIUI_API
    void shapeAnchorHelperSetComputedContentWidth(float width);

    /**
     */
    OMNIUI_API
    void shapeAnchorHelperSetComputedContentHeight(float height);

    /**
     */
    OMNIUI_API
    inline void invalidateAnchor() {m_anchorFrame->rebuild();}

    /**
     */
    OMNIUI_API
    virtual float closestParametricPosition(const float pX, const float pY) = 0;

    /**
     */
    OMNIUI_CALLBACK(Anchor, void);

    /**
     */
    OMNIUI_PROPERTY(float, anchorPosition, DEFAULT, 0.5f, READ, getAnchorPosition, WRITE, setAnchorPosition);

    /**
     */
    OMNIUI_PROPERTY(Alignment, anchorAlignment, DEFAULT, Alignment::eCenter, READ, getAnchorAlignment, WRITE, setAnchorAlignment);

protected:
    /**
     */
    OMNIUI_API
    ShapeAnchorHelper();

    /**
     */
    OMNIUI_API
    static float _alignmentHOffset(const Alignment& alignment, float contentWidth)
    {
        if (alignment & Alignment::eRight)
        {
            return -contentWidth;
        }
        else if (alignment & Alignment::eHCenter)
        {
            return 0.5f * -contentWidth;
        }
        // else
        return 0.0f;
    }

    /**
     */
    OMNIUI_API
    static float _alignmentVOffset(const Alignment& alignment, float contentHeight)
    {
        if (alignment & Alignment::eBottom)
        {
            return -contentHeight;
        }
        else if (alignment & Alignment::eVCenter)
        {
            return 0.5f * -contentHeight;
        }
        // else
        return 0.0f;
    }

    // the Frame for the anchor
    std::shared_ptr<Frame> m_anchorFrame;

};

OMNIUI_NAMESPACE_CLOSE_SCOPE
