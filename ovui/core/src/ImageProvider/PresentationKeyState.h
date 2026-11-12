/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

// Internal state of presentation keys. ImageProvider and the draw guard use it, and so do the
// tests. It is not part of the public API.

#include <omni/ui/Api.h>

#include <cstddef>
#include <cstdint>

namespace omni
{
namespace ui
{

/// Why a key is not given out or is removed from a draw list.
enum class PresentationKeyFallback
{
    eNone,
    eRetired,   ///< The feeder retired the key.
    eUnmapped,  ///< The renderer reports no drawable for the key.
    eNotMapped, ///< The renderer does not report the key as mapped (state unknown, or no renderer).
    eExpired,   ///< The opt-in lease ended: no new frame in time.
};

/// Text for a log line, for example "retired".
const char* presentationKeyFallbackText(PresentationKeyFallback reason);

/// After the last provider lets a key go, the draw guard checks the key in this number of passes:
/// the pass of the frame in which the feed ended, and one more. Then the records of the key are freed.
constexpr uint64_t kReleasedPresentationKeyPasses = 2;

/// The most records of done feeds that wait for their last passes in a host that draws its frames without
/// the draw guard: it never ends those passes, so above this number the oldest records are freed first.
/// The limit never frees a record whose key can still be in draw data that waits for the guard (a record of
/// the last kReleasedPresentationKeyPasses ImGui frames). So when more feeds than this end within two frames,
/// the guard still checks every key, and frees the records after their passes.
constexpr size_t kMaxReleasedPresentationKeys = 4096;

/**
 * @brief Remembers that a presentation key was given out by getImGuiReference().
 *
 * While a provider holds the key, the draw guard checks it in every pass, so a client can keep the
 * reference and draw it in a later frame. When the last provider lets the key go, the guard checks
 * it for kReleasedPresentationKeyPasses more passes, and then forgets it.
 * @param renderer The renderer handle of the provider, as given by acquireRenderer().
 */
OMNIUI_API
void recordIssuedPresentationKey(void* renderer, uint64_t key);

/**
 * @brief Counts a provider that holds a presentation key. A held key is live until it is retired.
 * A new hold of a retired key makes it live again (a new feed that uses the key).
 */
OMNIUI_API
void holdPresentationKey(uint64_t key);

/**
 * @brief Ends the hold of a provider. When the last hold ends, the feed of the key is done: its
 * records, also the retired state, are freed (after the passes of kReleasedPresentationKeyPasses
 * when the key was given out).
 */
OMNIUI_API
void releasePresentationKey(uint64_t key);

/// @brief Marks a key as retired for all providers that hold it, and for the last passes of a done feed.
OMNIUI_API
void retirePresentationKey(uint64_t key);

/// @brief Tells if the key was retired and no new feed has held it since.
OMNIUI_API
bool isPresentationKeyRetired(uint64_t key);

/// @brief Time source of the lease, in nanoseconds. The default is steady_clock. nullptr restores it.
OMNIUI_API
void setPresentationKeyClock(uint64_t (*nowNs)());

/// @brief Current time of the lease, in nanoseconds.
OMNIUI_API
uint64_t presentationKeyNowNs();

/// @brief The lease in milliseconds. 0 (the default) means no lease.
OMNIUI_API
void setPresentationKeyLeaseMs(uint32_t ms);

/// @brief Returns the lease in milliseconds.
OMNIUI_API
uint32_t getPresentationKeyLeaseMs();

/// @brief Forgets all key records and the clock. For tests. It does not change the lease, so a test
/// can see the initial lease of the library.
OMNIUI_API
void resetPresentationKeyGuardForTest();

} // namespace ui
} // namespace omni
