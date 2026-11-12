/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/platform/Assert.h>
#include <omni/ui/platform/Log.h>

#include <omni/ui/scene/DepthGroup.h>
#include <omni/ui/scene/DistanceFadeGroup.h>
#include <omni/ui/scene/WidthSpaceGroup.h>
#include <omni/ui/scene/SelectionGroup.h>
#include <cmath>
#include <atomic>
#include <stdexcept>
#include <omni/ui/scene/Scene.h>
#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/Transform.h>

#include "AbstractContainerData.h"
#include "DragFollow.h"

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
    this->_setScaleToChangedFn([this](const auto&) { this->_markWritten(); });
    this->_setLookAtChangedFn([this](const auto&) { this->_markWritten(); });
    this->setTransform(transform);
}

void Transform::setTransform(Matrix44 const& value)
{
    if (checkIfEqual(m_transform, value))
    {
        return;
    }

    {
        DragFollow::Write write(this);
        write.noteTransform(this, m_transform, value);
        m_transform = value;
        this->_markWritten();
    }
    m__setTransformChangedFnCallbacks(value);
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
    this->_markWritten();
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

SelectionGroup::SelectionGroup(uint64_t id)
{
    this->setSelectionId(id);
}

uint64_t SelectionGroup::getSelectionId() const
{
    return m_selectionId;
}

void SelectionGroup::setSelectionId(uint64_t id)
{
    if (m_selectionId != id)
    {
        m_selectionId = id;
        if (auto* scene = this->_getScene())
            scene->_requestSelectionCollection();
        this->forceDirty(DirtyReason::kDirtyReasonDescendantChanged);
    }
}

std::shared_ptr<const SelectionData> SelectionGroup::getSelectionData() const
{
    return m_selectionData;
}

void SelectionGroup::setSelectionData(std::shared_ptr<const SelectionData> data)
{
    if (m_selectionData != data)
    {
        m_selectionData = std::move(data);
        if (auto* scene = this->_getScene())
            scene->_requestSelectionCollection();
        this->forceDirty(DirtyReason::kDirtyReasonDescendantChanged);
    }
}

void SelectionGroup::_preDrawContent(
    const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height)
{
    if (auto* scene = this->_getScene())
        scene->_requestSelectionCollection();
    Transform::_preDrawContent(input, projection, view, width, height);
}

void SelectionGroup::_drawContent(const Matrix44& projection, const Matrix44& view)
{
    if (auto* scene = this->_getScene())
        scene->_requestSelectionCollection();
    Transform::_drawContent(projection, view);
}

namespace
{
// Only a fast negative check, never ownership of a Scene or a group. Unattached
// and already-destroyed-but-retained groups can cause an extra hierarchy query.
std::atomic<size_t> s_depthGroups{0};
}

DepthGroup::DepthGroup(DepthPolicy policy)
{
    this->setDepthPolicy(policy);
    s_depthGroups.fetch_add(1, std::memory_order_relaxed);
}

DepthGroup::~DepthGroup()
{
    s_depthGroups.fetch_sub(1, std::memory_order_relaxed);
}

bool DepthGroup::_hasInstances()
{
    return s_depthGroups.load(std::memory_order_relaxed) != 0;
}

DepthPolicy DepthGroup::getDepthPolicy() const
{
    return m_depthPolicy;
}

void DepthGroup::setDepthPolicy(DepthPolicy policy)
{
    switch (policy)
    {
    case DepthPolicy::eInherit:
    case DepthPolicy::eDefault:
    case DepthPolicy::eTestOnly:
    case DepthPolicy::eTestAndWrite:
    case DepthPolicy::eOverlay:
        break;
    default:
        return;
    }
    if (m_depthPolicy != policy)
    {
        m_depthPolicy = policy;
        if (auto* scene = this->_getScene())
        {
            scene->_requestDepthCollection();
        }
        this->forceDirty(DirtyReason::kDirtyReasonDescendantChanged);
    }
}

void DepthGroup::_preDrawContent(
    const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height)
{
    if (m_depthPolicy != DepthPolicy::eInherit)
    {
        if (auto* scene = this->_getScene())
        {
            scene->_requestDepthCollection();
        }
    }
    Transform::_preDrawContent(input, projection, view, width, height);
}

void DepthGroup::_drawContent(const Matrix44& projection, const Matrix44& view)
{
    // Also covers groups created by a manipulator after the pre-draw traversal.
    if (m_depthPolicy != DepthPolicy::eInherit)
    {
        if (auto* scene = this->_getScene())
        {
            scene->_requestDepthCollection();
        }
    }
    Transform::_drawContent(projection, view);
}

DistanceFadeGroup::DistanceFadeGroup(const DistanceFade& fade)
{
    this->setDistanceFade(fade);
}

const DistanceFade& DistanceFadeGroup::getDistanceFade() const
{
    return m_fade;
}

void DistanceFadeGroup::setDistanceFade(const DistanceFade& fade)
{
    const double normalLength2 = glm::dot(fade.planeNormal, fade.planeNormal);
    if (!std::isfinite(fade.start) || !std::isfinite(fade.end) ||
        !std::isfinite(normalLength2) || (normalLength2 != 0 && std::abs(normalLength2 - 1.0) > 1e-6))
        throw std::invalid_argument("DistanceFade requires finite distances and a zero or unit normal");
    if (!(m_fade == fade))
    {
        m_fade = fade;
        if (auto* scene = this->_getScene())
            scene->_requestDistanceFadeCollection();
        this->forceDirty(DirtyReason::kDirtyReasonDescendantChanged);
    }
}

void DistanceFadeGroup::_preDrawContent(
    const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height)
{
    if (auto* scene = this->_getScene())
        scene->_requestDistanceFadeCollection();
    Transform::_preDrawContent(input, projection, view, width, height);
}

void DistanceFadeGroup::_drawContent(const Matrix44& projection, const Matrix44& view)
{
    if (auto* scene = this->_getScene())
        scene->_requestDistanceFadeCollection();
    Transform::_drawContent(projection, view);
}

WidthSpaceGroup::WidthSpaceGroup(StrokeWidthSpace space, Float pointAntialiasingWidth)
{
    this->setWidthSpace(space);
    this->setPointAntialiasingWidth(pointAntialiasingWidth);
}

Float WidthSpaceGroup::getPointAntialiasingWidth() const
{
    return m_pointAntialiasingWidth;
}

void WidthSpaceGroup::setPointAntialiasingWidth(Float width)
{
    if (!std::isfinite(width) || width < 0.0)
        throw std::invalid_argument("Point antialiasing width must be finite and nonnegative");
    if (m_pointAntialiasingWidth != width)
    {
        m_pointAntialiasingWidth = width;
        if (auto* scene = this->_getScene())
            scene->_requestWidthSpaceCollection();
        this->forceDirty(DirtyReason::kDirtyReasonDescendantChanged);
    }
}

StrokeWidthSpace WidthSpaceGroup::getWidthSpace() const
{
    return m_space;
}

void WidthSpaceGroup::setWidthSpace(StrokeWidthSpace space)
{
    if (space != StrokeWidthSpace::ePixels && space != StrokeWidthSpace::eWorld &&
        space != StrokeWidthSpace::ePixelDiameter)
        throw std::invalid_argument("Unknown stroke width space");
    if (m_space != space)
    {
        m_space = space;
        if (auto* scene = this->_getScene())
            scene->_requestWidthSpaceCollection();
        this->forceDirty(DirtyReason::kDirtyReasonDescendantChanged);
    }
}

void WidthSpaceGroup::_preDrawContent(
    const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height)
{
    if (auto* scene = this->_getScene())
        scene->_requestWidthSpaceCollection();
    Transform::_preDrawContent(input, projection, view, width, height);
}

void WidthSpaceGroup::_drawContent(const Matrix44& projection, const Matrix44& view)
{
    if (auto* scene = this->_getScene())
        scene->_requestWidthSpaceCollection();
    Transform::_drawContent(projection, view);
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
