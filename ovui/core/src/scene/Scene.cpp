/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/platform/Assert.h>
#include <omni/ui/platform/Log.h>

#include <omni/ui/scene/DrawList.h>
#include <omni/ui/scene/GestureManager.h>
#include <omni/ui/scene/Scene.h>

#include <algorithm>
#include <iterator>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

static constexpr uint64_t kProfilerMask = 1;

struct Scene::SceneData
{
    SceneData()
        : m_drawList(new DrawList)
        , m_defaultGestureManager(std::make_shared<GestureManager>())
    {
    }

    ~SceneData() = default;

    std::unique_ptr<DrawList> m_drawList;
    std::vector<DepthDrawBuffer> m_depthDrawBuffers;
    bool m_depthCollectionRequested = false;
    bool m_hasDepthPolicies = false;
    std::vector<DistanceFadeDrawBuffer> m_distanceFadeDrawBuffers;
    bool m_distanceFadeCollectionRequested = false;
    bool m_hasDistanceFadeGroups = false;
    std::vector<WidthSpaceDrawBuffer> m_widthSpaceDrawBuffers;
    bool m_widthSpaceCollectionRequested = false;
    bool m_hasWidthSpaceGroups = false;
    std::vector<SelectionDrawBuffer> m_selectionDrawBuffers;
    bool m_selectionCollectionRequested = false;
    bool m_hasSelectionGroups = false;

    std::shared_ptr<GestureManager> m_defaultGestureManager;
    std::vector<std::shared_ptr<GestureManager>> m_gestureManagers;

    // All the managers of the children, in the order of collection. When two
    // managers want the same input, this order decides which one gets it.
    std::unordered_set<GestureManager*> m_cachedManagers;
    // shared_ptr keeps the managers of m_cachedManagers alive for the frame,
    // preventing use-after-free if a callback destroys a shape.
    std::vector<std::shared_ptr<GestureManager>> m_cachedManagersAlive;
    std::unordered_set<AbstractGesture*> m_cachedGestures;
};

Scene::Scene() : m_data(new SceneData)
{
}

Scene::~Scene()
{
    this->destroy();
}

void Scene::destroy()
{
    SceneData& data = _getData<SceneData>();
    if (data.m_drawList)
    {
        data.m_drawList->destroy();
    }
    data.m_depthDrawBuffers.clear();
    data.m_depthCollectionRequested = data.m_hasDepthPolicies = false;
    data.m_distanceFadeDrawBuffers.clear();
    data.m_distanceFadeCollectionRequested = data.m_hasDistanceFadeGroups = false;
    data.m_widthSpaceDrawBuffers.clear();
    data.m_widthSpaceCollectionRequested = data.m_hasWidthSpaceGroups = false;
    data.m_selectionDrawBuffers.clear();
    data.m_selectionCollectionRequested = data.m_hasSelectionGroups = false;
    data.m_cachedGestures.clear();
    data.m_cachedManagers.clear();
    data.m_cachedManagersAlive.clear();
    AbstractContainer::destroy();
}

void Scene::_preDrawContent(
    const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height)
{
    // Transform will update the cache state of its draw buffer before beginFrame().
    AbstractContainer::_preDrawContent(input, projection, view, width, height);

    SceneData& data = _getData<SceneData>();

    // If caching is on, the preparation of draw list needs to be postponed into _drawContent().
    if (!this->_isCaching())
    {
        data.m_drawList->beginFrame();
    }

    // TODO: We need to clean and keep the capacity
    auto& cacheManagers = data.m_cachedManagers;
    cacheManagers.clear();
    data.m_cachedManagersAlive.clear();
    // Keep shared_ptrs to the managers so they stay alive for the frame.
    // Any manager in cacheManagers was inserted via gesture->getManager().get() in
    // AbstractShape::_collectManagers, so it has at least one tracked gesture
    // whose shared_ptr<GestureManager> we can recover.
    if (this->isVisible())
    {
        this->_collectManagers(cacheManagers);
        std::unordered_set<AbstractGesture*> gestures;
        for (auto* raw : cacheManagers)
        {
            gestures.clear();
            raw->_collectGestures(gestures);
            if (!gestures.empty())
            {
                data.m_cachedManagersAlive.push_back((*gestures.begin())->getManager());
            }
        }
    }
    for (auto& manager : cacheManagers)
    {
        manager->setView(projection, view, { width, height });
    }
    for (auto& manager : cacheManagers)
    {
        manager->preProcess(input);
    }
}

