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

    std::shared_ptr<GestureManager> m_defaultGestureManager;
    std::vector<std::shared_ptr<GestureManager>> m_gestureManagers;

    // All the managers of the children
    std::unordered_set<GestureManager*> m_cachedManagers;
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
    data.m_cachedGestures.clear();
    data.m_cachedManagers.clear();
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
    // Get all the managers
    if (this->isVisible())
    {
        this->_collectManagers(cacheManagers);
    }
    for (auto* manager : cacheManagers)
    {
        manager->setView(projection, view, { width, height });
    }
    for (auto* manager : cacheManagers)
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
        for (auto* manager : data.m_cachedManagers)
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

        for (auto* manager : cachedManagers)
        {
            filterPrevented(allGestures);
            manager->prevent(allGestures);
        }
    }

    {
        for (auto* manager : cachedManagers)
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

    for (auto* manager : data.m_cachedManagers)
    {
        manager->postProcess();
    }

    AbstractContainer::_postDrawContent(projection, view);

    data.m_drawList->endFrame();
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

const DrawData& Scene::_getDrawData() const
{
    return _getData<SceneData>().m_drawList->getDrawData();
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
