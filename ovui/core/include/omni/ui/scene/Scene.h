/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "AbstractContainer.h"
#include "DepthGroup.h"
#include "DistanceFadeGroup.h"
#include "WidthSpaceGroup.h"
#include "SelectionGroup.h"
#include "Object.h"

#include <memory>
#include <unordered_set>
#include <vector>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class DrawBuffer;
class DrawBufferIndex;
struct DrawData;
class DrawList;
class AbstractGesture;



/**
 * @brief Represents the root of the scene and holds the shapes, gestures and
 * managers.
 */
class OMNIUI_SCENE_CLASS_API Scene : public AbstractContainer
{
    OMNIUI_SCENE_OBJECT(Scene);

public:
    OMNIUI_SCENE_API
    virtual ~Scene();

    OMNIUI_SCENE_API
    void destroy() override;

    /**
     * @brief Returns gesture manager used by default.
     */
    OMNIUI_SCENE_API
    const std::shared_ptr<GestureManager>& getDefaultGestureManager() const;

    /**
     * @brief Return the number of buffers used. Using for unit testing.
     */
    OMNIUI_SCENE_API
    size_t getDrawListBufferCount() const;

    /** Empty unless explicit depth policies are present. Valid until the next draw. */
    OMNIUI_SCENE_API
    const std::vector<DepthDrawBuffer>& getDepthDrawBuffers() const;

    /** Explicit policies can be present even if every scoped buffer is hidden. */
    OMNIUI_SCENE_API
    bool hasDepthPolicies() const;

    /** Query the current hierarchy before collection, without touching geometry.
     * True when a visible item resolves to TEST_ONLY or TEST_AND_WRITE. Default
     * and overlay policies do not request external scene depth. Items created
     * later during a manipulator's draw are first reported by the next query.
     */
    OMNIUI_SCENE_API
    bool hasVisibleDepthDemand() const;

    /** Active per-buffer fades, valid until the next draw. */
    OMNIUI_SCENE_API
    const std::vector<DistanceFadeDrawBuffer>& getDistanceFadeDrawBuffers() const;
    OMNIUI_SCENE_API
    bool hasDistanceFades() const;

    /** Visible scoped width policies, valid until the next draw; empty for ordinary scenes. */
    OMNIUI_SCENE_API
    const std::vector<WidthSpaceDrawBuffer>& getWidthSpaceDrawBuffers() const;
    /** Includes hidden width groups even when the visible collection is empty. */
    OMNIUI_SCENE_API
    bool hasWidthSpacePolicies() const;

    /** Visible nonzero selection labels, valid until the next draw/destruction.
     * Empty for ordinary scenes. This accessor does not perform a pick.
     */
    OMNIUI_SCENE_API
    const std::vector<SelectionDrawBuffer>& getSelectionDrawBuffers() const;

protected:
    friend class SelectionGroup;
    void _requestSelectionCollection() const;
    void _collectSelectionDrawBuffers();
    friend class WidthSpaceGroup;
    void _requestWidthSpaceCollection() const;
    void _collectWidthSpaceDrawBuffers();
    friend class DistanceFadeGroup;
    void _requestDistanceFadeCollection() const;
    void _collectDistanceFadeDrawBuffers();
    friend class DepthGroup;
    void _requestDepthCollection() const;
    void _collectDepthDrawBuffers();
    friend class AbstractItem;
    friend class SceneView;

    OMNIUI_SCENE_API
    Scene();

    void _preDrawContent(
        const MouseInput&, const Matrix44& projection, const Matrix44& view, float width, float height) override;
    void _drawContent(const Matrix44& projection, const Matrix44& view) override;
    void _postDrawContent(const Matrix44& projection, const Matrix44& view) override;

    const DrawData& _getDrawData() const;
    DrawList* _getDrawList() const;
    DrawBufferIndex& _getDrawBufferIndex() override;

    const Scene* _getScene() const override
    {
        return this;
    }

    // Override this interface to always call _drawContent()
    bool _needDrawContent() override
    {
        return true;
    }

    template <typename T> T& _getData() const
    {
        return *m_data;
    }

    struct SceneData;
    std::unique_ptr<SceneData> m_data;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