void Scene::_drawContent(const Matrix44& projection, const Matrix44& view)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    SceneData& data = _getData<SceneData>();
    auto& cachedGestures = data.m_cachedGestures;
    auto& cachedManagers = data.m_cachedManagers;

    // TODO: We need to clean and keep the capacity
    cachedGestures.clear();

    {
        for (auto& manager : cachedManagers)
        {
            manager->_collectGestures(cachedGestures);
        }
    }

    {
        std::unordered_set<AbstractGesture*> allGestures;
        // Ignore nullptrs and gestures with invisible senders.
        std::copy_if(cachedGestures.begin(), cachedGestures.end(), std::inserter(allGestures, allGestures.end()),
                     [](AbstractGesture* gesture)
                     {
                         if (gesture == nullptr)
                             return false;
                         auto sender = gesture->getSender();
                         return (sender != nullptr) && (sender->computeVisibility());
                     });
        // Filter prevented gestures.
        auto filterPrevented = [](auto& allGestures)
        {
            for (auto it = allGestures.begin(); it != allGestures.end();)
            {
                auto* gesture = *it;
                if (!gesture->_getCanBePrevented() || gesture->getState() == GestureState::ePrevented)
                {
                    it = allGestures.erase(it);
                }
                else
                {
                    ++it;
                }
            }
        };

        for (auto& manager : cachedManagers)
        {
            filterPrevented(allGestures);
            manager->prevent(allGestures);
        }
    }

    {
        for (auto& manager : cachedManagers)
        {
            manager->process();
        }
    }

    // Gestures can change the content, calling beginFrame() after to clear the dirty buffers.
    if (this->_isCaching())
    {
        data.m_drawList->beginFrame();
    }

    {
        DrawBufferIndex& drawBufferIndex = this->_getDrawBufferIndex();
        if (AbstractContainer::_needDrawContent())
        {
            this->_drawChildren(projection, view);
        }
    }
}

void Scene::_postDrawContent(const Matrix44& projection, const Matrix44& view)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    SceneData& data = _getData<SceneData>();

    for (auto& manager : data.m_cachedManagers)
    {
        manager->postProcess();
    }

    AbstractContainer::_postDrawContent(projection, view);

    data.m_drawList->endFrame();
    data.m_cachedManagers.clear();
    data.m_cachedManagersAlive.clear();
    data.m_cachedGestures.clear();
    // Existing scenes incur no extra walk. Explicit-policy scenes recollect even
    // with cached geometry: visibility and destruction need not dirty root buffers.
    if (data.m_depthCollectionRequested || data.m_hasDepthPolicies)
    {
        this->_collectDepthDrawBuffers();
    }
    // Keep requests made between frames (including changes to hidden groups)
    // until collection has consumed them.
    data.m_depthCollectionRequested = false;
    if (data.m_distanceFadeCollectionRequested || data.m_hasDistanceFadeGroups)
        this->_collectDistanceFadeDrawBuffers();
    data.m_distanceFadeCollectionRequested = false;
    if (data.m_widthSpaceCollectionRequested || data.m_hasWidthSpaceGroups)
        this->_collectWidthSpaceDrawBuffers();
    data.m_widthSpaceCollectionRequested = false;
    if (data.m_selectionCollectionRequested || data.m_hasSelectionGroups)
        this->_collectSelectionDrawBuffers();
    data.m_selectionCollectionRequested = false;
}

const std::shared_ptr<GestureManager>& Scene::getDefaultGestureManager() const
{
    return _getData<SceneData>().m_defaultGestureManager;
}

size_t Scene::getDrawListBufferCount() const
{
    auto drawList = this->_getDrawList();
    if (OMNIUI_LIKELY(drawList))
    {
        return drawList->getBufferCount();
    }
    return 0;
}

const std::vector<DepthDrawBuffer>& Scene::getDepthDrawBuffers() const
{
    return _getData<SceneData>().m_depthDrawBuffers;
}

bool Scene::hasDepthPolicies() const
{
    return _getData<SceneData>().m_hasDepthPolicies;
}

