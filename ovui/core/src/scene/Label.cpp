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

#include <omni/ui/platform/Assert.h>

#include <omni/ui/scene/AbstractContainer.h>
#include <omni/ui/scene/DragGesture.h>
#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/Label.h>
#include <omni/ui/scene/Math.h>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

Label::Label(const std::string& text)
{
    this->setTextChangedFn(std::bind(&This::_dirty, this));
    this->setColorChangedFn(std::bind(&This::_dirty, this));
    this->setAlignmentChangedFn(std::bind(&This::_dirty, this));
    this->setSizeChangedFn(std::bind(&This::_dirty, this));
    this->setText(text);
}

Label::~Label() = default;

void Label::_drawContent(const Matrix44& projection, const Matrix44& view)
{   
    if (this->getText().empty())
    {
        return;
    }

    auto drawList = this->_getDrawList();
    if (OMNIUI_LIKELY(drawList))
    {
        drawList->addText(this->getText(), { 0.0, 0.0, 0.0 },
            this->getColor(), this->getSize(), this->getAlignment());
    }
}

void Label::intersect(const Vector3 origin,
                      const Vector3 direction,
                      const Vector2 mouse,
                      const Matrix44& projection,
                      const Matrix44& view,
                      GestureState state)
{
}

const AbstractGesture::GesturePayload* Label::getGesturePayload() const
{
    return nullptr;
}

const AbstractGesture::GesturePayload* Label::getGesturePayload(GestureState state) const
{
    return nullptr;
}

void Label::_dirty()
{
    this->forceDirty(DirtyReason::kDirtyReasonContentChanged);
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
