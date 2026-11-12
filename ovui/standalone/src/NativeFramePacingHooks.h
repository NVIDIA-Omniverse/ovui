/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

// The renderer slot of the native frame-pacing coordinator.
//
// ovui owns the image slots, the CUDA/Vulkan upload and the present worker; it
// owns no renderer call. An optional package installs the table below with
// setNativeFramePacingHooks(). That package owns the render worker thread and
// every renderer call. Its worker drives ovui through the host table ovui hands
// over in openRenderer(): it waits for a camera, uploads each produced group
// into ovui's slots, and reports when it parks or ends. The standalone Python
// module exposes the setter as `_set_native_frame_pacing_hooks(capsule)`.
// Without a table the coordinator reports `supported = false` and the
// application presents on the UI tick.
//
// This header is part of the ovui SDK, so the package that fills the slot
// builds against the same layout. Everything here is plain C data.

#include <omni/ui/Api.h>

#include <cstddef>
#include <cstdint>

namespace omni::ui::standalone
{

inline constexpr uint32_t kNativeFramePacingHooksVersion = 3U;
inline constexpr char kNativeFramePacingHooksCapsuleName[] = "omni.ui.native_frame_pacing_hooks";

/** Pixel format of a paced image. The value matches omni::ui::PixelFormat. */
enum NativeFramePacingPixelFormat : uint32_t
{
    eNativeFramePacingRgba8Unorm = 0U,
};

/** Outcome of openRenderer() and of one render-worker step. */
enum NativeFramePacingStatus : uint32_t
{
    /** openRenderer(): the session is open. */
    eNativeFramePacingOk = 0U,
    /** Step: enqueued; no group is ready yet. */
    eNativeFramePacingEnqueued = 1U,
    /** Step: `group` holds one complete ordered frame group. */
    eNativeFramePacingGroupReady = 2U,
    /** Step: the drain finished. The render loop stops without an error. */
    eNativeFramePacingDrained = 3U,
    /** The call failed. lastError() names the reason. */
    eNativeFramePacingFailed = 4U,
    /** openRenderer(): the runtime does not match the interfaces the package was built against. */
    eNativeFramePacingIncompatible = 5U,
    /** Step: this frame failed, the session continues. */
    eNativeFramePacingRetryable = 6U,
};

/** Outcome of publishGroup(), the same values as the coordinator's PublishResult. */
enum NativeFramePacingPublish : uint32_t
{
    /** The group reached the slot ring, or there was nothing to publish. */
    eNativeFramePacingPublished = 0U,
    /** This frame was dropped; the session stays alive. */
    eNativeFramePacingSkippedRetryable = 1U,
    /** Unrecoverable; the render loop must stop. */
    eNativeFramePacingPublishFailed = 2U,
};

/** How the render loop of a session ended, as ovui sees it. */
enum NativeFramePacingLoopEnd : uint32_t
{
    /** The session ended or failed. The worker leaves the session. */
    eNativeFramePacingLoopExited = 0U,
    /** A render pause. The worker parks until it is resumed or the session closes. */
    eNativeFramePacingLoopParked = 1U,
};

/**
 * One extracted image of an ordered frame group.
 *
 * `devicePtr` is filled when the package mapped the image on the GPU, `pixels`
 * when it copied the image to the host. `gpuResident` says which one holds the
 * image. Both pointers stay valid until publishGroup() returns.
 */
struct NativeFramePacingImage
{
    const void* devicePtr;
    uint64_t deviceRowStride;
    const uint8_t* pixels;
    uint64_t pixelsSize;
    uint32_t width;
    uint32_t height;
    /** One of NativeFramePacingPixelFormat. */
    uint32_t pixelFormat;
    uint32_t gpuResident;
    /**
     * The CUDA stream on which the image becomes complete. 0 means the image
     * is already complete when the step returns; 1 is the legacy default CUDA
     * stream.
     */
    uint64_t readyStream;
    /**
     * The completion signal of this image: a CUDA event (cudaEvent_t) that is
     * signaled when this image is complete, or 0 when there is none. A CUDA
     * event carries no counter value; the event itself marks this frame.
     * ovui makes its copy wait for the event. The event stays valid until
     * publishGroup() returns.
     */
    uint64_t readyEvent;
};

/**
 * One complete ordered frame group, in presentation order. The last entry is
 * the real rendered frame; the entries before it are generated.
 */
struct NativeFramePacingGroup
{
    const NativeFramePacingImage* images;
    /** One renderer timestamp per image, in the same order. */
    const double* frameEndTimes;
    uint64_t imageCount;
    /** The camera matrix the group was rendered with. */
    double cameraWorld[16];
};

/** What ovui decides for one step of the render worker. */
struct NativeFramePacingStepDesc
{
    uint32_t structSize;
    /** Non-zero while ovui can still publish a GPU-resident image. */
    uint32_t allowGpuMapping;
    /** The renderer end time of the last accepted real frame, when there is one. */
    uint32_t hasLastAcceptedRealEndTime;
    double lastAcceptedRealEndTime;
};

/** What one step of the render worker produced. */
struct NativeFramePacingStepOutput
{
    uint32_t structSize;
    /** One of NativeFramePacingStatus. */
    uint32_t status;
    /** Non-zero when this group was rejected for its renderer timestamps. */
    uint32_t rendererTimestampOrderViolation;
    /** Non-zero when `group` is complete, even if `status` is a failure. */
    uint32_t groupValid;
    NativeFramePacingGroup group;
};

/**
 * The functions ovui gives the render worker for one session. Only the render
 * worker calls them, from its own thread. `context` is ovui's and goes back as
 * the first argument.
 */
struct NativeFramePacingHost
{
    uint32_t structSize;
    void* context;
    /**
     * Block until a camera publication is waiting and the slot ring can take a
     * group, and copy the camera into `world`. False ends the render loop: the
     * session is stopping, pausing or gone.
     */
    bool (*waitForWork)(void* context, uint64_t token, double world[16]);
    /** True once the session is stopping or pausing; outstanding work is only drained. */
    bool (*stopRequested)(void* context, uint64_t token);
    /** The camera `world` was written to the renderer. Fill `desc` for the step. */
    void (*beginStep)(void* context, uint64_t token, const double world[16], NativeFramePacingStepDesc* desc);
    /**
     * Account for one step and, when it holds a ready group, upload the group
     * into ovui's slot ring. Returns a NativeFramePacingPublish. On return
     * ovui has queued its copies; `cudaSyncStream` names the CUDA stream they
     * and the CUDA-to-Vulkan signal were queued on, which the worker passes to
     * the renderer when it releases a GPU-resident mapping.
     */
    uint32_t (*publishGroup)(void* context,
                             uint64_t token,
                             const NativeFramePacingStepOutput* output,
                             uint64_t* cudaSyncStream);
    /** Report a failure of the render worker. */
    void (*reportError)(void* context, const char* message);
    /** The render loop of `token` returned. Returns a NativeFramePacingLoopEnd. */
    uint32_t (*renderLoopEnded)(void* context, uint64_t token);
    /** A parked worker woke. True to run the render loop again, false to leave the session. */
    bool (*renderResumed)(void* context, uint64_t token);
};

/** Everything the package needs to borrow the renderer for one session. */
struct NativeFramePacingOpenDesc
{
    uint32_t structSize;
    uintptr_t renderer;
    const char* libraryPath;
    uint32_t renderVarStride;
    uint32_t renderVarNameOffset;
    uint32_t renderVarHandleOffset;
    const char* renderProductPath;
    const char* cameraPath;
    /** Valid until closeRenderer(token) returns true. */
    const NativeFramePacingHost* host;
};

/** Renderer facts ovui reports in NativeFramePacingStats. */
struct NativeFramePacingRendererInfo
{
    uint32_t structSize;
    uint32_t versionMajor;
    uint32_t versionMinor;
    uint32_t versionPatch;
    uint64_t liveStepResults;
    uint64_t liveMappings;
    uint64_t fetchPolls;
    uint64_t fetchBoundedWaits;
    uint32_t generatedFrameActivationSupported;
    uint32_t generatedFrameRuntimeSupported;
    uint32_t generatedFrameX3X4Supported;
    uint32_t generatedFrameGlobalEnableOpinionPresent;
    uint32_t generatedFrameRequestedEnabled;
    int32_t generatedFrameRequestedCount;
    /** Null-terminated sentence for NativeFramePacingStats::dlssGeneratedFrameCapability. */
    char generatedFrameCapability[256];
};

/**
 * What a frame source can do, for the checks ovui makes before it starts its
 * threads. Each field is non-zero when the frame source meets the condition.
 */
struct NativeFramePacingCapabilities
{
    uint32_t structSize;
    /** The frame source can operate on a thread other than the UI thread. */
    uint32_t operatesOffUiThread;
    /** The frame source renders without the queue of ovui's presentation thread. */
    uint32_t usesOwnQueue;
    /** ovui's presentation thread can read the rendered images and their completion signals. */
    uint32_t presentReadsImages;
};

/**
 * Function table for the renderer half of native frame pacing. Every function
 * must be set. `token` is the ovui presentation-session token.
 */
struct NativeFramePacingHooks
{
    uint32_t structSize;
    uint32_t version;
    /**
     * Borrow the renderer for `token` and hand the session to the persistent
     * render worker, starting the worker on first use. The worker begins once
     * `desc->host->waitForWork` lets it. Returns a NativeFramePacingStatus.
     */
    uint32_t (*openRenderer)(uint64_t token, const NativeFramePacingOpenDesc* desc);
    /**
     * ovui has raised its pause request. Wait until the render worker has
     * parked or left the session, then release every retained renderer handle,
     * so Python has the renderer to itself. False when a release must be
     * retried.
     */
    bool (*pauseRenderWorker)(uint64_t token);
    /** Wake the parked worker. False when it has left the session. */
    bool (*resumeRenderWorker)(uint64_t token);
    /**
     * ovui has raised its stop request. Wake a parked worker, wait until the
     * worker has left the session, drain the retained results and maps and
     * give the renderer back. The worker is not joined; it waits for the next
     * session. False when a release must be retried; call again.
     */
    bool (*closeRenderer)(uint64_t token);
    /** Final teardown: join the render worker. Called with no session open. */
    void (*shutdownWorker)();
    /** Fill `output` with the current renderer facts. Never waits for a frame. */
    void (*readRendererInfo)(uint64_t token, NativeFramePacingRendererInfo* output);
    /**
     * Copy the last error message into `buffer` and return its length without
     * the terminator. A null `buffer` only measures.
     */
    size_t (*lastError)(char* buffer, size_t capacity);
    /** Fill `output` with what the frame source can do. Called before ovui starts its threads. */
    void (*queryCapabilities)(NativeFramePacingCapabilities* output);
    /**
     * Cancel the outstanding request of `token`. Callable from each thread;
     * never waits. The frame source stops the request at the first possible
     * time and publishes no image for it.
     */
    void (*cancel)(uint64_t token);
};

/**
 * Install `hooks` (or remove them with nullptr). The table must stay alive.
 * Returns false, and leaves the slot empty, when the table has another
 * version, is too small or misses a function.
 */
OMNIUI_API bool setNativeFramePacingHooks(const NativeFramePacingHooks* hooks);
OMNIUI_API const NativeFramePacingHooks* getNativeFramePacingHooks();

/**
 * Send a cancel for `token` to the installed frame source. Callable from each
 * thread; never waits. Returns false when no frame source is installed.
 */
OMNIUI_API bool sendNativeFramePacingCancel(uint64_t token);

} // namespace omni::ui::standalone
