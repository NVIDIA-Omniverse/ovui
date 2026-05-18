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

#define _USE_MATH_DEFINES
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/Frame.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/ShapeAnchorHelper.h>


OMNIUI_NAMESPACE_OPEN_SCOPE

void ShapeAnchorHelper::shapeAnchorHelperSetComputedContentWidth(float width)
{
    m_anchorFrame->setComputedContentWidth(0.0f);
}

void ShapeAnchorHelper::shapeAnchorHelperSetComputedContentHeight(float height)
{
    m_anchorFrame->setComputedContentHeight(0.0f);
}

ShapeAnchorHelper::ShapeAnchorHelper()
{
    OMNIKIT_WITH_CONTAINER(nullptr)
    {
        m_anchorFrame = Frame::create();
    }

    this->setAnchorChangedFn(
        [this]()
        {
            if (this->hasAnchorFn())
            {
                m_anchorFrame->setBuildFn(this->m_AnchorCallback);
            }
            else
            {
                m_anchorFrame->setBuildFn(nullptr);
            }

            if (m_anchorFrame->hasBuildFn())
            {
                m_anchorFrame->rebuild();
            }
            else
            {
                m_anchorFrame->clear();
            }
            // make sure we compute size of child widget to fit the content.
            m_anchorFrame->setComputedWidth(0);
            m_anchorFrame->setComputedHeight(0);
        });
}

ShapeAnchorHelper::~ShapeAnchorHelper() = default;


OMNIUI_NAMESPACE_CLOSE_SCOPE
