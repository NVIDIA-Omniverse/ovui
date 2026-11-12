/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "ImageProvider.h"
#include "IByteImageGpu.h"

#include <cstdint>
#include <functional>
#include <memory>

namespace omni
{
namespace ui
{

/// What one ByteImageProvider upload did. See ByteImageProvider for what each
/// status guarantees.
struct ByteImageUploadResult
{
    UploadStatus status = UploadStatus::eFailed;
    /// Grows with each accepted upload of this provider. 0 when status is
    /// eFailed. Compare it with ByteImageProvider::getCompletedUploadId().
    uint64_t uploadId = 0;
    /// Devices that were asked for, and devices that accepted. See
    /// UploadResult. Both are 0 when the backend has no device mask.
    uint32_t requestedDeviceMask = 0;
    uint32_t uploadedDeviceMask = 0;
    /// Why nothing new was accepted (eFailed or eNoBackend): a short static
    /// text, or null. It is never freed.
    const char* cause = nullptr;

    /// True when the backend accepted the pixels (eEnqueued or eComplete).
    /// This is not proof that a draw can sample them yet.
    bool accepted() const { return status == UploadStatus::eEnqueued || status == UploadStatus::eComplete; }
    explicit operator bool() const { return accepted(); }
};

/// One step in the life of an upload, sent to subscribers of a provider.
struct ByteImageUploadEvent
{
    enum class Kind : uint32_t
    {
        eFailed,    ///< The upload was rejected. The old pixels stay.
        eEnqueued,  ///< The backend accepted the pixels. The copy may still run.
        eCompleted, ///< The copy of upload ``uploadId`` finished.
    };
    Kind kind = Kind::eFailed;
    uint64_t uploadId = 0;
    uint32_t requestedDeviceMask = 0;
    uint32_t uploadedDeviceMask = 0;
};

/// Image provider that is filled with pixel data from the CPU or from a GPU
/// pointer.
///
/// Every setBytesData* call has a checked twin named uploadBytesData*. The
/// twins return a ByteImageUploadResult. The setBytesData* functions are kept
/// unchanged, with the same signature and the same ``void`` result, so that
/// code built against an older header still links and loads. This matters on
/// Windows, where the return type is part of the exported name. New code
/// should call the upload* functions.
///
/// What a result guarantees:
///  - eFailed: nothing new was accepted. Previous pixels stay. They are not
///    removed, so isReferenceValid() stays true when an earlier upload worked.
///    Use the result, not isReferenceValid(), to know if new pixels arrived.
///  - eEnqueued: the backend accepted the pixels and ordered the copy before
///    later sampling on its device. A draw that is submitted later samples the
///    new pixels, but the copy may still run. Learn when it finished with
///    getCompletedUploadId() or an upload event.
///  - eComplete: the copy finished, and the backend proved it. A source can
///    be released.
///  - eNoBackend: no GPU backend is registered (no renderer). Nothing was
///    uploaded, and this is not a failure: it is not counted and sends no
///    event.
///  - With a device mask the result is accepted only when every requested
///    device accepted. uploadedDeviceMask tells which ones did.
///  - Presented to the screen is not covered. The provider has no knowledge of
///    the frame in which a draw is shown.
///  - A backend that cannot report results (no IByteImageGpuChecked) gives
///    eEnqueued when it returned a texture reference and eFailed when it did
///    not. It cannot report a rejected upload that returned the old reference,
///    and getCompletedUploadId() stays 0 for it: nothing proves a copy ended.
///  - Replacing the backend with PlatformRegistry::setByteImageGpu() drops the
///    checked interface of the old one.
///
/// Threads: call the setBytesData* and uploadBytesData* functions on the UI
/// thread, as all changes of an ImageProvider (see ImageProvider). A render
/// thread gives its frames with publishOnUiThread(), for example
/// ``provider->publishOnUiThread([frame](ImageProvider& p) {
/// static_cast<ByteImageProvider&>(p).uploadBytesDataFromGPU(frame->ptr, frame->size); }, true)``,
/// where ``frame`` is a std::shared_ptr that keeps the GPU memory until the
/// upload has run.
class OMNIUI_CLASS_API ByteImageProvider : public ImageProvider
{
public:
    OMNIUI_API
    ByteImageProvider();

    OMNIUI_API
    virtual ~ByteImageProvider();

    /**
     * @brief Sets byte data that the image provider will turn into an image.
     * @param bytes Data bytes.
     * @param size Tuple of image size, (width, height).
     * @param stride Number of bytes between rows of data bytes. Value kAutoCalculateStride could be used to
     * auto-calculate stride based on format, given data bytes have no gaps.
     * @param format Image format.
     */
    OMNIUI_API
    virtual void setBytesData(const uint8_t* bytes,
                              UInt2 size,
                              size_t stride = kAutoCalculateStride,
                              PixelFormat format = PixelFormat::eRGBA8_UNORM);

    OMNIUI_API
    virtual void setMipMappedBytesData(const uint8_t* const* mipMapBytes,
                                       size_t* mipMapStrides,
                                       size_t mipMapCount,
                                       UInt2 size,
                                       PixelFormat format = PixelFormat::eRGBA8_UNORM);

