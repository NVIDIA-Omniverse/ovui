/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include "AbstractShape.h"
#include "Math.h"
#include "Object.h"

#include <omni/ui/Alignment.h>

#include <string>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * Defines a standard label for user interface items
 */
class OMNIUI_SCENE_CLASS_API Label : public AbstractShape
{
    OMNIUI_SCENE_OBJECT(Label);

public:
    OMNIUI_SCENE_API
    virtual ~Label();

    OMNIUI_SCENE_API
    void intersect(const Vector3 origin,
                   const Vector3 direction,
                   const Vector2 mouse,
                   const Matrix44& projection,
                   const Matrix44& view,
                   GestureState state) override;

    OMNIUI_SCENE_API
    const AbstractGesture::GesturePayload* getGesturePayload() const override;

    OMNIUI_SCENE_API
    const AbstractGesture::GesturePayload* getGesturePayload(GestureState state) const override;

    /**
     * @brief This property holds the label's text.
     */
    OMNIUI_PROPERTY(std::string, text, READ, getText, WRITE, setText, NOTIFY, setTextChangedFn);

    /**
     * @brief The color of the text
     */
    OMNIUI_PROPERTY(Color4, color, DEFAULT, Color4{ 1.0 }, READ, getColor, WRITE, setColor, NOTIFY, setColorChangedFn);

    /**
     * @brief This property holds the alignment of the label's contents
     * By default, the contents of the label are left-aligned and vertically-centered.
     */
    OMNIUI_PROPERTY(Alignment, alignment, DEFAULT, Alignment::eLeftCenter, READ, getAlignment, WRITE, setAlignment, NOTIFY, setAlignmentChangedFn);

    /**
     * @brief The font size
     */
    OMNIUI_PROPERTY(float, size, DEFAULT, 12.0, READ, getSize, WRITE, setSize, NOTIFY, setSizeChangedFn);

protected:
    /**
     * @brief A standard label for user interface items
     *
     * @param text The string with the text to display
     */
    OMNIUI_SCENE_API
    Label(const std::string& text);

    OMNIUI_SCENE_API
    void _drawContent(const Matrix44& projection, const Matrix44& view) override;

    void _dirty();
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
