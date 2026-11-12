/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "StandaloneInit.h"

#include <cstdint>

namespace omni::ui::standalone
{

/**
 * Make the work that ovui queues next on the legacy default CUDA stream wait
 * until a paced image is complete.
 *
 * `readyEvent` is the completion signal of the image (a cudaEvent_t, or 0).
 * `readyStream` is the CUDA stream on which the image becomes complete: 0 for
 * an image that is already complete, 1 for the legacy default stream.
 *
 * Returns false when ovui cannot follow the signal: an image on another
 * stream without an event, or an event on a build without CUDA.
 */
OMNIUI_STANDALONE_API bool waitForPacedImage(uint64_t readyStream, uint64_t readyEvent);

} // namespace omni::ui::standalone