    OMNIUI_API
    virtual void setMipMappedBytesData(const uint8_t* bytes,
                                       UInt2 size,
                                       size_t stride,
                                       PixelFormat format = PixelFormat::eRGBA8_UNORM,
                                       size_t maxMipLevels = SIZE_MAX);

    OMNIUI_API
    virtual void setBytesDataFromGPU(const uint8_t* bytes,
                                     UInt2 size,
                                     size_t stride = kAutoCalculateStride,
                                     PixelFormat format = PixelFormat::eRGBA8_UNORM);

    /// Checked twin of setBytesData().
    OMNIUI_API
    ByteImageUploadResult uploadBytesData(const uint8_t* bytes,
                                          UInt2 size,
                                          size_t stride = kAutoCalculateStride,
                                          PixelFormat format = PixelFormat::eRGBA8_UNORM);

    /// Checked twin of the first setMipMappedBytesData().
    OMNIUI_API
    ByteImageUploadResult uploadMipMappedBytesData(const uint8_t* const* mipMapBytes,
                                                   size_t* mipMapStrides,
                                                   size_t mipMapCount,
                                                   UInt2 size,
                                                   PixelFormat format = PixelFormat::eRGBA8_UNORM);

    /// Checked twin of the second setMipMappedBytesData().
    OMNIUI_API
    ByteImageUploadResult uploadMipMappedBytesData(const uint8_t* bytes,
                                                   UInt2 size,
                                                   size_t stride,
                                                   PixelFormat format = PixelFormat::eRGBA8_UNORM,
                                                   size_t maxMipLevels = SIZE_MAX);

    /// Checked twin of setBytesDataFromGPU().
    OMNIUI_API
    ByteImageUploadResult uploadBytesDataFromGPU(const uint8_t* bytes,
                                                 UInt2 size,
                                                 size_t stride = kAutoCalculateStride,
                                                 PixelFormat format = PixelFormat::eRGBA8_UNORM);

    /// The result of the last upload call of this provider. Status is eFailed
    /// before the first call.
    OMNIUI_API
    ByteImageUploadResult getLastUploadResult() const;

    /// How many upload calls of this provider were rejected. eNoBackend is not
    /// counted.
    OMNIUI_API
    uint64_t getUploadFailureCount() const;

    /// Records an upload call that was refused before it reached the backend,
    /// for example input that cannot be read. It counts the failure, makes it
    /// the last result, sends an eFailed event and logs ``cause``, which must
    /// be a static text.
    OMNIUI_API
    ByteImageUploadResult rejectUpload(const char* cause);

    /// The highest upload id whose copy finished, or 0. It asks the backend,
    /// and it sends eCompleted events for copies that finished since the last
    /// call. prepareDraw() calls it, so events also come with each draw.
    OMNIUI_API
    uint64_t getCompletedUploadId();

    /// Subscribe to upload events of this provider. The callback runs on the
    /// thread that made the call that caused the event. It must not call
    /// subscribe or unsubscribe for this provider. An exception that leaves a
    /// callback is logged with its message; the upload and the other
    /// callbacks are not affected. Returns an id for
    /// unsubscribeUploadEvents(). The id is never 0.
    OMNIUI_API
    uint64_t subscribeUploadEvents(std::function<void(const ByteImageUploadEvent&)> callback);

    OMNIUI_API
    void unsubscribeUploadEvents(uint64_t subscriptionId);

    /// Test hook for this provider only. Its next ``count`` upload calls fail
    /// with eFailed before they reach the backend. Previous pixels stay.
    /// Other providers are not affected. Use it to test a fallback without a
    /// patched renderer. Pass 0 to stop. Returns how many injected failures
    /// were still waiting.
    OMNIUI_API
    uint32_t injectUploadFailures(uint32_t count);

    /// For code that uploads for this provider without its upload functions
    /// (native frame pacing). Takes one injected failure of this provider if
    /// one is waiting, and returns true if it did. The caller must then treat
    /// its upload as rejected.
    OMNIUI_API
    bool takeInjectedUploadFailure();

    /// True when a GPU backend is registered, so that an upload can succeed. A
    /// false result is a missing renderer, not a refused upload.
    OMNIUI_API
    static bool hasUploadBackend();

    OMNIUI_API
    void prepareDraw(float widgetWidth, float widgetHeight) override;

protected:
    friend class GpuResourcesCache;

    void _updateImage(const uint8_t* const* mipMapBuffers,
                      size_t* mipMapStrides,
                      size_t mipMapCount,
                      UInt2 size,
                      PixelFormat format,
                      bool fromGpu = false);
    ByteImageUploadResult _uploadImage(const uint8_t* const* mipMapBuffers,
                                       size_t* mipMapStrides,
                                       size_t mipMapCount,
                                       UInt2 size,
                                       PixelFormat format,
                                       bool fromGpu);
    OMNIUI_API
    void _releaseImage() override;

    OMNIUI_API
    bool mergeTextureOptions(TextureOptions& textureOptions) const override;

    OMNIUI_API
    bool setTextureOptions(TextureOptions textureOptions) override;

    IByteImageGpu::Handle m_gpuState = nullptr;
    std::unique_ptr<TextureOptions> m_textureOptions;
};

}
}
