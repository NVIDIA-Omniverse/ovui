/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "StandaloneInit.h"

#include <array>
#include <cstdint>
#include <memory>
#include <string>

struct ImDrawData;

namespace omni {
namespace ui {

class ByteImageProvider;

namespace standalone {

class VulkanBackend;

struct OMNIUI_STANDALONE_API NativeFramePacingStats
{
    bool supported = false;
    bool active = false;
    double presentRate = 0.0;
    uint32_t rendererVersionMajor = 0;
    uint32_t rendererVersionMinor = 0;
    uint32_t rendererVersionPatch = 0;
    /// Identifies the active borrow. Zero while inactive. Only the holder of
    /// this token owns the session the other counters describe.
    uint64_t sessionToken = 0;
    uint64_t uiGeometryGenerations = 0;
    uint64_t realRenderCompletions = 0;
    uint64_t generatedImages = 0;
    uint64_t selectedViewportImageChanges = 0;
    uint64_t selectedViewportContentChanges = 0;
    /// Product-wide stage counters used in both synchronous and native paced
    /// rendering. metricsEpoch changes whenever ownership changes so a rate
    /// sample never bridges two renderer sessions.
    uint64_t metricsEpoch = 0;
    uint64_t rendererCompletions = 0;
    uint64_t selectedContentChanges = 0;
    /// Monotonic real-renderer identity carried from completion through the
    /// ordered selection and successful Vulkan presentation boundaries.
    uint64_t selectedRendererFrames = 0;
    uint64_t lastSelectedRendererFrameSerial = 0;
    uint64_t presentedRendererFrames = 0;
    /// Identities of the threads that render and present this session. The
    /// same values across sessions mean the workers were reused.
    uint64_t renderWorkerThread = 0;
    uint64_t presentWorkerThread = 0;
    uint64_t lastPresentedRendererFrameSerial = 0;
    uint64_t rendererFrameOrderViolations = 0;
    uint64_t presentSubmitCalls = 0;
    uint64_t presentSubmitSuccesses = 0;
    uint64_t presentSubmitTotalNanoseconds = 0;
    uint64_t presentSubmitMaxNanoseconds = 0;
    uint64_t successfulPresentIntervals = 0;
    uint64_t successfulPresentIntervalTotalNanoseconds = 0;
    uint64_t successfulPresentIntervalMaxNanoseconds = 0;
    uint64_t successfulPresentIntervalsOver40ms = 0;
    uint64_t successfulPresentIntervalsOver100ms = 0;
    uint64_t successfulPresentIntervalsOver1s = 0;
    uint64_t totalPresents = 0;
    uint64_t repeatedPresents = 0;
    bool windowSurfaceActive = false;
    uint64_t windowPresents = 0;
    uint64_t windowPresentDeferrals = 0;
    uint64_t swapchainRecreations = 0;
    uint32_t swapchainWidth = 0;
    uint32_t swapchainHeight = 0;
    /// Effective product backend and Vulkan WSI policy/mode.  The mode names
    /// successful submission policy only; they do not claim compositor
    /// consumption or physical scanout timing.
    std::string backend;
    std::string presentPolicy;
    std::string activePresentMode;
    uint64_t completedFrameGroups = 0;
    uint64_t completedFrameGroupsSize1 = 0;
    uint64_t completedFrameGroupsSize2 = 0;
    uint64_t completedFrameGroupsSize3 = 0;
    uint64_t completedFrameGroupsSize4 = 0;
    uint64_t replacedFrameGroups = 0;
    uint64_t droppedImages = 0;
    uint64_t presentedGeneratedImages = 0;
    uint64_t rendererTimestampIntervals = 0;
    uint64_t rendererTimestampIntervalTotalNanoseconds = 0;
    uint64_t rendererTimestampIntervalMaxNanoseconds = 0;
    uint64_t rendererTimestampOrderViolations = 0;
    uint64_t presentationDeadlineMisses = 0;
    double lastPresentedFrameEndTime = 0.0;
    /// Images published straight from a CUDA device pointer (no host readback).
    uint64_t gpuResidentPublications = 0;
    /// Images published through the host copy because the GPU path was
    /// unavailable for that frame. Non-zero means the fallback is in use.
    uint64_t hostFallbackPublications = 0;
    /// Times a GPU-resident upload was refused by the device pair. Non-zero
    /// means GPU publication latched off and the host path took over.
    uint64_t gpuPublicationFailures = 0;
    uint64_t ownershipGeneration = 0;
    uint64_t liveStepResults = 0;
    uint64_t liveMappings = 0;
    uint64_t borrowedSlots = 0;
    uint64_t staleGenerationRejections = 0;
    uint64_t cameraPublications = 0;
    uint64_t cameraIntegrations = 0;
    double maximumPredictionOffset = 0.0;
    uint64_t fetchPolls = 0;
    uint64_t fetchBoundedWaits = 0;
    uint64_t errors = 0;
    bool dlssGeneratedFrameActivationSupported = false;
    bool dlssGeneratedFrameRuntimeSupported = false;
    bool dlssGeneratedFrameX3X4Supported = false;
    bool dlssGeneratedFrameGlobalEnableOpinionPresent = false;
    bool dlssGeneratedFrameRequestedEnabled = false;
    int32_t dlssGeneratedFrameRequestedCount = 0;
    bool dlssGeneratedFrameEffectiveActive = false;
    int32_t dlssGeneratedFrameEffectiveCount = 0;
    bool selectedImageIsGenerated = false;
    bool hasSelectedCameraWorld = false;
    bool hasPredictedCameraWorld = false;
    bool hasAuthoritativeCameraWorld = false;
    bool renderLoopExited = false;
    bool renderLoopFatal = false;
    bool renderPaused = false;
    /// The render worker waits, no render is due and no frame group is pending:
    /// under "on_change" the picture on screen has its settle frames.
    bool renderIdle = false;
    std::array<double, 16> selectedCameraWorld{};
    std::array<double, 16> predictedCameraWorld{};
    std::array<double, 16> authoritativeCameraWorld{};
    std::string statusReason;
    std::string dlssGeneratedFrameCapability;
    std::string lastError;
};

/// Configure independent Vulkan presentation. A positive rate starts replay
/// with a finite opt-in target, -1 requests work-conserving max throughput,
/// and zero disables replay and keeps the existing UI-tick presentation path.
OMNIUI_STANDALONE_API bool setNativeFramePacingPresentRate(double framesPerSecond);
OMNIUI_STANDALONE_API double getNativeFramePacingPresentRate();

/// Borrow an existing renderer. Python remains the sole owner and must
/// call stopNativeFramePacing() before replacing or destroying it.
OMNIUI_STANDALONE_API uint64_t startNativeFramePacing(
    uintptr_t renderer,
    const char* libraryPath,
    uint32_t renderVarStride,
    uint32_t renderVarNameOffset,
    uint32_t renderVarHandleOffset,
    std::shared_ptr<ByteImageProvider> provider,
    const char* renderProductPath,
    const char* cameraPath,
    uint32_t width,
    uint32_t height);

/// Atomically publish a complete camera intent. The native render thread is
/// the sole renderer caller while the borrow is active and may extrapolate the
/// translation from linearVelocity between publications.
OMNIUI_STANDALONE_API bool publishNativeFramePacingState(
    uint64_t token,
    uint32_t width,
    uint32_t height,
    const std::array<double, 16>& worldMatrix,
    const std::array<double, 3>& linearVelocity,
    double timestampSeconds);

/// Temporarily return sole renderer access to Python without stopping the
/// presentation session. The output thread keeps the last complete viewport
/// image available and presents fresh ordinary-UI generations with that image
/// while the render worker is drained and joined.
OMNIUI_STANDALONE_API bool pauseNativeFramePacingRender(uint64_t token);

/// Resume the drained render worker under the same presentation-session token.
/// With ``render`` false, the resume itself does not render under
/// ``"on_change"``: the caller changed nothing that the picture shows. A
/// changed camera or size, a render request and the settle frames left still
/// render.
OMNIUI_STANDALONE_API bool resumeNativeFramePacingRender(uint64_t token, bool render);

/// When the render worker renders: ``"continuous"`` (the default) whenever
/// the slot ring can take a frame; ``"on_change"`` only for a changed camera
/// or size, a new session, a resume or requestNativeFramePacingRender, and
/// then ``settleFrames`` more frames (the renderer's temporal accumulation
/// settles), so an idle viewport does not render. False for an unknown
/// policy or a stale token.
OMNIUI_STANDALONE_API bool setNativeFramePacingRenderPolicy(uint64_t token, const char* policy, uint32_t settleFrames);

/// Under ``"on_change"``: render once more (and the settle frames), for a
/// change the camera does not show, such as a stage edit.
OMNIUI_STANDALONE_API bool requestNativeFramePacingRender(uint64_t token);

/// Revoke the renderer borrow, drain the non-cancellable renderer operations with
/// bounded individual waits, join both native threads, and retire all slots.
OMNIUI_STANDALONE_API bool stopNativeFramePacing(uint64_t token);

OMNIUI_STANDALONE_API NativeFramePacingStats getNativeFramePacingStats();
OMNIUI_STANDALONE_API void resetFrameThroughputMetrics();
OMNIUI_STANDALONE_API void recordSynchronousRendererCompletion();
OMNIUI_STANDALONE_API void recordSynchronousContentSelection();

/// Platform hooks. submitNativeFramePacingDrawData deep-copies the completed
/// UI geometry and returns true when native presentation owns Vulkan output.
/// A pending pre-swap capture forces a fresh replay snapshot.
OMNIUI_STANDALONE_API void beginNativeFramePacingUiUpdate(VulkanBackend* backend);
OMNIUI_STANDALONE_API bool submitNativeFramePacingDrawData(
    VulkanBackend* backend,
    const ImDrawData* drawData,
    int width,
    int height,
    uint64_t* outGeneration = nullptr,
    bool forceFresh = false);
OMNIUI_STANDALONE_API bool waitNativeFramePacingPresentation(
    uint64_t uiGeneration,
    uint64_t timeoutNanoseconds);

/// Register the active Vulkan backend after platform initialization. Passing
/// nullptr revokes it during platform teardown.
OMNIUI_STANDALONE_API void registerNativeFramePacingBackend(VulkanBackend* backend);

/// Stop any outstanding borrow before ImGui/Vulkan/platform teardown.
OMNIUI_STANDALONE_API void shutdownNativeFramePacing();

} // namespace standalone
} // namespace ui
} // namespace omni
