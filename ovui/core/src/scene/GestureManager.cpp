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

#include <omni/ui/platform/Log.h>

#include <omni/ui/Profile.h>

#include <omni/ui/scene/AbstractGesture.h>
#include <omni/ui/scene/AbstractItem.h>
#include <omni/ui/scene/AbstractShape.h>
#include <omni/ui/scene/DragGesture.h>
#include <omni/ui/scene/GestureManager.h>
#include <omni/ui/scene/ScrollGesture.h>

#include <algorithm>
#include <iterator>


OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

static constexpr uint64_t kProfilerMask = 1;

struct GestureManager::GestureManagerData
{
    std::unique_ptr<GestureManagerData> m_data;
    // A data structure that stores the latest prevention-related state for each
    // gesture currently being managed. By preserving this state information
    // across frames, the prevention logic can optimize its processing, avoiding
    // unnecessary checks for gestures whose state hasn't changed.
    std::unordered_map<AbstractGesture*, GestureState> m_preventionStateCache;

    std::unordered_map<AbstractGesture*, PreventCache> m_cachedGestures;

    Matrix44 m_projection = Matrix44{ (Float)1.0 };
    Matrix44 m_view = Matrix44{ (Float)1.0 };
    Vector2 m_frameSize = Vector2{ (Float)0.0 };
    uint32_t m_maxWait = 0;
};

GestureManager::GestureManager()
    : m_data(new GestureManagerData)
{
}

GestureManager::~GestureManager()
{
}

void GestureManager::setView(const Matrix44& projection, const Matrix44& view, const Vector2& frameSize)
{
    auto& data = *m_data;
    data.m_projection = projection;
    data.m_view = view;
    data.m_frameSize = frameSize;
}

void GestureManager::preProcess(const MouseInput& input)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& data = *m_data;
    MouseInput amendedInput = this->amendInput(input);
    {
        for (auto&& it : data.m_cachedGestures)
        {
            AbstractGesture* gesture = it.first;
            gesture->dispatchInput(amendedInput, data.m_projection, data.m_view, data.m_frameSize);
        }
    }

    {
        for (auto&& it : data.m_cachedGestures)
        {
            AbstractGesture* gesture = it.first;
            gesture->preProcess(data.m_projection, data.m_view);
        }
    }

    {
        for (auto&& it : data.m_cachedGestures)
        {
            AbstractGesture* gesture = it.first;

            auto sender = gesture->getSender();
            if (!sender || !sender->computeVisibility())
            {
                continue;
            }

            auto state = gesture->getState();
            if (it.second.canBePreventedState == state)
            {
                // If the gesture didn't change, we don't call python code
                continue;
            }

            it.second.canBePreventedState = state;

            gesture->_setCanBePrevented(this->canBePrevented(gesture));
        }
    }

}

void GestureManager::prevent(const std::unordered_set<AbstractGesture*>& allGestures)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& data = *m_data;

    // Step 1: Clean up non-existent gestures from cached prevention states
    for (auto it = data.m_preventionStateCache.begin(); it != data.m_preventionStateCache.end();)
    {
        if (allGestures.find(it->first) == allGestures.end())
        {
            it = data.m_preventionStateCache.erase(it);
        }
        else
        {
            ++it;
        }
    }

    // Step 2: Identify gestures that need checking
    std::vector<AbstractGesture*> gesturesToCheck;

    for (auto* gesture : allGestures)
    {
        auto gestureState = gesture->getState();
        auto emplaced = data.m_preventionStateCache.emplace(gesture, gestureState);
        GestureState& cachedState = emplaced.first->second;

        // If gesture state hasn't changed, skip this gesture
        if (!emplaced.second && cachedState == gestureState && gesture->getManager().get() == this)
        {
            continue;
        }

        // State has changed, update cache and add to check list
        cachedState = gestureState;
        gesturesToCheck.push_back(gesture);
    }

    // Step 3: Attempt to prevent checked gestures
    // Reversed logic: call this->shouldPrevent for all the gestures against changed gestures
    // It was before (slow): call this->shouldPrevent for changed gestures against all the gestures
    if (!gesturesToCheck.empty())
    {
        for (auto&& it : data.m_cachedGestures)
        {
            AbstractGesture* preventingGesture = it.first;

            // Ignore nullptrs and gestures with no sender
            if (!preventingGesture || !preventingGesture->getSender())
            {
                continue;
            }

            for (auto* gestureToPrevent : gesturesToCheck)
            {
                if (gestureToPrevent == preventingGesture)
                {
                    continue;
                }

                if (this->shouldPrevent(gestureToPrevent, preventingGesture))
                {
                    gestureToPrevent->setState(GestureState::ePrevented);
                }
            }
        }
    }
}

void GestureManager::process()
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& data = *m_data;
    if (data.m_cachedGestures.empty())
    {
        OMNIUI_LOG_WARN("GestureManager::process - No Cached Gestures, this is possibly because the Scene was destroyed while still processing.");
        return;
    }

    for (auto&& it : data.m_cachedGestures)
    {
        AbstractGesture* gesture = it.first;
        if (gesture->isStateChanged())
        {
            gesture->process();
        }
    }
}

