/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "NativeFrameReady.h"

#if defined(OMNIUI_HAS_CUDA_INTEROP)
#    include <cuda_runtime.h>
#endif

namespace omni::ui::standalone
{

bool waitForPacedImage(uint64_t readyStream, uint64_t readyEvent)
{
    if (readyEvent != 0)
    {
#if defined(OMNIUI_HAS_CUDA_INTEROP)
        // The event marks this frame on whatever stream made it.
        return cudaStreamWaitEvent(cudaStreamLegacy, reinterpret_cast<cudaEvent_t>(readyEvent), 0) == cudaSuccess;
#else
        return false;
#endif
    }
    // Without an event, only an image that is already complete, or one made on
    // the legacy default stream that ovui's copy follows, can be read.
    return readyStream <= 1;
}

} // namespace omni::ui::standalone
