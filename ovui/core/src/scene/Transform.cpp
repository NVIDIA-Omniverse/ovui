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
#include <omni/ui/platform/Log.h>

#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/Transform.h>

#include "AbstractContainerData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct Transform::TransformData : public AbstractContainer::AbstractContainerData
{
    TransformData(Matrix44 m) : m_cachedTransform(m) {}

    ~TransformData() override = default;

    Matrix44 m_cachedTransform;

    std::shared_ptr<TransformBasis> m_basis;
};


Transform::Transform(const Matrix44& transform)
    : AbstractContainer(new TransformData(transform))
{
    this->setTransform(transform);
}

Transform::Transform()
    : Transform(Matrix44{ (Float)1.0 })
{
}


Transform::~Transform()
{
    this->destroy();
}

void Transform::destroy()
{
    auto& data = _getData<TransformData>();
    auto drawList = this->_getDrawList();
    if (drawList && !data.m_bufferIndex.empty())
    {
        // Calling begin and end should remove the buffer in drawList
        drawList->clearBuffers(data.m_bufferIndex);
        data.m_bufferIndex.clear();
    }

    if (data.m_basis)
    {
        data.m_basis->_detachFromTransform();
        data.m_basis = nullptr;
    }

    AbstractContainer::destroy();
}

void Transform::_preDrawContent(
    const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height)
{
    Matrix44 accumulated;
    if (this->getScaleTo() != Space::eCurrent || this->getLookAt() != LookAt::eNone)
    {
        // We need to cache AccumulatedTransform
        accumulated = this->getParent()->getAccumulatedTransform();
    }

    auto& data = _getData<TransformData>();
    Matrix44 prevCachedTransform = data.m_cachedTransform;

    if (this->getScaleTo() == Space::eNdc || this->getScaleTo() == Space::eScreen)
    {
        // Rotate accumulated matrix to orient axes to the same direction with
        // the camera.
        Matrix44 rotated = accumulated;
        rotated.setLookAtView(view);

        // Get the position of the origin and X axis in NDC
        Matrix44 pvt = projection * view * rotated;
        Vector4 origin = pvt * Vector4{ 0.0, 0.0, 0.0, 1.0 };
        Vector4 axis = pvt * Vector4{ 1.0, 0.0, 0.0, 1.0 };

        // The length of X in NDC
        // TODO: We need to do it for each axis, but since we normalize the
        // screen aspect, it sould be OK
        Float scale = (Float)1.0 / glm::distance(Vector3{ origin / origin.w }, Vector3{ axis / axis.w });
        if (this->getScaleTo() == Space::eScreen)
        {
            // Divide by resolution to convert to Screen
            scale /= width;
        }
        data.m_cachedTransform = Matrix44::getScaleMatrix(scale, scale, scale) * this->getTransform();
    }
    else
    {
        if (this->getScaleTo() != Space::eCurrent)
        {
            OMNIUI_LOG_ERROR_ONCE("[omni.ui.scene] Transform doesn't support scaling to %s space",
                                getSpaceName(this->getScaleTo()).c_str());
        }

        if (this->getBasis())
        {
            data.m_cachedTransform = this->getBasis()->getMatrix() * this->getTransform();
        }
        else
        {
            data.m_cachedTransform = this->getTransform();
        }
    }

    if (this->getLookAt() == LookAt::eCamera)
    {
        Matrix44 need = accumulated * data.m_cachedTransform;
        need.setLookAtView(view);

        data.m_cachedTransform = accumulated.getInverse() * need;
    }

    if (this->_isCaching() && prevCachedTransform != data.m_cachedTransform)
    {
        this->forceDirty(DirtyReason::kDirtyReasonDescendantChanged);
        // Update the all transform descendants.
        this->_dirtyTransform();
    }

    AbstractContainer::_preDrawContent(input, projection, view, width, height);
}

void Transform::_drawContent(const Matrix44& projection, const Matrix44& view)
{
    auto drawList = this->_getDrawList();
    if (OMNIUI_UNLIKELY(static_cast<bool>(drawList) == false))
    {
        return;
    }

    auto& data = _getData<TransformData>();
    drawList->beginTransform(data.m_cachedTransform, data.m_bufferIndex, data.m_basis);

    this->_drawChildren(projection, view);

    OMNIUI_ASSERT(drawList == this->_getDrawList());
    data.m_bufferIndex = drawList->endTransform();
}

Matrix44 Transform::getAccumulatedTransform() const
{
    if (this->getBasis())
    {
        return this->getBasis()->getMatrix() * this->getTransform();
    }

    // TODO: the recursion can be slow. We need to cache it.
    auto& data = _getData<TransformData>();
    if (this->getParent())
    {
        return this->getParent()->getAccumulatedTransform() * data.m_cachedTransform;
    }

    return data.m_cachedTransform;
}

std::shared_ptr<TransformBasis> Transform::getBasis() const
{
    auto& data = _getData<TransformData>();
    return data.m_basis;
}

void Transform::setBasis(std::shared_ptr<TransformBasis> basis)
{
    auto& data = _getData<TransformData>();
    if (data.m_basis)
    {
        data.m_basis->_detachFromTransform();
    }

    if (basis)
    {
        basis->_attachToTransform();
    }

    data.m_basis = basis;
}

void Transform::_dirtyTransform()
{
    DrawBufferIndex& drawBufferIndex = this->_getDrawBufferIndex();
    drawBufferIndex.setTransformDirty(true);

    for (auto& child : _getChildren())
    {
        Transform* pTransform = dynamic_cast<Transform*>(child.get());
        if (pTransform)
        {
            pTransform->_dirtyTransform();
        }
    }
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
