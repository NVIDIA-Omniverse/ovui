/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <omni/ui/Shape.h>
#include <imgui/imgui.h>

#include "WidgetData.h"

#include <memory>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct Shape::ShapeData : public Widget::WidgetData
{
    ~ShapeData() override;

    ImVec2 m_startPoint = { 0, 0 };
    ImVec2 m_shapeSize = { 0, 0 };

};

struct Shape::FreeShapeData : public Shape::ShapeData
{
    FreeShapeData(std::shared_ptr<Widget> start,
                  std::shared_ptr<Widget> end)
        : m_startPointWidget(start)
        , m_endPointWidget(end)
    {
    }

    FreeShapeData(const Shape::ShapeData& data,
                  std::shared_ptr<Widget> start,
                  std::shared_ptr<Widget> end)
        : Shape::ShapeData(data)
        , m_startPointWidget(start)
        , m_endPointWidget(end)
    {
    }
    ~FreeShapeData() override;

    // Track our bounding box for mouse events, because we set computed width/height to zero.
    Widget::BoundingBox m_bbox = { {0.f, 0.f}, {0.f, 0.f} };

    std::weak_ptr<Widget> m_startPointWidget;
    std::weak_ptr<Widget> m_endPointWidget;
};
OMNIUI_NAMESPACE_CLOSE_SCOPE