bool Scene::hasVisibleDepthDemand() const
{
    if (!DepthGroup::_hasInstances())
        return false;
    auto demand = [&](auto&& self, const AbstractContainer& container, DepthPolicy policy) -> bool
    {
        if (!container.isVisible())
            return false;
        if (const auto* group = dynamic_cast<const DepthGroup*>(&container))
            if (group->getDepthPolicy() != DepthPolicy::eInherit)
                policy = group->getDepthPolicy();
        for (const auto& child : container._getChildren())
        {
            if (!child->isVisible())
                continue;
            if (const auto* nested = dynamic_cast<const AbstractContainer*>(child.get()))
            {
                if (self(self, *nested, policy))
                    return true;
            }
            else if (policy == DepthPolicy::eTestOnly || policy == DepthPolicy::eTestAndWrite)
                return true;
        }
        return false;
    };
    return demand(demand, *this, DepthPolicy::eDefault);
}

void Scene::_requestDepthCollection() const
{
    _getData<SceneData>().m_depthCollectionRequested = true;
}

void Scene::_collectDepthDrawBuffers()
{
    auto& data = _getData<SceneData>();
    auto& result = data.m_depthDrawBuffers;
    result.clear();
    bool explicitPolicy = false;
    // Only Transform (including DepthGroup) and Scene own draw buffers.
    // Other containers can share a surrounding transform's buffers.
    auto collect = [&](auto&& self, AbstractContainer& container, DepthPolicy policy, bool visible) -> void
    {
        visible = visible && container.isVisible();
        if (auto* group = dynamic_cast<DepthGroup*>(&container))
        {
            if (group->getDepthPolicy() != DepthPolicy::eInherit)
            {
                policy = group->getDepthPolicy();
                explicitPolicy = true;
            }
        }
        if (visible && (&container == this || dynamic_cast<Transform*>(&container)))
        {
            const auto& indices = container._getDrawBufferIndex();
            for (size_t i = 0; i < indices.size(); ++i)
            {
                const auto index = indices[i];
                if (index < data.m_drawList->m_buffers.size())
                {
                    const auto* buffer = data.m_drawList->m_buffers[index].get();
                    if (buffer)
                    {
                        result.push_back({ buffer, policy });
                    }
                }
            }
        }
        for (const auto& child : container._getChildren())
        {
            if (auto* nested = dynamic_cast<AbstractContainer*>(child.get()))
            {
                self(self, *nested, policy, visible);
            }
        }
    };
    collect(collect, *this, DepthPolicy::eDefault, true);
    data.m_hasDepthPolicies = explicitPolicy;
    if (!explicitPolicy)
    {
        result.clear();
    }
}

const DrawData& Scene::_getDrawData() const
{
    return _getData<SceneData>().m_drawList->getDrawData();
}

const std::vector<DistanceFadeDrawBuffer>& Scene::getDistanceFadeDrawBuffers() const
{
    return _getData<SceneData>().m_distanceFadeDrawBuffers;
}

bool Scene::hasDistanceFades() const
{
    return !this->getDistanceFadeDrawBuffers().empty();
}

void Scene::_requestDistanceFadeCollection() const
{
    _getData<SceneData>().m_distanceFadeCollectionRequested = true;
}

void Scene::_collectDistanceFadeDrawBuffers()
{
    auto& data = _getData<SceneData>();
    auto& result = data.m_distanceFadeDrawBuffers;
    result.clear();
    data.m_hasDistanceFadeGroups = false;
    auto collect = [&](auto&& self, AbstractContainer& container, DistanceFade fade, bool visible) -> void
    {
        visible = visible && container.isVisible();
        if (auto* group = dynamic_cast<DistanceFadeGroup*>(&container))
        {
            fade = group->getDistanceFade();
            data.m_hasDistanceFadeGroups = true;
        }
        if (visible && fade.enabled && (&container == this || dynamic_cast<Transform*>(&container)))
        {
            const auto& indices = container._getDrawBufferIndex();
            for (size_t i = 0; i < indices.size(); ++i)
            {
                const auto index = indices[i];
                if (index < data.m_drawList->m_buffers.size())
                {
                    if (const auto* buffer = data.m_drawList->m_buffers[index].get())
                        result.push_back({ buffer, fade });
                }
            }
        }
        for (const auto& child : container._getChildren())
            if (auto* nested = dynamic_cast<AbstractContainer*>(child.get()))
                self(self, *nested, fade, visible);
    };
    collect(collect, *this, DistanceFade{}, true);
}