void GestureManager::postProcess()
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& data = *m_data;
    if (data.m_cachedGestures.empty())
    {
        OMNIUI_LOG_WARN("GestureManager::postProcess - No Cached Gestures, this is possibly because the Scene was destroyed while still processing.");
        return;
    }

    for (auto&& it : data.m_cachedGestures)
    {
        AbstractGesture* gesture = it.first;
        gesture->postProcess();
    }
}

bool GestureManager::canBePrevented(AbstractGesture* gesture) const
{
    auto state = gesture->getState();
    // Only some gestures can be prevented
    return state == GestureState::eBegan || state == GestureState::eChanged || state == GestureState::eEnded;
}

bool GestureManager::shouldPrevent(AbstractGesture* gesture, const AbstractGesture* gesturePreventer) const
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    // Prevent the gesture if they start at the same time
    auto statePreventer = gesturePreventer->getState();

    // This previously checked:
    //    bool shouldPrevent = statePreventer == GestureState::eChanged || statePreventer == GestureState::eEnded;
    // It is unclear the intent of the "|| statePreventer == GestureState::eEnded", but it interferes with
    // mouse-chording (i.e. one gesture is drag via right mouse and another is drag via middle + right mouse).
    // In the chording case, the middle + right drag will cancel the right drag, and that should not
    // prevent middle + right drag from starting.
    //
    bool shouldPrevent = statePreventer == GestureState::eChanged;
    if (shouldPrevent)
    {
        shouldPrevent = gesturePreventer->getGesturePayload()->rayDistance <= gesture->getGesturePayload()->rayDistance;

        // Another hack; primarily for default camera manipulation
        // "Right-drag" is camera look and "Right-mouse + Scroll" adjusts flight speed
        // Flight mode is also entered when "Right-mouse-down", so in this case the scroll
        // should not be prevented as it needs to still adjust speed while navigating
        // This likely only works due to Scroll gesture having a single state of eEnded
        //
        if (shouldPrevent)
        {
            const DragGesture* dragGesturePreventer = dynamic_cast<const DragGesture*>(gesturePreventer);
            if (dragGesturePreventer)
            {
                const ScrollGesture* scrollGesture = dynamic_cast<const ScrollGesture*>(gesture);
                if (scrollGesture)
                {
                    const uint32_t dragMods = dragGesturePreventer->getModifiers();
                    const uint32_t scrollMods = scrollGesture->getModifiers();
                    const bool modsMatch = (dragMods == scrollMods) || scrollMods == UINT32_MAX;
                    if (modsMatch)
                    {
                        // This compares getMouseButton bitmask directly as they must match exactly
                        // When they match return false for "do not prevent"
                        //
                        return GestureButtons(dragGesturePreventer->getMouseButton()) == GestureButtons(scrollGesture->getMouseButton()) ? false : true;
                    }
                }
            }
        }
    }
    else if (statePreventer == GestureState::eEnded)
    {
        shouldPrevent = gesturePreventer->getGesturePayload()->rayDistance <= gesture->getGesturePayload()->rayDistance;
        if (shouldPrevent)
        {
            // Preserve the GestureState::eEnded behavior mentioned above by validating the new drag-gesture
            // has all of the mouse-buttons the current drag gesture does.
            //
            const DragGesture* dragGesturePreventer = dynamic_cast<const DragGesture*>(gesturePreventer);
            if (dragGesturePreventer)
            {
                const DragGesture* dragGesture = dynamic_cast<const DragGesture*>(gesture);
                if (dragGesture)
                {
                    const uint32_t dragModsA = dragGesturePreventer->getModifiers();
                    const uint32_t dragModsB = dragGesture->getModifiers();
                    const bool modsMatch = (dragModsA == dragModsB) || dragModsB == UINT32_MAX;
                    if (modsMatch)
                    {
                        const GestureButtons buttonsB(dragGesture->getMouseButton());
                        if (buttonsB.isMultiButton() && buttonsB.contains(dragGesturePreventer->getMouseButton()))
                        {
                            // All buttons in first drag are in new drag, do not prevent it
                            return false;
                        }
                    }
                }
            }
        }
    }

    return shouldPrevent;
}

MouseInput GestureManager::amendInput(MouseInput input) const
{
    // Nothing to do. Use the given input with no change.
    return input;
}

void GestureManager::_trackGesture(AbstractGesture* gesture)
{
    m_data->m_cachedGestures.emplace(std::piecewise_construct, std::forward_as_tuple(gesture), std::forward_as_tuple());
}

void GestureManager::_loseGesture(AbstractGesture* gesture)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    m_data->m_cachedGestures.erase(gesture);
}

void GestureManager::_collectGestures(std::unordered_set<AbstractGesture*>& gesture) const
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    auto& data = *m_data;
    std::transform(data.m_cachedGestures.begin(), data.m_cachedGestures.end(), std::inserter(gesture, gesture.end()),
                   [](const auto& cache) { return cache.first; });
}

void GestureManager::setMaxWait(uint32_t maxWait, bool force)
{
    // Take the greatest maximum wait length
    auto& data = *m_data;
    data.m_maxWait = force ? maxWait : std::max(data.m_maxWait, maxWait);
}

void GestureManager::setMaxWait(uint32_t maxWait)
{
    setMaxWait(maxWait, false);
}

OMNIUI_SCENE_API

uint32_t GestureManager::getMaxWait() const
{
    return m_data->m_maxWait;
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
