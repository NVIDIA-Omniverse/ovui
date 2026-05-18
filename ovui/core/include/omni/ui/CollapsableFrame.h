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
#include "Frame.h"

#include <functional>
#include <memory>
#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

class Rectangle;

/**
 * @brief CollapsableFrame is a frame widget that can hide or show its content. It has two states expanded and
 * collapsed. When it's collapsed, it looks like a button. If it's expanded, it looks like a button and a frame with the
 * content. It's handy to group properties, and temporarily hide them to get more space for something else.
 */
class OMNIUI_CLASS_API CollapsableFrame : public Frame
{
    OMNIUI_OBJECT(CollapsableFrame)

public:
    /**
     * @brief Reimplemented. It adds a widget to m_body.
     *
     * @see Container::addChild
     */
    OMNIUI_API
    void addChild(std::shared_ptr<Widget> widget) override;

    /**
     * @brief Reimplemented the method to indicate the width hint that represents the preferred size of the widget.
     * Currently this widget can't be smaller than the minimal size of the child widgets.
     *
     * @see Widget::setComputedContentWidth
     */
    OMNIUI_API
    void setComputedContentWidth(float width) override;

    /**
     * @brief Reimplemented the method to indicate the height hint that represents the preferred size of the widget.
     * Currently this widget can't be smaller than the minimal size of the child widgets.
     *
     * @see Widget::setComputedContentHeight
     */
    OMNIUI_API
    void setComputedContentHeight(float height) override;

    /**
     * @brief Set flags to rebuild the body and header of this frame on the next drawing cycle
     */
    OMNIUI_API
    void rebuild() override;

    /**
     * @brief Set dynamic header that will be created dynamiclly when it is needed. The function is called inside a
     * ui.Frame scope that the widget will be parented correctly.
     */
    OMNIUI_CALLBACK(BuildHeader, void, bool, std::string);

    /**
     * @brief The state of the CollapsableFrame.
     */
    OMNIUI_PROPERTY(bool, collapsed, DEFAULT, false, READ, isCollapsed, WRITE, setCollapsed, NOTIFY, setCollapsedChangedFn);

    /**
     * @brief The header text
     */
    OMNIUI_PROPERTY(std::string, title, READ, getTitle, WRITE, setTitle, NOTIFY, setTitleChangedFn);

    /**
     * @brief This property holds the alignment of the label in the default header.
     * By default, the contents of the label are left-aligned and vertically-centered.
     */
    OMNIUI_PROPERTY(Alignment,
                    alignment,
                    DEFAULT,
                    Alignment::eLeftCenter,
                    READ,
                    getAlignment,
                    WRITE,
                    setAlignment,
                    NOTIFY,
                    setAlignmentChangedFn);


protected:
    /**
     * @brief Constructs CollapsableFrame
     *
     * @param text The text for the caption of the frame.
     */
    OMNIUI_API
    CollapsableFrame(const std::string& text = {});

    /**
     * @brief Creates widgets that represent the header. Basically, it creates a triangle and a label. This function is
     * called every time the frame collapses/expands, so if Python user wants to reimplement it, he doesn't care about
     * keeping widgets and tracking the state of the frame.
     */
    virtual void _buildHeader();

private:
    struct CollapsableFrameData;

    /**
     * @brief Checks if it's necessary to recreate the header and call _buildHeader.
     */
    void _updateHeader();

    /**
     * @brief Sets a flag that it's necessary to recreate the header.
     */
    void _invalidateState();
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
