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

#include <imgui/imgui.h>
#include <omni/ui/CollapsableFrame.h>
#include <omni/ui/HStack.h>
#include <omni/ui/InvisibleButton.h>
#include <omni/ui/Label.h>
#include <omni/ui/Profile.h>
#include <omni/ui/Rectangle.h>
#include <omni/ui/Spacer.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/Triangle.h>
#include <omni/ui/VStack.h>
#include <omni/ui/ZStack.h>

#include "FrameData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

struct CollapsableFrame::CollapsableFrameData : public Frame::FrameData
{
    ~CollapsableFrameData() override = default;

    // The important widgets we need to access.
    // Two rectangles to fill the background.
    std::shared_ptr<Rectangle> m_backgroundHeader;
    std::shared_ptr<Rectangle> m_backgroundBody;
    // The frame for the title
    std::shared_ptr<Frame> m_header;
    // The frame for the body
    std::shared_ptr<Frame> m_body;

    // If true, the header will be recreated.
    bool m_headerNeedsToBeUpdated = true;
};


CollapsableFrame::CollapsableFrame(const std::string& text)
    // Disables padding. CollapsableFrame creates multiple nested frames and we need to have only one padding applied.
    : Frame(false, new CollapsableFrameData)

{
    std::shared_ptr<Frame> frame;
    OMNIKIT_WITH_CONTAINER(nullptr)
    {
        // TODO: We need a flag to create() to specify we don't need to parent it.
        frame = Frame::create();
    }

    // Set it as a root component.
    Frame::addChild(frame);
    // Restrict margin, because we already have it in this CollapsableFrame. Each next frame shouldn't use margin.
    frame->useMarginFromStyle(false);
    frame->setParent(this);

    auto& data = _getData<CollapsableFrameData>();
    OMNIKIT_WITH_CONTAINER(frame)
    {
        OMNIKIT_WITH_CONTAINER(ZStack::create())
        {
            // Put the rectangle to the background and draw the header on top of it. If we put them side by side, there
            // is a visible border between them if one of rectangles have rounded corners.
            data.m_backgroundBody = Rectangle::create();
            data.m_backgroundBody->setStyleTypeNameOverride(this->getTypeName());

            OMNIKIT_WITH_CONTAINER(VStack::create())
            {
                auto zStack = ZStack::create();
                zStack->setHeight(Pixel(0.0f));
                OMNIKIT_WITH_CONTAINER(zStack)
                {
                    // Collapse/expand is here
                    auto button = InvisibleButton::create();
                    button->setClickedFn([this]() { this->setCollapsed(!this->isCollapsed()); });

                    data.m_backgroundHeader = Rectangle::create();
                    data.m_backgroundHeader->setStyleTypeNameOverride(this->getTypeName());
                    data.m_backgroundHeader->setBackgroundColorProperty(StyleColorProperty::eSecondaryColor);

                    data.m_header = Frame::create();
                    data.m_header->setStyleTypeNameOverride(this->getTypeName());
                }

                data.m_body = Frame::create();
                data.m_body->setStyleTypeNameOverride(this->getTypeName());
            }
        }
    }

    // Set title before setTitleChangedFn to make sure it didn't call _invalidateState because we call it after because
    // it's possible that setTitle will not call _invalidateState. It happens when the title is empty.
    this->setTitle(text);
    this->setTitleChangedFn(std::bind(&This::_invalidateState, this));
    this->setCollapsedChangedFn(std::bind(&This::_invalidateState, this));
    this->setAlignmentChangedFn(std::bind(&This::_invalidateState, this));

    this->setNameChangedFn([this](const auto& name) {
        auto& data = _getData<CollapsableFrameData>();
        data.m_backgroundHeader->setName(name);
        data.m_backgroundBody->setName(name);
    });

    this->_invalidateState();
}

void CollapsableFrame::addChild(std::shared_ptr<Widget> canvas)
{
    // Recirect children to m_body.
    _getData<CollapsableFrameData>().m_body->addChild(canvas);
    canvas->useMarginFromStyle(useMarginFromStyle());
    canvas->setScale(this->_getScale());
}

void CollapsableFrame::setComputedContentWidth(float width)
{
    this->_updateHeader();
    Frame::setComputedContentWidth(width);
}

void CollapsableFrame::setComputedContentHeight(float height)
{
    this->_updateHeader();
    Frame::setComputedContentHeight(height);
}

void CollapsableFrame::rebuild()
{
    this->_invalidateState();
    Frame::rebuild();
}

void CollapsableFrame::_buildHeader()
{
    const std::string& typeName = This::getTypeName();

    // It's called every time to recreate the header. For Python reimplementation it's the shortest way to reimplement
    // header without comlicated code.
    auto hStack = HStack::create();
    // we need to document that, but it enable to control the style for the header nore directly
    hStack->setName("header");
    OMNIKIT_WITH_CONTAINER(hStack)
    {
        // TODO: We need to get it from style.
        constexpr float triangleSize = 8.0f;
        Spacer::create()->setWidth(Pixel(triangleSize));

        auto triangleCenter = VStack::create();
        triangleCenter->setWidth(Pixel(triangleSize));
        OMNIKIT_WITH_CONTAINER(triangleCenter)
        {
            // Center the triangle.
            Spacer::create();

            auto triangle = Triangle::create();
            triangle->setStyleTypeNameOverride(typeName);
            triangle->setBackgroundColorProperty(StyleColorProperty::eColor);
            triangle->setHeight(Pixel(triangleSize));
            triangle->setAlignment(this->isCollapsed() ? Alignment::eRightCenter : Alignment::eCenterBottom);

            Spacer::create();
        }

        Spacer::create()->setWidth(Pixel(triangleSize));

        auto label = Label::create(this->getTitle());
        label->setStyleTypeNameOverride(typeName);
        label->setAlignment(this->getAlignment());

        Spacer::create()->setWidth(Pixel(triangleSize));
    }
}

void CollapsableFrame::_updateHeader()
{
    auto& data = _getData<CollapsableFrameData>();
    if (!data.m_headerNeedsToBeUpdated)
    {
        return;
    }

    OMNIUI_PROFILE_VERBOSE_WIDGET_FUNCTION;

    data.m_headerNeedsToBeUpdated = false;

    // TODO: We need to rename the members of CornerFlag because they conflict with the names of alignment and we can't
    // incude both. CornerFlag::eTop = 3U; CornerFlag::eAll = 15U
    static StyleContainer styleCornerTop{ "", StyleEnumProperty::eCornerFlag, 3U };
    static StyleContainer styleCornerAll{ "", StyleEnumProperty::eCornerFlag, 15U };
    data.m_backgroundHeader->setStyle(this->isCollapsed() ? styleCornerAll : styleCornerTop);

    OMNIKIT_WITH_CONTAINER(data.m_header)
    {
        if (this->hasBuildHeaderFn())
        {
            // Custom header
            this->callBuildHeaderFn(this->isCollapsed(), this->getTitle());
        }
        else
        {
            this->_buildHeader();
        }
    }
}

void CollapsableFrame::_invalidateState()
{
    auto& data = _getData<CollapsableFrameData>();
    data.m_body->setVisible(!this->isCollapsed());
    data.m_backgroundBody->setVisible(!this->isCollapsed());

    this->forceWidthDirty(SizeDirtyReason::eSizeChanged);
    this->forceHeightDirty(SizeDirtyReason::eSizeChanged);

    data.m_headerNeedsToBeUpdated = true;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
