/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "DragFollow.h"

#include <omni/ui/scene/AbstractContainer.h>
#include <omni/ui/scene/AbstractShape.h>
#include <omni/ui/scene/Line.h>
#include <omni/ui/scene/Points.h>
#include <omni/ui/scene/Transform.h>

#include <algorithm>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

namespace DragFollow
{

namespace
{
// The tracker whose callback (or declared follow) is running, and the item whose write is told with more detail.
thread_local Tracker* t_active = nullptr;
thread_local const AbstractItem* t_classified = nullptr;

// A callback that writes to more transforms than this is not recognised as a follow.
constexpr size_t kMaxEntries = 8;

Vector3 translationOf(const Matrix44& m)
{
    return Vector3{ m[3][0], m[3][1], m[3][2] };
}

// Do the two matrices differ in the translation only?
bool differInTranslationOnly(const Matrix44& a, const Matrix44& b)
{
    return a[0] == b[0] && a[1] == b[1] && a[2] == b[2] && a[3][3] == b[3][3];
}

// Does the transform keep the translation that is written to it as it is? A space to scale to, a turn to the camera and a
// basis change what a write means.
bool isPlainTransform(const Transform* transform)
{
    return transform->getScaleTo() == Space::eCurrent && transform->getLookAt() == Transform::LookAt::eNone &&
           !transform->getBasis();
}

bool hasIdentityLinearPart(const Matrix44& m)
{
    for (int column = 0; column < 3; ++column)
    {
        for (int row = 0; row < 4; ++row)
        {
            if (m[column][row] != (column == row ? 1.0 : 0.0))
            {
                return false;
            }
        }
    }
    return m[3][3] == 1.0;
}

// Does every transform above the item move the world by what a translation under it moves it by?
bool isPlainAbove(const AbstractItem* item)
{
    for (const AbstractItem* parent = item->getParent(); parent; parent = parent->getParent())
    {
        if (auto* transform = dynamic_cast<const Transform*>(parent))
        {
            if (!isPlainTransform(transform) || !hasIdentityLinearPart(transform->getTransform()))
            {
                return false;
            }
        }
    }
    return true;
}
} // namespace

// A basis is a matrix that is written without a write of the transform, so a change of it has no stamp.
static bool hasBasisAbove(const AbstractItem* item)
{
    for (; item; item = item->getParent())
    {
        auto* transform = dynamic_cast<const Transform*>(item);
        if (transform && transform->getBasis())
        {
            return true;
        }
    }
    return false;
}

uint64_t getStamp(const AbstractItem* item)
{
    uint64_t stamp = 0;
    for (; item; item = item->getParent())
    {
        stamp = std::max(stamp, item->getWriteStamp());
    }
    return stamp;
}

std::atomic<uint32_t> g_openWindows{ 0 };

void Write::_open(const AbstractItem* item)
{
    m_tracker = t_active;
    m_previous = t_classified;
    m_open = true;
    if (m_tracker)
    {
        t_classified = item;
    }
}

void Write::_close()
{
    if (m_tracker)
    {
        t_classified = m_previous;
    }
}

void noteWriteOpen(const AbstractItem* item)
{
    if (t_active && t_classified != item)
    {
        t_active->noteOpaque(item);
    }
}

void Tracker::reset()
{
    m_answered = false;
    m_stamp = 0;
    m_havePointer = false;
    m_baselinePending = false;
    m_rejected = false;
    m_sender.reset();
}

void Tracker::setPointer(const Pointer& pointer)
{
    m_pointer = pointer;
    m_havePointer = true;
}

void Tracker::enter(const AbstractShape* sender, const Report& report, bool callback)
{
    m_outer = t_active;
    t_active = this;
    g_openWindows.fetch_add(1, std::memory_order_relaxed);
    m_sender = sender ? sender->weak_from_this() : std::weak_ptr<const AbstractItem>();
    m_report = report;
    m_inWindow = callback;
    m_declaredWrites = 0;
    m_opaqueWrites = 0;
    m_overflow = false;
    m_entries.clear();
    m_lineStart = m_lineEnd = m_points = false;
    m_repeated = false;
    m_lineShift = m_pointsShift = true;
}

void Tracker::leave()
{
    t_active = m_outer;
    m_outer = nullptr;
    g_openWindows.fetch_sub(1, std::memory_order_relaxed);
    m_inWindow = false;
    const auto sender = m_sender.lock();
    m_answered = sender && _verdict(sender.get());
    m_rejected = !m_answered && (m_declaredWrites + m_opaqueWrites > 0 || m_overflow || m_repeated || !m_entries.empty() || m_lineStart ||
                                 m_lineEnd || m_points);
    m_stamp = getStamp(sender.get());
}

void Tracker::enterDeclared()
{
    const auto sender = m_sender.lock();
    if (m_declaredScopes++ == 0 && !m_inWindow && sender)
    {
        // Outside of a callback: the consumer applies a movement that a call reported in a later update.
        m_outer = t_active;
        t_active = this;
        g_openWindows.fetch_add(1, std::memory_order_relaxed);
        m_declaredWrites = 0;
        m_opaqueWrites = 0;
        m_enterStamp = getStamp(sender.get());
    }
}

void Tracker::leaveDeclared()
{
    if (m_declaredScopes == 0)
    {
        return;
    }
    if (--m_declaredScopes == 0 && !m_inWindow && t_active == this)
    {
        t_active = m_outer;
        m_outer = nullptr;
        g_openWindows.fetch_sub(1, std::memory_order_relaxed);
        // The follow is the answer to the last call only if nothing else wrote to the shape since that call was answered.
        const auto sender = m_sender.lock();
        if (sender && !m_rejected && m_enterStamp == m_stamp && m_declaredWrites > 0 && m_opaqueWrites == 0)
        {
            m_answered = true;
            m_stamp = getStamp(sender.get());
        }
    }
}

bool Tracker::isFollow(const AbstractShape* sender, const Pointer& pointer) const
{
    return m_answered && m_havePointer && sender && m_sender.lock().get() == sender && pointer == m_pointer &&
           getStamp(sender) == m_stamp && !hasBasisAbove(sender);
}

bool Tracker::_isRelevant(const AbstractItem* item) const
{
    const auto sender = m_sender.lock();
    for (const AbstractItem* up = sender.get(); up; up = up->getParent())
    {
        if (up == item)
        {
            return true;
        }
    }
    return false;
}

void Tracker::noteOpaque(const AbstractItem* item)
{
    if (!_isRelevant(item))
    {
        return;
    }
    if (m_declaredScopes)
    {
        ++m_declaredWrites;
    }
    else
    {
        ++m_opaqueWrites;
    }
}

void Tracker::noteTransform(const Transform* transform, const Matrix44& before, const Matrix44& after)
{
    if (!_isRelevant(transform))
    {
        return;
    }
    if (m_declaredScopes)
    {
        ++m_declaredWrites;
        return;
    }
    for (auto& entry : m_entries)
    {
        if (entry.transform == transform)
        {
            entry.shift = entry.shift && differInTranslationOnly(entry.after, after);
            entry.after = after;
            m_repeated = true;
            return;
        }
    }
    if (m_entries.size() >= kMaxEntries)
    {
        m_overflow = true;
        return;
    }
    m_entries.push_back({ transform, transform->weak_from_this(), before, after, differInTranslationOnly(before, after) });
}

void Tracker::noteLineEnd(const Line* line, bool start, const Vector3& before, const Vector3& after)
{
    if (line != m_sender.lock().get())
    {
        return;
    }
    if (m_declaredScopes)
    {
        ++m_declaredWrites;
        return;
    }
    m_repeated = m_repeated || (start ? m_lineStart : m_lineEnd);
    (start ? m_lineStart : m_lineEnd) = true;
    m_lineShift = m_lineShift && after == before + m_report.moved;
}

void Tracker::notePositions(const Points* points, const std::vector<Vector3>& before, const std::vector<Vector3>& after)
{
    if (points != m_sender.lock().get())
    {
        return;
    }
    if (m_declaredScopes)
    {
        ++m_declaredWrites;
        return;
    }
    m_repeated = m_repeated || m_points;
    m_points = true;
    if (!m_pointsShift)
    {
        return;
    }
    // Every position is the old one plus the movement: this is the one place where the cost grows with the shape, and it
    // is paid only by the write of a callback, which has made the whole list itself.
    bool shift = before.size() == after.size();
    for (size_t i = 0; shift && i < after.size(); ++i)
    {
        shift = after[i] == before[i] + m_report.moved;
    }
    m_pointsShift = shift;
}

bool Tracker::_verdict(const AbstractItem* sender)
{
    if (m_opaqueWrites > 0 || m_overflow || m_repeated)
    {
        return false;
    }
    const int kinds = (m_entries.empty() ? 0 : 1) + ((m_lineStart || m_lineEnd) ? 1 : 0) + (m_points ? 1 : 0);
    if (kinds == 0)
    {
        // Only declared writes, or none.
        return m_declaredWrites > 0;
    }
    if (kinds > 1 || !m_report.valid)
    {
        return false;
    }
    if (m_points)
    {
        return m_pointsShift && isPlainAbove(sender);
    }
    if (m_lineStart || m_lineEnd)
    {
        return m_lineStart && m_lineEnd && m_lineShift && isPlainAbove(sender);
    }

    // The translations of the transforms above the shape.
    for (const auto& entry : m_entries)
    {
        const auto alive = entry.alive.lock();
        if (!alive || !entry.shift || !isPlainTransform(entry.transform) || !isPlainAbove(entry.transform))
        {
            return false;
        }
    }
    const Vector3& moved = m_report.moved;
    if (m_entries.size() > 1)
    {
        // The movement shared equally between the transforms.
        const Vector3 share = moved / static_cast<Float>(m_entries.size());
        for (const auto& entry : m_entries)
        {
            if (translationOf(entry.after) != translationOf(entry.before) + share)
            {
                return false;
            }
        }
        return true;
    }

    // One transform: the old translation plus the movement, exactly. A number that another arithmetic gives (the start plus the
    // sum, an absolute point) is also what an edit of one unit of the last digit writes, and a stored matrix cannot tell the two
    // apart, so it is called; a consumer that wants no call for it declares the write.
    const Vector3 before = translationOf(m_entries[0].before);
    const Vector3 written = translationOf(m_entries[0].after);
    return written == before + moved;
}

} // namespace DragFollow

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
