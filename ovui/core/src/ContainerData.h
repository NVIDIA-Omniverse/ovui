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

#include "platform/Assert.h"
#include <omni/ui/Container.h>
#include "platform/Log.h"

#include "WidgetData.h"

#include <memory>
#include <atomic>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct Container::ContainerData : public Widget::WidgetData
{
    ~ContainerData() override = default;

    class DrawCallData;
    DrawCallData* m_drawCallData = nullptr;

    inline bool destroy();
    inline bool addChild(std::shared_ptr<Widget> widget);
    inline bool clear();
};

//
// This object represents a work-around for continuing problems in omni::ui where
// users can easily write code that will delete / de-allocate the actual object
// in event handlers (i.e. callbacks from the draw-loop).
//
// The usage is simple, at the top of any call that needs to:
//  1. stop "this" from being deleted / de-allocated  during the lifetime of a block
//  2. stop clear from being executed during the lifetime of a block
//  3. stop destroy from being executed during the lifetime of a block
//
// Container::DrawCallData drawCache(std::static_pointer_cast<Container>(shared_from_this()));
//
// This will hold a single std::shared_ptr until ~DrawCallData is run, so the object
// cannot be deleted until the scope/block is left.
//
// Additionally, when the destructor is run it will check if any "clear" or "destroy" call
// was requested in the scope/block it was created in and if so call clear, then destroy
// before the (possibly last) std::shared_ptr is released.
//

class Container::ContainerData::DrawCallData
{
    // Back pointer to calling object to preserve lifetime until this object is destructed
    //
    std::shared_ptr<Container> m_scopedThis;
    ContainerData& m_data;
    std::vector<std::shared_ptr<Widget>> m_addedChildren;
    std::atomic_bool m_clearRequested = { false };
    std::atomic_bool m_destroyRequested = { false };
    std::atomic_bool m_addChildAllowed = { false };

    void dumpPythonStack(bool toStdOut = false)
    {
        IUiLog* logger = PlatformRegistry::instance().log();
        if (logger)
        {
            logger->dumpPythonStack(toStdOut);
        }
    }

    void logAnClearCachedChildren(const char* methodName)
    {
        OMNIUI_LOG_ERROR("%s was called during an event or draw, this is not supported", methodName);
        dumpPythonStack();

        if (!m_addedChildren.empty())
        {
            OMNIUI_LOG_ERROR("%zu children that were scheduled to be added are being destroyed", m_addedChildren.size());
            m_addedChildren.clear();
        }
    }

public:
    DrawCallData(std::shared_ptr<Container> thisObj, ContainerData& data, bool allowAddChild = false)
        : m_scopedThis(std::move(thisObj))
        , m_data(data)
        , m_addChildAllowed(allowAddChild)
    {
        OMNIUI_ASSERT(static_cast<bool>(m_scopedThis) == true);
        OMNIUI_ASSERT(static_cast<bool>(m_data.m_drawCallData) == false);

        m_data.m_drawCallData = this;
    }

    ~DrawCallData()
    {
        OMNIUI_ASSERT(static_cast<bool>(m_scopedThis) == true);
        OMNIUI_ASSERT(m_data.m_drawCallData == this);

        // Reset the field to nullptr so any requests processed now will go through
        //
        m_data.m_drawCallData = nullptr;

        if (m_clearRequested)
        {
            m_scopedThis->clear();
        }
        if (m_destroyRequested)
        {
            m_scopedThis->destroy();
        }
        else if (!m_addedChildren.empty())
        {
            // If destroy wasn't called, add any cached children to the object now.
            //
            for (auto&& child : m_addedChildren)
            {
                m_scopedThis->addChild(std::move(child));
            }
        }
        // Will be done by destruction anyway
        // m_scopedThis.reset();
    }

    bool allowAddChildren() const
    {
        return m_addChildAllowed;
    }

    void disAllowAddChildren()
    {
        m_addChildAllowed = false;
    }

    void clearRequested()
    {
        m_clearRequested = true;
        logAnClearCachedChildren("Container::clear");
    }

    void destroyRequested()
    {
        m_destroyRequested = true;
        logAnClearCachedChildren("Container::destroy");
    }

    void addChildRequested(std::shared_ptr<Widget> child, bool singleChild = false)
    {
        OMNIUI_LOG_WARN("Container::addChild attempting to add a child during a draw callback");
        dumpPythonStack(true);

        // If destroy was requested, don't bother adding child as the parent-object is going to be 'destroyed' anyway.
        // If clear was requested, then adding is ok, as m_addedChildren are added after delayed clear is executed.
        // Both cached destroy and clear methods will clear m_addedChildren when called so m_addedChildren should only
        // contain children added after last call to clear().
        //
        if (!m_destroyRequested)
        {
            // omni::ui::Frame (and possibly others) can only have a single child.  So
            // clear all previously cached children in those cases.
            //
            if (singleChild)
            {
                m_addedChildren.clear();
            }
            m_addedChildren.emplace_back(std::move(child));
        }
    }
};

bool Container::ContainerData::destroy()
{
    if (OMNIUI_UNLIKELY(m_drawCallData))
    {
        m_drawCallData->destroyRequested();
        return true;
    }
    return false;
}

bool Container::ContainerData::addChild(std::shared_ptr<Widget> widget)
{
    if (OMNIUI_UNLIKELY(m_drawCallData && !m_drawCallData->allowAddChildren()))
    {
        m_drawCallData->addChildRequested(std::move(widget), true);
        return true;
    }
    return false;
}

bool Container::ContainerData::clear()
{
    if (OMNIUI_UNLIKELY(m_drawCallData))
    {
        m_drawCallData->clearRequested();
        return true;
    }
    return false;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
