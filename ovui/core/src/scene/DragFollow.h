/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/platform/Assert.h>
#include <omni/ui/scene/Math.h>

#include <atomic>
#include <cstdint>
#include <memory>
#include <vector>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class AbstractItem;
class AbstractShape;
class Line;
class Points;
class Transform;

/**
 * The follow of the pointer, for DragGesture.
 *
 * A consumer that follows the pointer moves the shape by the ``moved`` that a call reported, while its callback runs.
 * The next frame has the payload of the new place under a still pointer, and it must not be a second call for the same
 * movement. The gesture decides this from what was written and when, not from the numbers of the payload:
 *
 * - Every write that can change the payload (the matrix of a transform, the geometry of a shape, the structure above it)
 *   takes a stamp from a process-wide counter (AbstractItem::getWriteStamp). A frame can only be the follow of the last
 *   call when no write has happened to the shape or above it since the callback returned, and the pointer and the camera
 *   are the same. A color, a thickness or a size is not geometry and takes no stamp.
 * - While a callback runs, the writes to the shape and to the items above it are told to the gesture by the code that
 *   makes them (``DragFollow::Write``, which costs one load when no callback runs). When the callback returns, they are
 *   the follow if the consumer declared them (``DragGesture::beginFollowing``), or if each of them is exactly what the
 *   movement gives: see ``Tracker::_verdict``. A write that is not is an edit, and the next frame is called.
 *
 * Nothing is copied when no callback runs, the stamp is one integer for each item, and a callback that moves the shape by a
 * Transform costs the same for a shape of any size. The write of every position of a ``Points`` inside a callback is compared
 * with the old positions once, as the callback has built the whole list itself.
 */
namespace DragFollow
{

// What a call reports, as far as a follow needs it.
struct Report
{
    // ``moved`` of the payload.
    Vector3 moved = Vector3{ 0.0 };
    bool valid = false;
};

// The pointer and the camera of a frame. A change of the payload under the same pointer and camera is a change of the scene.
struct Pointer
{
    Vector2 mouse = Vector2{ 0.0 };
    Vector3 origin = Vector3{ 0.0 };
    Vector3 direction = Vector3{ 0.0 };
    Matrix44 projection;
    Matrix44 view;
    Vector2 frameSize = Vector2{ 0.0 };

    bool operator==(const Pointer& other) const
    {
        return mouse == other.mouse && origin == other.origin && direction == other.direction &&
               projection == other.projection && view == other.view && frameSize == other.frameSize;
    }
};

class Tracker
{
public:
    // A drag begins (or ends): forget everything about the earlier one.
    void reset();

    // The call of a frame is going to be made (or has been made) with this pointer and report.
    void setPointer(const Pointer& pointer);

    // A callback (a window) runs for ``sender`` with this report, or the consumer declares the follow of the last call.
    void enter(const AbstractShape* sender, const Report& report, bool callback);
    void leave();
    void enterDeclared();
    void leaveDeclared();

    // The ``moved`` of the next frames is measured from the payload of the last call, until a call is made again. The shape
    // keeps the baseline only for one intersection, so the gesture asks for it in every frame in which it is pending, and a
    // gesture that is gone leaves nothing behind.
    void setBaselinePending(bool pending)
    {
        m_baselinePending = pending;
    }

    bool isBaselinePending() const
    {
        return m_baselinePending;
    }

    // Is a frame of ``sender`` with a different payload only the follow of the last call? True only when the pointer and the
    // camera are the ones of that call, the callback answered it, and nothing has written to the shape or above it since.
    bool isFollow(const AbstractShape* sender, const Pointer& pointer) const;

    // The writes that the hooks tell.
    void noteOpaque(const AbstractItem* item);
    void noteTransform(const Transform* transform, const Matrix44& before, const Matrix44& after);
    void noteLineEnd(const Line* line, bool start, const Vector3& before, const Vector3& after);
    void notePositions(const Points* points, const std::vector<Vector3>& before, const std::vector<Vector3>& after);

private:
    struct Entry
    {
        const Transform* transform;
        // The transform can be gone (the callback may have dropped it) when the writes are judged.
        std::weak_ptr<const AbstractItem> alive;
        Matrix44 before;
        Matrix44 after;
        bool shift;
    };

    bool _isRelevant(const AbstractItem* item) const;
    bool _verdict(const AbstractItem* sender);

    // The drag: the arithmetic of the follow.

    bool m_baselinePending = false;
    // The last callback made writes that were not the follow: a later declared write must not take them for the follow.
    bool m_rejected = false;

    // The last call: was it answered by what its callback wrote, and what did the shape look like then.
    bool m_answered = false;
    uint64_t m_stamp = 0;
    bool m_havePointer = false;
    Pointer m_pointer;

    // The window.
    // The shape that the gesture is on. It can go away while its callback runs.
    std::weak_ptr<const AbstractItem> m_sender;
    Report m_report;
    bool m_inWindow = false;
    uint32_t m_declaredScopes = 0;
    uint64_t m_enterStamp = 0;
    uint32_t m_declaredWrites = 0;
    uint32_t m_opaqueWrites = 0;
    bool m_overflow = false;
    std::vector<Entry> m_entries;
    // The callback wrote the same transform, end or positions more than once: the history is not one follow.
    bool m_repeated = false;
    bool m_lineStart = false;
    bool m_lineEnd = false;
    bool m_lineShift = true;
    bool m_points = false;
    bool m_pointsShift = true;
    Tracker* m_outer = nullptr;
};

// The largest stamp of the item and of the items above it.
uint64_t getStamp(const AbstractItem* item);

// The number of windows (callbacks and declared scopes) that are open in the process. The hooks below test it first, so that
// the writes of code that is not in a callback cost one load.
extern std::atomic<uint32_t> g_openWindows;

// A write that is told to the open window of the thread. It exists for the length of the write, the generic ``noteWrite``
// that the stamp makes is not told again for the item, and the write is told with more detail by the ``note*`` calls.
class Write
{
public:
    explicit Write(const AbstractItem* item)
    {
        if (OMNIUI_UNLIKELY(g_openWindows.load(std::memory_order_relaxed) != 0))
        {
            _open(item);
        }
    }

    ~Write()
    {
        if (OMNIUI_UNLIKELY(m_open))
        {
            _close();
        }
    }

    Write(const Write&) = delete;
    Write& operator=(const Write&) = delete;

    void noteTransform(const Transform* transform, const Matrix44& before, const Matrix44& after)
    {
        if (m_tracker)
        {
            m_tracker->noteTransform(transform, before, after);
        }
    }

    void noteLineEnd(const Line* line, bool start, const Vector3& before, const Vector3& after)
    {
        if (m_tracker)
        {
            m_tracker->noteLineEnd(line, start, before, after);
        }
    }

    void notePositions(const Points* points, const std::vector<Vector3>& before, const std::vector<Vector3>& after)
    {
        if (m_tracker)
        {
            m_tracker->notePositions(points, before, after);
        }
    }

private:
    void _open(const AbstractItem* item);
    void _close();

    Tracker* m_tracker = nullptr;
    const AbstractItem* m_previous = nullptr;
    bool m_open = false;
};

void noteWriteOpen(const AbstractItem* item);

// An opaque write of the item (a write that is not told with more detail).
inline void noteWrite(const AbstractItem* item)
{
    if (OMNIUI_UNLIKELY(g_openWindows.load(std::memory_order_relaxed) != 0))
    {
        noteWriteOpen(item);
    }
}

} // namespace DragFollow

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