const std::vector<WidthSpaceDrawBuffer>& Scene::getWidthSpaceDrawBuffers() const
{
    return _getData<SceneData>().m_widthSpaceDrawBuffers;
}

void Scene::_requestWidthSpaceCollection() const
{
    _getData<SceneData>().m_widthSpaceCollectionRequested = true;
}

bool Scene::hasWidthSpacePolicies() const
{
    return _getData<SceneData>().m_hasWidthSpaceGroups;
}

void Scene::_collectWidthSpaceDrawBuffers()
{
    auto& data = _getData<SceneData>();
    auto& result = data.m_widthSpaceDrawBuffers;
    result.clear();
    data.m_hasWidthSpaceGroups = false;
    auto collect = [&](auto&& self, AbstractContainer& container, StrokeWidthSpace space, Float pointAa, bool visible) -> void
    {
        visible = visible && container.isVisible();
        if (auto* group = dynamic_cast<WidthSpaceGroup*>(&container))
        {
            space = group->getWidthSpace();
            pointAa = group->getPointAntialiasingWidth();
            data.m_hasWidthSpaceGroups = true;
        }
        if (visible && (&container == this || dynamic_cast<Transform*>(&container)))
        {
            const auto& indices = container._getDrawBufferIndex();
            for (size_t i = 0; i < indices.size(); ++i)
            {
                const auto index = indices[i];
                if (index < data.m_drawList->m_buffers.size())
                    if (const auto* buffer = data.m_drawList->m_buffers[index].get())
                        result.push_back({buffer, space, pointAa});
            }
        }
        for (const auto& child : container._getChildren())
            if (auto* nested = dynamic_cast<AbstractContainer*>(child.get()))
                self(self, *nested, space, pointAa, visible);
    };
    collect(collect, *this, StrokeWidthSpace::ePixels, 0.0, true);
    if (!data.m_hasWidthSpaceGroups)
        result.clear();
}

const std::vector<SelectionDrawBuffer>& Scene::getSelectionDrawBuffers() const
{
    return _getData<SceneData>().m_selectionDrawBuffers;
}

void Scene::_requestSelectionCollection() const
{
    _getData<SceneData>().m_selectionCollectionRequested = true;
}

void Scene::_collectSelectionDrawBuffers()
{
    auto& data = _getData<SceneData>();
    auto& result = data.m_selectionDrawBuffers;
    result.clear();
    data.m_hasSelectionGroups = false;
    auto collect = [&](auto&& self, AbstractContainer& container, uint64_t id,
                       std::shared_ptr<const SelectionData> metadata, bool visible) -> void
    {
        visible = visible && container.isVisible();
        if (auto* group = dynamic_cast<SelectionGroup*>(&container))
        {
            id = group->getSelectionId();
            if (auto own = group->getSelectionData())
                metadata = std::move(own);
            data.m_hasSelectionGroups = true;
        }
        if (visible && id && (&container == this || dynamic_cast<Transform*>(&container)))
        {
            const auto& indices = container._getDrawBufferIndex();
            for (size_t i = 0; i < indices.size(); ++i)
            {
                const auto index = indices[i];
                if (index < data.m_drawList->m_buffers.size())
                    if (const auto* buffer = data.m_drawList->m_buffers[index].get())
                        result.push_back({buffer, id, metadata});
            }
        }
        for (const auto& child : container._getChildren())
            if (auto* nested = dynamic_cast<AbstractContainer*>(child.get()))
                self(self, *nested, id, metadata, visible);
    };
    collect(collect, *this, uint64_t(0), {}, true);
}

DrawList* Scene::_getDrawList() const
{
    return _getData<SceneData>().m_drawList.get();
}

DrawBufferIndex& Scene::_getDrawBufferIndex()
{
    auto drawList = this->_getDrawList();
    if (OMNIUI_LIKELY(drawList))
    {
        return drawList->getRootBufferIndex();
    }

    OMNIUI_LOG_ERROR("Scene::_getDrawBufferIndex has no draw list assigned.");
    static DrawBufferIndex s_emptyIndex = {};
    return s_emptyIndex;
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
