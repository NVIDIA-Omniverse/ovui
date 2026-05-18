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

#include "BezierCurve.h"
#include "Circle.h"
#include "Ellipse.h"
#include "Line.h"
#include "Rectangle.h"
#include "Triangle.h"

#include <memory>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The free widget is the widget that is independent of the layout. It means it is stuck to other widgets.
 * When initializing, it's necessary to provide two widgets, and the shape is drawn from one widget position to
 * the another.
 */
#define _OMNIUI_DEFINE_FREE_SHAPE(name, parent)                                                                        \
    class name : public parent                                                                                         \
    {                                                                                                                  \
        OMNIUI_OBJECT(name)                                                                                            \
                                                                                                                       \
    protected:                                                                                                         \
        OMNIUI_API                                                                                                     \
        name(std::shared_ptr<Widget> start, std::shared_ptr<Widget> end)                                               \
        {                                                                                                              \
            _makeFreeShape(std::move(start), std::move(end));                                                          \
        }                                                                                                              \
                                                                                                                       \
        OMNIUI_API                                                                                                     \
        void _drawContent(float elapsedTime) override                                                                  \
        {                                                                                                              \
            ImVec2 start, size;                                                                                        \
            if (Shape::_getFreeShapeInfo(start, size))                                                                 \
            {                                                                                                          \
                this->_drawShapeShadow(elapsedTime, start.x, start.y, size.x, size.y);                                 \
                this->_drawShape(elapsedTime, start.x, start.y, size.x, size.y);                                       \
            }                                                                                                          \
        }                                                                                                              \
                                                                                                                       \
        OMNIUI_API                                                                                                     \
        Widget::BoundingBox _getInteractionBBox() const override                                                       \
        {                                                                                                              \
            return Shape::_getFreeShapeInteractionBBox();                                                              \
        }                                                                                                              \
    }

_OMNIUI_DEFINE_FREE_SHAPE(FreeBezierCurve, BezierCurve);
_OMNIUI_DEFINE_FREE_SHAPE(FreeCircle, Circle);
_OMNIUI_DEFINE_FREE_SHAPE(FreeEllipse, Ellipse);
_OMNIUI_DEFINE_FREE_SHAPE(FreeLine, Line);
_OMNIUI_DEFINE_FREE_SHAPE(FreeRectangle, Rectangle);
_OMNIUI_DEFINE_FREE_SHAPE(FreeTriangle, Triangle);

#undef _OMNIUI_DEFINE_FREE_SHAPE

OMNIUI_NAMESPACE_CLOSE_SCOPE
